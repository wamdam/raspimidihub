"""Low-level ctypes bindings to ALSA sequencer API.

This avoids a dependency on python3-pyalsa which may not be packaged
for all architectures. We only bind the subset we need.
"""

import ctypes
import ctypes.util
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_char_p,
    c_int,
    c_uint,
    c_uint8,
    c_void_p,
    pointer,
)
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag

# --- Load libasound ---

_lib_path = ctypes.util.find_library("asound")
if _lib_path is None:
    raise ImportError("libasound2 not found. Install with: sudo apt install libasound2-dev")
_lib = ctypes.CDLL(_lib_path)

# --- Constants ---

SND_SEQ_OPEN_DUPLEX = 3
SND_SEQ_NONBLOCK = 1
SND_SEQ_PORT_CAP_READ = 1 << 0
SND_SEQ_PORT_CAP_SUBS_READ = 1 << 5
SND_SEQ_PORT_CAP_WRITE = 1 << 1
SND_SEQ_PORT_CAP_SUBS_WRITE = 1 << 6
SND_SEQ_PORT_TYPE_MIDI_GENERIC = 1 << 1
SND_SEQ_PORT_TYPE_APPLICATION = 1 << 20
SND_SEQ_PORT_CAP_NO_EXPORT = 1 << 7

SND_SEQ_CLIENT_SYSTEM = 0
SND_SEQ_PORT_SYSTEM_ANNOUNCE = 1

MIDI_THROUGH_CLIENT_ID = 14

SND_SEQ_QUEUE_DIRECT = 253
SND_SEQ_ADDRESS_SUBSCRIBERS = 254


class SeqEventType(IntEnum):
    PORT_START = 63
    PORT_EXIT = 64
    CLIENT_START = 60
    CLIENT_EXIT = 61


# --- Opaque pointer types ---

class SndSeq(Structure):
    pass

SndSeqPtr = POINTER(SndSeq)


# --- snd_seq_addr_t ---

class SndSeqAddr(Structure):
    _fields_ = [
        ("client", c_uint8),
        ("port", c_uint8),
    ]


# --- snd_seq_port_subscribe_t (opaque, heap-allocated) ---

class SndSeqPortSubscribe(Structure):
    pass

SndSeqPortSubscribePtr = POINTER(SndSeqPortSubscribe)


# --- snd_seq_client_info_t / snd_seq_port_info_t (opaque) ---

class SndSeqClientInfo(Structure):
    pass

class SndSeqPortInfo(Structure):
    pass

SndSeqClientInfoPtr = POINTER(SndSeqClientInfo)
SndSeqPortInfoPtr = POINTER(SndSeqPortInfo)


# --- snd_seq_query_subscribe_t (opaque) ---

class SndSeqQuerySubscribe(Structure):
    pass

SndSeqQuerySubscribePtr = POINTER(SndSeqQuerySubscribe)


# --- MIDI event types for filtering ---

class MidiEventType(IntEnum):
    # Channel voice messages
    NOTEON = 6
    NOTEOFF = 7
    KEYPRESS = 8        # Polyphonic aftertouch
    CONTROLLER = 10     # CC
    PGMCHANGE = 11      # Program Change
    CHANPRESS = 12      # Channel aftertouch
    PITCHBEND = 13
    # System messages
    SYSEX = 130
    # Realtime / Clock
    CLOCK = 36          # MIDI Clock (0xF8)
    START = 37          # 0xFA
    CONTINUE = 38       # 0xFB
    STOP = 39           # 0xFC
    SENSING = 42        # Active sensing 0xFE
    TICK = 35           # MIDI Tick


# Message type groups for filtering UI
MSG_FILTER_GROUPS = {
    "note": {MidiEventType.NOTEON, MidiEventType.NOTEOFF, MidiEventType.KEYPRESS},
    "cc": {MidiEventType.CONTROLLER},
    "pc": {MidiEventType.PGMCHANGE},
    "pitchbend": {MidiEventType.PITCHBEND},
    "aftertouch": {MidiEventType.CHANPRESS, MidiEventType.KEYPRESS},
    "sysex": {MidiEventType.SYSEX},
    "clock": {MidiEventType.CLOCK, MidiEventType.START, MidiEventType.CONTINUE,
              MidiEventType.STOP, MidiEventType.TICK, MidiEventType.SENSING},
}


