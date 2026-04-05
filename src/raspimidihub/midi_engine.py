"""MIDI routing engine with hotplug support.

Manages all-to-all MIDI connections between USB MIDI devices
using the ALSA sequencer API.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from .alsa_seq import AlsaSeq, MidiDevice, SeqEventType
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
        self._filter_engine: FilterEngine | None = None
        self._debounce_task: asyncio.Task | None = None
        self._running = False
        self._on_change_callbacks: list = []

    @property
    def devices(self) -> list[MidiDevice]:
        return self._devices

    @property
    def connections(self) -> set[Connection]:
        return self._connections

    def on_change(self, callback):
        """Register a callback for device/connection changes."""
        self._on_change_callbacks.append(callback)

    def _notify_change(self):
        for cb in self._on_change_callbacks:
            try:
                cb()
            except Exception:
                log.exception("Error in change callback")

    @property
    def filter_engine(self) -> FilterEngine | None:
        return self._filter_engine

    def start(self) -> None:
        """Open ALSA sequencer and perform initial scan + connect."""
        self._seq = AlsaSeq("RaspiMIDIHub")
        self._filter_engine = FilterEngine(self._seq)
        log.info("ALSA sequencer opened, client ID %d", self._seq.client_id)
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
        self._devices = self._seq.scan_devices()
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

    def _scan_and_connect(self) -> None:
        """Full state reconstruction: scan devices and connect all."""
        self.disconnect_all()
        self.scan_devices()
        connections = self.connect_all()

        device_names = [d.name for d in self._devices]
        log.info("Devices: %s", device_names if device_names else "(none)")
        log.info("Connections: %d active", len(connections))
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

                # Process filtered MIDI events
                if self._filter_engine:
                    self._filter_engine.process_event(ev)

            if hotplug:
                self._schedule_rescan()

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
