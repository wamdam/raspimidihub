"""Stable device identification for USB / BLE / built-in MIDI devices.

ALSA client IDs change on every reconnect. We need stable identifiers
to persist routing configurations across reboots and reconnects.

Stable ID formats:
  USB w/ serial: "usb-<vid>:<pid>-<serial>"     (canonical, port-independent)
  USB w/o serial:"usb-<bus>-<port_path>-<vid>:<pid>"  (legacy, port-bound)
  Bluetooth:     "bt-<mac_address>"
  Built-in:      "builtin-<card_id>"
  Plugin:        "plugin-<instance_id>"

A USB device with a usable iSerialNumber is identified by it — the ID
survives replugging into any port. Devices without one (or with a
factory placeholder like "000000000001") fall back to the port-bound
legacy form; for two *identical* serial-less devices the port is the
only distinguishing feature there is.

Re-recognition of moved / renamed devices is handled by the registry's
session aliases (see DeviceRegistry.scan): a device whose saved ID no
longer matches is re-bound by exact port evidence or — only for newly
appeared devices, and only when unambiguous — by a VID:PID soft match.
Aliases are in-memory; the config keeps the saved IDs until a
deliberate Save commits the migration (commit_aliases)."""

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Cache for `_get_bluealsa_macs()`. Two `bluetoothctl devices ...`
# subprocesses run per call (~100 ms each), and scan_devices() calls
# this twice (engine + registry), so every refresh of /api/devices was
# spending ~400 ms on what's almost always the same data. Pair/connect
# state changes rarely; cache for a few seconds and invalidate
# explicitly from the BT API endpoints when needed.
_BT_MACS_TTL_S = 10.0
_bt_macs_cache: dict = {"value": None, "ts": 0.0}


def invalidate_bluealsa_macs_cache() -> None:
    """Force the next `_get_bluealsa_macs()` call to re-query bluetoothctl.

    Call after any operation that changes BT pair / connect state so
    a follow-up device scan sees the new device or its absence."""
    _bt_macs_cache["value"] = None
    _bt_macs_cache["ts"] = 0.0


@dataclass
class StableDeviceInfo:
    stable_id: str  # The REGISTERED identity — canonical, or a session alias
    vid: str  # USB vendor ID (hex)
    pid: str  # USB product ID (hex)
    usb_path: str  # USB topology path (e.g. "1-1.2")
    card_num: int  # ALSA card number
    display_name: str  # User-facing name (custom or default)
    custom_name: str = ""  # User-assigned name (empty = use default)
    is_plugin: bool = False  # True for virtual instrument plugins
    is_bluetooth: bool = False  # True for BLE-MIDI devices via BlueALSA
    serial: str = ""  # Usable USB serial ("" if absent or a placeholder)
    canonical_id: str = ""  # The device's own identity (serial or port form)
    legacy_id: str = ""  # Port-bound form, always set for USB devices

    @property
    def name(self) -> str:
        return self.custom_name or self.display_name


def _identity_serial(raw: str) -> str:
    """Sanitize a USB iSerialNumber for use as a device identity.

    Returns "" when the serial is missing or obviously a factory
    placeholder — using a placeholder would COLLIDE two identical
    devices on a port-independent ID, which is worse than today's
    port-bound behaviour. Rejected: very short values, single
    repeated characters, and all-zeros(-then-one) patterns (the
    Digitone II ships "000000000001").

    Characters outside [A-Za-z0-9_.-] are replaced with "-" so the
    result is safe inside connection IDs and URLs (Roland pads
    serials with trailing spaces, for example)."""
    s = (raw or "").strip()
    if len(s) < 3:
        return ""
    if re.fullmatch(r"0+1?", s):
        return ""
    if len(set(s)) == 1:
        return ""
    return re.sub(r"[^A-Za-z0-9_.\-]", "-", s)


