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


# --- snd_seq_event_t (simplified, we only need type field) ---

class SndSeqEvent(Structure):
    _fields_ = [
        ("type", c_uint8),
        ("flags", c_uint8),
        ("tag", c_uint8),
        ("queue", c_uint8),
        ("time", c_uint8 * 8),
        ("source", SndSeqAddr),
        ("dest", SndSeqAddr),
        ("data", c_uint8 * 48),  # union, we don't parse beyond type
    ]

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

    def scan_devices(self) -> list[MidiDevice]:
        """Enumerate all MIDI clients and ports, filtering system/self."""
        devices = []

        cinfo = SndSeqClientInfoPtr()
        check(snd_seq_client_info_malloc(byref(cinfo)), "malloc client_info")
        pinfo = SndSeqPortInfoPtr()
        check(snd_seq_port_info_malloc(byref(pinfo)), "malloc port_info")

        try:
            snd_seq_client_info_set_client(cinfo, -1)
            while snd_seq_query_next_client(self._handle, cinfo) >= 0:
                client_id = snd_seq_client_info_get_client(cinfo)

                # Skip System, Midi Through, ourselves, and other user-space clients
                if client_id in (SND_SEQ_CLIENT_SYSTEM, MIDI_THROUGH_CLIENT_ID, self._client_id):
                    continue

                client_type = snd_seq_client_info_get_type(cinfo)
                if client_type == SND_SEQ_USER_CLIENT:
                    continue  # Only connect hardware (kernel) MIDI devices

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
