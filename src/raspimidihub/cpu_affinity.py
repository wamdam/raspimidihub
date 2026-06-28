"""CPU-affinity layout for the isolated-core appliance.

The Pi's cores are split so the two latency-critical workloads each get a
quiet, contention-free core:

* the **loop core** runs ONLY the asyncio / MIDI loop;
* the **plugin core(s)** run ONLY the plugin threads (which emit notes
  immediately on their own thread, so they need low, consistent wake
  latency);
* the **housekeeping cores** run everything else — kernel, IRQs, the WiFi
  AP daemons, zeroconf, BLE, the worker pool and the forked save/encode
  child.

The split is driven by the kernel ``isolcpus`` list (``/sys/devices/
system/cpu/isolated``) so the code adapts to the cmdline without
hardcoding core numbers:

* ``isolcpus=2,3`` → loop=3, plugins={2}, housekeeping={0,1}  (target)
* ``isolcpus=3``   → loop=3, plugins=housekeeping={0,1,2}     (interim,
  before the cmdline/reboot — plugins just share the housekeeping cores)
* nothing isolated (dev box / CI) → every helper is a no-op.

New threads inherit the affinity of the thread that created them, and
almost everything is spawned from the loop thread (pinned to the loop
core) — so without help those threads inherit the loop core and get
*forced* onto it. Threads we own call :func:`move_to_housekeeping` or
:func:`move_to_plugin_cores` at entry; library threads we don't control
(e.g. python-zeroconf) are swept off the loop core by
:func:`enforce_isolation`.
"""

import logging
import os

log = logging.getLogger(__name__)


def _all_cpus() -> set[int]:
    try:
        return set(range(os.cpu_count() or 1))
    except Exception:
        return {0}


def _parse_cores(raw: str) -> set[int]:
    """Parse a Linux CPU-list string ("3", "2-3", "0,2-3") to a set."""
    cores: set[int] = set()
    for part in raw.strip().split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-")
                cores.update(range(int(a), int(b) + 1))
            else:
                cores.add(int(part))
        except ValueError:
            continue
    return cores


def isolated_cores() -> set[int]:
    """The kernel-isolated cores (``isolcpus``), parsed from /sys. Empty
    on a box without isolation (dev / CI)."""
    try:
        return _parse_cores(open("/sys/devices/system/cpu/isolated").read())
    except OSError:
        return set()


def _layout() -> tuple[int | None, set[int], set[int]]:
    """Return (loop_core, plugin_cores, housekeeping_cores).

    loop_core is None when nothing is isolated → all helpers no-op."""
    iso = isolated_cores()
    allc = _all_cpus()
    if not iso:
        return (None, allc, allc)
    loop = max(iso)                      # designate the highest isolated core
    plugins = iso - {loop}              # the remaining isolated core(s)
    house = allc - iso                 # the normal, ticking cores
    if not house:                      # everything isolated — keep all
        house = allc
    if not plugins:                    # only one isolated core → plugins share housekeeping
        plugins = house
    return (loop, plugins, house)


def loop_core() -> int | None:
    """The core reserved for the asyncio/MIDI loop, or None off-appliance."""
    return _layout()[0]


def plugin_cpus() -> set[int]:
    return _layout()[1]


def housekeeping_cpus() -> set[int]:
    return _layout()[2]


def housekeeping_taskset_arg() -> str:
    """Comma-separated housekeeping core list for `taskset -c` (WiFi
    daemon spawns). Falls back to all cores off-appliance."""
    return ",".join(str(c) for c in sorted(housekeeping_cpus()))


def _set_affinity(cpus: set[int]) -> None:
    try:
        os.sched_setaffinity(0, cpus)
    except (AttributeError, OSError):
        pass


def move_to_housekeeping() -> None:
    """Pin the CALLING thread to the housekeeping cores (off the loop and
    plugin cores). For the clock refill, worker pool and forked
    save/encode child. No-op off-appliance."""
    loop, _plugins, house = _layout()
    if loop is None:
        return
    _set_affinity(house)


def move_to_plugin_cores() -> None:
    """Pin the CALLING thread to the plugin core(s). Call at the top of
    each plugin thread so its immediate note sends run on a quiet,
    contention-free core. No-op off-appliance."""
    loop, plugins, _house = _layout()
    if loop is None:
        return
    _set_affinity(plugins)


def pin_loop() -> bool:
    """Pin the CALLING thread (the asyncio loop) to the loop core. Returns
    True if a loop core exists and the pin was applied."""
    loop, _plugins, _house = _layout()
    if loop is None:
        return False
    try:
        if loop not in os.sched_getaffinity(0):
            log.info("loop core %s not in allowed set — skipping pin", loop)
            return False
        os.sched_setaffinity(0, {loop})
        return True
    except (AttributeError, OSError) as e:
        log.info("loop pin not available: %s", e)
        return False


def enforce_isolation(loop_tid: int) -> int:
    """Sweep every thread of this process: move any thread OTHER than the
    loop off the loop core, onto the housekeeping cores. Plugin threads
    (pinned to the plugin core) don't have the loop core in their mask, so
    they're left alone. Catches library threads (zeroconf, …) we can't pin
    at the source. Returns the number of threads moved; no-op
    off-appliance."""
    loop, _plugins, house = _layout()
    if loop is None:
        return 0
    moved = 0
    try:
        tids = os.listdir("/proc/self/task")
    except OSError:
        return 0
    for t in tids:
        try:
            tid = int(t)
        except ValueError:
            continue
        if tid == loop_tid:
            continue
        try:
            if loop in os.sched_getaffinity(tid):
                os.sched_setaffinity(tid, house)
                moved += 1
        except (OSError, ProcessLookupError):
            continue
    return moved
