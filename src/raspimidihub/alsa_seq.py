"""Low-level ctypes bindings to ALSA sequencer API.

This avoids a dependency on python3-pyalsa which may not be packaged
for all architectures. We only bind the subset we need.
"""

import ctypes
import ctypes.util
import os
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_char,
    c_char_p,
    c_int,
    c_uint,
    c_uint8,
    c_uint16,
    c_uint32,
    c_void_p,
    pointer,
)
from dataclasses import dataclass, field
from enum import IntEnum

# --- Load libasound ---

if os.environ.get("RASPIMIDIHUB_TEST_MODE"):
    # Test mode: provide a mock lib so structs/enums are importable without libasound
    class _MockFunc:
        """Mock ALSA function that accepts any attribute assignment and returns 0."""
        def __init__(self):
            self.restype = None
            self.argtypes = None
        def __call__(self, *args, **kwargs):
            return 0
    class _MockLib:
        """Mock libasound that returns mock functions for all attribute access."""
        def __getattr__(self, name):
            return _MockFunc()
    _lib = _MockLib()
else:
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
SND_SEQ_PORT_CAP_INACTIVE = 1 << 8       # UMP group without an active FB
SND_SEQ_PORT_CAP_UMP_ENDPOINT = 1 << 9   # group-spanning UMP endpoint port

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


# --- snd_seq_real_time_t (used for queue-scheduled events) ---

class SndSeqRealTime(Structure):
    _fields_ = [
        ("tv_sec", c_uint),
        ("tv_nsec", c_uint),
    ]


# --- snd_seq_remove_events_t (opaque, used for cancelling queued events) ---

class SndSeqRemoveEvents(Structure):
    pass

SndSeqRemoveEventsPtr = POINTER(SndSeqRemoveEvents)


# --- Event time-stamp / mode flags + remove-events condition flags ---

SND_SEQ_TIME_STAMP_REAL = 0x01      # bit 0 = real-time (vs tick)
SND_SEQ_TIME_MODE_ABS = 0x00        # bit 1 cleared = absolute (vs relative)
SND_SEQ_REMOVE_OUTPUT = 0x02
SND_SEQ_REMOVE_TAG_MATCH = 0x200

# Variable-length payload bit. Set in ev.flags for SYSEX events whose
# payload lives in data.ext.{len, ptr}. Without it the kernel reads
# fixed-layout fields and the SysEx bytes never leave userspace.
SND_SEQ_EVENT_LENGTH_VARIABLE = 1 << 2  # kernel: SNDRV_SEQ_EVENT_LENGTH_VARIABLE
# (was 0x01 — the TIME_STAMP_REAL bit — which made every variable-length
# SysEx send fail with EINVAL; found by the MIDI-CI work, fixed 2026-07)


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
    # High-resolution channel messages the kernel emits when it
    # down-converts MIDI 2.0 traffic for a legacy client (previously
    # invisible to us — unknown types were silently dropped)
    CONTROL14 = 14      # SND_SEQ_EVENT_CONTROL14 (14-bit CC pair)
    NONREGPARAM = 15    # SND_SEQ_EVENT_NONREGPARAM (NRPN)
    REGPARAM = 16       # SND_SEQ_EVENT_REGPARAM (RPN)
    # Realtime / Clock (ALSA seq event types, NOT raw MIDI bytes)
    CLOCK = 36          # SND_SEQ_EVENT_CLOCK
    START = 30          # SND_SEQ_EVENT_START
    CONTINUE = 31       # SND_SEQ_EVENT_CONTINUE
    STOP = 32           # SND_SEQ_EVENT_STOP
    TICK = 33           # SND_SEQ_EVENT_TICK
    SENSING = 35        # SND_SEQ_EVENT_SENSING
    SONGPOS = 38        # SND_SEQ_EVENT_SONGPOS


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