def vidpid_of_stable_id(stable_id: str) -> str | None:
    """Extract "vid:pid" from either USB stable-ID form, or None.

    Disambiguated IDs ("...#2") return None on purpose — a saved entry
    for one of several identical devices must never be soft-matched."""
    if "#" in stable_id:
        return None
    m = re.match(r"^usb-([0-9a-fA-F]{4}:[0-9a-fA-F]{4})-", stable_id)
    if m:
        return m.group(1).lower()
    m = re.search(r"-([0-9a-fA-F]{4}:[0-9a-fA-F]{4})$", stable_id)
    if m:
        return m.group(1).lower()
    return None


def _find_usb_ancestor(device_path: Path) -> Path | None:
    """Walk up sysfs to find the USB device node (has idVendor)."""
    path = device_path.resolve()
    for _ in range(10):  # max depth
        if (path / "idVendor").is_file():
            return path
        parent = path.parent
        if parent == path:
            break
        path = parent
    return None


def get_card_stable_id(card_num: int) -> StableDeviceInfo | None:
    """Get stable identification for an ALSA sound card."""
    card_path = Path(f"/sys/class/sound/card{card_num}")
    if not card_path.exists():
        return None

    device_link = card_path / "device"
    if not device_link.exists():
        # Built-in device without a device link
        try:
            card_id = (card_path / "id").read_text().strip()
        except OSError:
            card_id = f"card{card_num}"
        return StableDeviceInfo(
            stable_id=f"builtin-{card_id}",
            vid="", pid="", usb_path="",
            card_num=card_num,
            display_name=card_id,
        )

    usb_dev = _find_usb_ancestor(device_link)
    if usb_dev is None:
        # Non-USB device (e.g. platform device)
        try:
            card_id = (card_path / "id").read_text().strip()
        except OSError:
            card_id = f"card{card_num}"
        return StableDeviceInfo(
            stable_id=f"builtin-{card_id}",
            vid="", pid="", usb_path="",
            card_num=card_num,
            display_name=card_id,
        )

    try:
        vid = (usb_dev / "idVendor").read_text().strip()
        pid = (usb_dev / "idProduct").read_text().strip()
    except OSError:
        vid, pid = "0000", "0000"

    # USB path: extract bus and port path from the sysfs path
    # e.g. /sys/devices/platform/soc/3f980000.usb/usb1/1-1/1-1.2/...
    usb_path = ""
    dev_name = usb_dev.name  # e.g. "1-1.2" or "1-1.4:1.0"
    # Strip interface number if present
    dev_name = dev_name.split(":")[0]
    usb_path = dev_name

    try:
        card_id = (card_path / "id").read_text().strip()
    except OSError:
        card_id = f"card{card_num}"

    # Try to get a better display name from USB product string
    display_name = card_id
    try:
        product = (usb_dev / "product").read_text().strip()
        if product:
            display_name = product
    except OSError:
        pass

    try:
        serial = _identity_serial((usb_dev / "serial").read_text())
    except OSError:
        serial = ""

    # Canonical identity: serial-based (port-independent) when the
    # device has a usable serial, otherwise the port-bound legacy form.
    legacy_id = f"usb-{usb_path}-{vid}:{pid}"
    canonical_id = f"usb-{vid}:{pid}-{serial}" if serial else legacy_id

    return StableDeviceInfo(
        stable_id=canonical_id,
        vid=vid, pid=pid,
        usb_path=usb_path,
        card_num=card_num,
        display_name=display_name,
        serial=serial,
        canonical_id=canonical_id,
        legacy_id=legacy_id,
    )


