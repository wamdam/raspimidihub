"""Stall forensics — catches event-loop stalls red-handed.

The `loop_lag_meter` (loops.py) measures THAT the loop stalled but runs
on the loop itself, so it cannot see WHAT blocked it. This sensor
pairs with it: a small watchdog thread samples every 50 ms — every
thread's current Python frame, kernel wait channel (wchan), and CPU
time — into a short ring buffer. When the meter observes a lag above
`threshold_ms`, it flags the window; the watchdog then builds an
episode from the ring (all on its own thread, so the loop pays
nothing):

* the loop thread's frame during the stall — was it executing Python
  (a heavy json encode, filter work, ...) or blocked in a syscall?
* the loop thread's wchan — `ep_poll`/`poll_schedule_timeout` = idle
  in epoll (the wake itself was delayed → OS-level scheduling: IRQ
  bursts, CPU migration); `do_futex`/`futex_wait_queue_me` = waiting
  on the GIL or a lock; `waitpid` = waiting on a child.
* the "GIL hog" — the non-loop thread that burned the most CPU during
  the window (a worker thread running a big json/gzip encode starves
  the loop of the GIL even though the encode is "off the loop").

Read the three together:

  loop frame in app code + high loop cpu_ms
      → the loop itself ran heavy code (on-loop encode / busy loop).
  loop at selectors.py + wchan futex + a worker hog with high cpu_ms
      → GIL starvation from a worker-thread encode (the classic trap:
      json/gzip hold the GIL even from `to_thread`).
  loop at `ep_poll`, no hog, cpu_ms ~ 0
      → the loop was idle and READY but the OS delayed it: IRQ/softirq
      bursts on the isolated core, CFS latency, or thermal throttling.

Episodes are kept bounded (newest first), each one is warn-logged to
journald, and all of them are served by `GET /api/debug/stalls`.
"""

import collections
import logging
import os
import sys
import threading
import time

log = logging.getLogger(__name__)

# Sample cadence (s) and ring length → ~4.8 s of lookback behind every
# stall report. 100 ms is the sweet spot on the Pi: `sys._current_frames`
# + per-thread /proc reads cost ~2-4 ms of GIL per pass, so a faster
# cadence makes the sensor itself a measurable loop-latency source (the
# first live capture showed the sensor as the top CPU consumer).
SAMPLE_INTERVAL = 0.1
RING_SAMPLES = 48
# Lag (ms) above which the meter asks for a fingerprint. Far above the
# normal scheduler noise (p999 ~ 7 ms on the live hub) — below it,
# reports would just be churn.
DEFAULT_THRESHOLD_MS = 100.0
# Kept episodes per sensor (newest first) + max threads listed per
# episode (by CPU) — keeps /api/debug/stalls small.
MAX_EPISODES = 10
MAX_THREADS_PER_EPISODE = 5


def _jiffies_to_ms(tick) -> float:
    hz = os.sysconf("SC_CLK_TCK") or 100
    return tick / hz * 1000.0


def _task_cpu(tid: int) -> int | None:
    """utime+stime (jiffies) for one thread; None if it died mid-read."""
    try:
        with open(f"/proc/self/task/{tid}/stat", "rb") as f:
            raw = f.read().decode(errors="replace")
        # comm may contain spaces/parens — split after the LAST ')'.
        rpar = raw.rfind(")")
        fields = raw[rpar + 2:].split()
        return int(fields[11]) + int(fields[12])  # utime(14) stime(15)
    except (OSError, ValueError, IndexError):
        return None


def _task_wchan(tid: int) -> str:
    """Kernel wait channel for one thread ('0' = running)."""
    try:
        with open(f"/proc/self/task/{tid}/wchan", "rb") as f:
            return f.read().decode(errors="replace").strip() or "0"
    except OSError:
        return "?"


def _frame_fp(frames: dict, ident: int) -> str:
    f = frames.get(ident)
    if f is None:
        return "n/a"
    file = f.f_code.co_filename.rsplit("/", 1)[-1]
    return f"{file}:{f.f_lineno} ({f.f_code.co_name})"


