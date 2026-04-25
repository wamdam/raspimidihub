"""MIDI routing engine with hotplug support.

Manages all-to-all MIDI connections between USB MIDI devices
using the ALSA sequencer API.
"""

import asyncio
import logging
from dataclasses import dataclass

from .alsa_seq import AlsaSeq, MidiDevice, MidiEventType, SeqEventType
from .device_id import DeviceRegistry
from .midi_filter import FilterEngine

log = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 0.5


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
        self._on_change_callbacks: list = []
        self._on_midi_event_callbacks: list = []
        # Per-port message counters for rate metering
        self._port_msg_counts: dict[str, int] = {}  # "client:port" -> count
        self._port_rates: dict[str, int] = {}  # "client:port" -> msgs/sec (last snapshot)
        # Per-edge note refcount: Connection -> {(channel, note): count}
        # An edge is considered "holding" a note while count > 0. The same
        # (ch, note) can stack across overlapping note-ons on the same edge.
        self._active_notes: dict[Connection, dict[tuple[int, int], int]] = {}
        # CC observatory: (src_client, src_port, channel, cc) -> last value.
        # Updated from CC events seen on the monitor port. `_cc_dirty` tracks
        # keys that changed since the last delta snapshot for SSE broadcast.
        self._cc_cache: dict[tuple[int, int, int, int], int] = {}
        self._cc_dirty: set[tuple[int, int, int, int]] = set()

    @property
    def devices(self) -> list[MidiDevice]:
        return self._devices

    @property
    def connections(self) -> set[Connection]:
        return self._connections

    def on_change(self, callback):
        """Register a callback for device/connection changes."""
        self._on_change_callbacks.append(callback)

    def on_midi_event(self, callback):
        """Register a callback for MIDI events (for monitoring)."""
        self._on_midi_event_callbacks.append(callback)

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
        # Include plugin ALSA client IDs so they're discovered as devices
        plugin_clients = set()
        if self._plugin_host:
            plugin_clients = self._plugin_host.get_plugin_client_ids()
        self._devices = self._seq.scan_devices(include_user_clients=plugin_clients)
        # Update device registry with stable IDs (hardware devices via sysfs)
        hw_client_ids = [d.client_id for d in self._devices if d.client_id not in plugin_clients]
        self._device_registry.scan(hw_client_ids)
        # Register plugin devices in the registry
        if self._plugin_host:
            for inst in self._plugin_host.get_instances():
                if inst.alsa_client:
                    self._device_registry.register_plugin(
                        inst.alsa_client.client_id, inst.id, inst.name)
        return self._devices

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
        """Subscribe monitor port to all device output ports for MIDI activity UI."""
        if self._monitor_port < 0 or not self._seq:
            return

        # Unsubscribe from devices that are gone
        for client_id in list(self._monitored_clients):
            if client_id not in {d.client_id for d in self._devices}:
                self._monitored_clients.discard(client_id)

        # Subscribe to new devices
        for dev in self._devices:
            if dev.client_id in self._monitored_clients:
                continue
            for port in dev.input_ports:  # input = produces MIDI data
                try:
                    self._seq.subscribe(dev.client_id, port.port_id,
                                        self._seq.client_id, self._monitor_port)
                    self._monitored_clients.add(dev.client_id)
                except OSError:
                    pass

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

        # Drop direct connections that referenced the gone client
        self._connections = {c for c in self._connections
                             if c.src_client != gone_client_id
                             and c.dst_client != gone_client_id}
        self._purge_active_notes_for_client(gone_client_id)
        self._purge_cc_cache_for_client(gone_client_id)

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

        # Remember which stable IDs were present before the rescan so we
        # can identify newly-appeared devices afterwards.
        prev_stable_ids: set[str] = set()
        for d in self._devices:
            info = self._device_registry.get_by_client(d.client_id)
            if info:
                prev_stable_ids.add(info.stable_id)

        self.disconnect_all()
        self.scan_devices()

        new_stable_ids: set[str] = set()
        for d in self._devices:
            info = self._device_registry.get_by_client(d.client_id)
            if info:
                new_stable_ids.add(info.stable_id)
        appeared = new_stable_ids - prev_stable_ids

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
        """Async event loop listening for ALSA sequencer events."""
        if not self._seq:
            raise RuntimeError("Engine not started")

        self._running = True
        loop = asyncio.get_event_loop()
        fd = self._seq.fileno()

        log.info("Listening for MIDI hotplug events on fd %d", fd)

        while self._running:
            # Wait for the fd to become readable
            future = loop.create_future()

            def _on_readable(fut=future):
                if not fut.done():
                    fut.set_result(None)

            loop.add_reader(fd, _on_readable)
            try:
                await future
            finally:
                loop.remove_reader(fd)

            if not self._running:
                break

            # Drain pending events (max batch to avoid starving asyncio)
            hotplug = False
            max_events = 256
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
                        self._track_cc_event(ev)

                # Notify MIDI event listeners (for monitoring)
                if self._on_midi_event_callbacks:
                    for cb in self._on_midi_event_callbacks:
                        try:
                            cb(ev)
                        except Exception:
                            pass

                # Forward clock events to plugin clock bus
                # (deduplicate: only process on monitor port)
                if self._plugin_host:
                    if ev.type == MidiEventType.CLOCK:
                        if ev.dest.port == self._monitor_port:
                            self._plugin_host.clock_bus.on_clock_tick()
                    elif ev.type == MidiEventType.START:
                        self._plugin_host.clock_bus.on_start()
                    elif ev.type == MidiEventType.CONTINUE:
                        self._plugin_host.clock_bus.on_continue()
                    elif ev.type == MidiEventType.STOP:
                        self._plugin_host.clock_bus.on_stop()

                # Process filtered MIDI events
                if self._filter_engine:
                    self._filter_engine.process_event(ev)

            if hotplug:
                self._schedule_rescan()

    def panic(self) -> None:
        """Silence all sounding notes across every outbound destination.

        Sends CC 123 (All Notes Off) + CC 120 (All Sound Off) on all 16
        channels to every unique destination that has active connections,
        then asks each plugin to release its internal note state.
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

        panic_port = self._monitor_port if self._monitor_port >= 0 else 0
        dests = {(c.dst_client, c.dst_port) for c in self._connections}

        for dst_client, dst_port in dests:
            for ch in range(16):
                for cc in (123, 120):  # All Notes Off, All Sound Off
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
        log.info("Panic: sent All Notes Off to %d destinations", len(dests))

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

    # --- CC observatory ---

    def _track_cc_event(self, ev) -> None:
        """Update `_cc_cache` from a CC event seen on the monitor port."""
        ch = ev.data.control.channel
        cc = ev.data.control.param
        val = ev.data.control.value
        key = (ev.source.client, ev.source.port, ch, cc)
        if self._cc_cache.get(key) != val:
            self._cc_cache[key] = val
            self._cc_dirty.add(key)

    def _purge_cc_cache_for_client(self, client_id: int) -> None:
        """Drop CC cache entries originating from `client_id`."""
        for key in [k for k in self._cc_cache if k[0] == client_id]:
            self._cc_cache.pop(key, None)
            self._cc_dirty.discard(key)

    def cc_snapshot(self) -> list[dict]:
        """Return the full current CC state — every (port, channel, cc) we've
        observed at least once since the last clear."""
        return [
            {"src_client": sc, "src_port": sp,
             "channel": ch, "cc": cc, "value": val}
            for (sc, sp, ch, cc), val in self._cc_cache.items()
        ]

    def cc_snapshot_dirty(self) -> list[dict]:
        """Return CC entries that changed since the last call. Clears the
        dirty set so subsequent calls only see new changes."""
        out = []
        for key in self._cc_dirty:
            if key not in self._cc_cache:
                continue
            sc, sp, ch, cc = key
            out.append({"src_client": sc, "src_port": sp,
                        "channel": ch, "cc": cc, "value": self._cc_cache[key]})
        self._cc_dirty.clear()
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
