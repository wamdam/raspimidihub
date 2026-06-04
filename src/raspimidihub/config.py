"""Configuration persistence for RaspiMIDIHub.

Config is stored on the boot partition (FAT32) and operated from a tmpfs copy.
Save flow: write tmpfs temp -> validate -> remount rw -> copy -> sync -> remount ro -> backup
"""

import contextlib
import gzip
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

PERSISTENT_DIR = Path("/boot/firmware/raspimidihub")
PERSISTENT_CONFIG = PERSISTENT_DIR / "config.json"
RUNTIME_DIR = Path("/run/raspimidihub")
RUNTIME_CONFIG = RUNTIME_DIR / "config.json"

# --- Backups + autosave -------------------------------------------------
# Both live on the (normally read-only) FAT boot partition next to
# config.json. Backups are explicit checkpoints written on each manual
# Save; autosave is a rolling resume-snapshot written debounced while
# editing (and on clean shutdown), double-buffered so a hard power cut
# can never leave us with only a corrupt file.
BACKUP_DIR = PERSISTENT_DIR / "backups"
BACKUP_INDEX = BACKUP_DIR / "index.json"
MAX_BACKUPS = 50
# Two ping-pong autosave slots; gzip's built-in CRC is the validity
# check (a truncated write fails to decompress → we use the other slot).
AUTOSAVE_SLOTS = (PERSISTENT_DIR / "autosave-0.json.gz",
                  PERSISTENT_DIR / "autosave-1.json.gz")
_BOOT_MOUNT = "/boot/firmware"


@contextlib.contextmanager
def _boot_rw():
    """Remount the boot partition read-write for the duration of the
    block, sync, then put it back read-only. Mirrors the rw/ro cycle
    save() has always used — minimising the window in which a power
    cut could touch FAT metadata."""
    subprocess.run(["mount", "-o", "remount,rw", _BOOT_MOUNT],
                   check=True, capture_output=True, timeout=5)
    try:
        yield
        subprocess.run(["sync"], timeout=5)
    finally:
        subprocess.run(["mount", "-o", "remount,ro", _BOOT_MOUNT],
                       capture_output=True, timeout=5)


def uptime_seconds() -> float:
    """Seconds since boot. There is no RTC on the appliance, so wall-clock
    time is unreliable — uptime is the only monotonic reference we have.
    Survives service restarts (CLOCK_MONOTONIC), resets on reboot."""
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return time.monotonic()


def boot_id() -> str:
    """Per-boot UUID (regenerated on each reboot, stable across service
    restarts). Lets us tell whether a backup's stored uptime is
    comparable to 'now' — i.e. was it written in the current boot."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def _count_mappings(cfg: dict) -> int:
    """Total filter-mappings across all connections (active + saved-
    disconnected) — the figure a user most fears losing."""
    total = 0
    for bucket in ("connections", "disconnected"):
        for c in cfg.get(bucket, []) or []:
            if isinstance(c, dict):
                total += len(c.get("mappings") or [])
    return total


def summarize_config_diff(old: dict, new: dict) -> str:
    """A short, human-readable indicator of what changed between two
    configs — structural counts only, not which knob. e.g.
    '+1 instrument · -1 connection · -18 mappings'.

    When none of the counted categories moved we still distinguish two
    cases: 'settings changed' when the configs differ in some other way
    (a renamed cell, a re-bound CC, a drop-button or theme tweak, an
    edited plugin param — anything not reflected in the four counts),
    and '(no changes)' when the two snapshots are byte-for-byte equal.
    '(initial)' when there's no prior config."""
    if not isinstance(old, dict) or not old:
        return "(initial)"
    parts = []

    def delta(label, n_old, n_new):
        d = n_new - n_old
        if d:
            unit = label if abs(d) == 1 else label + "s"
            parts.append(f"{'+' if d > 0 else ''}{d} {unit}")

    delta("instrument", len(old.get("plugins") or []), len(new.get("plugins") or []))
    delta("connection", len(old.get("connections") or []), len(new.get("connections") or []))
    delta("mapping", _count_mappings(old), _count_mappings(new))
    delta("device name", len(old.get("device_names") or {}), len(new.get("device_names") or {}))
    if parts:
        return " · ".join(parts)
    return "settings changed" if old != new else "(no changes)"

