"""BLE-MIDI bridge: translates BLE GATT notifications <-> ALSA sequencer events.

Each connected BLE-MIDI device gets its own ALSA sequencer client with IN/OUT
ports, making it appear as a regular MIDI device in the routing matrix.

Uses dbus-next for async D-Bus communication with BlueZ.
"""

import asyncio
import logging
import struct
import time
from collections import deque

log = logging.getLogger(__name__)

# BLE-MIDI GATT UUIDs (RFC 8160 / Apple BLE-MIDI spec)
MIDI_SERVICE_UUID = "03b80e5a-ede8-4b33-a751-6ce34ec4c700"
MIDI_CHAR_UUID = "7772e5db-3868-4112-a1a9-f2669d106bf3"

# MIDI status byte ranges
_STATUS_NOTE_OFF = 0x80
_STATUS_NOTE_ON = 0x90
_STATUS_POLY_PRESSURE = 0xA0
_STATUS_CC = 0xB0
_STATUS_PROGRAM = 0xC0
_STATUS_CHAN_PRESSURE = 0xD0
_STATUS_PITCH_BEND = 0xE0

# Bytes expected after status (excluding status byte itself)
_STATUS_DATA_LEN = {
    0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2,  # 2 data bytes
    0xC0: 1, 0xD0: 1,                      # 1 data byte
    0xE0: 2,                                # 2 data bytes
}


def parse_ble_midi(data: bytes | bytearray) -> list[tuple[int, list[int]]]:
    """Parse a BLE-MIDI packet into a list of (timestamp_ms, midi_bytes).

    BLE-MIDI packet format (RFC 8160):
    - Byte 0: header (bit 7 set, bits 6-0 = upper 6 bits of timestamp)
    - Byte 1+: alternating timestamp-low bytes (bit 7 set) and MIDI data bytes
    - Timestamp byte: bit 7 set, bits 6-0 = lower 7 bits of timestamp
    - MIDI status bytes: 0x80-0xEF (bit 7 set, but context distinguishes from timestamp)
    - MIDI data bytes: 0x00-0x7F (bit 7 clear)
    - Running status: subsequent messages can omit the status byte

    Returns list of (timestamp_ms, [status, data1, data2, ...]) tuples.
    """
    if len(data) < 3:
        return []

    messages = []
    i = 0

    # Header byte: bit 7 must be set
    header = data[i]
    if not (header & 0x80):
        return []
    ts_high = header & 0x3F  # upper 6 bits of 13-bit timestamp
    i += 1

    running_status = 0

    while i < len(data):
        # Expect timestamp-low byte (bit 7 set)
        if i < len(data) and (data[i] & 0x80):
            ts_low = data[i] & 0x7F
            timestamp = (ts_high << 7) | ts_low
            i += 1
        else:
            timestamp = 0

        if i >= len(data):
            break

        # Check if next byte is a status byte or data byte
        if data[i] & 0x80:
            # Could be a new status byte (0x80-0xEF) or system message
            if data[i] >= 0xF0:
                # System messages — skip for now (SysEx, etc.)
                i += 1
                while i < len(data) and not (data[i] & 0x80):
                    i += 1
                continue
            running_status = data[i]
            i += 1

        if running_status == 0:
            # No status yet, skip
            if i < len(data) and not (data[i] & 0x80):
                i += 1
            continue

        # Determine how many data bytes to read
        status_type = running_status & 0xF0
        expected = _STATUS_DATA_LEN.get(status_type, 0)

        midi_bytes = [running_status]
        for _ in range(expected):
            if i >= len(data):
                break
            if data[i] & 0x80:
                break  # Next timestamp or status, stop collecting
            midi_bytes.append(data[i])
            i += 1

        if len(midi_bytes) == 1 + expected:
            messages.append((timestamp, midi_bytes))

    return messages


def encode_ble_midi(midi_bytes: list[int], timestamp_ms: int = 0) -> bytes:
    """Encode raw MIDI bytes into a BLE-MIDI packet.

    Args:
        midi_bytes: [status, data1, data2, ...]
        timestamp_ms: 13-bit millisecond timestamp (0-8191)

    Returns BLE-MIDI packet bytes.
    """
    ts = timestamp_ms & 0x1FFF
    ts_high = (ts >> 7) & 0x3F
    ts_low = ts & 0x7F

    header = 0x80 | ts_high
    ts_byte = 0x80 | ts_low

    return bytes([header, ts_byte] + midi_bytes)


