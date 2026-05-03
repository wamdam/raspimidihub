"""BLE-MIDI bridge: translates BLE GATT notifications <-> ALSA sequencer events.

Each connected BLE-MIDI device gets its own ALSA sequencer client with IN/OUT
ports, making it appear as a regular MIDI device in the routing matrix.

Uses dbus-next for async D-Bus communication with BlueZ.

Why a userspace bridge at all
-----------------------------

BlueZ ships its own `midi` plugin (`profiles/midi/midi.c`) that is meant
to do exactly this — and on paper it's the "default Linux tool" for
BLE-MIDI. We don't use it. Verified end-to-end with btmon + aseqdump
on WIDI Master:

  - btmon: ATT Handle Value Notification (handle 0x001b) packets
    arrive on the radio every time a key is pressed.
  - aseqdump -p <bluetoothd-client>:0 captures zero events.

So the radio receives BLE-MIDI fine, but BlueZ's plugin doesn't forward
the GATT notifications to its ALSA seq client. The only symptom in the
journal is `profiles/midi/midi.c:midi_io_initial_read_cb() MIDI I/O:
Failed to read initial request` — BLE-MIDI characteristics generally
don't allow Read (only Notify), and the plugin appears to give up
rather than fall back to subscribe-only.

bluez-alsa with `-p midi` was also tried: its `midi` profile is for
classic Bluetooth MIDI hardware (rare), not BLE-MIDI. It sees the
GATT tree but never creates a PCM/seq.

So we disable BlueZ's `midi` plugin via a systemd drop-in
(`/etc/systemd/system/bluetooth.service.d/no-midi.conf` passes
`-P midi` to bluetoothd) and own the GATT subscription in this module.
Latency cost is negligible: BLE-MIDI's connection interval (7.5–15 ms)
dominates everything we add (one D-Bus signal handler + ioctl,
typically <200 µs on the isolated CPU 3).

Persistence: BlueZ writes to /var/lib/bluetooth (bond keys, device
cache). Our root is read-only, so we mount a tmpfs there at boot and
restore from a tarball on /boot/firmware via raspimidihub-bt-state.
"""