def alsa_client_to_card(client_id: int) -> int | None:
    """Map an ALSA sequencer client ID to a sound card number.

    Tries multiple strategies:
    1. Parse card= from /proc/asound/seq/clients (works on some kernels)
    2. Match seq client name to card long name in /proc/asound/cards
    3. Scan /proc/asound/cardN/midiN for matching content
    """
    # Strategy 1: direct card number from seq/clients
    client_name = None
    try:
        with open("/proc/asound/seq/clients") as f:
            current_client = None
            for line in f:
                m = re.match(r'^Client\s+(\d+)\s*:\s*"(.+?)"', line)
                if m:
                    current_client = int(m.group(1))
                    m.group(2)
                    continue
                if current_client == client_id:
                    cm = re.search(r'\[.*card\s*=\s*(\d+)', line)
                    if cm:
                        return int(cm.group(1))
            # Remember the client name for strategy 2
            # Re-scan to get the name for our client_id
        with open("/proc/asound/seq/clients") as f:
            for line in f:
                m = re.match(r'^Client\s+(\d+)\s*:\s*"(.+?)"', line)
                if m and int(m.group(1)) == client_id:
                    client_name = m.group(2)
                    break
    except OSError:
        pass

    # Strategy 2: match client name to /proc/asound/cards long name
    if client_name:
        try:
            with open("/proc/asound/cards") as f:
                for line in f:
                    cm = re.match(r'^\s*(\d+)\s+\[', line)
                    if cm:
                        card_num = int(cm.group(1))
                        # Next line has the long name
                        next_line = next(f, "").strip()
                        if client_name in next_line:
                            return card_num
        except OSError:
            pass

    # Strategy 3: scan /proc/asound/cardN/midiN for matching name
    if client_name:
        for card_dir in sorted(Path("/proc/asound").glob("card*")):
            try:
                card_num = int(card_dir.name.replace("card", ""))
            except ValueError:
                continue
            for midi_file in card_dir.glob("midi*"):
                try:
                    content = midi_file.read_text()
                    if client_name in content:
                        return card_num
                except OSError:
                    pass

    return None