class StallSensor:
    """Watches for event-loop stalls and fingerprints their cause."""

    def __init__(self, loop_tid: int, threshold_ms: float = DEFAULT_THRESHOLD_MS,
                 sample_interval: float = SAMPLE_INTERVAL):
        self.loop_tid = loop_tid
        self.threshold_ms = threshold_ms
        self._interval = sample_interval
        self._ring: collections.deque = collections.deque(maxlen=RING_SAMPLES)
        # (ts, lag_ms) requests from the meter; the watchdog consumes
        # them on its own thread so the loop only does one append.
        self._requests: list[tuple[float, float]] = []
        self._requests_lock = threading.Lock()
        self._episodes: collections.deque = collections.deque(maxlen=MAX_EPISODES)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="stall-sensor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # Called from the loop thread (loop_lag_meter) — must be cheap and
    # allocation-light: one list append under a tiny lock.
    def report_requested(self, lag_ms: float) -> None:
        with self._requests_lock:
            self._requests.append((time.monotonic(), lag_ms))

    # ------------------------------------------------------------------
    def _sample(self) -> dict:
        frames = sys._current_frames()
        threads = {}
        for t in threading.enumerate():
            try:
                tid = t.native_id
            except AttributeError:
                continue
            cpu = _task_cpu(tid)
            if cpu is None:
                continue
            threads[tid] = {
                "name": t.name,
                "cpu": cpu,
                "frame": _frame_fp(frames, t.ident),
            }
        # Only the loop's wchan per sample (one read) — the other
        # threads' wchan is read once when an episode is built.
        return {"ts": time.monotonic(), "threads": threads,
                "loop_wchan": _task_wchan(self.loop_tid)}

    def _run(self) -> None:
        self._sample()  # prime the ring
        while not self._stop.wait(self._interval):
            self._ring.append(self._sample())
            with self._requests_lock:
                pending = self._requests
                self._requests = []
            for _ts, lag_ms in pending:
                self._make_episode(lag_ms)

    def _make_episode(self, lag_ms: float) -> None:
        """Build one episode from the WHOLE ring (~2.5 s).

        The meter flags a lag the moment the loop wakes up — i.e. just
        AFTER the stall — so the stall lives somewhere inside the ring.
        Per-thread CPU deltas run ring-start→ring-end (who burned CPU
        over the window); the loop's frame/wchan are traced across the
        ring with consecutive duplicates collapsed — a stalled loop
        shows its frozen frame repeated (e.g. "… ×24"), while a healthy
        2.5 s of loop samples shows the usual churn."""
        ring = list(self._ring)
        if len(ring) < 2:
            return
        first, last = ring[0], ring[-1]
        if self.loop_tid not in last["threads"]:
            return

        entries = []
        for tid, t1 in last["threads"].items():
            t0 = first["threads"].get(tid)
            if t0 is None:
                continue
            entries.append({
                "tid": tid,
                "name": t1["name"],
                "cpu_ms": _jiffies_to_ms(t1["cpu"] - t0["cpu"]),
                # Live wchan read (one pass, ≤100 ms stale).
                "wchan": _task_wchan(tid),
                "frame": t1["frame"],
            })
        entries.sort(key=lambda e: e["cpu_ms"], reverse=True)
        hogs = [e for e in entries if e["tid"] != self.loop_tid]
        loop0 = first["threads"][self.loop_tid]
        loop1 = last["threads"][self.loop_tid]
        loop_wchan = last.get("loop_wchan", "?")

        # Loop frame trace: collapse consecutive equal (frame, wchan).
        trace = []
        prev = None
        for s in ring:
            lt = s["threads"].get(self.loop_tid)
            if lt is None:
                continue
            key = (lt["frame"], s.get("loop_wchan", "?"))
            if key == prev:
                trace[-1]["n"] += 1
            else:
                trace.append({"frame": key[0], "wchan": key[1], "n": 1})
                prev = key
        # The dominant entry is the most-likely frozen state; report the
        # top entries by run length so a shifting frame stays visible.
        dominant = max(trace, key=lambda e: e["n"])
        episode = {
            "t_mono": last["ts"],
            "wall": time.strftime("%Y-%m-%d %H:%M:%S"),
            "lag_ms": round(lag_ms, 1),
            "window_s": round(last["ts"] - first["ts"], 2),
            "loop": {
                "cpu_ms": round(_jiffies_to_ms(loop1["cpu"] - loop0["cpu"]), 1),
                "wchan": loop_wchan,
                "frame": loop1["frame"],
                "frozen": {"frame": dominant["frame"],
                           "wchan": dominant["wchan"],
                           "samples": dominant["n"]},
            },
            "hog": {k: v for k, v in hogs[0].items()} if hogs else None,
            "threads": [
                {"name": e["name"], "cpu_ms": round(e["cpu_ms"], 1),
                 "wchan": e["wchan"], "frame": e["frame"]}
                for e in entries[:MAX_THREADS_PER_EPISODE]
            ],
        }
        self._episodes.appendleft(episode)
        log.warning(
            "loop stall %.0f ms: loop frozen %s wchan=%s (%d/%d samples, "
            "cpu %.0f ms)%s",
            lag_ms, dominant["frame"], dominant["wchan"],
            dominant["n"], len(ring), episode["loop"]["cpu_ms"],
            f" | hog: {episode['hog']['name']} "
            f"{episode['hog']['frame']} ({episode['hog']['cpu_ms']:.0f} ms cpu)"
            if episode["hog"] else "",
        )

    # ------------------------------------------------------------------
    def episodes(self) -> dict:
        """Snapshot for the debug endpoint."""
        return {
            "threshold_ms": self.threshold_ms,
            "episodes": list(self._episodes),
        }