import asyncio
import logging
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
            # Could be a new status byte (0x80-0xEF) or system message.
            if data[i] >= 0xF0:
                sys_status = data[i]
                i += 1
                # System Real-Time (0xF8-0xFF): single byte, no data.
                # Don't update running_status — real-time can interleave
                # without breaking a running channel-voice conversation.
                if sys_status >= 0xF8:
                    messages.append((timestamp, [sys_status]))
                    continue
                # System Common with data bytes: handle the short ones
                # we care about (Song Position Pointer, Song Select,
                # MTC Quarter Frame). SysEx (0xF0/0xF7) still TODO —
                # needs a multi-packet reassembly buffer.
                if sys_status == 0xF2:    # Song Position Pointer
                    sc_data_expected = 2
                elif sys_status in (0xF1, 0xF3):  # MTC QF, Song Select
                    sc_data_expected = 1
                elif sys_status == 0xF6:  # Tune Request
                    messages.append((timestamp, [sys_status]))
                    continue
                else:
                    # SysEx or unknown — drop the rest until next status
                    while i < len(data) and not (data[i] & 0x80):
                        i += 1
                    continue
                sys_bytes = [sys_status]
                for _ in range(sc_data_expected):
                    if i >= len(data) or (data[i] & 0x80):
                        break
                    sys_bytes.append(data[i])
                    i += 1
                if len(sys_bytes) == 1 + sc_data_expected:
                    messages.append((timestamp, sys_bytes))
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

    def __init__(self, address: str, name: str, on_disconnected=None):
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
        # Callback fired when BlueZ reports the BLE link dropped after a
        # successful bridge. Owner uses this to remove the bridge from
        # its dict, close the ALSA seq client, and let the engine's
        # hotplug rescan update the matrix.
        self._on_disconnected = on_disconnected
        self._dev_props = None  # for un-subscribing the Connected watcher
        self._connected_handler = None
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
        """Find GATT characteristic, start notifications, create ALSA ports.

        Every D-Bus call is wrapped in a timeout — bluetoothd can hang
        forever on an unresponsive peripheral (or one that demands
        pairing we can't satisfy), and the previous version manifested
        that as the user seeing a button stuck on "Connecting…" with
        no log output. With the timeouts, each step either succeeds
        within a few seconds or logs a clear failure."""
        try:
            from dbus_next import BusType
            from dbus_next.aio import MessageBus
        except ImportError:
            log.error("dbus-next not installed, cannot bridge BLE-MIDI")
            return False

        try:
            self._bus = await asyncio.wait_for(
                MessageBus(bus_type=BusType.SYSTEM).connect(), timeout=5.0)
        except (asyncio.TimeoutError, Exception) as e:
            log.error("Failed to connect to system D-Bus: %s", e)
            return False

        # Connect to device via D-Bus (keeps connection alive as long as bus lives)
        dev_dbus_path = ("/org/bluez/hci0/dev_"
                         + self.address.replace(":", "_").upper())
        try:
            dev_intr = await asyncio.wait_for(
                self._bus.introspect("org.bluez", dev_dbus_path),
                timeout=5.0)
            dev_obj = self._bus.get_proxy_object(
                "org.bluez", dev_dbus_path, dev_intr)
            dev_iface = dev_obj.get_interface("org.bluez.Device1")
            dev_props = dev_obj.get_interface(
                "org.freedesktop.DBus.Properties")

            # Initiate BLE connection from this D-Bus session.
            # If the device is "Connected: yes" but services aren't
            # resolved, BlueZ is in a known stuck state (we've seen
            # this with WIDI Master on first attempt: Connected: yes
            # but the GATT tree under the device path is empty). The
            # documented workaround is a Disconnect → Connect cycle
            # to force fresh service discovery.
            conn = await dev_props.call_get("org.bluez.Device1", "Connected")
            sr = await dev_props.call_get("org.bluez.Device1", "ServicesResolved")
            if conn.value and not sr.value:
                log.info("Bouncing %s connection to clear stuck GATT", self.address)
                try:
                    await asyncio.wait_for(
                        dev_iface.call_disconnect(), timeout=5.0)
                    await asyncio.sleep(1.0)
                except (asyncio.TimeoutError, Exception) as e:
                    log.warning("Disconnect before bounce failed for %s: %s",
                                self.address, e)
                conn = await dev_props.call_get("org.bluez.Device1", "Connected")
            if not conn.value:
                log.info("Connecting to %s via D-Bus...", self.address)
                try:
                    await asyncio.wait_for(
                        dev_iface.call_connect(), timeout=10.0)
                except asyncio.TimeoutError:
                    log.warning("D-Bus Connect() timed out for %s", self.address)
                    return False
                except Exception as e:
                    log.warning("D-Bus Connect() failed for %s: %s",
                                self.address, e)
                    return False

            # Wait for ServicesResolved. Register the handler FIRST so
            # we don't miss a flip between the property read and the
            # subscription, then re-check the property — that closes
            # the race without needing a poll fallback.
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
                sr = await dev_props.call_get(
                    "org.bluez.Device1", "ServicesResolved")
                if sr.value:
                    resolved.set()
                # Some BLE-MIDI peripherals (e.g. WIDI Master) take
                # well over 30s to publish their full GATT tree on
                # first connect — 60s is a generous backstop. If even
                # that isn't enough the user can re-tap Connect;
                # bridges aren't cached on failure, so a retry is a
                # fresh attempt.
                if not resolved.is_set():
                    done, pending = await asyncio.wait(
                        [asyncio.ensure_future(resolved.wait()),
                         asyncio.ensure_future(disconnected.wait())],
                        timeout=60.0,
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
                                "after 60s", self.address)
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
        try:
            char_introspection = await asyncio.wait_for(
                self._bus.introspect("org.bluez", char_path), timeout=5.0)
        except asyncio.TimeoutError:
            log.error("Introspect of MIDI char timed out for %s", self.address)
            return False
        char_obj = self._bus.get_proxy_object("org.bluez", char_path,
                                               char_introspection)
        self._char_iface = char_obj.get_interface(
            "org.bluez.GattCharacteristic1")
        self._char_props = char_obj.get_interface(
            "org.freedesktop.DBus.Properties")

        # Listen for Value changes BEFORE StartNotify so we don't race
        # the first notification.
        self._char_props.on_properties_changed(self._on_properties_changed)

        # Some BLE-MIDI peripherals (WIDI Master in current firmware)
        # mark the MIDI characteristic as encrypted-only, so BlueZ
        # initiates a Pair handshake on StartNotify. With no agent +
        # no bond that hangs until our timeout. Pair explicitly here
        # — succeeds via Just-Works on the agent registered by the
        # bridge — and Trust so reconnects are auto-accepted later.
        try:
            paired = await dev_props.call_get(
                "org.bluez.Device1", "Paired")
            if not paired.value:
                log.info("Pairing %s before subscribing to MIDI char",
                         self.address)
                try:
                    await asyncio.wait_for(
                        dev_iface.call_pair(), timeout=15.0)
                except asyncio.TimeoutError:
                    log.warning("Pair timed out for %s — proceeding "
                                "anyway, StartNotify may still work",
                                self.address)
                except Exception as e:
                    # AlreadyExists / AuthenticationFailed — log and
                    # continue, some devices reject Pair but allow
                    # encrypted notify anyway.
                    log.warning("Pair failed for %s: %s — continuing",
                                self.address, e)
                # Trust the device so future reconnects skip the
                # confirmation dance.
                try:
                    await asyncio.wait_for(
                        dev_props.call_set(
                            "org.bluez.Device1", "Trusted",
                            __import__("dbus_next").Variant("b", True)),
                        timeout=3.0)
                except Exception:
                    pass
        except Exception as e:
            log.warning("Could not check Paired state for %s: %s",
                        self.address, e)

        # Subscribe to notifications. StartNotify can hang indefinitely
        # if BlueZ is mid-pair or the peripheral demands authentication
        # we can't supply — the timeout makes that surface as a clean
        # failure rather than a stuck UI.
        try:
            await asyncio.wait_for(
                self._char_iface.call_start_notify(), timeout=10.0)
        except asyncio.TimeoutError:
            log.error("StartNotify timed out for %s — likely auth required",
                      self.address)
            return False
        except Exception as e:
            log.error("StartNotify failed for %s: %s", self.address, e)
            return False

        # Create ALSA sequencer client. Name == device alias so the
        # detection in device_id.py (`name in bt_macs`) matches and
        # registers it with the `bt-<MAC>` stable id. default_ports
        # off so we don't get a stray "output" port alongside OUT/IN.
        from .alsa_seq import AlsaSeq
        self._alsa = AlsaSeq(self.name, default_ports=False)
        self._out_port = self._alsa.create_port("OUT", readable=True)
        self._in_port = self._alsa.create_port("IN", writable=True)
        self.alsa_client_id = self._alsa.client_id

        log.info("BLE-MIDI bridge started for %s (%s), ALSA client %d",
                 self.name, self.address, self.alsa_client_id)

        # Watch for BlueZ-side disconnection so the matrix updates
        # when the peripheral goes out of range or powers off. Without
        # this, our ALSA seq client stays around indefinitely and the
        # device shows as still online.
        self._dev_props = dev_props
        loop = asyncio.get_event_loop()

        def _on_dev_props(iface, changed, invalidated):
            if iface != "org.bluez.Device1":
                return
            if "Connected" in changed:
                v = changed["Connected"]
                if hasattr(v, "value"):
                    v = v.value
                if not v and self._on_disconnected:
                    log.info("BlueZ reports %s disconnected — tearing "
                             "down bridge", self.address)
                    loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(
                            self._on_disconnected(self.address)))

        self._connected_handler = _on_dev_props
        dev_props.on_properties_changed(_on_dev_props)

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

        from ctypes import pointer

        from .alsa_seq import (
            SND_SEQ_ADDRESS_SUBSCRIBERS,
            SND_SEQ_QUEUE_DIRECT,
            MidiEventType,
            SndSeqEvent,
            snd_seq_event_output_direct,
        )

        # The 13-bit BLE-MIDI timestamps are interesting for jitter
        # smoothing but we forward immediately — discard.
        for _timestamp_ms, midi_bytes in messages:
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
            elif status == 0xF8:  # Timing Clock
                ev.type = MidiEventType.CLOCK
            elif status == 0xFA:  # Start
                ev.type = MidiEventType.START
            elif status == 0xFB:  # Continue
                ev.type = MidiEventType.CONTINUE
            elif status == 0xFC:  # Stop
                ev.type = MidiEventType.STOP
            elif status == 0xF2 and len(midi_bytes) >= 3:  # Song Position
                ev.type = MidiEventType.SONGPOS
                ev.data.control.value = midi_bytes[1] | (midi_bytes[2] << 7)
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
                # Use asyncio-compatible polling. Bind `fd` into the
                # closure as a default arg to dodge B023 — without it,
                # the lambda would resolve `fd` lazily on each call
                # and break if the outer loop reassigned it.
                loop = asyncio.get_event_loop()
                ready = await loop.run_in_executor(
                    None, lambda f=fd: select.select([f], [], [], 0.05))
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
                        # dbus-next maps GATT 'ay' to Python bytes;
                        # passing a list raises TypeError. encode_ble_midi
                        # already returns bytes — pass as-is.
                        await self._char_iface.call_write_value(packet, {})
                    except Exception as e:
                        log.warning("BLE write failed: %s", e)
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
        # System Real-Time and Song Position. Single-byte real-time
        # messages don't have a channel; the BLE-MIDI spec allows them
        # to ride in the same packet as channel-voice via repeated
        # timestamp bytes — encode_ble_midi handles that for us when
        # we send each as its own packet.
        elif ev_type == MidiEventType.CLOCK:
            return [0xF8]
        elif ev_type == MidiEventType.START:
            return [0xFA]
        elif ev_type == MidiEventType.CONTINUE:
            return [0xFB]
        elif ev_type == MidiEventType.STOP:
            return [0xFC]
        elif ev_type == MidiEventType.SONGPOS:
            val = ev.data.control.value & 0x3FFF
            return [0xF2, val & 0x7F, (val >> 7) & 0x7F]
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

        # Detach the Connected-property watcher first so a late-firing
        # signal during teardown can't re-enter _on_disconnected.
        if self._dev_props and self._connected_handler:
            try:
                self._dev_props.off_properties_changed(self._connected_handler)
            except Exception:
                pass
            self._connected_handler = None
            self._dev_props = None

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