def _get_bluealsa_macs() -> dict[str, str]:
    """Map BT device names → MAC addresses via bluetoothctl.

    Covers BOTH Paired and Connected devices because BLE-MIDI peripherals
    (e.g. WIDI Master) often show up Connected without being Paired —
    BlueZ creates an ALSA seq client for them either way. The legacy
    `paired-devices` subcommand was removed from bluetoothctl years ago;
    `devices Paired` / `devices Connected` are the current syntax.

    Cached for `_BT_MACS_TTL_S` seconds; the BT API endpoints call
    `invalidate_bluealsa_macs_cache()` after any operation that mutates
    pair / connect state.

    Returns {} silently on any error so callers can blindly use the dict
    as a "is this name a BT device?" lookup without try/except blocks."""
    now = time.monotonic()
    cached = _bt_macs_cache["value"]
    if cached is not None and (now - _bt_macs_cache["ts"]) < _BT_MACS_TTL_S:
        return cached
    macs: dict[str, str] = {}
    for sub in ("Paired", "Connected"):
        try:
            result = subprocess.run(
                ["bluetoothctl", "devices", sub],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                m = re.match(r"^Device\s+([0-9A-Fa-f:]{17})\s+(.+)$", line)
                if m:
                    macs[m.group(2)] = m.group(1)  # name → MAC
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    _bt_macs_cache["value"] = macs
    _bt_macs_cache["ts"] = now
    return macs


class DeviceRegistry:
    """Maps between ALSA client IDs and stable device identifiers."""

    def __init__(self):
        self._by_client: dict[int, StableDeviceInfo] = {}
        self._by_stable_id: dict[str, StableDeviceInfo] = {}
        self._custom_names: dict[str, str] = {}  # stable_id -> custom name
        # Set of stable_ids whose CLOCK / START / STOP / CONTINUE
        # events should NOT feed the global ClockBus. Used when more
        # than one piece of hardware sends MIDI Clock and the user
        # wants only one to drive the system tempo. Read on the
        # engine's hot path (every clock tick) — keep it a set lookup.
        self._clock_blocked: set[str] = set()
        # --- Re-recognition state (session-scoped, never persisted) ---
        # canonical_id -> the saved ID this device is registered under.
        # An alias means "this device IS the one the config calls X".
        # Cleared per-entry by commit_aliases() (deliberate Save) or
        # when the saved ID stops being referenced by the config.
        self._alias_by_canonical: dict[str, str] = {}
        # Canonical IDs present in the previous scan. Soft-matching is
        # restricted to devices NOT in here ("newly appeared") so a
        # device that was demonstrably co-present with the saved one
        # can never be mistaken for it mid-session. reset_presence()
        # re-arms everything (Load / Restore / Import = boot-like).
        self._present_canonicals: set[str] = set()
        # stable_ids the current config refers to (connections,
        # disconnected, device names, clock-block list). Refreshed by
        # the engine before every scan.
        self._referenced_ids: set[str] = set()

    def load_custom_names(self, names: dict[str, str]):
        """Load custom device names from config."""
        self._custom_names = dict(names)

    def set_referenced_ids(self, ids: set[str]) -> None:
        """Tell the registry which stable_ids the current config uses.

        Drives identity resolution in scan(): referenced IDs are what
        unresolved devices can be re-bound to. The engine refreshes
        this before every scan so Load / Restore / Import are covered
        automatically."""
        self._referenced_ids = set(ids)

    def reset_presence(self) -> None:
        """Forget which devices were present in the previous scan.

        The next scan treats every device as newly appeared, making
        them all eligible for soft-matching — boot-like semantics.
        Called when a config is deliberately (re)loaded."""
        self._present_canonicals = set()

    def aliases(self) -> dict[str, str]:
        """Active session aliases as {saved_id: canonical_id}."""
        return {saved: canonical
                for canonical, saved in self._alias_by_canonical.items()}

    def commit_aliases(self) -> dict[str, str]:
        """Migrate all aliased devices to their canonical IDs.

        Called by the deliberate Save: re-registers each aliased device
        under its canonical ID and re-keys custom names + clock-block
        entries, then returns {saved_id: canonical_id} so the caller
        can persist the migrated references. Until this runs, the
        config keeps the saved IDs (aliases are session-only), so a
        wrong soft-match can never be cemented by the autosave."""
        migrated: dict[str, str] = {}
        for canonical, saved in list(self._alias_by_canonical.items()):
            info = self._by_stable_id.pop(saved, None)
            if info is not None:
                info.stable_id = canonical
                self._by_stable_id[canonical] = info
            migrated[saved] = canonical
            if saved in self._custom_names:
                self._custom_names.setdefault(
                    canonical, self._custom_names.pop(saved))
            if saved in self._clock_blocked:
                self._clock_blocked.discard(saved)
                self._clock_blocked.add(canonical)
            log.info("Committed device identity %s -> %s", saved, canonical)
        self._alias_by_canonical.clear()
        return migrated

    def load_clock_blocked(self, stable_ids: list[str]) -> None:
        """Restore the clock-blocked set from config at boot."""
        self._clock_blocked = set(stable_ids or [])

    def set_clock_blocked(self, stable_id: str, blocked: bool) -> None:
        """Block (or unblock) a device's MIDI Clock from feeding the
        ClockBus. Idempotent; survives hotplug because we key on
        stable_id, not the volatile ALSA client_id."""
        if blocked:
            self._clock_blocked.add(stable_id)
        else:
            self._clock_blocked.discard(stable_id)

    def is_clock_blocked(self, stable_id: str) -> bool:
        return stable_id in self._clock_blocked

    def is_client_clock_blocked(self, client_id: int) -> bool:
        """Hot-path lookup used by the engine for every Clock event.
        Returns False for unknown clients so a brand-new device that
        plugged in before its scan finished still feeds the bus."""
        info = self._by_client.get(client_id)
        if info is None:
            return False
        return info.stable_id in self._clock_blocked

    def get_clock_blocked(self) -> list[str]:
        """Sorted list for stable JSON serialization in config."""
        return sorted(self._clock_blocked)

    def scan(self, alsa_client_ids: list[int],
             client_names: dict[int, str] | None = None,
             ) -> dict[int, StableDeviceInfo]:
        """Scan and register devices for the given ALSA client IDs.

        `client_names` is an optional `{client_id: ALSA-client-name}`
        mapping. When provided, BlueALSA-managed BLE-MIDI clients are
        detected by name and registered with `bt-<MAC>` stable ids.
        Caller passes None for non-BT setups to skip the bluetoothctl
        subprocess entirely."""
        self._by_client.clear()
        self._by_stable_id.clear()

        # Track how many times each base stable_id appears to disambiguate
        seen_ids: dict[str, int] = {}
        # USB devices register after the loop so identity resolution
        # (exact / legacy / alias / soft-match) sees them all at once.
        usb_pending: list[tuple[int, StableDeviceInfo]] = []

        # Detect Bluetooth MIDI devices (BlueALSA clients). Only
        # populate the MAC map if we have client_names — without it
        # there's nothing to match against.
        bt_macs = _get_bluealsa_macs() if client_names else {}

        for client_id in sorted(alsa_client_ids):
            name = client_names.get(client_id, "") if client_names else ""

            # BLE-MIDI: BlueZ (or bluealsa with `-p midi`) creates an
            # ALSA seq client whose name == the BT device alias when a
            # BLE-MIDI peripheral is connected. Match against the
            # name→MAC table from bluetoothctl. Use the MAC as the
            # stable id so routing survives reconnects (the ALSA
            # client id changes every session).
            if name and name in bt_macs:
                mac = bt_macs.get(name)
                if mac:
                    stable_id = f"bt-{mac}"
                    info = StableDeviceInfo(
                        stable_id=stable_id,
                        vid="", pid="", usb_path="",
                        card_num=-1,
                        display_name=name,
                        is_bluetooth=True,
                    )
                    if stable_id in self._custom_names:
                        info.custom_name = self._custom_names[stable_id]
                    self._by_client[client_id] = info
                    self._by_stable_id[stable_id] = info
                    continue

            card_num = alsa_client_to_card(client_id)
            if card_num is None:
                continue

            info = get_card_stable_id(card_num)
            if info is None:
                continue

            if info.legacy_id:
                # USB device — identity is decided collectively after
                # the loop (exact / legacy / alias / soft-match).
                usb_pending.append((client_id, info))
            else:
                self._register(client_id, info, seen_ids)

        self._resolve_usb_identities(usb_pending)
        for client_id, info in usb_pending:
            self._register(client_id, info, seen_ids)

        return self._by_client

    def _register(self, client_id: int, info: StableDeviceInfo,
                  seen_ids: dict[str, int]) -> None:
        """Register a device under its (resolved) stable_id, with #N
        disambiguation for duplicates and custom-name lookup."""
        base_id = info.stable_id
        count = seen_ids.get(base_id, 0) + 1
        seen_ids[base_id] = count
        if count > 1:
            info.stable_id = f"{base_id}#{count}"
            log.info("Duplicate device %s, disambiguated to %s",
                     base_id, info.stable_id)

        if info.stable_id in self._custom_names:
            info.custom_name = self._custom_names[info.stable_id]

        self._by_client[client_id] = info
        self._by_stable_id[info.stable_id] = info

    def _resolve_usb_identities(
            self, pending: list[tuple[int, StableDeviceInfo]]) -> None:
        """Decide which stable_id each USB device registers under.

        Rules, in order (also see the module docstring):
          exact:  the device's canonical ID is referenced by the config
                  -> register as canonical.
          legacy: its port-bound form is referenced -> register under
                  that (same evidence as the pre-serial scheme; this
                  supersedes an alias another device may hold on the ID).
          alias:  a previously established session alias sticks while
                  its target is still referenced.
          soft:   a NEWLY APPEARED, unclaimed device with exactly one
                  unresolved referenced entry of the same VID:PID ->
                  bind as a session alias. Any ambiguity (2 entries, 2
                  candidates, "#N" entries) -> no match, on purpose.
        """
        referenced = {r for r in self._referenced_ids if r.startswith("usb-")}
        present_now = {info.canonical_id for _, info in pending}

        # Self-cleaning: drop aliases whose device is gone or whose
        # target the config no longer references (e.g. after Load).
        self._alias_by_canonical = {
            c: t for c, t in self._alias_by_canonical.items()
            if c in present_now and t in referenced}

        appeared = present_now - self._present_canonicals
        self._present_canonicals = present_now

        # Pass 1 — evidence-based claims. claims: saved_id -> canonical
        # of the device that proved ownership this scan.
        claims: dict[str, str] = {}
        for _, info in pending:
            if info.canonical_id in referenced:
                info.stable_id = info.canonical_id
                self._alias_by_canonical.pop(info.canonical_id, None)
                claims[info.canonical_id] = info.canonical_id
            elif (info.legacy_id != info.canonical_id
                  and info.legacy_id in referenced):
                info.stable_id = info.legacy_id
                self._alias_by_canonical[info.canonical_id] = info.legacy_id
                claims[info.legacy_id] = info.canonical_id

        # Exact evidence supersedes a foreign alias on the same ID: the
        # impostor reverts to its canonical identity this scan.
        for canonical, saved in list(self._alias_by_canonical.items()):
            if saved in claims and claims[saved] != canonical:
                del self._alias_by_canonical[canonical]
                log.info("Alias %s -> %s superseded by exact match",
                         saved, canonical)

        # Pass 2 — apply surviving aliases.
        for _, info in pending:
            if info.stable_id != info.canonical_id:
                continue  # resolved in pass 1
            saved = self._alias_by_canonical.get(info.canonical_id)
            if saved and saved not in claims:
                info.stable_id = saved
                claims[saved] = info.canonical_id

        # Pass 3 — soft-match: unresolved referenced entries vs newly
        # appeared, unclaimed devices, 1:1 per VID:PID only.
        registered_ids = {info.stable_id for _, info in pending}
        unresolved_by_vp: dict[str, list[str]] = {}
        for sid in referenced - registered_ids:
            vp = vidpid_of_stable_id(sid)
            if vp:
                unresolved_by_vp.setdefault(vp, []).append(sid)
        cands_by_vp: dict[str, list[StableDeviceInfo]] = {}
        for _, info in pending:
            if (info.stable_id == info.canonical_id
                    and info.canonical_id not in referenced
                    and info.legacy_id not in referenced
                    and info.canonical_id not in self._alias_by_canonical
                    and info.canonical_id in appeared):
                vp = f"{info.vid}:{info.pid}".lower()
                cands_by_vp.setdefault(vp, []).append(info)
        for vp, sids in unresolved_by_vp.items():
            cands = cands_by_vp.get(vp, [])
            if len(sids) == 1 and len(cands) == 1:
                info, saved = cands[0], sids[0]
                self._alias_by_canonical[info.canonical_id] = saved
                info.stable_id = saved
                log.info("Re-recognized %s as saved device %s "
                         "(unambiguous VID:PID match)",
                         info.canonical_id, saved)

    def get_by_client(self, client_id: int) -> StableDeviceInfo | None:
        return self._by_client.get(client_id)

    def get_by_stable_id(self, stable_id: str) -> StableDeviceInfo | None:
        return self._by_stable_id.get(stable_id)

    def client_for_stable_id(self, stable_id: str) -> int | None:
        """Find current ALSA client ID for a stable device ID."""
        for client_id, info in self._by_client.items():
            if info.stable_id == stable_id:
                return client_id
        return None

    def set_custom_name(self, stable_id: str, name: str):
        """Set a custom display name for a device."""
        self._custom_names[stable_id] = name
        if stable_id in self._by_stable_id:
            self._by_stable_id[stable_id].custom_name = name

    def get_custom_names(self) -> dict[str, str]:
        return dict(self._custom_names)

    def register_plugin(self, client_id: int, instance_id: str, display_name: str) -> StableDeviceInfo:
        """Register a plugin virtual device (no sysfs card, stable ID = plugin-{id})."""
        stable_id = f"plugin-{instance_id}"
        info = StableDeviceInfo(
            stable_id=stable_id,
            vid="", pid="", usb_path="",
            card_num=-1,
            display_name=display_name,
            is_plugin=True,
        )
        if stable_id in self._custom_names:
            info.custom_name = self._custom_names[stable_id]
        self._by_client[client_id] = info
        self._by_stable_id[stable_id] = info
        return info

    def unregister_plugin(self, instance_id: str) -> None:
        """Remove a plugin device from the registry."""
        stable_id = f"plugin-{instance_id}"
        self._by_stable_id.pop(stable_id, None)
        to_remove = [cid for cid, info in self._by_client.items() if info.stable_id == stable_id]
        for cid in to_remove:
            del self._by_client[cid]

    def all_devices(self) -> list[StableDeviceInfo]:
        return list(self._by_client.values())