class SndSeqEventExt(Structure):
    """Variable-length payload descriptor used by SYSEX events.
    Packed (no padding) so on 64-bit ptr sits at offset 4 and the
    whole thing still fits the 12-byte event-data union — matches
    ALSA's `__attribute__((packed))` snd_seq_ev_ext_t."""
    _pack_ = 1
    _fields_ = [
        ("len", c_uint),
        ("ptr", c_void_p),
    ]

class SndSeqEventData(ctypes.Union):
    _fields_ = [
        ("note", SndSeqEventNote),
        ("control", SndSeqEventCtrl),
        ("ext", SndSeqEventExt),
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
snd_seq_get_any_client_info = _func("snd_seq_get_any_client_info", c_int, SndSeqPtr, c_int, SndSeqClientInfoPtr)

# Client types
SND_SEQ_USER_CLIENT = 1
SND_SEQ_KERNEL_CLIENT = 2

# --- UMP / MIDI 2.0 capability (kernel >= 6.5 + alsa-lib >= 1.2.10) ---

# Client MIDI protocol versions (snd_seq_client_info midi_version field)
SND_SEQ_CLIENT_LEGACY_MIDI = 0
SND_SEQ_CLIENT_UMP_MIDI_1_0 = 1
SND_SEQ_CLIENT_UMP_MIDI_2_0 = 2


def _optional_func(name, restype, *argtypes):
    """Bind a symbol that older alsa-lib builds don't export (None if absent)."""
    try:
        fn = getattr(_lib, name)
    except AttributeError:
        return None
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


# get/set_client_info are ancient and always present; the midi_version
# accessors appeared in alsa-lib 1.2.10 and gate the whole UMP API.
snd_seq_get_client_info = _func("snd_seq_get_client_info", c_int, SndSeqPtr, SndSeqClientInfoPtr)
snd_seq_set_client_info = _func("snd_seq_set_client_info", c_int, SndSeqPtr, SndSeqClientInfoPtr)
snd_seq_client_info_get_midi_version = _optional_func(
    "snd_seq_client_info_get_midi_version", c_int, SndSeqClientInfoPtr)
snd_seq_client_info_set_midi_version = _optional_func(
    "snd_seq_client_info_set_midi_version", None, SndSeqClientInfoPtr, c_int)


@dataclass(frozen=True)
class UmpSupport:
    """Result of the one-shot UMP capability probe."""
    alsa_lib: bool  # alsa-lib exports the midi_version accessors (>= 1.2.10)
    kernel: bool    # kernel sequencer accepts a UMP client (CONFIG_SND_SEQ_UMP)

    @property
    def capable(self) -> bool:
        return self.alsa_lib and self.kernel


_ump_support: UmpSupport | None = None


def probe_ump_support(force: bool = False) -> UmpSupport:
    """Detect UMP (MIDI 2.0) support once per process.

    Kernel side: a kernel without CONFIG_SND_SEQ_UMP ignores or rejects
    a client's midi_version, so set UMP-MIDI-1.0 on a throwaway client
    and read it back — anything but the requested value means no kernel
    support. The throwaway client never creates ports, so it is
    invisible to device scans and other seq clients.
    """
    global _ump_support
    if _ump_support is not None and not force:
        return _ump_support

    alsa_lib = (snd_seq_client_info_get_midi_version is not None
                and snd_seq_client_info_set_midi_version is not None)
    kernel = False
    if alsa_lib:
        handle = SndSeqPtr()
        if snd_seq_open(byref(handle), b"default", SND_SEQ_OPEN_DUPLEX, SND_SEQ_NONBLOCK) >= 0:
            try:
                info = SndSeqClientInfoPtr()
                if snd_seq_client_info_malloc(byref(info)) >= 0:
                    try:
                        if snd_seq_get_client_info(handle, info) >= 0:
                            snd_seq_client_info_set_midi_version(
                                info, SND_SEQ_CLIENT_UMP_MIDI_1_0)
                            if (snd_seq_set_client_info(handle, info) >= 0
                                    and snd_seq_get_client_info(handle, info) >= 0):
                                kernel = (snd_seq_client_info_get_midi_version(info)
                                          == SND_SEQ_CLIENT_UMP_MIDI_1_0)
                    finally:
                        snd_seq_client_info_free(info)
            finally:
                snd_seq_close(handle)

    _ump_support = UmpSupport(alsa_lib=alsa_lib, kernel=kernel)
    return _ump_support


# --- UMP event + endpoint/function-block info (alsa-lib >= 1.2.10) ---

SND_SEQ_EVENT_UMP = 1 << 5  # ev.flags bit: the event carries a UMP packet


class SndSeqUmpEventUnion(ctypes.Union):
    _fields_ = [
        ("data", SndSeqEventData),
        ("ump", c_uint32 * 4),
    ]


class SndSeqUmpEvent(Structure):
    """snd_seq_ump_event_t — same header as snd_seq_event_t, but the
    payload union additionally holds one full 128-bit UMP packet.
    Valid member is selected by flags & SND_SEQ_EVENT_UMP."""
    _fields_ = [
        ("type", c_uint8),
        ("flags", c_uint8),
        ("tag", c_uint8),
        ("queue", c_uint8),
        ("time", c_uint8 * 8),
        ("source", SndSeqAddr),
        ("dest", SndSeqAddr),
        ("u", SndSeqUmpEventUnion),
    ]

    @property
    def is_ump(self) -> bool:
        return bool(self.flags & SND_SEQ_EVENT_UMP)

    @property
    def ump_words(self) -> tuple[int, int, int, int]:
        return tuple(self.u.ump)

    @property
    def data(self) -> SndSeqEventData:
        """Legacy union view — valid when is_ump is False, so code
        written for SndSeqEvent (announce handling etc.) works on
        non-UMP events read from a UMP client unchanged."""
        return self.u.data

    @property
    def channel(self) -> int:
        return self.u.data.note.channel


SndSeqUmpEventPtr = POINTER(SndSeqUmpEvent)


class SndUmpEndpointInfo(Structure):
    """struct snd_ump_endpoint_info (kernel uapi sound/asound.h, __packed)."""
    _pack_ = 1
    _fields_ = [
        ("card", c_int),
        ("device", c_int),
        ("flags", c_uint),
        ("protocol_caps", c_uint),
        ("protocol", c_uint),
        ("num_blocks", c_uint),
        ("version", c_uint16),
        ("family_id", c_uint16),
        ("model_id", c_uint16),
        ("manufacturer_id", c_uint),
        ("sw_revision", c_uint8 * 4),
        ("padding", c_uint16),
        ("name", c_char * 128),
        ("product_id", c_char * 128),
        ("reserved", c_uint8 * 32),
    ]


class SndUmpBlockInfo(Structure):
    """struct snd_ump_block_info (kernel uapi sound/asound.h, __packed)."""
    _pack_ = 1
    _fields_ = [
        ("card", c_int),
        ("device", c_int),
        ("block_id", c_uint8),
        ("direction", c_uint8),
        ("active", c_uint8),
        ("first_group", c_uint8),
        ("num_groups", c_uint8),
        ("midi_ci_version", c_uint8),
        ("sysex8_streams", c_uint8),
        ("ui_hint", c_uint8),
        ("flags", c_uint),
        ("name", c_char * 128),
        ("reserved", c_uint8 * 32),
    ]


# Endpoint info flags / protocol bits (kernel uapi)
SNDRV_UMP_EP_INFO_STATIC_BLOCKS = 0x01
SNDRV_UMP_EP_INFO_PROTO_MIDI1 = 0x0100
SNDRV_UMP_EP_INFO_PROTO_MIDI2 = 0x0200
# Block direction / flags
SNDRV_UMP_DIR_INPUT = 0x01
SNDRV_UMP_DIR_OUTPUT = 0x02
SNDRV_UMP_DIR_BIDIRECTION = 0x03
SNDRV_UMP_BLOCK_IS_MIDI1 = 1 << 0

snd_seq_ump_event_input = _optional_func(
    "snd_seq_ump_event_input", c_int, SndSeqPtr, POINTER(SndSeqUmpEventPtr))
snd_seq_ump_event_output = _optional_func(
    "snd_seq_ump_event_output", c_int, SndSeqPtr, SndSeqUmpEventPtr)
snd_seq_set_client_midi_version = _optional_func(
    "snd_seq_set_client_midi_version", c_int, SndSeqPtr, c_int)
snd_seq_get_ump_endpoint_info = _optional_func(
    "snd_seq_get_ump_endpoint_info", c_int, SndSeqPtr, c_int, c_void_p)
snd_seq_get_ump_block_info = _optional_func(
    "snd_seq_get_ump_block_info", c_int, SndSeqPtr, c_int, c_int, c_void_p)
snd_seq_set_ump_endpoint_info = _optional_func(
    "snd_seq_set_ump_endpoint_info", c_int, SndSeqPtr, c_void_p)
snd_seq_set_ump_block_info = _optional_func(
    "snd_seq_set_ump_block_info", c_int, SndSeqPtr, c_int, c_void_p)
snd_seq_port_info_get_ump_group = _optional_func(
    "snd_seq_port_info_get_ump_group", c_int, SndSeqPortInfoPtr)
snd_seq_port_info_set_ump_group = _optional_func(
    "snd_seq_port_info_set_ump_group", None, SndSeqPortInfoPtr, c_int)

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
snd_seq_delete_simple_port = _func(
    "snd_seq_delete_simple_port", c_int,
    SndSeqPtr, c_int,
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

# Queue lifecycle (used by PluginAlsaClient for scheduled-event delivery).
# Note: snd_seq_start_queue / _stop_queue are static-inline wrappers in
# the ALSA headers and aren't exported as symbols; we call the underlying
# snd_seq_control_queue with the right event-type code instead.
snd_seq_alloc_named_queue = _func("snd_seq_alloc_named_queue", c_int, SndSeqPtr, c_char_p)
snd_seq_free_queue = _func("snd_seq_free_queue", c_int, SndSeqPtr, c_int)
snd_seq_control_queue = _func(
    "snd_seq_control_queue", c_int, SndSeqPtr, c_int, c_int, c_int, SndSeqEventPtr)


def snd_seq_start_queue(handle, queue_id, ev=None) -> int:
    # SND_SEQ_EVENT_START = 30, value=0 (unused for queue control)
    return snd_seq_control_queue(handle, queue_id, 30, 0, ev)


def snd_seq_stop_queue(handle, queue_id, ev=None) -> int:
    # SND_SEQ_EVENT_STOP = 32
    return snd_seq_control_queue(handle, queue_id, 32, 0, ev)

# Remove-events: lets a client cancel its own pending queued events
# (e.g. drop-button cancel removes the snapshot CCs scheduled for the
# upcoming bar boundary).
snd_seq_remove_events_malloc = _func(
    "snd_seq_remove_events_malloc", c_int, POINTER(SndSeqRemoveEventsPtr))
snd_seq_remove_events_free = _func(
    "snd_seq_remove_events_free", None, SndSeqRemoveEventsPtr)
snd_seq_remove_events_set_condition = _func(
    "snd_seq_remove_events_set_condition", None, SndSeqRemoveEventsPtr, c_uint)
snd_seq_remove_events_set_tag = _func(
    "snd_seq_remove_events_set_tag", None, SndSeqRemoveEventsPtr, c_int)
snd_seq_remove_events_set_queue = _func(
    "snd_seq_remove_events_set_queue", None, SndSeqRemoveEventsPtr, c_int)
snd_seq_remove_events = _func(
    "snd_seq_remove_events", c_int, SndSeqPtr, SndSeqRemoveEventsPtr)

# Error string
snd_strerror = _func("snd_strerror", c_char_p, c_int)


def set_event_time_real(ev: SndSeqEvent, sec: int, nsec: int) -> None:
    """Stamp an event for absolute real-time queue delivery at (sec, nsec)
    on the queue's own clock. Caller is responsible for setting ev.queue
    to a running queue's id and calling snd_seq_event_output (NOT _direct)."""
    ev.flags = SND_SEQ_TIME_STAMP_REAL  # ABS=0, real-time=1
    rt = SndSeqRealTime.from_address(ctypes.addressof(ev) + SndSeqEvent.time.offset)
    rt.tv_sec = sec
    rt.tv_nsec = nsec


# --- High-level helpers ---

@dataclass
class MidiPort:
    port_id: int
    name: str
    is_input: bool   # can be read from (produces MIDI data)
    is_output: bool  # can be written to (consumes MIDI data)
    ump_group: int = 0          # 1-16 for UMP group ports, 0 otherwise
    is_ump_endpoint: bool = False  # the group-spanning catch-all port


@dataclass
class MidiDevice:
    client_id: int
    name: str
    ports: list[MidiPort] = field(default_factory=list)
    # UMP endpoint capability (kernel-discovered; empty on non-UMP
    # devices and on systems without UMP support)
    is_ump: bool = False
    midi2_protocol: bool = False      # endpoint is MIDI 2.0 capable
    endpoint_name: str = ""
    product_id: str = ""              # unique product instance id
    static_blocks: bool = False
    function_blocks: list[dict] = field(default_factory=list)

    @property
    def input_ports(self) -> list[MidiPort]:
        return [p for p in self.ports if p.is_input]

    @property
    def output_ports(self) -> list[MidiPort]:
        return [p for p in self.ports if p.is_output]


def apply_ump_port_policy(ports: list[MidiPort], num_blocks: int) -> list[MidiPort]:
    """Choose which of a UMP endpoint's seq ports the hub presents.

    The kernel exposes port 0 (group-spanning endpoint) plus one port
    per group — up to 17 rows for one device. Policy (FSD-03): with
    two or more function blocks show the named per-group ports and
    hide the catch-all; with zero/one block collapse to the single
    endpoint port. Inactive group ports are filtered upstream via
    SND_SEQ_PORT_CAP_INACTIVE."""
    if num_blocks >= 2:
        kept = [p for p in ports if not p.is_ump_endpoint]
        return kept or ports
    kept = [p for p in ports if p.is_ump_endpoint]
    return kept or ports


def check(ret: int, msg: str = "ALSA error"):
    if ret < 0:
        err = snd_strerror(ret)
        raise OSError(f"{msg}: {err.decode() if err else f'error {ret}'}")


class AlsaSeq:
    """Wrapper around an ALSA sequencer client handle."""

    def __init__(self, client_name: str = "RaspiMIDIHub",
                 default_ports: bool = True, midi_version: int = 0):
        """Wrap an ALSA seq client.

        `default_ports=True` (the historical behaviour) auto-creates
        an announce-listener port and a generic "output" port. Set
        False when the caller wants a clean slate — e.g. the BLE-MIDI
        bridge creates its own OUT / IN ports and would otherwise end
        up with a confusing extra "output" port hanging off the same
        client.

        `midi_version` requests a UMP client (1 = UMP MIDI 1.0, 2 =
        UMP MIDI 2.0). Best-effort: on kernels/libs without UMP the
        client stays legacy — check `self.midi_version` for what was
        actually granted. The kernel converts events between clients
        of different versions, so a UMP client interoperates with
        legacy peers transparently."""
        self._handle = SndSeqPtr()
        check(snd_seq_open(byref(self._handle), b"default", SND_SEQ_OPEN_DUPLEX, SND_SEQ_NONBLOCK),
              "Failed to open ALSA sequencer")
        snd_seq_set_client_name(self._handle, client_name.encode())
        self._client_id = snd_seq_client_id(self._handle)

        self._midi_version = 0
        if midi_version and probe_ump_support().capable \
                and snd_seq_set_client_midi_version is not None:
            if snd_seq_set_client_midi_version(self._handle, midi_version) >= 0:
                self._midi_version = midi_version

        self._announce_port = -1
        self._output_port = -1
        if default_ports:
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

        # Subscribe to system announcements (only if we created the
        # announce port; bridge clients with default_ports=False don't
        # need to listen for hotplug — that's the engine's job).
        if self._announce_port >= 0:
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
                    # Only connect hardware (kernel) MIDI devices +
                    # whitelisted plugins — EXCEPT user clients that
                    # declare a UMP endpoint with function blocks:
                    # that's a deliberate "I am a MIDI 2.0 device"
                    # announcement (virtual soft-synths, test peers,
                    # future gadget-side bridges), so treat them like
                    # hardware. Cheap ioctl; returns None for everyone
                    # else, including our own monitor client.
                    info = self.read_ump_device_info(client_id)
                    if not (info and info["function_blocks"]):
                        continue

                name_raw = snd_seq_client_info_get_name(cinfo)
                client_name = name_raw.decode("utf-8", errors="replace") if name_raw else f"Client {client_id}"

                ports = []
                snd_seq_port_info_set_client(pinfo, client_id)
                snd_seq_port_info_set_port(pinfo, -1)
                while snd_seq_query_next_port(self._handle, pinfo) >= 0:
                    cap = snd_seq_port_info_get_capability(pinfo)
                    snd_seq_port_info_get_type(pinfo)

                    # Skip no-export ports and UMP groups with no active FB
                    if cap & (SND_SEQ_PORT_CAP_NO_EXPORT | SND_SEQ_PORT_CAP_INACTIVE):
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
                        ump_group=(snd_seq_port_info_get_ump_group(pinfo)
                                   if snd_seq_port_info_get_ump_group is not None else 0),
                        is_ump_endpoint=bool(cap & SND_SEQ_PORT_CAP_UMP_ENDPOINT),
                    ))

                if ports:
                    dev = MidiDevice(client_id=client_id, name=client_name, ports=ports)
                    self._fill_ump_info(dev)
                    devices.append(dev)
        finally:
            snd_seq_client_info_free(cinfo)
            snd_seq_port_info_free(pinfo)

        return devices

    def scan_one_client(self, client_id: int) -> "MidiDevice | None":
        """Query ONE client's ports → MidiDevice (or None if it has no
        subscribable ports / doesn't exist). The cheap incremental
        alternative to scan_devices() for a just-created plugin client:
        no full enumeration, no bluetoothctl, no per-device sysfs."""
        cinfo = SndSeqClientInfoPtr()
        check(snd_seq_client_info_malloc(byref(cinfo)), "malloc client_info")
        pinfo = SndSeqPortInfoPtr()
        check(snd_seq_port_info_malloc(byref(pinfo)), "malloc port_info")
        try:
            if snd_seq_get_any_client_info(self._handle, client_id, cinfo) < 0:
                return None
            name_raw = snd_seq_client_info_get_name(cinfo)
            client_name = (name_raw.decode("utf-8", errors="replace")
                           if name_raw else f"Client {client_id}")
            ports = []
            snd_seq_port_info_set_client(pinfo, client_id)
            snd_seq_port_info_set_port(pinfo, -1)
            while snd_seq_query_next_port(self._handle, pinfo) >= 0:
                cap = snd_seq_port_info_get_capability(pinfo)
                if cap & (SND_SEQ_PORT_CAP_NO_EXPORT | SND_SEQ_PORT_CAP_INACTIVE):
                    continue
                is_input = bool(cap & SND_SEQ_PORT_CAP_READ and cap & SND_SEQ_PORT_CAP_SUBS_READ)
                is_output = bool(cap & SND_SEQ_PORT_CAP_WRITE and cap & SND_SEQ_PORT_CAP_SUBS_WRITE)
                if not is_input and not is_output:
                    continue
                port_id = snd_seq_port_info_get_port(pinfo)
                pn_raw = snd_seq_port_info_get_name(pinfo)
                port_name = (pn_raw.decode("utf-8", errors="replace")
                             if pn_raw else f"Port {port_id}")
                ports.append(MidiPort(
                    port_id=port_id, name=port_name,
                    is_input=is_input, is_output=is_output,
                    ump_group=(snd_seq_port_info_get_ump_group(pinfo)
                               if snd_seq_port_info_get_ump_group is not None else 0),
                    is_ump_endpoint=bool(cap & SND_SEQ_PORT_CAP_UMP_ENDPOINT)))
            if not ports:
                return None
            dev = MidiDevice(client_id=client_id, name=client_name, ports=ports)
            self._fill_ump_info(dev)
            return dev
        finally:
            snd_seq_client_info_free(cinfo)
            snd_seq_port_info_free(pinfo)

    def list_user_client_names(self) -> dict[int, str]:
        """Return {client_id: name} for every USER-type ALSA seq client.

        Used to spot externally-created BLE-MIDI clients (BlueZ creates
        an ALSA seq client per connected BLE-MIDI device, named after
        the device) so the engine can opt them into the main scan even
        though they're not in the plugin / Python-bridge whitelist."""
        result: dict[int, str] = {}
        cinfo = SndSeqClientInfoPtr()
        check(snd_seq_client_info_malloc(byref(cinfo)), "malloc client_info")
        try:
            snd_seq_client_info_set_client(cinfo, -1)
            while snd_seq_query_next_client(self._handle, cinfo) >= 0:
                cid = snd_seq_client_info_get_client(cinfo)
                if cid in (SND_SEQ_CLIENT_SYSTEM, MIDI_THROUGH_CLIENT_ID, self._client_id):
                    continue
                if snd_seq_client_info_get_type(cinfo) != SND_SEQ_USER_CLIENT:
                    continue
                name_raw = snd_seq_client_info_get_name(cinfo)
                name = name_raw.decode("utf-8", errors="replace") if name_raw else ""
                result[cid] = name
        finally:
            snd_seq_client_info_free(cinfo)
        return result

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

    def delete_port(self, port_id: int) -> None:
        """Delete a port created with create_port. The kernel drops all
        of the port's subscriptions along with it. A client holds at
        most ~254 ports, so every transient port MUST be deleted when
        its owner lets go of it — leaking them eventually makes all
        port creation fail with EINVAL."""
        check(snd_seq_delete_simple_port(self._handle, port_id),
              f"Failed to delete port {port_id}")

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
            # The Timer fires on its own thread (spawned from whatever
            # scheduled the flush — often the loop thread on the isolated
            # core); migrate it onto the housekeeping cores so the CC
            # sends don't run on the loop's core.
            from . import cpu_affinity
            cpu_affinity.move_to_housekeeping()
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

    @property
    def midi_version(self) -> int:
        """Effective client MIDI version (0 legacy, 1/2 UMP)."""
        return self._midi_version

    def read_ump_event(self) -> SndSeqUmpEvent | None:
        """Read one event as snd_seq_ump_event (non-blocking).

        For UMP clients this is the input path: UMP packets arrive with
        flags & SND_SEQ_EVENT_UMP set (payload in .ump_words); classic
        events (announce, queue control, ...) still arrive on the same
        fd with the flag clear and the legacy .u.data union valid."""
        if snd_seq_ump_event_input is None:
            return None
        ev = SndSeqUmpEventPtr()
        ret = snd_seq_ump_event_input(self._handle, byref(ev))
        if ret < 0:
            return None  # EAGAIN or error
        return ev.contents

    def send_ump(self, words, dest_client: int, dest_port: int,
                 source_port: int | None = None) -> None:
        """Send one UMP packet (1-4 x 32-bit words) directly."""
        ev = SndSeqUmpEvent()
        ev.flags = SND_SEQ_EVENT_UMP
        ev.queue = SND_SEQ_QUEUE_DIRECT
        ev.source.client = self._client_id
        ev.source.port = self._output_port if source_port is None else source_port
        ev.dest.client = dest_client
        ev.dest.port = dest_port
        for i, w in enumerate(words):
            ev.u.ump[i] = w
        ret = snd_seq_ump_event_output(self._handle, pointer(ev))
        if ret >= 0:
            ret = snd_seq_drain_output(self._handle)
        if ret < 0:
            err = snd_strerror(ret)
            import logging
            logging.getLogger(__name__).warning(
                "send_ump to %d:%d failed: %s", dest_client, dest_port,
                err.decode() if err else f"error {ret}")

    def _fill_ump_info(self, dev: MidiDevice) -> None:
        """Populate a scanned device's UMP capability fields and apply
        the port presentation policy. No-op for non-UMP devices and on
        systems without UMP support."""
        info = self.read_ump_device_info(dev.client_id)
        if info is None:
            return
        dev.is_ump = True
        dev.midi2_protocol = info["midi2_protocol"]
        dev.endpoint_name = info["endpoint_name"]
        dev.product_id = info["product_id"]
        dev.static_blocks = info["static_blocks"]
        dev.function_blocks = info["function_blocks"]
        dev.ports = apply_ump_port_policy(dev.ports, len(info["function_blocks"]))

    def read_ump_device_info(self, client_id: int) -> dict | None:
        """UMP capability summary of a client, or None (not a UMP
        endpoint / no UMP support on this system)."""
        if not probe_ump_support().capable:
            return None
        ep = self.get_ump_endpoint_info(client_id)
        if ep is None:
            return None
        blocks = []
        for b in range(min(ep.num_blocks, 32)):
            bi = self.get_ump_block_info(client_id, b)
            if bi is None:
                continue
            blocks.append({
                "name": bi.name.decode("utf-8", errors="replace"),
                "direction": bi.direction,
                "first_group": bi.first_group,
                "num_groups": bi.num_groups,
                "active": bool(bi.active),
                "ui_hint": bi.ui_hint,
                "is_midi1": bool(bi.flags & SNDRV_UMP_BLOCK_IS_MIDI1),
            })
        return {
            "endpoint_name": ep.name.decode("utf-8", errors="replace"),
            "product_id": ep.product_id.decode("utf-8", errors="replace"),
            "midi2_protocol": bool(ep.protocol_caps & SNDRV_UMP_EP_INFO_PROTO_MIDI2),
            "static_blocks": bool(ep.flags & SNDRV_UMP_EP_INFO_STATIC_BLOCKS),
            "function_blocks": blocks,
        }

    def get_ump_endpoint_info(self, client_id: int) -> SndUmpEndpointInfo | None:
        """UMP endpoint info of a client, or None (not a UMP endpoint /
        no kernel support)."""
        if snd_seq_get_ump_endpoint_info is None:
            return None
        info = SndUmpEndpointInfo()
        if snd_seq_get_ump_endpoint_info(self._handle, client_id, byref(info)) < 0:
            return None
        return info

    def get_ump_block_info(self, client_id: int, block: int) -> SndUmpBlockInfo | None:
        """Function block info of a UMP endpoint client, or None."""
        if snd_seq_get_ump_block_info is None:
            return None
        info = SndUmpBlockInfo()
        if snd_seq_get_ump_block_info(self._handle, client_id, block, byref(info)) < 0:
            return None
        return info

    def set_ump_endpoint_info(self, info: SndUmpEndpointInfo) -> bool:
        """Declare this client's own UMP endpoint info (UMP clients only)."""
        return (snd_seq_set_ump_endpoint_info is not None
                and snd_seq_set_ump_endpoint_info(self._handle, byref(info)) >= 0)

    def set_ump_block_info(self, block: int, info: SndUmpBlockInfo) -> bool:
        """Declare one of this client's own function blocks."""
        return (snd_seq_set_ump_block_info is not None
                and snd_seq_set_ump_block_info(self._handle, block, byref(info)) >= 0)

    def close(self) -> None:
        if self._handle:
            snd_seq_close(self._handle)
            self._handle = SndSeqPtr()