DEFAULT_CONFIG = {
    "version": 1,
    "mode": "all-to-all",
    "default_routing": "all",
    "connections": [],
    "disconnected": [],
    "wifi": {
        "mode": "ap",
        "ap_ssid": "",
        "ap_password": "midihub1",
        "client_ssid": "",
        "client_password": "",
        # Phase 5.5: how aggressively the Pi should reach the internet
        # for update fetches. ap_only = stay AP, fail with actionable
        # error if no ethernet path. wifi_for_updates = transient switch
        # to client just for the fetch, then back. wifi_always = stay
        # in client mode (only useful when no AP clients are present).
        "wifi_mode_pref": "ap_only",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, returning new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    """Manages configuration with persistent storage on the boot partition."""

    def __init__(self):
        self._data: dict = DEFAULT_CONFIG.copy()
        self._fallback_active = False
        # Monotonic autosave sequence; restored from the slots on boot
        # so a power cut never makes a stale slot look newer.
        self._autosave_seq = 0
        # When the newest autosave was written, in the no-RTC scheme:
        # uptime seconds + boot id (stamped into the slot and restored
        # on boot). Lets the Backup panel show a "last autosave n ago"
        # for the current boot, or "before last reboot" otherwise.
        # None until the first autosave of this process / a loaded slot.
        self._autosave_up: int | None = None
        self._autosave_boot: str = ""
        # True once load() resolved to an autosave slot — surfaced so
        # the UI can hint "resumed unsaved work" if it wants.
        self._loaded_from_autosave = False
        # Per-instance JSON-fragment cache for the autosave encode:
        # {instance_id: (encode_seq, fragment_bytes)}. json.dumps holds
        # the GIL, so re-encoding every plugin on each autosave would
        # stall the loop ever harder as trackers multiply. Instead we
        # reuse the cached fragment of any instance whose encode_seq
        # hasn't moved (see write_autosave). Empty until the first
        # autosave; cleared whenever instances are wholesale replaced
        # (Load / Restore / Import) via clear_autosave_cache().
        self._autosave_frag_cache: dict[str, tuple[int, bytes]] = {}

    @property
    def data(self) -> dict:
        return self._data

    @property
    def fallback_active(self) -> bool:
        return self._fallback_active

    @property
    def mode(self) -> str:
        return self._data.get("mode", "all-to-all")

    @property
    def default_routing(self) -> str:
        return self._data.get("default_routing", "all")

    @property
    def connections(self) -> list:
        return self._data.get("connections", [])

    @property
    def disconnected(self) -> list:
        return self._data.get("disconnected", [])

    @property
    def wifi(self) -> dict:
        return self._data.get("wifi", DEFAULT_CONFIG["wifi"])

    def _apply_loaded(self, data: dict, source: str) -> None:
        self._data = _deep_merge(DEFAULT_CONFIG, data)
        # Drop the legacy "presets" key — feature was removed, but old
        # configs on disk still carry the dict.
        self._data.pop("presets", None)
        self._fallback_active = False
        log.info("Loaded config from %s", source)

    def _load_from_files(self) -> bool:
        """Load the deliberate save: runtime → persistent → .bak → defaults.
        Returns True if a valid config was found."""
        for path in (RUNTIME_CONFIG, PERSISTENT_CONFIG,
                     PERSISTENT_CONFIG.with_suffix(".json.bak")):
            if path.is_file():
                try:
                    data = json.loads(path.read_text())
                    if not isinstance(data, dict) or "version" not in data:
                        log.warning("Invalid config at %s, trying next", path)
                        continue
                    self._apply_loaded(data, str(path))
                    return True
                except (json.JSONDecodeError, OSError) as e:
                    log.warning("Failed to load %s: %s", path, e)
                    continue
        log.warning("No valid config found, using defaults (all-to-all)")
        self._data = DEFAULT_CONFIG.copy()
        self._fallback_active = True
        return False

    def load(self) -> bool:
        """Boot load. Prefer the newest valid autosave slot (resume the
        last edited state, even after a hard power cut), falling back to
        the deliberate save (runtime → persistent → .bak → defaults).
        Returns True if a valid config (autosave or saved) was loaded.
        """
        self._loaded_from_autosave = False
        snap = self._read_autosave()
        if snap is not None:
            seq, data = snap
            self._autosave_seq = seq
            if isinstance(data, dict) and "version" in data:
                self._apply_loaded(data, f"autosave (seq {seq})")
                self._loaded_from_autosave = True
                return True
        # No usable autosave — fall back to the deliberate save, but keep
        # the autosave seq so the next write doesn't look older than a
        # surviving slot.
        return self._load_from_files()

    def load_manual(self) -> bool:
        """Load the last deliberate Save, ignoring autosave — this backs
        the 'Load' button, whose whole point is to revert to the user's
        committed checkpoint."""
        return self._load_from_files()

    async def aload_manual(self) -> bool:
        import asyncio
        return await asyncio.to_thread(self.load_manual)

    def save(self, make_backup: bool = False) -> bool:
        """Save config to persistent storage with rw/ro remount cycle.
        When `make_backup` is set, a rolling gzipped checkpoint is also
        written inside the same rw window (so a manual Save costs one
        remount, not two). Returns True on success.
        """
        try:
            config_json = json.dumps(self._data, indent=2, ensure_ascii=False)

            # Validate by re-parsing
            json.loads(config_json)

            # Write to runtime copy first
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            tmp = RUNTIME_CONFIG.with_suffix(".tmp")
            tmp.write_text(config_json)
            tmp.replace(RUNTIME_CONFIG)

            # Remount boot partition rw, copy, remount ro
            with _boot_rw():
                PERSISTENT_DIR.mkdir(parents=True, exist_ok=True)

                # Backup existing config
                if PERSISTENT_CONFIG.is_file():
                    shutil.copy2(PERSISTENT_CONFIG, PERSISTENT_CONFIG.with_suffix(".json.bak"))

                # Write new config
                tmp_persistent = PERSISTENT_CONFIG.with_suffix(".tmp")
                tmp_persistent.write_text(config_json)
                tmp_persistent.replace(PERSISTENT_CONFIG)

                if make_backup:
                    try:
                        self._write_backup_locked()
                    except Exception:
                        log.exception("Backup write failed (config still saved)")

            self._fallback_active = False
            log.info("Config saved to %s", PERSISTENT_CONFIG)
            return True

        except Exception:
            log.exception("Failed to save config")
            return False

    async def asave(self, make_backup: bool = False) -> bool:
        """Async wrapper — runs the blocking remount/sync on a worker thread
        so the asyncio event loop keeps pumping MIDI/SSE during the write."""
        import asyncio
        return await asyncio.to_thread(self.save, make_backup)

    # ---- Backups (rolling gzipped checkpoints, written on manual Save) ----

    def _write_backup_locked(self) -> None:
        """Write the current config as a new gzipped backup + index entry,
        pruning to MAX_BACKUPS. MUST be called inside a `_boot_rw()` block
        (the boot partition is rw). Summary is diffed against the most
        recent prior backup so the user sees what changed since then."""
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        index = self._read_backup_index()
        prev = self._read_backup_data(index[-1]["seq"]) if index else {}
        seq = (index[-1]["seq"] + 1) if index else 1
        summary = summarize_config_diff(prev, self._data)
        fname = f"backup-{seq:05d}.json.gz"
        blob = gzip.compress(
            json.dumps(self._data, ensure_ascii=False).encode("utf-8"))
        (BACKUP_DIR / fname).write_bytes(blob)
        # Store uptime + boot id instead of a wall-clock date — the
        # appliance has no RTC, so an absolute timestamp would be a lie.
        # The UI turns these into a relative "n ago" for the current boot.
        index.append({"seq": seq, "up": int(uptime_seconds()), "boot": boot_id(),
                      "summary": summary, "bytes": len(blob), "file": fname})
        # Prune oldest beyond MAX_BACKUPS.
        while len(index) > MAX_BACKUPS:
            old = index.pop(0)
            with contextlib.suppress(OSError):
                (BACKUP_DIR / old["file"]).unlink()
        BACKUP_INDEX.write_text(json.dumps(index, indent=2))

    def _read_backup_index(self) -> list:
        try:
            idx = json.loads(BACKUP_INDEX.read_text())
            return idx if isinstance(idx, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _read_backup_data(self, seq: int) -> dict:
        for e in self._read_backup_index():
            if e.get("seq") == seq:
                try:
                    raw = gzip.decompress((BACKUP_DIR / e["file"]).read_bytes())
                    return json.loads(raw)
                except (OSError, json.JSONDecodeError, gzip.BadGzipFile):
                    return {}
        return {}

    def list_backups(self) -> list:
        """Newest-first list for the UI: {seq, summary, bytes, age_seconds,
        same_session}. `age_seconds` is how long ago (within the current
        boot) the backup was written; it's None for backups from an
        earlier boot, where no honest relative time exists (no RTC) and
        only `seq` gives ordering."""
        cur_up = uptime_seconds()
        cur_boot = boot_id()
        out = []
        for e in sorted(self._read_backup_index(),
                        key=lambda x: x.get("seq", 0), reverse=True):
            same = bool(e.get("boot")) and e.get("boot") == cur_boot
            age = int(cur_up - e.get("up", 0)) if same else None
            if age is not None and age < 0:
                age = None  # clock skew guard
            out.append({"seq": e.get("seq"), "summary": e.get("summary", ""),
                        "bytes": e.get("bytes", 0),
                        "age_seconds": age, "same_session": same})
        return out

    def backup_data(self, seq: int) -> dict:
        """Decompressed config dict for one backup, or {} if missing."""
        return self._read_backup_data(int(seq))

    # ---- Autosave (debounced rolling resume-snapshot, ping-pong) ----

    def clear_autosave_cache(self) -> None:
        """Drop the per-instance fragment cache. Called when the live
        instance set is wholesale replaced (Load / Restore / Import) —
        the recreated instances start their encode_seq counters fresh,
        so a stale (id, seq) pair could otherwise falsely match and
        splice an outdated fragment into the next autosave."""
        self._autosave_frag_cache.clear()

    def _encode_instance(self, inst: dict) -> bytes:
        """JSON-encode one serialized plugin instance to a fragment.
        Isolated so the cache hit/miss path (and tests) can count how
        many instances actually get re-encoded per autosave."""
        return json.dumps(inst, ensure_ascii=False).encode("utf-8")

    def _encode_autosave_payload(self, seq: int, up: int, boot: str,
                                 plugin_seqs) -> bytes:
        """Build the autosave payload bytes
        ({"seq", "up", "boot", "data": {...}}). `up`/`boot` stamp WHEN
        the slot was written (uptime + boot id, the no-RTC scheme) so
        the Backup panel can show a "last autosave n ago".

        With `plugin_seqs` ({instance_id: encode_seq}) we splice the
        `plugins` array from per-instance JSON fragments, reusing the
        cached fragment of any instance whose encode_seq is unchanged
        and re-encoding only the ones that moved — so the GIL-holding
        json.dumps cost scales with *edited* trackers, not their total
        count. Without it (no plugin host) we fall back to a plain
        full-document encode."""
        if plugin_seqs is None:
            return json.dumps(
                {"seq": seq, "up": up, "boot": boot, "data": self._data},
                ensure_ascii=False).encode("utf-8")

        cache = self._autosave_frag_cache
        plugins = self._data.get("plugins") or []
        frags = []
        live_ids = set()
        for inst in plugins:
            iid = inst.get("id") if isinstance(inst, dict) else None
            eseq = plugin_seqs.get(iid) if iid is not None else None
            cached = cache.get(iid) if iid is not None else None
            if eseq is not None and cached is not None and cached[0] == eseq:
                frag = cached[1]
            else:
                frag = self._encode_instance(inst)
                if iid is not None and eseq is not None:
                    cache[iid] = (eseq, frag)
            frags.append(frag)
            if iid is not None:
                live_ids.add(iid)
        # Evict cache entries for instances that no longer exist.
        for stale in set(cache) - live_ids:
            del cache[stale]

        plugins_bytes = b"[" + b",".join(frags) + b"]"
        # Encode every top-level field EXCEPT plugins fresh (they're
        # small and cheap), then splice the assembled plugins array in
        # by hand so we never json.dumps the big plugin payload whole.
        top = {k: v for k, v in self._data.items() if k != "plugins"}
        data_top = json.dumps(top, ensure_ascii=False).encode("utf-8")
        if data_top == b"{}":
            data_bytes = b'{"plugins":' + plugins_bytes + b"}"
        else:
            data_bytes = data_top[:-1] + b',"plugins":' + plugins_bytes + b"}"
        return (b'{"seq":' + str(seq).encode("ascii")
                + b',"up":' + str(int(up)).encode("ascii")
                + b',"boot":' + json.dumps(boot).encode("utf-8")
                + b',"data":' + data_bytes + b"}")

    def write_autosave(self, plugin_seqs=None) -> bool:
        """Persist the current in-memory config to the next ping-pong
        slot so a hard power cut resumes the last edited state on boot.
        Writes the slot NOT holding the current sequence, so the prior
        good snapshot always survives. `plugin_seqs` ({instance_id:
        encode_seq}, captured on the loop) enables the per-instance
        fragment cache. Returns True on success."""
        try:
            seq = self._autosave_seq + 1
            slot = AUTOSAVE_SLOTS[seq % 2]
            up, boot = int(uptime_seconds()), boot_id()
            # json.dumps holds the GIL (stalls the loop); gzip + io
            # release it, so only the encode is on the critical path —
            # which is exactly what the fragment cache shrinks.
            payload = self._encode_autosave_payload(seq, up, boot, plugin_seqs)
            blob = gzip.compress(payload)
            with _boot_rw():
                PERSISTENT_DIR.mkdir(parents=True, exist_ok=True)
                slot.write_bytes(blob)
            self._autosave_seq = seq
            self._autosave_up = up
            self._autosave_boot = boot
            return True
        except Exception:
            log.exception("Autosave failed")
            return False

    def _read_autosave(self):
        """Return (seq, data) of the newest valid autosave slot, or None.
        Side effect: records the winning slot's write-time (uptime +
        boot id) on self so autosave_status() can report it after a
        boot-time load (older v1 slots without these keys → unknown)."""
        best = None
        for slot in AUTOSAVE_SLOTS:
            if not slot.is_file():
                continue
            try:
                obj = json.loads(gzip.decompress(slot.read_bytes()))
                seq, data = int(obj["seq"]), obj["data"]
                if not isinstance(data, dict):
                    continue
                if best is None or seq > best[0]:
                    best = (seq, data, obj.get("up"), obj.get("boot", ""))
            except (OSError, json.JSONDecodeError, gzip.BadGzipFile, KeyError, ValueError):
                continue
        if best is None:
            return None
        seq, data, up, boot = best
        self._autosave_up = int(up) if isinstance(up, (int, float)) else None
        self._autosave_boot = boot or ""
        return (seq, data)

    def autosave_status(self) -> dict | None:
        """Relative-time status of the newest autosave, for the Backup
        panel: {seq, age_seconds, same_session}. None if no autosave
        has been written this boot or loaded from a slot. age_seconds
        is None for an autosave from a previous boot (no honest
        relative time without an RTC) — the UI shows 'before last
        reboot' then."""
        if self._autosave_up is None:
            return None
        cur_up = uptime_seconds()
        same = bool(self._autosave_boot) and self._autosave_boot == boot_id()
        age = int(cur_up - self._autosave_up) if same else None
        if age is not None and age < 0:
            age = None  # clock-skew / restart guard
        return {"seq": self._autosave_seq, "age_seconds": age,
                "same_session": same}

    async def aload(self) -> bool:
        """Async wrapper around load() — symmetric with asave()."""
        import asyncio
        return await asyncio.to_thread(self.load)

    def init_runtime_copy(self):
        """Copy persistent config to runtime tmpfs (called at boot via ExecStartPre)."""
        try:
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            if PERSISTENT_CONFIG.is_file():
                shutil.copy2(PERSISTENT_CONFIG, RUNTIME_CONFIG)
                log.info("Copied config to runtime: %s", RUNTIME_CONFIG)
        except PermissionError:
            log.warning("Cannot create %s (not root?), using in-memory config", RUNTIME_DIR)
            log.info("Copied config to runtime: %s", RUNTIME_CONFIG)

    def set_mode(self, mode: str):
        self._data["mode"] = mode

    def set_connections(self, connections: list):
        self._data["connections"] = connections