# --- snd_seq_event_t ---

class SndSeqEventNote(Structure):
    _fields_ = [
        ("channel", c_uint8),
        ("note", c_uint8),
        ("velocity", c_uint8),
        ("off_velocity", c_uint8),
        ("duration", c_uint),
    ]

class SndSeqEventCtrl(Structure):
    _fields_ = [
        ("channel", c_uint8),
        ("unused", c_uint8 * 3),
        ("param", c_uint),
        ("value", c_int),
    ]

class SndSeqEventData(ctypes.Union):
    _fields_ = [
        ("note", SndSeqEventNote),
        ("control", SndSeqEventCtrl),
        ("raw8", c_uint8 * 12),
    ]

class SndSeqEvent(Structure):
    _fields_ = [
        ("type", c_uint8),
        ("flags", c_uint8),
        ("tag", c_uint8),
        ("queue", c_uint8),
        ("time", c_uint8 * 8),
        ("source", SndSeqAddr),
        ("dest", SndSeqAddr),
        ("data", SndSeqEventData),
        ("_pad", c_uint8 * 36),  # rest of the union
    ]

    @property
    def channel(self) -> int:
        """Extract MIDI channel (0-15) from the event."""
        return self.data.note.channel

SndSeqEventPtr = POINTER(SndSeqEvent)


# --- Function prototypes ---

def _func(name, restype, *argtypes):
    fn = getattr(_lib, name)
    fn.restype = restype
    fn.argtypes = argtypes
    return fn

# Core
snd_seq_open = _func("snd_seq_open", c_int, POINTER(SndSeqPtr), c_char_p, c_int, c_int)
snd_seq_close = _func("snd_seq_close", c_int, SndSeqPtr)
snd_seq_set_client_name = _func("snd_seq_set_client_name", c_int, SndSeqPtr, c_char_p)
snd_seq_client_id = _func("snd_seq_client_id", c_int, SndSeqPtr)
snd_seq_poll_descriptors_count = _func("snd_seq_poll_descriptors_count", c_int, SndSeqPtr, c_int)
snd_seq_poll_descriptors = _func("snd_seq_poll_descriptors", c_int, SndSeqPtr, c_void_p, c_uint, c_int)
snd_seq_event_input = _func("snd_seq_event_input", c_int, SndSeqPtr, POINTER(SndSeqEventPtr))
snd_seq_event_output = _func("snd_seq_event_output", c_int, SndSeqPtr, SndSeqEventPtr)
snd_seq_event_output_direct = _func("snd_seq_event_output_direct", c_int, SndSeqPtr, SndSeqEventPtr)
snd_seq_drain_output = _func("snd_seq_drain_output", c_int, SndSeqPtr)

# Client info
snd_seq_client_info_malloc = _func("snd_seq_client_info_malloc", c_int, POINTER(SndSeqClientInfoPtr))
snd_seq_client_info_free = _func("snd_seq_client_info_free", None, SndSeqClientInfoPtr)
snd_seq_client_info_set_client = _func("snd_seq_client_info_set_client", None, SndSeqClientInfoPtr, c_int)
snd_seq_client_info_get_client = _func("snd_seq_client_info_get_client", c_int, SndSeqClientInfoPtr)
snd_seq_client_info_get_name = _func("snd_seq_client_info_get_name", c_char_p, SndSeqClientInfoPtr)
snd_seq_client_info_get_type = _func("snd_seq_client_info_get_type", c_int, SndSeqClientInfoPtr)
snd_seq_query_next_client = _func("snd_seq_query_next_client", c_int, SndSeqPtr, SndSeqClientInfoPtr)

# Client types
SND_SEQ_USER_CLIENT = 1
SND_SEQ_KERNEL_CLIENT = 2