class _BleDevice:
    """Bridge for a single BLE-MIDI device."""

    def __init__(self, address: str, name: str):
        self.address = address
        self.name = name
        self.alsa_client_id: int | None = None
        self._alsa = None  # AlsaSeq instance
        self._out_port: int = -1  # readable: BLE -> ALSA -> other devices
        self._in_port: int = -1   # writable: other devices -> ALSA -> BLE
        self._char_path: str | None = None  # D-Bus object path for GATT char
        self._bus = None
        self._running = False
        self._read_task: asyncio.Task | None = None
        # Latency tracking
        self._latencies: deque = deque(maxlen=100)
        self._last_latency_ms: float = 0

    @property
    def latency_ms(self) -> float:
        """Rolling average latency in milliseconds."""
        if not self._latencies:
            return 0
        return sum(self._latencies) / len(self._latencies)

    async def connect(self) -> bool:
        """Find GATT characteristic, start notifications, create ALSA ports."""
        try:
            from dbus_next.aio import MessageBus
            from dbus_next import BusType
        except ImportError:
            log.error("dbus-next not installed, cannot bridge BLE-MIDI")
            return False

        try:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        except Exception as e:
            log.error("Failed to connect to system D-Bus: %s", e)
            return False

        # Connect to device via D-Bus (keeps connection alive as long as bus lives)
        dev_dbus_path = ("/org/bluez/hci0/dev_"
                         + self.address.replace(":", "_").upper())
        try:
            dev_intr = await self._bus.introspect("org.bluez", dev_dbus_path)
            dev_obj = self._bus.get_proxy_object(
                "org.bluez", dev_dbus_path, dev_intr)
            dev_iface = dev_obj.get_interface("org.bluez.Device1")
            dev_props = dev_obj.get_interface(
                "org.freedesktop.DBus.Properties")

            # Initiate BLE connection from this D-Bus session
            conn = await dev_props.call_get("org.bluez.Device1", "Connected")
            if not conn.value:
                log.info("Connecting to %s via D-Bus...", self.address)
                try:
                    await dev_iface.call_connect()
                except Exception as e:
                    log.warning("D-Bus Connect() failed for %s: %s",
                                self.address, e)
                    return False

            # Check if already resolved
            sr = await dev_props.call_get(
                "org.bluez.Device1", "ServicesResolved")
            if not sr.value:
                # Wait for the signal
                resolved = asyncio.Event()
                disconnected = asyncio.Event()

                def on_props_changed(iface, changed, invalidated):
                    if iface != "org.bluez.Device1":
                        return
                    for key, val in changed.items():
                        v = val.value if hasattr(val, "value") else val
                        if key == "ServicesResolved" and v:
                            resolved.set()
                        if key == "Connected" and not v:
                            disconnected.set()

                dev_props.on_properties_changed(on_props_changed)

                try:
                    done, pending = await asyncio.wait(
                        [asyncio.ensure_future(resolved.wait()),
                         asyncio.ensure_future(disconnected.wait())],
                        timeout=15.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()

                    if disconnected.is_set():
                        log.warning("Device %s disconnected while waiting "
                                    "for GATT services", self.address)
                        return False
                    if not resolved.is_set():
                        log.warning("GATT services not resolved for %s "
                                    "after 15s", self.address)
                        return False
                finally:
                    dev_props.off_properties_changed(on_props_changed)

        except Exception as e:
            log.warning("Cannot check ServicesResolved for %s: %s",
                        self.address, e)
            return False

        log.info("GATT services resolved for %s, searching for MIDI char",
                 self.address)

        # Find GATT characteristic via D-Bus object manager
        introspection = await self._bus.introspect("org.bluez", "/")
        obj_mgr = self._bus.get_proxy_object("org.bluez", "/", introspection)
        mgr_iface = obj_mgr.get_interface("org.freedesktop.DBus.ObjectManager")
        objects = await mgr_iface.call_get_managed_objects()

        # Search for the BLE-MIDI characteristic
        dev_path_suffix = "dev_" + self.address.replace(":", "_").upper()
        char_path = None

        for path, interfaces in objects.items():
            if dev_path_suffix not in path:
                continue
            if "org.bluez.GattCharacteristic1" not in interfaces:
                continue
            props = interfaces["org.bluez.GattCharacteristic1"]
            uuid = props.get("UUID")
            if uuid and hasattr(uuid, "value"):
                uuid = uuid.value
            if str(uuid).lower() == MIDI_CHAR_UUID:
                char_path = path
                break

        if not char_path:
            log.warning("BLE-MIDI characteristic not found for %s", self.address)
            return False

        self._char_path = char_path
        log.info("Found BLE-MIDI characteristic at %s", char_path)

        # Get the characteristic proxy
        char_introspection = await self._bus.introspect("org.bluez", char_path)
        char_obj = self._bus.get_proxy_object("org.bluez", char_path,
                                               char_introspection)
        self._char_iface = char_obj.get_interface(
            "org.bluez.GattCharacteristic1")
        self._char_props = char_obj.get_interface(
            "org.freedesktop.DBus.Properties")

        # Subscribe to notifications
        try:
            await self._char_iface.call_start_notify()
        except Exception as e:
            log.error("StartNotify failed for %s: %s", self.address, e)
            return False

        # Listen for Value changes
        self._char_props.on_properties_changed(self._on_properties_changed)

        # Create ALSA sequencer client
        from .alsa_seq import AlsaSeq
        client_name = f"BLE {self.name}"
        self._alsa = AlsaSeq(client_name)
        self._out_port = self._alsa.create_port("OUT", readable=True)
        self._in_port = self._alsa.create_port("IN", writable=True)
        self.alsa_client_id = self._alsa.client_id

        log.info("BLE-MIDI bridge started for %s (%s), ALSA client %d",
                 self.name, self.address, self.alsa_client_id)

        # Start ALSA -> BLE forwarding task
        self._running = True
        self._read_task = asyncio.ensure_future(self._alsa_read_loop())

        return True

    def _on_properties_changed(self, interface: str, changed: dict,
                                invalidated: list):
        """Handle GATT characteristic Value notifications (BLE -> ALSA)."""
        if interface != "org.bluez.GattCharacteristic1":
            return
        value = changed.get("Value")
        if value is None:
            return
        # dbus-next wraps in Variant
        if hasattr(value, "value"):
            value = value.value

        arrival = time.monotonic()
        data = bytes(value)

        messages = parse_ble_midi(data)
        if not messages or not self._alsa:
            return

        from .alsa_seq import (
            SndSeqEvent, MidiEventType, SND_SEQ_ADDRESS_SUBSCRIBERS,
            SND_SEQ_QUEUE_DIRECT, snd_seq_event_output_direct,
        )
        from ctypes import pointer

        for timestamp_ms, midi_bytes in messages:
            if len(midi_bytes) < 2:
                continue

            status = midi_bytes[0]
            status_type = status & 0xF0
            channel = status & 0x0F

            ev = SndSeqEvent()
            ev.source.client = self._alsa.client_id
            ev.source.port = self._out_port
            ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
            ev.dest.port = 0
            ev.queue = SND_SEQ_QUEUE_DIRECT
            ev.flags = 0

            if status_type == _STATUS_NOTE_ON and len(midi_bytes) >= 3:
                ev.type = MidiEventType.NOTEON
                ev.data.note.channel = channel
                ev.data.note.note = midi_bytes[1]
                ev.data.note.velocity = midi_bytes[2]
            elif status_type == _STATUS_NOTE_OFF and len(midi_bytes) >= 3:
                ev.type = MidiEventType.NOTEOFF
                ev.data.note.channel = channel
                ev.data.note.note = midi_bytes[1]
                ev.data.note.velocity = midi_bytes[2]
            elif status_type == _STATUS_CC and len(midi_bytes) >= 3:
                ev.type = MidiEventType.CONTROLLER
                ev.data.control.channel = channel
                ev.data.control.param = midi_bytes[1]
                ev.data.control.value = midi_bytes[2]
            elif status_type == _STATUS_PROGRAM and len(midi_bytes) >= 2:
                ev.type = MidiEventType.PGMCHANGE
                ev.data.control.channel = channel
                ev.data.control.value = midi_bytes[1]
            elif status_type == _STATUS_PITCH_BEND and len(midi_bytes) >= 3:
                ev.type = MidiEventType.PITCHBEND
                ev.data.control.channel = channel
                ev.data.control.value = (midi_bytes[2] << 7) | midi_bytes[1]
            elif status_type == _STATUS_CHAN_PRESSURE and len(midi_bytes) >= 2:
                ev.type = MidiEventType.CHANPRESS
                ev.data.control.channel = channel
                ev.data.control.value = midi_bytes[1]
            elif status_type == _STATUS_POLY_PRESSURE and len(midi_bytes) >= 3:
                ev.type = MidiEventType.KEYPRESS
                ev.data.note.channel = channel
                ev.data.note.note = midi_bytes[1]
                ev.data.note.velocity = midi_bytes[2]
            else:
                continue

            try:
                snd_seq_event_output_direct(self._alsa._handle, pointer(ev))
            except Exception as e:
                log.debug("ALSA send failed: %s", e)

        # Track latency (BLE timestamp vs local arrival)
        self._last_latency_ms = (time.monotonic() - arrival) * 1000
        self._latencies.append(self._last_latency_ms)

    async def _alsa_read_loop(self):
        """Poll ALSA IN port and forward events to BLE device."""
        import select

        while self._running and self._alsa:
            try:
                fd = self._alsa.fileno()
                # Use asyncio-compatible polling
                loop = asyncio.get_event_loop()
                ready = await loop.run_in_executor(
                    None, lambda: select.select([fd], [], [], 0.05))
                if not ready[0]:
                    continue

                ev = self._alsa.read_event()
                if ev is None:
                    continue

                # Only forward events arriving on our IN port
                if ev.dest.port != self._in_port:
                    continue

                midi_bytes = self._event_to_midi(ev)
                if midi_bytes:
                    packet = encode_ble_midi(midi_bytes)
                    try:
                        await self._char_iface.call_write_value(
                            list(packet), {})
                    except Exception as e:
                        log.debug("BLE write failed: %s", e)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug("ALSA read error: %s", e)
                await asyncio.sleep(0.01)

    @staticmethod
    def _event_to_midi(ev) -> list[int] | None:
        """Convert an ALSA SndSeqEvent to raw MIDI bytes."""
        from .alsa_seq import MidiEventType
        try:
            ev_type = MidiEventType(ev.type)
        except ValueError:
            return None

        ch = ev.data.note.channel & 0x0F

        if ev_type == MidiEventType.NOTEON:
            return [_STATUS_NOTE_ON | ch, ev.data.note.note, ev.data.note.velocity]
        elif ev_type == MidiEventType.NOTEOFF:
            return [_STATUS_NOTE_OFF | ch, ev.data.note.note, ev.data.note.velocity]
        elif ev_type == MidiEventType.CONTROLLER:
            return [_STATUS_CC | ch, ev.data.control.param & 0x7F,
                    ev.data.control.value & 0x7F]
        elif ev_type == MidiEventType.PGMCHANGE:
            return [_STATUS_PROGRAM | ch, ev.data.control.value & 0x7F]
        elif ev_type == MidiEventType.PITCHBEND:
            val = ev.data.control.value
            return [_STATUS_PITCH_BEND | ch, val & 0x7F, (val >> 7) & 0x7F]
        elif ev_type == MidiEventType.CHANPRESS:
            return [_STATUS_CHAN_PRESSURE | ch, ev.data.control.value & 0x7F]
        elif ev_type == MidiEventType.KEYPRESS:
            return [_STATUS_POLY_PRESSURE | ch, ev.data.note.note,
                    ev.data.note.velocity]
        return None

    async def disconnect(self):
        """Stop bridge and clean up."""
        self._running = False
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self._char_iface:
            try:
                await self._char_iface.call_stop_notify()
            except Exception:
                pass

        if self._alsa:
            self._alsa.close()
            self._alsa = None
            self.alsa_client_id = None

        if self._bus:
            self._bus.disconnect()
            self._bus = None

        log.info("BLE-MIDI bridge stopped for %s", self.address)


class BleMidiBridge:
    """Manages BLE-MIDI bridges for all connected devices."""

    def __init__(self):
        self._bridges: dict[str, _BleDevice] = {}  # address -> _BleDevice

    async def start_bridge(self, address: str, name: str) -> bool:
        """Start a BLE-MIDI bridge for a connected device.

        Returns True if the bridge started successfully (GATT char found,
        ALSA ports created). Returns False if the device doesn't expose
        BLE-MIDI or services haven't resolved yet.
        """
        if address in self._bridges:
            log.info("Bridge already active for %s", address)
            return True

        dev = _BleDevice(address, name)
        ok = await dev.connect()
        if ok:
            self._bridges[address] = dev
            return True
        return False

    async def stop_bridge(self, address: str):
        """Stop and remove a BLE-MIDI bridge."""
        dev = self._bridges.pop(address, None)
        if dev:
            await dev.disconnect()

    async def stop_all(self):
        """Stop all active bridges."""
        for address in list(self._bridges.keys()):
            await self.stop_bridge(address)

    def get_bridges(self) -> list[dict]:
        """Return status of all active bridges."""
        return [
            {
                "address": dev.address,
                "name": dev.name,
                "alsa_client_id": dev.alsa_client_id,
                "latency_ms": round(dev.latency_ms, 1),
            }
            for dev in self._bridges.values()
        ]

    def get_alsa_client_ids(self) -> list[int]:
        """Return ALSA client IDs for all active bridges (for device scan)."""
        return [d.alsa_client_id for d in self._bridges.values()
                if d.alsa_client_id is not None]

    def get_latency(self, address: str) -> float:
        """Get latency for a specific device."""
        dev = self._bridges.get(address)
        return dev.latency_ms if dev else 0