# BlueZ D-Bus path we register our pairing agent at. Any non-existent
# path under /org/bluez works.
_AGENT_PATH = "/org/raspimidihub/btagent"


def _build_just_works_agent():
    """Construct a Just-Works pairing agent class.

    Built lazily so the import of dbus_next.service only happens on
    machines that actually have dbus-next (it's a debian dep, but we
    keep the module importable in test environments without it).

    BlueZ requires SOMETHING to handle Agent1 callbacks during Pair
    on peripherals that demand encryption (WIDI Master is one). With
    capability "NoInputNoOutput" we declare we have no display and no
    keyboard — that picks the Just-Works association mode, where no
    user interaction is needed and the pairing succeeds immediately.
    Each method body is a no-op or a vacuous return; the absence of
    a raised exception is what BlueZ treats as 'OK, proceed'."""
    from dbus_next.service import ServiceInterface, method

    class JustWorksAgent(ServiceInterface):
        def __init__(self):
            super().__init__("org.bluez.Agent1")

        @method()
        def Release(self):
            pass

        @method()
        def RequestPinCode(self, device: "o") -> "s":  # noqa: F821
            return ""

        @method()
        def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: F821
            pass

        @method()
        def RequestPasskey(self, device: "o") -> "u":  # noqa: F821
            return 0

        @method()
        def DisplayPasskey(self, device: "o", passkey: "u",  # noqa: F821
                           entered: "q"):  # noqa: F821
            pass

        @method()
        def RequestConfirmation(self, device: "o",  # noqa: F821
                                passkey: "u"):  # noqa: F821
            # Numeric Comparison: blindly confirm. Acceptable for a
            # MIDI hub that's the only thing the user actively pairs.
            pass

        @method()
        def RequestAuthorization(self, device: "o"):  # noqa: F821
            pass

        @method()
        def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: F821
            pass

        @method()
        def Cancel(self):
            pass

    return JustWorksAgent()