# Port info
snd_seq_port_info_malloc = _func("snd_seq_port_info_malloc", c_int, POINTER(SndSeqPortInfoPtr))
snd_seq_port_info_free = _func("snd_seq_port_info_free", None, SndSeqPortInfoPtr)
snd_seq_port_info_set_client = _func("snd_seq_port_info_set_client", None, SndSeqPortInfoPtr, c_int)
snd_seq_port_info_set_port = _func("snd_seq_port_info_set_port", None, SndSeqPortInfoPtr, c_int)
snd_seq_port_info_get_port = _func("snd_seq_port_info_get_port", c_int, SndSeqPortInfoPtr)
snd_seq_port_info_get_name = _func("snd_seq_port_info_get_name", c_char_p, SndSeqPortInfoPtr)
snd_seq_port_info_get_capability = _func("snd_seq_port_info_get_capability", c_uint, SndSeqPortInfoPtr)
snd_seq_port_info_get_type = _func("snd_seq_port_info_get_type", c_uint, SndSeqPortInfoPtr)
snd_seq_query_next_port = _func("snd_seq_query_next_port", c_int, SndSeqPtr, SndSeqPortInfoPtr)

# Port creation (for subscribing to announce events)
snd_seq_create_simple_port = _func(
    "snd_seq_create_simple_port", c_int,
    SndSeqPtr, c_char_p, c_uint, c_uint,
)

# Subscriptions
snd_seq_port_subscribe_malloc = _func("snd_seq_port_subscribe_malloc", c_int, POINTER(SndSeqPortSubscribePtr))
snd_seq_port_subscribe_free = _func("snd_seq_port_subscribe_free", None, SndSeqPortSubscribePtr)
snd_seq_port_subscribe_set_sender = _func("snd_seq_port_subscribe_set_sender", None, SndSeqPortSubscribePtr, POINTER(SndSeqAddr))
snd_seq_port_subscribe_set_dest = _func("snd_seq_port_subscribe_set_dest", None, SndSeqPortSubscribePtr, POINTER(SndSeqAddr))
snd_seq_subscribe_port = _func("snd_seq_subscribe_port", c_int, SndSeqPtr, SndSeqPortSubscribePtr)
snd_seq_unsubscribe_port = _func("snd_seq_unsubscribe_port", c_int, SndSeqPtr, SndSeqPortSubscribePtr)

# Query subscriptions
snd_seq_query_subscribe_malloc = _func("snd_seq_query_subscribe_malloc", c_int, POINTER(SndSeqQuerySubscribePtr))
snd_seq_query_subscribe_free = _func("snd_seq_query_subscribe_free", None, SndSeqQuerySubscribePtr)
snd_seq_query_subscribe_set_root = _func("snd_seq_query_subscribe_set_root", None, SndSeqQuerySubscribePtr, POINTER(SndSeqAddr))
snd_seq_query_subscribe_set_type = _func("snd_seq_query_subscribe_set_type", None, SndSeqQuerySubscribePtr, c_int)
snd_seq_query_subscribe_set_index = _func("snd_seq_query_subscribe_set_index", None, SndSeqQuerySubscribePtr, c_int)
snd_seq_query_subscribe_get_addr = _func("snd_seq_query_subscribe_get_addr", POINTER(SndSeqAddr), SndSeqQuerySubscribePtr)
snd_seq_query_subscribe_get_index = _func("snd_seq_query_subscribe_get_index", c_int, SndSeqQuerySubscribePtr)
snd_seq_query_port_subscribers = _func("snd_seq_query_port_subscribers", c_int, SndSeqPtr, SndSeqQuerySubscribePtr)

# Connect/disconnect to system announce port
snd_seq_connect_from = _func("snd_seq_connect_from", c_int, SndSeqPtr, c_int, c_int, c_int)

# Error string
snd_strerror = _func("snd_strerror", c_char_p, c_int)


# --- High-level helpers ---

