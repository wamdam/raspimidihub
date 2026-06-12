"""MIDI routing engine with hotplug support.

Manages all-to-all MIDI connections between USB MIDI devices
using the ALSA sequencer API.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from .alsa_seq import AlsaSeq, MidiDevice, MidiEventType, SeqEventType
from .device_id import DeviceRegistry
from .midi_filter import FilterEngine, MidiFilter, MidiMapping

log = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 0.5


def _edge_needs_userspace(filter_dict: dict | None,
                          mapping_dicts: list[dict]) -> bool:
    """True if a (filter, mappings) pair must run via the FilterEngine."""
    if mapping_dicts:
        return True
    if filter_dict and not MidiFilter.from_dict(filter_dict).is_passthrough:
        return True
    return False


def _normalised_filter(filter_dict: dict | None) -> dict | None:
    """Round-trip a filter dict through MidiFilter so the comparison is
    insensitive to msg_types order, missing channel_mask defaults, etc."""
    if not filter_dict:
        return None
    return MidiFilter.from_dict(filter_dict).to_dict()


def _filter_equal(a: dict | None, b: dict | None) -> bool:
    return _normalised_filter(a) == _normalised_filter(b)


def _mappings_equal(a: list[dict], b: list[dict]) -> bool:
    """Compare two mapping lists by their canonicalised dict form."""
    if len(a) != len(b):
        return False
    norm = lambda lst: [MidiMapping.from_dict(m).to_dict() for m in lst]
    try:
        return norm(a) == norm(b)
    except (KeyError, ValueError):
        return a == b


@dataclass
class Connection:
    src_client: int
    src_port: int
    dst_client: int
    dst_port: int

    def __hash__(self):
        return hash((self.src_client, self.src_port, self.dst_client, self.dst_port))

    def __eq__(self, other):
        return (self.src_client, self.src_port, self.dst_client, self.dst_port) == \
               (other.src_client, other.src_port, other.dst_client, other.dst_port)


class MidiEngine:
    """Manages MIDI device discovery and all-to-all routing."""

    def __init__(self):
        self._seq: AlsaSeq | None = None
        self._devices: list[MidiDevice] = []
        self._connections: set[Connection] = set()
        self._disconnected: dict[str, dict] = {}  # conn_id -> {filter, mappings}
        self._filter_engine: FilterEngine | None = None
        self._device_registry: DeviceRegistry = DeviceRegistry()
        self._plugin_host = None  # set externally after import
        self._monitor_port: int = -1
        self._monitored_clients: set[int] = set()
        self._debounce_task: asyncio.Task | None = None
        self._running = False
        self._config = None  # set externally for config-aware rescan
        # Stable-IDs known at the END of the last _scan_and_connect.
        # Used to compute "newly appeared" devices for the saved-config
        # restore on hotplug. We don't read self._devices for this
        # because external read-only callers (e.g. GET /api/devices)
        # can call scan_devices() between the bridge appearing and the
        # debounced rescan running, polluting self._devices with the
        # new device — which would make `appeared` empty and skip the
        # saved connections for that device.
        self._stable_ids_at_last_scan_and_connect: set[str] = set()
        self._on_change_callbacks: list = []
        self._on_midi_event_callbacks: list = []
        self._on_transport_start_callbacks: list = []
        # Optional latency reporter — set by __main__ to server.record_latency.
        # Used by run_event_loop to measure userspace-routed midi-in→midi-out.
        self._latency_cb = None
        # Config-dirty tracker: True iff the in-memory routing/plugin/filter
        # state diverges from /boot/firmware/raspimidihub/config.json.
        # Mutations call mark_dirty(); save_config / load_config clear it.
        # Drives the small dark-red asterisk on the bottom-nav Routing icon.
        # _dirty_loop + _dirty_sse_cb together let mark/clear (which are
        # often called from sync code paths and worker threads) schedule
        # an SSE broadcast on the asyncio loop without crossing thread
        # boundaries unsafely.
        self.config_dirty = False
        self._dirty_loop = None
        self._dirty_sse_cb = None
        # Monotonically-bumped on every mark_dirty (even while already
        # dirty) + the time of the last bump. The autosaver polls these
        # to debounce: write a snapshot a few seconds after edits settle.
        self._change_seq = 0
        self._last_change_t = 0.0
        # Per-port message counters for rate metering
        self._port_msg_counts: dict[str, int] = {}  # "client:port" -> count
        self._port_rates: dict[str, int] = {}  # "client:port" -> msgs/sec (last snapshot)
        # Per-edge note refcount: Connection -> {(channel, note): count}
        # An edge is considered "holding" a note while count > 0. The same
        # (ch, note) can stack across overlapping note-ons on the same edge.
        self._active_notes: dict[Connection, dict[tuple[int, int], int]] = {}
        # CC observatory: (dst_client, dst_port, channel, cc) -> last value.
        # Keyed by destination — answers "what's the most recent CC value
        # this destination received on (ch, cc)?". Written at the
        # monitor-port snoop site: each CC event seen on the monitor port
        # is fanned out to every matrix destination of its source.
        # `_cc_dest_dirty` tracks keys changed since the last delta snapshot.
        self._cc_dest_cache: dict[tuple[int, int, int, int], int] = {}
        self._cc_dest_dirty: set[tuple[int, int, int, int]] = set()

    @property
    def devices(self) -> list[MidiDevice]:
        return self._devices

    @property
    def connections(self) -> set[Connection]:
        return self._connections

    @property
    def monitor_port(self) -> int:
        """ALSA seq port id our engine uses to subscribe-from every
        device for activity / clock / latency accounting. External
        listeners (LED blinker, clock-quarter SSE) gate on this so
        they count each source event once, not once-per-filter-port."""
        return self._monitor_port

    def mark_dirty(self) -> None:
        """Mark the in-memory config as diverged from disk.

        The SSE flip is idempotent — only the False→True transition
        broadcasts. The change counter bumps on EVERY call though (even
        while already dirty), so the polling autosaver sees each edit.
        Safe to call from any thread."""
        self._change_seq += 1
        self._last_change_t = time.monotonic()
        if self.config_dirty:
            return
        self.config_dirty = True
        self._notify_dirty_change(True)

    def clear_dirty(self) -> None:
        """In-memory state now matches disk. Called by save_config /
        load_config / config_import paths."""
        if not self.config_dirty:
            return
        self.config_dirty = False
        self._notify_dirty_change(False)

    def _notify_dirty_change(self, dirty: bool) -> None:
        if not (self._dirty_loop and self._dirty_sse_cb):
            return
        cb = self._dirty_sse_cb

        async def _fire():
            try:
                await cb("config-dirty", {"dirty": dirty})
            except Exception:
                pass
        try:
            asyncio.run_coroutine_threadsafe(_fire(), self._dirty_loop)
        except RuntimeError:
            # Loop closed during shutdown.
            pass

    def on_change(self, callback):
        """Register a callback for device/connection changes."""
        self._on_change_callbacks.append(callback)

    def on_midi_event(self, callback):
        """Register a callback for MIDI events (for monitoring)."""
        self._on_midi_event_callbacks.append(callback)

    def on_transport_start(self, callback):
        """Register a callback fired on incoming MIDI Start (no args)."""
        self._on_transport_start_callbacks.append(callback)

    def _notify_change(self):
        for cb in self._on_change_callbacks:
            try:
                cb()
            except Exception:
                log.exception("Error in change callback")

    @property
    def filter_engine(self) -> FilterEngine | None:
        return self._filter_engine

    @property
    def device_registry(self) -> DeviceRegistry:
        return self._device_registry

    def start(self) -> None:
        """Open ALSA sequencer. Caller must run _scan_and_connect after plugins load."""
        self._seq = AlsaSeq("RaspiMIDIHub")
        self._filter_engine = FilterEngine(self._seq)
        # Create a monitor port to receive copies of MIDI events for the UI
        self._monitor_port = self._seq.create_port("monitor", writable=True)
        log.info("ALSA sequencer opened, client ID %d, monitor port %d",
                 self._seq.client_id, self._monitor_port)

    def stop(self) -> None:
        """Disconnect all and close ALSA sequencer."""
        if self._seq:
            self.disconnect_all()
            self._seq.close()
            self._seq = None
        self._running = False

    def scan_devices(self) -> list[MidiDevice]:
        """Scan for MIDI devices and return them."""
        if not self._seq:
            return []
        # Include plugin and BLE-bridge ALSA client IDs so they're
        # discovered as devices alongside hardware. Both are user-
        # type ALSA clients (not kernel cards) and would otherwise be
        # filtered out by scan_devices' default hardware-only mode.
        user_clients: set[int] = set()
        if self._plugin_host:
            user_clients |= self._plugin_host.get_plugin_client_ids()
        ble_bridge = getattr(self, "_ble_bridge", None)
        ble_client_ids: set[int] = set()
        if ble_bridge is not None:
            ble_client_ids = set(ble_bridge.get_alsa_client_ids())
            user_clients |= ble_client_ids
        # BlueZ (modern kernels) also creates an ALSA seq user client
        # per connected BLE-MIDI peripheral, named after the device.
        # Whitelist any user client whose name matches a known BT
        # device alias — otherwise scan_devices() would skip them and
        # the matrix would silently miss the device.
        from .device_id import _get_bluealsa_macs
        bt_macs = _get_bluealsa_macs()
        if bt_macs:
            for cid, name in self._seq.list_user_client_names().items():
                if name in bt_macs:
                    user_clients.add(cid)
                    ble_client_ids.add(cid)
        self._devices = self._seq.scan_devices(include_user_clients=user_clients)
        # Update device registry with stable IDs (hardware devices via
        # sysfs + BLE-MIDI by name → MAC). Exclude plugin clients only;
        # BLE clients are treated as hardware-ish so DeviceRegistry.scan
        # routes them through the `name in bt_macs` branch and gives
        # them `bt-<MAC>` stable ids.
        plugin_only_clients = user_clients - ble_client_ids
        hw_client_ids = [d.client_id for d in self._devices
                         if d.client_id not in plugin_only_clients]
        # Pass {client_id: name} so DeviceRegistry can identify
        # BlueALSA-managed BLE-MIDI clients by name and key them on
        # `bt-<MAC>` instead of trying to read sysfs (they don't have
        # a card). Names come from the scan we just did.
        client_names = {d.client_id: d.name for d in self._devices}
        # Feed the registry the stable_ids the current config refers to —
        # this drives device re-recognition (exact / legacy / soft-match)
        # inside the scan. Recomputed every time so Load / Restore /
        # Import are automatically covered.
        self._device_registry.set_referenced_ids(self._referenced_stable_ids())
        self._device_registry.scan(hw_client_ids, client_names=client_names)
        # Register plugin devices in the registry
        if self._plugin_host:
            for inst in self._plugin_host.get_instances():
                if inst.alsa_client:
                    self._device_registry.register_plugin(
                        inst.alsa_client.client_id, inst.id, inst.name)
        # BLE-MIDI bridge devices are registered by the regular
        # device_registry.scan() above — the bridge names its ALSA
        # client after the BT alias, so the `name in bt_macs` branch
        # in DeviceRegistry.scan() picks it up and assigns a
        # `bt-<MAC>` stable_id. Earlier code overwrote that with
        # `plugin-ble-...`, which broke offline-stable routing.
        return self._devices

    def _referenced_stable_ids(self) -> set[str]:
        """All stable_ids the current config refers to — connections,
        disabled cells, device names, and the clock-block list. Input
        for the registry's identity resolution."""
        config = self._config
        if config is None:
            return set()
        refs: set[str] = set()
        for c in list(config.connections) + list(config.disconnected):
            for key in ("src_stable_id", "dst_stable_id"):
                sid = c.get(key)
                if sid:
                    refs.add(sid)
        refs.update((config.data.get("device_names") or {}).keys())
        refs.update(config.data.get("device_clock_blocked") or [])
        return refs

    def connect_all(self) -> set[Connection]:
        """Connect every input port to every output port on other devices."""
        if not self._seq:
            return set()

        new_connections: set[Connection] = set()
        devices = self._devices

        for src_dev in devices:
            for dst_dev in devices:
                if src_dev.client_id == dst_dev.client_id:
                    continue  # FR-1.3: skip self-connections

                for src_port in src_dev.input_ports:  # input = produces MIDI
                    for dst_port in dst_dev.output_ports:  # output = consumes MIDI
                        conn = Connection(
                            src_client=src_dev.client_id,
                            src_port=src_port.port_id,
                            dst_client=dst_dev.client_id,
                            dst_port=dst_port.port_id,
                        )
                        new_connections.add(conn)

        # Create subscriptions
        for conn in new_connections:
            if conn not in self._connections:
                try:
                    self._seq.subscribe(conn.src_client, conn.src_port,
                                        conn.dst_client, conn.dst_port)
                    log.debug("Connected %d:%d -> %d:%d",
                              conn.src_client, conn.src_port,
                              conn.dst_client, conn.dst_port)
                except OSError as e:
                    log.warning("Failed to connect %d:%d -> %d:%d: %s",
                                conn.src_client, conn.src_port,
                                conn.dst_client, conn.dst_port, e)

        self._connections = new_connections
        return new_connections

    def disconnect_all(self) -> None:
        """Remove all managed subscriptions and filters."""
        if not self._seq:
            return

        # Release any held notes on direct edges before tearing down
        # subscriptions, so destinations don't end up with stuck notes.
        for conn in list(self._active_notes):
            self.release_edge_notes(conn)

        # Clear filtered connections first
        if self._filter_engine:
            self._filter_engine.clear_all()

        for conn in self._connections:
            try:
                self._seq.unsubscribe(conn.src_client, conn.src_port,
                                      conn.dst_client, conn.dst_port)
            except OSError:
                pass  # device may already be gone

        self._connections.clear()
        self._active_notes.clear()

    def _update_monitor_subscriptions(self) -> None:
        """Subscribe monitor port to all device output ports for MIDI activity UI.

        Always re-issues `snd_seq_subscribe_port` rather than relying on
        `_monitored_clients` as a cache of "is this client subscribed?".
        Reason: when a device hot-plugs (CLIENT_EXIT followed by
        CLIENT_START with the same numeric client id — typical for an
        Elektron over USB) the kernel destroys our subscription at
        CLIENT_EXIT but the rescan that runs after the start sees the
        device is "still" in `_monitored_clients` and skips. Result:
        clock-quarter SSE / rate meter / clock indicator silently stop
        showing that device. The kernel returns EBUSY on a duplicate
        subscribe which we already swallow, so just always try."""
        if self._monitor_port < 0 or not self._seq:
            return

        live_clients = {d.client_id for d in self._devices}
        # Drop bookkeeping for devices that are gone, so the set doesn't
        # grow without bound across hotplugs.
        self._monitored_clients &= live_clients

        for dev in self._devices:
            for port in dev.input_ports:  # input = produces MIDI data
                try:
                    self._seq.subscribe(dev.client_id, port.port_id,
                                        self._seq.client_id, self._monitor_port)
                except OSError:
                    pass  # already subscribed (EBUSY) — re-attempt is harmless
                self._monitored_clients.add(dev.client_id)

    def _snapshot_live_state(self) -> tuple[list[dict], dict[str, dict]]:
        """Capture current connections + filters/mappings before teardown."""
        snapshot_conns = []
        registry = self._device_registry
        fe = self._filter_engine

        for conn in self._connections:
            conn_id = f"{conn.src_client}:{conn.src_port}-{conn.dst_client}:{conn.dst_port}"
            entry = {
                "src_client": conn.src_client, "src_port": conn.src_port,
                "dst_client": conn.dst_client, "dst_port": conn.dst_port,
            }
            src_info = registry.get_by_client(conn.src_client) if registry else None
            dst_info = registry.get_by_client(conn.dst_client) if registry else None
            if src_info:
                entry["src_stable_id"] = src_info.stable_id
            if dst_info:
                entry["dst_stable_id"] = dst_info.stable_id
            # Capture filter + mappings
            if fe:
                f = fe.get_filter(conn_id)
                if f:
                    entry["filter"] = f.to_dict()
                mappings = fe.get_mappings(conn_id)
                if mappings:
                    entry["mappings"] = [m.to_dict() for m in mappings]
            snapshot_conns.append(entry)

        snapshot_disconn = dict(self._disconnected)
        return snapshot_conns, snapshot_disconn

    def _cancel_pending_rescan(self) -> None:
        """Cancel any in-flight debounced rescan — used by the additive
        plugin add/remove fast paths to override the engine event-loop's
        hotplug-driven rescan in case it managed to schedule one before
        the new client made it into plugin_host._instances."""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
            self._debounce_task = None

    def handle_plugin_added(self) -> None:
        """Fast path for "a new plugin instance just appeared".

        No teardown. No disconnect_all. Just registers the new ALSA
        client, updates monitor subscriptions, and notifies listeners.
        Existing subscriptions, filter ports, and userspace mappings
        all stay live — clock and MIDI through filtered connections
        are not interrupted.

        Used instead of _schedule_rescan() when the caller knows the
        change is purely additive (no devices disappeared, no client
        IDs shuffled).
        """
        if not self._seq:
            return
        self._cancel_pending_rescan()
        self.scan_devices()
        self._update_monitor_subscriptions()
        self._notify_change()

    def handle_plugin_removed(self, gone_client_id: int) -> None:
        """Fast path for "a plugin instance is being removed".

        Drops only the connections that touch the going-away client,
        plus its monitor subscription. Other subscriptions stay live.
        """
        if not self._seq:
            return
        self._cancel_pending_rescan()

        # The plugin's alsa_client.close() already destroyed the seq
        # client and the kernel removed every subscription / port that
        # touched it. We don't need to issue any more ALSA syscalls —
        # we just prune our internal state to match.

        # Release notes held on edges where the source was this client
        # (destination is still alive — send NoteOff so it doesn't stick).
        # For edges where the destination is gone, just drop the entry —
        # the kernel already removed the subscription, the dst is dead.
        for conn in list(self._active_notes):
            if conn.dst_client == gone_client_id:
                self._active_notes.pop(conn, None)
            elif conn.src_client == gone_client_id:
                self.release_edge_notes(conn)

        # Drop direct connections that referenced the gone client
        self._connections = {c for c in self._connections
                             if c.src_client != gone_client_id
                             and c.dst_client != gone_client_id}
        self._purge_cc_dest_cache_for_client(gone_client_id)

        # Drop filtered-connection bookkeeping for the gone client
        if self._filter_engine:
            for conn_id in list(self._filter_engine.filtered_connections.keys()):
                try:
                    sc, _, dc, _ = self._parse_conn_id(conn_id)
                except (ValueError, IndexError):
                    continue
                if sc == gone_client_id or dc == gone_client_id:
                    self._filter_engine.filtered_connections.pop(conn_id, None)

        # Drop monitor subscription bookkeeping for the gone client
        self._monitored_clients.discard(gone_client_id)

        # Surgically prune the device list — no full ALSA re-enumeration
        self._devices = [d for d in self._devices if d.client_id != gone_client_id]
        info = self._device_registry.get_by_client(gone_client_id)
        if info:
            self._device_registry._by_client.pop(gone_client_id, None)
            self._device_registry._by_stable_id.pop(info.stable_id, None)

        self._notify_change()

    @staticmethod
    def _parse_conn_id(conn_id: str) -> tuple[int, int, int, int]:
        src, dst = conn_id.split("-")
        sc, sp = map(int, src.split(":"))
        dc, dp = map(int, dst.split(":"))
        return sc, sp, dc, dp

    def apply_saved_config(self, *,
                           snapshot: list[dict] | None = None,
                           snapshot_disconn: dict[str, dict] | None = None,
                           newly_present_stable_ids: set[str] | None = None) -> None:
        """Apply connections, filters, and mappings from `self._config`.

        When `snapshot` is provided (hotplug rescan), live state is preserved
        — user edits that weren't saved yet survive the rescan. Saved
        connections from config are additionally restored for any device
        that just appeared (wasn't present in the previous scan), so
        hot-plugging a keyboard brings back its routing without the user
        having to hit "Load Config". Disabled (disconnected) cells in
        config are honored regardless.
        """
        from .midi_filter import MidiFilter, MidiMapping

        config = self._config
        if config is None:
            return

        self.scan_devices()
        registry = self._device_registry

        if snapshot is not None:
            saved_conns = list(snapshot)
            snapshot_sigs = {
                (c.get("src_stable_id"), c.get("src_port"),
                 c.get("dst_stable_id"), c.get("dst_port"))
                for c in snapshot
                if c.get("src_stable_id") and c.get("dst_stable_id")
            }
            disabled_sigs = {
                (c.get("src_stable_id"), c.get("src_port", 0),
                 c.get("dst_stable_id"), c.get("dst_port", 0))
                for c in config.disconnected
                if c.get("src_stable_id") and c.get("dst_stable_id")
            }
            appeared = newly_present_stable_ids or set()
            for c in config.connections:
                ssid = c.get("src_stable_id")
                dsid = c.get("dst_stable_id")
                if not ssid or not dsid:
                    continue
                if ssid not in appeared and dsid not in appeared:
                    continue
                sig = (ssid, c.get("src_port", 0), dsid, c.get("dst_port", 0))
                if sig in snapshot_sigs or sig in disabled_sigs:
                    continue
                saved_conns.append(c)
        else:
            saved_conns = config.connections

        applied = 0
        pending = 0

        for c in saved_conns:
            try:
                src_port = c["src_port"]
                dst_port = c["dst_port"]
            except KeyError:
                continue

            src_stable = c.get("src_stable_id")
            dst_stable = c.get("dst_stable_id")

            if src_stable:
                src_client = registry.client_for_stable_id(src_stable)
            else:
                src_client = c.get("src_client")

            if dst_stable:
                dst_client = registry.client_for_stable_id(dst_stable)
            else:
                dst_client = c.get("dst_client")

            if src_client is None or dst_client is None:
                pending += 1
                continue

            current_clients = {d.client_id for d in self._devices}
            if src_client not in current_clients or dst_client not in current_clients:
                pending += 1
                continue

            conn = Connection(src_client, src_port, dst_client, dst_port)
            conn_id = f"{src_client}:{src_port}-{dst_client}:{dst_port}"

            filter_data = c.get("filter")
            mappings_data = c.get("mappings", [])
            needs_userspace = bool(mappings_data)

            if filter_data:
                midi_filter = MidiFilter.from_dict(filter_data)
                needs_userspace = needs_userspace or not midi_filter.is_passthrough
            else:
                midi_filter = MidiFilter()

            if needs_userspace and self._filter_engine:
                try:
                    self._seq.unsubscribe(src_client, src_port, dst_client, dst_port)
                except OSError:
                    pass
                self._filter_engine.add_filter(
                    src_client, src_port, dst_client, dst_port, midi_filter
                )
                for md in mappings_data:
                    try:
                        mapping = MidiMapping.from_dict(md)
                        self._filter_engine.add_mapping(conn_id, mapping)
                    except (ValueError, KeyError):
                        log.warning("Skipping invalid mapping on %s", conn_id)
                self._connections.add(conn)
                applied += 1
                continue

            try:
                self._seq.subscribe(src_client, src_port, dst_client, dst_port)
                self._connections.add(conn)
                applied += 1
            except OSError as e:
                log.warning("Failed to restore connection %d:%d -> %d:%d: %s",
                            src_client, src_port, dst_client, dst_port, e)

        if snapshot_disconn is not None:
            for old_conn_id, saved_data in snapshot_disconn.items():
                self._disconnected[old_conn_id] = saved_data

        for c in config.disconnected:
            src_stable = c.get("src_stable_id")
            dst_stable = c.get("dst_stable_id")
            src_client = registry.client_for_stable_id(src_stable) if src_stable else None
            dst_client = registry.client_for_stable_id(dst_stable) if dst_stable else None
            if src_client is not None and dst_client is not None:
                sp = c.get("src_port", 0)
                dp = c.get("dst_port", 0)
                conn_id = f"{src_client}:{sp}-{dst_client}:{dp}"
                saved_data = {}
                if "filter" in c:
                    saved_data["filter"] = c["filter"]
                if "mappings" in c:
                    saved_data["mappings"] = c["mappings"]
                self._disconnected[conn_id] = saved_data

        # Handle device pairs not in saved config: apply default_routing
        known_pairs = set()
        for c in saved_conns:
            src_stable = c.get("src_stable_id")
            dst_stable = c.get("dst_stable_id")
            if src_stable and dst_stable:
                known_pairs.add((src_stable, c.get("src_port", 0), dst_stable, c.get("dst_port", 0)))
        for c in config.disconnected:
            src_stable = c.get("src_stable_id")
            dst_stable = c.get("dst_stable_id")
            if src_stable and dst_stable:
                known_pairs.add((src_stable, c.get("src_port", 0), dst_stable, c.get("dst_port", 0)))

        if config.default_routing == "all":
            for src_dev in self._devices:
                for dst_dev in self._devices:
                    if src_dev.client_id == dst_dev.client_id:
                        continue
                    src_info = registry.get_by_client(src_dev.client_id)
                    dst_info = registry.get_by_client(dst_dev.client_id)
                    if src_info and src_info.is_plugin:
                        continue
                    if dst_info and dst_info.is_plugin:
                        continue
                    for src_port_obj in src_dev.input_ports:
                        for dst_port_obj in dst_dev.output_ports:
                            if src_info and dst_info:
                                key = (src_info.stable_id, src_port_obj.port_id,
                                       dst_info.stable_id, dst_port_obj.port_id)
                                if key in known_pairs:
                                    continue
                            conn = Connection(src_dev.client_id, src_port_obj.port_id,
                                              dst_dev.client_id, dst_port_obj.port_id)
                            if conn not in self._connections:
                                try:
                                    self._seq.subscribe(src_dev.client_id, src_port_obj.port_id,
                                                        dst_dev.client_id, dst_port_obj.port_id)
                                    self._connections.add(conn)
                                except OSError:
                                    pass

        log.info("Config restored: %d connections applied, %d pending (devices not present)",
                 applied, pending)

    def _scan_and_connect(self) -> None:
        """Rescan devices and restore connections from live state snapshot.

        Snapshots all connections + filters/mappings before teardown, then
        restores from the snapshot after rescan. This preserves unsaved
        changes across hotplug events. For devices that just appeared
        (weren't in the previous scan), also merges their saved
        connections from config so e.g. hot-plugging a keyboard brings
        back its routing without needing a "Load Config" press.
        """
        # Snapshot live state BEFORE teardown
        snapshot_conns, snapshot_disconn = self._snapshot_live_state()
        has_live_state = bool(snapshot_conns) or bool(snapshot_disconn)

        # `prev_stable_ids` comes from the snapshot we took at the END
        # of the previous _scan_and_connect — NOT from live
        # self._devices. Read-only API endpoints (GET /api/devices)
        # call scan_devices() and update self._devices, so by the time
        # the debounced post-hotplug rescan runs, a hot-plugged device
        # may already be in self._devices and look like it was always
        # present. Tracking the snapshot field separately keeps that
        # signal intact.
        prev_stable_ids = set(self._stable_ids_at_last_scan_and_connect)

        self.disconnect_all()
        self.scan_devices()

        new_stable_ids: set[str] = set()
        for d in self._devices:
            info = self._device_registry.get_by_client(d.client_id)
            if info:
                new_stable_ids.add(info.stable_id)
        appeared = new_stable_ids - prev_stable_ids
        self._stable_ids_at_last_scan_and_connect = new_stable_ids

        if has_live_state:
            self.apply_saved_config(snapshot=snapshot_conns,
                                    snapshot_disconn=snapshot_disconn,
                                    newly_present_stable_ids=appeared)
        elif self._config and self._config.mode == "custom":
            self.apply_saved_config()
        else:
            default_routing = "all"
            if self._config:
                default_routing = self._config.default_routing
            if default_routing == "all":
                self.connect_all()

        self._update_monitor_subscriptions()

        device_names = [d.name for d in self._devices]
        log.info("Devices: %s", device_names if device_names else "(none)")
        log.info("Connections: %d active", len(self._connections))
        self._notify_change()

    async def run_event_loop(self) -> None:
        """Async event loop listening for ALSA sequencer events.

        Single persistent fd reader + asyncio.Event signal. The earlier
        version did add_reader / remove_reader per iteration, which was
        ~7.5% of CPU under heavy MIDI input — selectors do real work
        on each register / unregister. Now the reader is wired once at
        startup; readable.set() fires from the IO callback, the loop
        drains pending events, clears, and waits again."""
        if not self._seq:
            raise RuntimeError("Engine not started")

        self._running = True
        loop = asyncio.get_event_loop()
        fd = self._seq.fileno()
        readable = asyncio.Event()
        loop.add_reader(fd, readable.set)
        log.info("Listening for MIDI hotplug events on fd %d", fd)

        try:
            await self._drain_alsa_events(readable, max_events=256)
        finally:
            loop.remove_reader(fd)

    async def _drain_alsa_events(self, readable: asyncio.Event,
                                  max_events: int) -> None:
        """Inner ALSA-event loop. Extracted only so run_event_loop's
        try/finally can guarantee remove_reader on shutdown without
        deeply nested control flow."""
        while self._running:
            await readable.wait()
            readable.clear()
            if not self._running:
                break

            # Drain pending events. max_events comes from the caller —
            # bounded so a hot ALSA queue can't starve the asyncio loop
            # of other work for too long.
            hotplug = False
            for _ in range(max_events):
                ev = self._seq.read_event()
                if ev is None:
                    break

                # Ignore events from our own client (filter port creation/events)
                if ev.source.client == self._seq.client_id:
                    continue

                # Check for hotplug announce events
                try:
                    ev_type = SeqEventType(ev.type)
                    if ev_type in (SeqEventType.PORT_START, SeqEventType.PORT_EXIT,
                                   SeqEventType.CLIENT_START, SeqEventType.CLIENT_EXIT):
                        affected_client = ev.data.raw8[0]
                        affected_port = ev.data.raw8[1]
                        # Ignore events from our own client
                        if affected_client == self._seq.client_id:
                            continue
                        # Plugin-managed clients are added/removed by the
                        # plugin host's fast paths (handle_plugin_added /
                        # handle_plugin_removed). Skip the global rescan
                        # for them — otherwise we'd tear down every filter
                        # port and re-subscribe everything just because a
                        # plugin instance came or went, glitching MIDI
                        # through every other connection.
                        if (self._plugin_host
                                and affected_client in self._plugin_host.get_plugin_client_ids()):
                            continue
                        log.info("Hotplug event: %s (client %d, port %d)",
                                 ev_type.name, affected_client, affected_port)
                        hotplug = True
                        continue
                except ValueError:
                    pass

                # Count messages per source port (monitor port only to avoid double-counting)
                if ev.dest.port == self._monitor_port:
                    key = f"{ev.source.client}:{ev.source.port}"
                    self._port_msg_counts[key] = self._port_msg_counts.get(key, 0) + 1
                    if ev.type in (int(MidiEventType.NOTEON), int(MidiEventType.NOTEOFF)):
                        self._track_note_event(ev)
                    elif ev.type == int(MidiEventType.CONTROLLER):
                        self._track_cc_to_destinations(ev)

                # Notify MIDI event listeners (for monitoring)
                if self._on_midi_event_callbacks:
                    for cb in self._on_midi_event_callbacks:
                        try:
                            cb(ev)
                        except Exception:
                            pass

                # Forward clock events to the global ClockBus.
                #
                # Sources that feed the bus:
                # - External hardware (not a plugin) — always feeds.
                # - Plugins with `feeds_clock_bus = True` (Master Clock).
                #
                # Plugins that process clock (Clock Divider, etc.) must NOT
                # feed the bus — their divided OUT would pollute the bus's
                # tempo and re-fire bus subscribers at the wrong rate.
                # Source-routed clock for those plugins is delivered via
                # `on_clock()` directly from the IN port (host.py).
                if self._plugin_host:
                    plugin_clients = self._plugin_host.get_plugin_client_ids()
                    is_plugin = ev.source.client in plugin_clients
                    feeds_bus = (not is_plugin) or self._plugin_host.client_feeds_clock_bus(ev.source.client)
                    # Per-device clock veto: hardware sources the user
                    # has unticked in the device-detail panel must not
                    # drive the bus. Plugins already gate via
                    # feeds_clock_bus and never appear here, so this
                    # only narrows hardware (and self-loop plugins
                    # never set feeds_clock_bus anyway).
                    if feeds_bus and self._device_registry.is_client_clock_blocked(ev.source.client):
                        feeds_bus = False
                    if ev.type == MidiEventType.CLOCK:
                        if ev.dest.port == self._monitor_port and feeds_bus:
                            self._plugin_host.clock_bus.on_clock_tick()
                    elif ev.type == MidiEventType.START and feeds_bus:
                        self._plugin_host.clock_bus.on_start()
                        for cb in self._on_transport_start_callbacks:
                            try:
                                cb()
                            except Exception:
                                log.exception("transport_start callback failed")
                    elif ev.type == MidiEventType.CONTINUE and feeds_bus:
                        self._plugin_host.clock_bus.on_continue()
                    elif ev.type == MidiEventType.STOP and feeds_bus:
                        self._plugin_host.clock_bus.on_stop()

                # Process filtered MIDI events. Time the userspace-routed
                # path so the engine can report a midi-in→midi-out latency
                # for connections that go through filters / mappings.
                # Kernel-routed (direct ALSA subscription) flows bypass
                # this entirely and don't show up in the metric, which is
                # the right thing — they're effectively zero-latency.
                if self._filter_engine:
                    t0 = time.monotonic()
                    forwarded = self._filter_engine.process_event(ev)
                    if forwarded and self._latency_cb:
                        self._latency_cb(
                            "midi_in_midi_out",
                            (time.monotonic() - t0) * 1000.0,
                        )

            if hotplug:
                self._schedule_rescan()

    def panic(self, hard: bool = False) -> None:
        """Silence sounding notes across every outbound destination.

        Soft (default): per-edge NoteOff for tracked active notes + CC 123
        (All Notes Off) on every channel of every destination + plugin
        panic_all(). Lets delay/reverb tails keep ringing.

        Hard: soft + CC 120 (All Sound Off) on every channel — for when the
        rig is genuinely stuck and tails don't matter.
        """
        if not self._seq:
            return

        import ctypes

        from .alsa_seq import (
            SND_SEQ_QUEUE_DIRECT,
            MidiEventType,
            SndSeqEvent,
            snd_seq_event_output_direct,
        )

        # Per-edge NoteOff for every tracked active note (surgical).
        for conn in list(self._active_notes):
            self.release_edge_notes(conn)

        panic_port = self._monitor_port if self._monitor_port >= 0 else 0
        dests = {(c.dst_client, c.dst_port) for c in self._connections}
        ccs = [123, 120] if hard else [123]

        for dst_client, dst_port in dests:
            for ch in range(16):
                for cc in ccs:
                    ev = SndSeqEvent()
                    ev.type = int(MidiEventType.CONTROLLER)
                    ev.data.control.channel = ch
                    ev.data.control.param = cc
                    ev.data.control.value = 0
                    ev.source.client = self._seq.client_id
                    ev.source.port = panic_port
                    ev.dest.client = dst_client
                    ev.dest.port = dst_port
                    ev.queue = SND_SEQ_QUEUE_DIRECT
                    ev.flags = 0
                    snd_seq_event_output_direct(self._seq.handle, ctypes.pointer(ev))

        if self._plugin_host:
            try:
                self._plugin_host.panic_all()
            except Exception:
                log.exception("panic_all failed")

        self._active_notes.clear()
        log.info("Panic (%s): %d destinations", "hard" if hard else "soft", len(dests))

    # --- Edge diff (Phase 2: smooth preset switching) ---

    def apply_edge_diff(self, target_edges: list[dict]) -> dict:
        """Reconcile current routing against `target_edges` with minimal
        disruption: untouched edges keep flowing, only changed/removed
        edges get reset.

        target_edges: each dict has the same shape as a saved-config
        connection — `src_stable_id`, `src_port`, `dst_stable_id`,
        `dst_port`, optional `filter` dict, optional `mappings` list.

        Returns a stats dict so callers can log / surface the outcome.
        """
        stats = {"removed": 0, "added": 0, "changed": 0, "untouched": 0, "skipped": 0}
        if not self._seq:
            return stats

        registry = self._device_registry
        fe = self._filter_engine

        # --- Snapshot current edges keyed by stable IDs ---
        current: dict[tuple, dict] = {}
        for conn in list(self._connections):
            src_info = registry.get_by_client(conn.src_client) if registry else None
            dst_info = registry.get_by_client(conn.dst_client) if registry else None
            if not src_info or not dst_info:
                continue  # can't form a stable key — leave untouched
            key = (src_info.stable_id, conn.src_port,
                   dst_info.stable_id, conn.dst_port)
            conn_id = f"{conn.src_client}:{conn.src_port}-{conn.dst_client}:{conn.dst_port}"
            f_obj = fe.get_filter(conn_id) if fe else None
            m_objs = fe.get_mappings(conn_id) if fe else []
            current[key] = {
                "conn": conn,
                "conn_id": conn_id,
                "filter_dict": f_obj.to_dict() if f_obj else None,
                "mapping_dicts": [m.to_dict() for m in m_objs],
                "is_userspace": fe.has_filter(conn_id) if fe else False,
            }

        # --- Build target map (skip edges whose endpoints don't resolve) ---
        target: dict[tuple, dict] = {}
        for edge in target_edges:
            src_sid = edge.get("src_stable_id")
            dst_sid = edge.get("dst_stable_id")
            if not (src_sid and dst_sid):
                stats["skipped"] += 1
                continue
            src_client = registry.client_for_stable_id(src_sid) if registry else None
            dst_client = registry.client_for_stable_id(dst_sid) if registry else None
            if src_client is None or dst_client is None:
                stats["skipped"] += 1
                continue
            key = (src_sid, edge["src_port"], dst_sid, edge["dst_port"])
            target[key] = {
                "src_client": src_client,
                "src_port": edge["src_port"],
                "dst_client": dst_client,
                "dst_port": edge["dst_port"],
                "filter_dict": edge.get("filter"),
                "mapping_dicts": edge.get("mappings", []),
            }

        current_keys = set(current.keys())
        target_keys = set(target.keys())

        # --- Removed edges: release notes + send CC 123 + tear down ---
        for key in current_keys - target_keys:
            try:
                self._remove_edge_smoothly(current[key])
                stats["removed"] += 1
            except Exception:
                log.exception("apply_edge_diff: failed to remove %s", current[key]["conn_id"])

        # --- Common edges: changed (in-place if possible) or untouched ---
        for key in current_keys & target_keys:
            cur = current[key]
            tgt = target[key]
            new_userspace = _edge_needs_userspace(tgt["filter_dict"], tgt["mapping_dicts"])
            same_mode = cur["is_userspace"] == new_userspace
            same_filter = _filter_equal(cur["filter_dict"], tgt["filter_dict"])
            same_mappings = _mappings_equal(cur["mapping_dicts"], tgt["mapping_dicts"])
            if same_mode and same_filter and same_mappings:
                stats["untouched"] += 1
                continue
            try:
                if same_mode and cur["is_userspace"]:
                    # In-place update — no resubscribe, no note disruption.
                    new_filter = (MidiFilter.from_dict(tgt["filter_dict"])
                                  if tgt["filter_dict"] else MidiFilter())
                    fe.update_filter(cur["conn_id"], new_filter)
                    fe.set_mappings(cur["conn_id"],
                                    [MidiMapping.from_dict(m) for m in tgt["mapping_dicts"]])
                else:
                    # Mode change — need to swap subscription. Release notes
                    # cleanly so the dst doesn't end up with a stuck note,
                    # then add the new edge.
                    self._remove_edge_smoothly(cur)
                    self._add_edge(tgt["src_client"], tgt["src_port"],
                                   tgt["dst_client"], tgt["dst_port"],
                                   tgt["filter_dict"], tgt["mapping_dicts"])
                stats["changed"] += 1
            except Exception:
                log.exception("apply_edge_diff: failed to update %s", cur["conn_id"])

        # --- Added edges ---
        for key in target_keys - current_keys:
            tgt = target[key]
            try:
                self._add_edge(tgt["src_client"], tgt["src_port"],
                               tgt["dst_client"], tgt["dst_port"],
                               tgt["filter_dict"], tgt["mapping_dicts"])
                stats["added"] += 1
            except Exception:
                log.exception("apply_edge_diff: failed to add edge %s", key)

        log.info("apply_edge_diff: %s", stats)
        return stats

    def _remove_edge_smoothly(self, info: dict) -> None:
        """Remove an edge without leaving stuck notes on the destination."""
        conn = info["conn"]
        used_channels = {ch for (ch, _n) in self._active_notes.get(conn, {})}
        self.release_edge_notes(conn)
        if used_channels:
            self._send_all_notes_off(conn.dst_client, conn.dst_port, used_channels)
        if info["is_userspace"] and self._filter_engine:
            self._filter_engine.remove_filter(info["conn_id"])
        else:
            try:
                self._seq.unsubscribe(conn.src_client, conn.src_port,
                                      conn.dst_client, conn.dst_port)
            except OSError:
                pass
        self._connections.discard(conn)

    def _add_edge(self, src_client: int, src_port: int,
                  dst_client: int, dst_port: int,
                  filter_dict: dict | None, mapping_dicts: list[dict]) -> None:
        """Install a new edge with optional filter + mappings."""
        needs_userspace = _edge_needs_userspace(filter_dict, mapping_dicts)
        fe = self._filter_engine
        conn = Connection(src_client, src_port, dst_client, dst_port)
        if needs_userspace and fe:
            midi_filter = (MidiFilter.from_dict(filter_dict)
                           if filter_dict else MidiFilter())
            fe.add_filter(src_client, src_port, dst_client, dst_port, midi_filter)
            conn_id = f"{src_client}:{src_port}-{dst_client}:{dst_port}"
            for md in mapping_dicts:
                try:
                    fe.add_mapping(conn_id, MidiMapping.from_dict(md))
                except (ValueError, KeyError):
                    pass
        else:
            try:
                self._seq.subscribe(src_client, src_port, dst_client, dst_port)
            except OSError:
                log.warning("apply_edge_diff: subscribe failed for %d:%d->%d:%d",
                            src_client, src_port, dst_client, dst_port)
                return
        self._connections.add(conn)

    def _send_all_notes_off(self, dst_client: int, dst_port: int,
                            channels: set[int]) -> None:
        """Emit CC 123 (All Notes Off) on each `channel` at the destination."""
        if not self._seq:
            return
        import ctypes

        from .alsa_seq import (
            SND_SEQ_QUEUE_DIRECT,
            SndSeqEvent,
            snd_seq_event_output_direct,
        )

        src_port = self._monitor_port if self._monitor_port >= 0 else 0
        for ch in channels:
            ev = SndSeqEvent()
            ev.type = int(MidiEventType.CONTROLLER)
            ev.data.control.channel = ch
            ev.data.control.param = 123
            ev.data.control.value = 0
            ev.source.client = self._seq.client_id
            ev.source.port = src_port
            ev.dest.client = dst_client
            ev.dest.port = dst_port
            ev.queue = SND_SEQ_QUEUE_DIRECT
            ev.flags = 0
            try:
                snd_seq_event_output_direct(self._seq.handle, ctypes.pointer(ev))
            except OSError:
                pass

    def snapshot_rates(self) -> dict[str, int]:
        """Snapshot per-port message rates (msgs/sec) and reset counters."""
        rates = dict(self._port_msg_counts)
        self._port_msg_counts.clear()
        self._port_rates = rates
        return rates

    # --- Per-edge note refcount tracking ---

    def _track_note_event(self, ev) -> None:
        """Update _active_notes for note-on/off events seen on the monitor port.

        For each edge whose source matches `ev.source`, increment on note-on
        (vel > 0) and decrement on note-off (or note-on with vel == 0).
        Filter-dropped events are not visible at this layer, so the counts
        are best-effort intent rather than ground truth.
        """
        ch = ev.data.note.channel
        note = ev.data.note.note
        is_on = ev.type == int(MidiEventType.NOTEON) and ev.data.note.velocity > 0
        is_off = ev.type == int(MidiEventType.NOTEOFF) or (
            ev.type == int(MidiEventType.NOTEON) and ev.data.note.velocity == 0
        )
        if not (is_on or is_off):
            return

        src_client = ev.source.client
        src_port = ev.source.port
        key = (ch, note)
        for conn in self._connections:
            if conn.src_client != src_client or conn.src_port != src_port:
                continue
            held = self._active_notes.setdefault(conn, {})
            if is_on:
                held[key] = held.get(key, 0) + 1
            else:
                count = held.get(key, 0)
                if count <= 1:
                    held.pop(key, None)
                    if not held:
                        self._active_notes.pop(conn, None)
                else:
                    held[key] = count - 1

    def _purge_active_notes_for_client(self, client_id: int) -> None:
        """Drop all per-edge note state for edges touching `client_id`."""
        for conn in list(self._active_notes):
            if conn.src_client == client_id or conn.dst_client == client_id:
                self._active_notes.pop(conn, None)

    def release_edge_notes(self, conn: Connection) -> None:
        """Send NoteOff for every note currently held on this edge.

        Called before an edge is removed so the destination doesn't end
        up with stuck notes. Sends events directly from the monitor port
        — works even after the kernel subscription is gone (e.g. when a
        plugin source client has just closed).

        Multi-source caveat: if another edge to the same destination is
        also holding the same (channel, note), this NoteOff will silence
        it too. Accepted trade-off: a stuck note is worse than a
        prematurely-released one, and the multi-source-same-note case
        is rare.
        """
        if not self._seq:
            return
        held = self._active_notes.pop(conn, None)
        if not held:
            return

        import ctypes

        from .alsa_seq import (
            SND_SEQ_QUEUE_DIRECT,
            SndSeqEvent,
            snd_seq_event_output_direct,
        )

        src_port = self._monitor_port if self._monitor_port >= 0 else 0
        for (channel, note), _count in held.items():
            ev = SndSeqEvent()
            ev.type = int(MidiEventType.NOTEOFF)
            ev.data.note.channel = channel
            ev.data.note.note = note
            ev.data.note.velocity = 0
            ev.source.client = self._seq.client_id
            ev.source.port = src_port
            ev.dest.client = conn.dst_client
            ev.dest.port = conn.dst_port
            ev.queue = SND_SEQ_QUEUE_DIRECT
            ev.flags = 0
            try:
                snd_seq_event_output_direct(self._seq.handle, ctypes.pointer(ev))
            except OSError:
                pass  # destination might already be gone

    # --- CC observatory (destination-keyed) ---

    def _track_cc_to_destinations(self, ev) -> None:
        """Walk the matrix from this CC's source and write the value to
        every destination's slot in `_cc_dest_cache`."""
        ch = ev.data.control.channel
        cc = ev.data.control.param
        val = ev.data.control.value
        sc = ev.source.client
        sp = ev.source.port
        for conn in self._connections:
            if conn.src_client != sc or conn.src_port != sp:
                continue
            key = (conn.dst_client, conn.dst_port, ch, cc)
            if self._cc_dest_cache.get(key) != val:
                self._cc_dest_cache[key] = val
                self._cc_dest_dirty.add(key)

    def _purge_cc_dest_cache_for_client(self, client_id: int) -> None:
        """Drop dest-keyed cache entries whose destination matches client_id."""
        for key in [k for k in self._cc_dest_cache if k[0] == client_id]:
            self._cc_dest_cache.pop(key, None)
            self._cc_dest_dirty.discard(key)

    def last_cc_to(self, dst_client: int, dst_port: int,
                   channel: int, cc: int) -> int | None:
        """Most recent CC value the engine forwarded to (dst, ch, cc), or
        None if no CC for that destination has been observed yet."""
        return self._cc_dest_cache.get((dst_client, dst_port, channel, cc))

    def cc_dest_snapshot(self) -> list[dict]:
        """Full current state of the destination-keyed CC cache."""
        return [
            {"dst_client": dc, "dst_port": dp,
             "channel": ch, "cc": cc, "value": val}
            for (dc, dp, ch, cc), val in self._cc_dest_cache.items()
        ]

    def cc_dest_snapshot_dirty(self) -> list[dict]:
        """Entries changed since the last call. Clears the dirty set."""
        out = []
        for key in self._cc_dest_dirty:
            if key not in self._cc_dest_cache:
                continue
            dc, dp, ch, cc = key
            out.append({"dst_client": dc, "dst_port": dp,
                        "channel": ch, "cc": cc, "value": self._cc_dest_cache[key]})
        self._cc_dest_dirty.clear()
        return out

    def active_notes_snapshot(self) -> list[dict]:
        """Return a serializable snapshot of currently held notes per edge.

        Edges whose connection has been removed are dropped so callers
        don't see stale entries from notes held when an edge was deleted
        mid-flight.
        """
        out = []
        for conn, held in self._active_notes.items():
            if not held or conn not in self._connections:
                continue
            out.append({
                "src_client": conn.src_client,
                "src_port": conn.src_port,
                "dst_client": conn.dst_client,
                "dst_port": conn.dst_port,
                "notes": [
                    {"channel": ch, "note": n, "count": c}
                    for (ch, n), c in held.items()
                ],
            })
        return out

    def _schedule_rescan(self) -> None:
        """Debounce rescans to allow multi-port devices to finish enumeration."""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.ensure_future(self._debounced_rescan())

    async def _debounced_rescan(self) -> None:
        """Wait for debounce period then rescan."""
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)
            log.info("Rescanning MIDI devices after hotplug...")
            self._scan_and_connect()
        except asyncio.CancelledError:
            pass
