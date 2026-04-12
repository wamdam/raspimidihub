"""MIDI routing engine with hotplug support.

Manages all-to-all MIDI connections between USB MIDI devices
using the ALSA sequencer API.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from .alsa_seq import AlsaSeq, MidiDevice, SeqEventType
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
        """Open ALSA sequencer and perform initial scan + connect."""
        self._seq = AlsaSeq("RaspiMIDIHub")
        self._filter_engine = FilterEngine(self._seq)
        # Create a monitor port to receive copies of MIDI events for the UI
        self._monitor_port = self._seq.create_port("monitor", writable=True)
        log.info("ALSA sequencer opened, client ID %d, monitor port %d",
                 self._seq.client_id, self._monitor_port)
        self._scan_and_connect()

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
        # Include plugin and BLE bridge ALSA client IDs so they're discovered
        user_clients = set()
        if self._plugin_host:
            user_clients = self._plugin_host.get_plugin_client_ids()
        ble_bridge = getattr(self, '_ble_bridge', None)
        ble_client_ids = set()
        if ble_bridge:
            ble_client_ids = set(ble_bridge.get_alsa_client_ids())
            user_clients |= ble_client_ids
        self._devices = self._seq.scan_devices(include_user_clients=user_clients)
        # Update device registry with stable IDs (hardware devices via sysfs)
        hw_client_ids = [d.client_id for d in self._devices
                         if d.client_id not in user_clients]
        self._device_registry.scan(hw_client_ids)
        # Register plugin devices in the registry
        if self._plugin_host:
            for inst in self._plugin_host.get_instances():
                if inst.alsa_client:
                    self._device_registry.register_plugin(
                        inst.alsa_client.client_id, inst.id, inst.name)
        # Register BLE-MIDI devices in the registry
        if ble_bridge:
            for b in ble_bridge.get_bridges():
                cid = b["alsa_client_id"]
                if cid and cid in ble_client_ids:
                    info = self._device_registry.register_plugin(
                        cid, f"ble-{b['address']}", b["name"])
                    info.is_plugin = False
                    info.is_bluetooth = True
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

    def _forward_clock_to_all(self, ev: 'SndSeqEvent') -> None:
        """Forward a clock/transport event to all devices that aren't sending clock.

        Tracks which clients are producing clock events (within a 2-second window)
        and excludes them from receiving forwarded clock — this prevents loops
        from devices like the KeyStep that echo clock back out.
        """
        import time
        src_client = ev.source.client
        now = time.monotonic()

        # Track clock sources (clients that have sent clock recently)
        if not hasattr(self, '_clock_sources'):
            self._clock_sources: dict[int, float] = {}  # client_id -> last_seen
        self._clock_sources[src_client] = now

        # Expire stale sources (not seen for 2 seconds)
        stale = [c for c, t in self._clock_sources.items() if now - t > 2.0]
        for c in stale:
            del self._clock_sources[c]

        for dev in self._devices:
            if dev.client_id == self._seq.client_id:
                continue  # skip our own client
            if dev.client_id in self._clock_sources:
                continue  # skip devices that are sending clock (prevents loops)
            for port in dev.output_ports:
                try:
                    self._seq.send_event(ev, dev.client_id, port.port_id)
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

    def _scan_and_connect(self) -> None:
        """Rescan devices and restore connections from live state snapshot.

        Snapshots all connections + filters/mappings before teardown, then
        restores from the snapshot after rescan. This preserves unsaved
        changes across hotplug events.
        """
        # Snapshot live state BEFORE teardown
        snapshot_conns, snapshot_disconn = self._snapshot_live_state()
        has_live_state = bool(snapshot_conns) or bool(snapshot_disconn)

        self.disconnect_all()
        self.scan_devices()

        from .__main__ import _apply_saved_config

        if has_live_state or (self._config and self._config.mode == "custom"):
            _apply_saved_config(self, self._config,
                                snapshot=snapshot_conns,
                                snapshot_disconn=snapshot_disconn)
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

            def _on_readable():
                if not future.done():
                    future.set_result(None)

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

                # Notify MIDI event listeners (for monitoring)
                if self._on_midi_event_callbacks:
                    for cb in self._on_midi_event_callbacks:
                        try:
                            cb(ev)
                        except Exception:
                            pass

                # Forward clock events to plugin clock bus and all devices
                # (deduplicate: only process on monitor port)
                from .alsa_seq import MidiEventType
                if ev.type in (MidiEventType.CLOCK, MidiEventType.START,
                               MidiEventType.CONTINUE, MidiEventType.STOP):
                    if ev.dest.port == self._monitor_port:
                        # Plugin clock bus
                        if self._plugin_host:
                            if ev.type == MidiEventType.CLOCK:
                                self._plugin_host.clock_bus.on_clock_tick()
                            elif ev.type == MidiEventType.START:
                                self._plugin_host.clock_bus.on_start()
                            elif ev.type == MidiEventType.CONTINUE:
                                self._plugin_host.clock_bus.on_continue()
                            elif ev.type == MidiEventType.STOP:
                                self._plugin_host.clock_bus.on_stop()
                        # Global clock bridge: forward to all devices
                        self._forward_clock_to_all(ev)

                # Process filtered MIDI events
                if self._filter_engine:
                    self._filter_engine.process_event(ev)

            if hotplug:
                self._schedule_rescan()

    def snapshot_rates(self) -> dict[str, int]:
        """Snapshot per-port message rates (msgs/sec) and reset counters."""
        rates = dict(self._port_msg_counts)
        self._port_msg_counts.clear()
        self._port_rates = rates
        return rates

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