@dataclass
class MidiPort:
    port_id: int
    name: str
    is_input: bool   # can be read from (produces MIDI data)
    is_output: bool  # can be written to (consumes MIDI data)


@dataclass
class MidiDevice:
    client_id: int
    name: str
    ports: list[MidiPort] = field(default_factory=list)

    @property
    def input_ports(self) -> list[MidiPort]:
        return [p for p in self.ports if p.is_input]

    @property
    def output_ports(self) -> list[MidiPort]:
        return [p for p in self.ports if p.is_output]


def check(ret: int, msg: str = "ALSA error"):
    if ret < 0:
        err = snd_strerror(ret)
        raise OSError(f"{msg}: {err.decode() if err else f'error {ret}'}")


class AlsaSeq:
    """Wrapper around an ALSA sequencer client handle."""

    def __init__(self, client_name: str = "RaspiMIDIHub"):
        self._handle = SndSeqPtr()
        check(snd_seq_open(byref(self._handle), b"default", SND_SEQ_OPEN_DUPLEX, SND_SEQ_NONBLOCK),
              "Failed to open ALSA sequencer")
        snd_seq_set_client_name(self._handle, client_name.encode())
        self._client_id = snd_seq_client_id(self._handle)

        # Create a port to receive system announce events
        self._announce_port = snd_seq_create_simple_port(
            self._handle,
            b"listen:announce",
            SND_SEQ_PORT_CAP_WRITE | SND_SEQ_PORT_CAP_SUBS_WRITE,
            SND_SEQ_PORT_TYPE_APPLICATION,
        )
        check(self._announce_port, "Failed to create announce port")

        # Create an output port for sending test events
        self._output_port = snd_seq_create_simple_port(
            self._handle,
            b"output",
            SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ,
            SND_SEQ_PORT_TYPE_MIDI_GENERIC | SND_SEQ_PORT_TYPE_APPLICATION,
        )
        check(self._output_port, "Failed to create output port")

        # CC coalescing state for send_event_coalesced
        self._cc_pending: dict = {}  # (dest, port, ch, cc) -> value
        self._cc_flush_timer = None

        # Subscribe to system announcements
        check(
            snd_seq_connect_from(
                self._handle, self._announce_port,
                SND_SEQ_CLIENT_SYSTEM, SND_SEQ_PORT_SYSTEM_ANNOUNCE,
            ),
            "Failed to subscribe to system announce",
        )

    @property
    def client_id(self) -> int:
        return self._client_id

    @property
    def handle(self) -> SndSeqPtr:
        return self._handle

    def fileno(self) -> int:
        """Return poll fd for use with asyncio."""
        import struct
        # pollfd is struct { int fd; short events; short revents; }
        count = snd_seq_poll_descriptors_count(self._handle, 1)  # POLLIN=1
        buf = ctypes.create_string_buffer(8 * count)  # sizeof(struct pollfd) = 8
        snd_seq_poll_descriptors(self._handle, buf, count, 1)
        fd = struct.unpack_from("i", buf, 0)[0]
        return fd

    def scan_devices(self, include_user_clients: set[int] | None = None) -> list[MidiDevice]:
        """Enumerate all MIDI clients and ports, filtering system/self.

        Args:
            include_user_clients: Set of user-space client IDs to include
                (e.g. plugin virtual devices). Other user clients are still skipped.
        """
        devices = []
        include_user_clients = include_user_clients or set()

        cinfo = SndSeqClientInfoPtr()
        check(snd_seq_client_info_malloc(byref(cinfo)), "malloc client_info")
        pinfo = SndSeqPortInfoPtr()
        check(snd_seq_port_info_malloc(byref(pinfo)), "malloc port_info")

        try:
            snd_seq_client_info_set_client(cinfo, -1)
            while snd_seq_query_next_client(self._handle, cinfo) >= 0:
                client_id = snd_seq_client_info_get_client(cinfo)

                # Skip System, Midi Through, ourselves
                if client_id in (SND_SEQ_CLIENT_SYSTEM, MIDI_THROUGH_CLIENT_ID, self._client_id):
                    continue

                client_type = snd_seq_client_info_get_type(cinfo)
                if client_type == SND_SEQ_USER_CLIENT and client_id not in include_user_clients:
                    continue  # Only connect hardware (kernel) MIDI devices + whitelisted plugins

                name_raw = snd_seq_client_info_get_name(cinfo)
                client_name = name_raw.decode("utf-8", errors="replace") if name_raw else f"Client {client_id}"

                ports = []
                snd_seq_port_info_set_client(pinfo, client_id)
                snd_seq_port_info_set_port(pinfo, -1)
                while snd_seq_query_next_port(self._handle, pinfo) >= 0:
                    cap = snd_seq_port_info_get_capability(pinfo)
                    port_type = snd_seq_port_info_get_type(pinfo)

                    # Skip ports that don't allow subscription or are no-export
                    if cap & SND_SEQ_PORT_CAP_NO_EXPORT:
                        continue

                    is_input = bool(cap & SND_SEQ_PORT_CAP_READ and cap & SND_SEQ_PORT_CAP_SUBS_READ)
                    is_output = bool(cap & SND_SEQ_PORT_CAP_WRITE and cap & SND_SEQ_PORT_CAP_SUBS_WRITE)

                    if not is_input and not is_output:
                        continue

                    port_id = snd_seq_port_info_get_port(pinfo)
                    port_name_raw = snd_seq_port_info_get_name(pinfo)
                    port_name = port_name_raw.decode("utf-8", errors="replace") if port_name_raw else f"Port {port_id}"

                    ports.append(MidiPort(
                        port_id=port_id,
                        name=port_name,
                        is_input=is_input,
                        is_output=is_output,
                    ))

                if ports:
                    devices.append(MidiDevice(client_id=client_id, name=client_name, ports=ports))
        finally:
            snd_seq_client_info_free(cinfo)
            snd_seq_port_info_free(pinfo)

        return devices

    def subscribe(self, src_client: int, src_port: int, dst_client: int, dst_port: int) -> None:
        """Create a port subscription (src output -> dst input)."""
        sub = SndSeqPortSubscribePtr()
        check(snd_seq_port_subscribe_malloc(byref(sub)), "malloc subscribe")
        try:
            sender = SndSeqAddr(client=src_client, port=src_port)
            dest = SndSeqAddr(client=dst_client, port=dst_port)
            snd_seq_port_subscribe_set_sender(sub, pointer(sender))
            snd_seq_port_subscribe_set_dest(sub, pointer(dest))
            ret = snd_seq_subscribe_port(self._handle, sub)
            if ret < 0 and ret != -16:  # -16 = EBUSY (already connected)
                check(ret, f"subscribe {src_client}:{src_port} -> {dst_client}:{dst_port}")
        finally:
            snd_seq_port_subscribe_free(sub)

    def unsubscribe(self, src_client: int, src_port: int, dst_client: int, dst_port: int) -> None:
        """Remove a port subscription."""
        sub = SndSeqPortSubscribePtr()
        check(snd_seq_port_subscribe_malloc(byref(sub)), "malloc subscribe")
        try:
            sender = SndSeqAddr(client=src_client, port=src_port)
            dest = SndSeqAddr(client=dst_client, port=dst_port)
            snd_seq_port_subscribe_set_sender(sub, pointer(sender))
            snd_seq_port_subscribe_set_dest(sub, pointer(dest))
            ret = snd_seq_unsubscribe_port(self._handle, sub)
            if ret < 0 and ret != -6:  # -6 = ENXIO (not connected)
                check(ret, f"unsubscribe {src_client}:{src_port} -> {dst_client}:{dst_port}")
        finally:
            snd_seq_port_subscribe_free(sub)

    def create_port(self, name: str, readable: bool = False, writable: bool = False) -> int:
        """Create a new port on this client. Returns port ID."""
        caps = 0
        if readable:
            caps |= SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ
        if writable:
            caps |= SND_SEQ_PORT_CAP_WRITE | SND_SEQ_PORT_CAP_SUBS_WRITE
        port_id = snd_seq_create_simple_port(
            self._handle, name.encode(), caps,
            SND_SEQ_PORT_TYPE_MIDI_GENERIC | SND_SEQ_PORT_TYPE_APPLICATION,
        )
        check(port_id, f"Failed to create port {name}")
        return port_id

    def send_event(self, ev: SndSeqEvent, dest_client: int, dest_port: int) -> None:
        """Send a MIDI event directly to a specific destination port."""
        ev.source.client = self._client_id
        ev.source.port = self._output_port
        ev.dest.client = dest_client
        ev.dest.port = dest_port
        ev.queue = SND_SEQ_QUEUE_DIRECT
        ev.flags = 0
        ret = snd_seq_event_output_direct(self._handle, pointer(ev))
        if ret < 0:
            err = snd_strerror(ret)
            import logging
            logging.getLogger(__name__).warning(
                "send_event to %d:%d failed: %s", dest_client, dest_port,
                err.decode() if err else f"error {ret}"
            )

    def send_event_coalesced(self, ev: SndSeqEvent, dest_client: int, dest_port: int) -> None:
        """Send a MIDI event with CC coalescing.

        For CC events, only the latest value per (dest, channel, cc#) is sent,
        flushed at ~333 Hz. Notes and other events pass through immediately.
        This prevents flooding the MIDI bus from rapid UI fader/wheel changes.
        """
        if ev.type == MidiEventType.CONTROLLER:
            key = (dest_client, dest_port, ev.data.control.channel, ev.data.control.param)
            self._cc_pending[key] = ev.data.control.value
            self._start_cc_flush()
        else:
            self.send_event(ev, dest_client, dest_port)

    def _start_cc_flush(self) -> None:
        """Start the CC flush timer if not already running."""
        if self._cc_flush_timer is not None:
            return
        import threading
        def flush():
            self._cc_flush_timer = None
            pending = dict(self._cc_pending)
            self._cc_pending.clear()
            for (dc, dp, ch, cc), val in pending.items():
                ev = SndSeqEvent()
                ev.type = MidiEventType.CONTROLLER
                ev.data.control.channel = ch
                ev.data.control.param = cc
                ev.data.control.value = val
                self.send_event(ev, dc, dp)
        self._cc_flush_timer = threading.Timer(0.003, flush)  # 3ms = ~333 Hz
        self._cc_flush_timer.daemon = True
        self._cc_flush_timer.start()

    def send_note_on(self, dest_client: int, dest_port: int,
                     channel: int, note: int, velocity: int = 100) -> None:
        """Send a MIDI Note On event."""
        ev = SndSeqEvent()
        ev.type = MidiEventType.NOTEON
        ev.data.note.channel = channel
        ev.data.note.note = note
        ev.data.note.velocity = velocity
        self.send_event(ev, dest_client, dest_port)

    def send_note_off(self, dest_client: int, dest_port: int,
                      channel: int, note: int) -> None:
        """Send a MIDI Note Off event."""
        ev = SndSeqEvent()
        ev.type = MidiEventType.NOTEOFF
        ev.data.note.channel = channel
        ev.data.note.note = note
        ev.data.note.velocity = 0
        self.send_event(ev, dest_client, dest_port)

    def send_cc(self, dest_client: int, dest_port: int,
                channel: int, cc: int, value: int) -> None:
        """Send a MIDI CC event."""
        ev = SndSeqEvent()
        ev.type = MidiEventType.CONTROLLER
        ev.data.control.channel = channel
        ev.data.control.param = cc
        ev.data.control.value = value
        self.send_event(ev, dest_client, dest_port)

    def read_event(self) -> SndSeqEvent | None:
        """Read one event (non-blocking). Returns None if no event available."""
        ev = SndSeqEventPtr()
        ret = snd_seq_event_input(self._handle, byref(ev))
        if ret < 0:
            return None  # EAGAIN or error
        return ev.contents

    def close(self) -> None:
        if self._handle:
            snd_seq_close(self._handle)
            self._handle = SndSeqPtr()