class BleMidiBridge:
    """Manages BLE-MIDI bridges for all connected devices."""

    def __init__(self):
        self._bridges: dict[str, _BleDevice] = {}  # address -> _BleDevice
        self._agent_registered = False
        self._bus = None  # MessageBus handle for the agent

    async def _ensure_agent(self) -> None:
        """Register a Just-Works pairing agent with BlueZ once.

        Idempotent. WIDI Master and similar BLE-MIDI peripherals
        require an encrypted/bonded link before they'll allow
        StartNotify on the MIDI characteristic. Without a registered
        agent BlueZ has nothing to drive the pairing exchange and
        Pair() (or any subscribe that triggers pairing internally)
        hangs until our timeout fires."""
        if self._agent_registered:
            return
        try:
            from dbus_next import BusType
            from dbus_next.aio import MessageBus
        except ImportError:
            log.warning("dbus-next missing; pairing will not work")
            return
        try:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            agent = _build_just_works_agent()
            self._bus.export(_AGENT_PATH, agent)
            intr = await self._bus.introspect("org.bluez", "/org/bluez")
            obj = self._bus.get_proxy_object("org.bluez", "/org/bluez", intr)
            mgr = obj.get_interface("org.bluez.AgentManager1")
            await mgr.call_register_agent(_AGENT_PATH, "NoInputNoOutput")
            try:
                await mgr.call_request_default_agent(_AGENT_PATH)
            except Exception:
                # Not fatal — we just want our agent to handle our
                # paired devices; default-agent is best-effort.
                pass
            self._agent_registered = True
            log.info("Registered BlueZ Just-Works pairing agent at %s",
                     _AGENT_PATH)
        except Exception as e:
            log.warning("Failed to register pairing agent: %s", e)

    async def start_bridge(self, address: str, name: str) -> bool:
        """Start a BLE-MIDI bridge for a connected device.

        Returns True if the bridge started successfully (GATT char found,
        ALSA ports created). Returns False if the device doesn't expose
        BLE-MIDI or services haven't resolved yet.
        """
        if address in self._bridges:
            log.info("Bridge already active for %s", address)
            return True

        await self._ensure_agent()

        dev = _BleDevice(address, name, on_disconnected=self._on_dev_dropped)
        ok = await dev.connect()
        if ok:
            self._bridges[address] = dev
            return True
        return False

    async def _on_dev_dropped(self, address: str) -> None:
        """Called from a device's Connected=false D-Bus signal.

        Tears down the bridge cleanly. Closing the AlsaSeq client fires
        an ALSA SND_SEQ_EVENT_CLIENT_EXIT which the engine's hotplug
        listener picks up — that drives the matrix update."""
        await self.stop_bridge(address)

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
