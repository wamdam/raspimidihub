"""Universal MIDI Packet (UMP) codec — pure Python, no ALSA.

Packs/unpacks the UMP message types the hub handles (M2-104-UM v1.1.2):
MIDI 2.0 channel voice (MT 0x4), MIDI 1.0 channel voice in UMP (MT 0x2),
system common/real-time (MT 0x1), SysEx7 (MT 0x3) and the UMP stream
messages (MT 0xF) needed for endpoint discovery. Utility packets (MT
0x0, JR timestamps etc.) are recognized and skipped per decision D5;
SysEx8/Mixed Data Set (MT 0x5) and Flex Data (MT 0xD) are recognized
(correct size, so streams stay in sync) but not decoded.

Values are raw wire-width integers (16-bit velocity, 32-bit CC/bend);
resolution scaling to/from MIDI 1.0 ranges is midi_scale's job (FSD-06),
not this module's.

UMP words arrive CPU-native from ALSA; no byte-order handling here.
"""

from dataclasses import dataclass, field
from enum import IntEnum

# --- Message types (MT nibble) ---

MT_UTILITY = 0x0
MT_SYSTEM = 0x1
MT_MIDI1_CV = 0x2
MT_DATA64 = 0x3       # SysEx7
MT_MIDI2_CV = 0x4
MT_DATA128 = 0x5      # SysEx8 / Mixed Data Set
MT_FLEX = 0xD
MT_STREAM = 0xF

# Packet size in 32-bit words per MT (spec Table 3 — reserved MTs have
# fixed sizes so unknown packets can be skipped without desync).
WORDS_PER_MT = (1, 1, 1, 2, 2, 4, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4)


def packet_words(first_word: int) -> int:
    """Number of 32-bit words in the packet starting with first_word."""
    return WORDS_PER_MT[(first_word >> 28) & 0xF]


# --- MIDI 2.0 channel voice opcodes (MT 0x4) ---

class Midi2Op(IntEnum):
    PER_NOTE_RCC = 0x0     # registered per-note controller
    PER_NOTE_ACC = 0x1     # assignable per-note controller
    RPN = 0x2              # registered controller
    NRPN = 0x3             # assignable controller
    REL_RPN = 0x4
    REL_NRPN = 0x5
    PER_NOTE_BEND = 0x6
    NOTE_OFF = 0x8
    NOTE_ON = 0x9
    POLY_PRESSURE = 0xA
    CC = 0xB
    PROGRAM = 0xC
    CHAN_PRESSURE = 0xD
    PITCH_BEND = 0xE
    PER_NOTE_MGMT = 0xF


# Center value of 32-bit bidirectional fields (pitch bend)
BEND32_CENTER = 0x8000_0000
# MIDI 2.0 Note Off velocity for translated 1.0 vel-0 note-ons (App. D)
NOTE_OFF_VELOCITY_DEFAULT = 0x8000


@dataclass(slots=True)
class UmpMessage:
    """One decoded UMP message.

    `kind` selects which fields are meaningful:
      note_on / note_off : channel, note, velocity(16), attr_type, attr_data
      poly_pressure      : channel, note, value(32)
      cc                 : channel, index(0-127), value(32)
      rpn / nrpn / rel_rpn / rel_nrpn : channel, bank, index, value(32;
                           rel_* two's-complement signed as unsigned)
      per_note_rcc / per_note_acc : channel, note, index(0-255), value(32)
      per_note_bend      : channel, note, value(32, center 0x80000000)
      per_note_mgmt      : channel, note, flags (bit1=Detach, bit0=Set)
      program            : channel, program, bank_valid, bank
      chan_pressure      : channel, value(32)
      pitch_bend         : channel, value(32, center 0x80000000)
      midi1              : raw MIDI 1.0-in-UMP (status, data1, data2)
      system             : status byte + data1/data2 (as midi1 fields)
      sysex7             : payload bytes when a message completes
      stream / utility / data128 / flex : recognized, fields per decoder
    """
    kind: str
    group: int = 0
    channel: int = 0
    note: int = 0
    index: int = 0
    bank: int = 0
    value: int = 0
    velocity: int = 0
    attr_type: int = 0
    attr_data: int = 0
    program: int = 0
    bank_valid: bool = False
    flags: int = 0
    status: int = 0
    data1: int = 0
    data2: int = 0
    payload: bytes = b""


_M2_KINDS = {
    Midi2Op.PER_NOTE_RCC: "per_note_rcc",
    Midi2Op.PER_NOTE_ACC: "per_note_acc",
    Midi2Op.RPN: "rpn",
    Midi2Op.NRPN: "nrpn",
    Midi2Op.REL_RPN: "rel_rpn",
    Midi2Op.REL_NRPN: "rel_nrpn",
    Midi2Op.PER_NOTE_BEND: "per_note_bend",
    Midi2Op.NOTE_OFF: "note_off",
    Midi2Op.NOTE_ON: "note_on",
    Midi2Op.POLY_PRESSURE: "poly_pressure",
    Midi2Op.CC: "cc",
    Midi2Op.PROGRAM: "program",
    Midi2Op.CHAN_PRESSURE: "chan_pressure",
    Midi2Op.PITCH_BEND: "pitch_bend",
    Midi2Op.PER_NOTE_MGMT: "per_note_mgmt",
}


def decode(words) -> UmpMessage | None:
    """Decode one UMP packet (sequence of 32-bit words) to a UmpMessage.

    Returns None for packets the hub deliberately ignores (utility /
    JR timestamps, SysEx8/MDS, Flex Data, reserved MTs). SysEx7
    continuation packets also return None — feed them through a
    Sysex7Assembler to get complete messages.
    """
    w0 = words[0]
    mt = (w0 >> 28) & 0xF
    group = (w0 >> 24) & 0xF

    if mt == MT_MIDI2_CV:
        return _decode_midi2(words, group)
    if mt == MT_MIDI1_CV:
        status = (w0 >> 16) & 0xFF
        return UmpMessage(kind="midi1", group=group, channel=status & 0x0F,
                          status=status, data1=(w0 >> 8) & 0x7F, data2=w0 & 0x7F)
    if mt == MT_SYSTEM:
        return UmpMessage(kind="system", group=group, status=(w0 >> 16) & 0xFF,
                          data1=(w0 >> 8) & 0x7F, data2=w0 & 0x7F)
    if mt == MT_STREAM:
        return _decode_stream(words)
    # MT_UTILITY (JR clock/timestamp — D5: strip), MT_DATA64 handled by
    # the assembler, MT_DATA128 / MT_FLEX / reserved: skip.
    return None


def _decode_midi2(words, group: int) -> UmpMessage | None:
    w0, w1 = words[0], words[1]
    op = (w0 >> 20) & 0xF
    kind = _M2_KINDS.get(op)
    if kind is None:  # 0x7 reserved
        return None
    ch = (w0 >> 16) & 0xF
    b1 = (w0 >> 8) & 0xFF   # note / bank / controller index (per opcode)
    b2 = w0 & 0xFF
    m = UmpMessage(kind=kind, group=group, channel=ch, value=w1)
    if op in (Midi2Op.NOTE_ON, Midi2Op.NOTE_OFF):
        m.note = b1 & 0x7F
        m.attr_type = b2
        m.velocity = (w1 >> 16) & 0xFFFF
        m.attr_data = w1 & 0xFFFF
    elif op == Midi2Op.POLY_PRESSURE:
        m.note = b1 & 0x7F
    elif op == Midi2Op.CC:
        m.index = b1 & 0x7F
    elif op in (Midi2Op.RPN, Midi2Op.NRPN, Midi2Op.REL_RPN, Midi2Op.REL_NRPN):
        m.bank = b1 & 0x7F
        m.index = b2 & 0x7F
    elif op in (Midi2Op.PER_NOTE_RCC, Midi2Op.PER_NOTE_ACC):
        m.note = b1 & 0x7F
        m.index = b2          # per-note controller index is 8-bit
    elif op == Midi2Op.PER_NOTE_BEND:
        m.note = b1 & 0x7F
    elif op == Midi2Op.PER_NOTE_MGMT:
        m.note = b1 & 0x7F
        m.flags = b2 & 0x03
    elif op == Midi2Op.PROGRAM:
        m.bank_valid = bool(b2 & 0x01)
        m.program = (w1 >> 24) & 0x7F
        m.bank = (((w1 >> 8) & 0x7F) << 7) | (w1 & 0x7F)
    # chan_pressure / pitch_bend: value=w1 is all that's needed
    return m


# --- MIDI 2.0 channel voice encoders (return tuples of 32-bit words) ---

def _m2_word0(group: int, op: int, channel: int, b1: int, b2: int) -> int:
    return ((MT_MIDI2_CV << 28) | ((group & 0xF) << 24) | ((op & 0xF) << 20)
            | ((channel & 0xF) << 16) | ((b1 & 0xFF) << 8) | (b2 & 0xFF))


def note_on(group, channel, note, velocity16, attr_type=0, attr_data=0):
    return (_m2_word0(group, Midi2Op.NOTE_ON, channel, note, attr_type),
            ((velocity16 & 0xFFFF) << 16) | (attr_data & 0xFFFF))


def note_off(group, channel, note, velocity16=NOTE_OFF_VELOCITY_DEFAULT,
             attr_type=0, attr_data=0):
    return (_m2_word0(group, Midi2Op.NOTE_OFF, channel, note, attr_type),
            ((velocity16 & 0xFFFF) << 16) | (attr_data & 0xFFFF))


def cc(group, channel, index, value32):
    return (_m2_word0(group, Midi2Op.CC, channel, index, 0),
            value32 & 0xFFFFFFFF)


def rpn(group, channel, bank, index, value32, *, assignable=False, relative=False):
    op = (Midi2Op.REL_NRPN if assignable else Midi2Op.REL_RPN) if relative \
        else (Midi2Op.NRPN if assignable else Midi2Op.RPN)
    return (_m2_word0(group, op, channel, bank, index), value32 & 0xFFFFFFFF)


def poly_pressure(group, channel, note, value32):
    return (_m2_word0(group, Midi2Op.POLY_PRESSURE, channel, note, 0),
            value32 & 0xFFFFFFFF)


def chan_pressure(group, channel, value32):
    return (_m2_word0(group, Midi2Op.CHAN_PRESSURE, channel, 0, 0),
            value32 & 0xFFFFFFFF)


def pitch_bend(group, channel, value32):
    return (_m2_word0(group, Midi2Op.PITCH_BEND, channel, 0, 0),
            value32 & 0xFFFFFFFF)


def per_note_bend(group, channel, note, value32):
    return (_m2_word0(group, Midi2Op.PER_NOTE_BEND, channel, note, 0),
            value32 & 0xFFFFFFFF)


def per_note_controller(group, channel, note, index, value32, *, assignable=False):
    op = Midi2Op.PER_NOTE_ACC if assignable else Midi2Op.PER_NOTE_RCC
    return (_m2_word0(group, op, channel, note, index), value32 & 0xFFFFFFFF)


def program_change(group, channel, program, bank=None):
    valid = bank is not None
    b = bank or 0
    return (_m2_word0(group, Midi2Op.PROGRAM, channel, 0, 1 if valid else 0),
            ((program & 0x7F) << 24) | (((b >> 7) & 0x7F) << 8) | (b & 0x7F))


def midi1_packet(group, status, data1=0, data2=0):
    """MIDI 1.0 channel voice message inside UMP (MT 0x2)."""
    return ((MT_MIDI1_CV << 28) | ((group & 0xF) << 24) | ((status & 0xFF) << 16)
            | ((data1 & 0x7F) << 8) | (data2 & 0x7F),)


def system_packet(group, status, data1=0, data2=0):
    """System common / real-time message (MT 0x1)."""
    return ((MT_SYSTEM << 28) | ((group & 0xF) << 24) | ((status & 0xFF) << 16)
            | ((data1 & 0x7F) << 8) | (data2 & 0x7F),)


# --- SysEx7 (MT 0x3): 6 payload bytes per 64-bit packet ---

_SX7_COMPLETE, _SX7_START, _SX7_CONTINUE, _SX7_END = 0, 1, 2, 3


def sysex7_encode(group: int, payload: bytes) -> list[tuple[int, int]]:
    """Chunk a SysEx payload (WITHOUT F0/F7 framing) into SysEx7 packets."""
    chunks = [payload[i:i + 6] for i in range(0, len(payload), 6)] or [b""]
    packets = []
    for i, chunk in enumerate(chunks):
        if len(chunks) == 1:
            status = _SX7_COMPLETE
        elif i == 0:
            status = _SX7_START
        elif i == len(chunks) - 1:
            status = _SX7_END
        else:
            status = _SX7_CONTINUE
        b = chunk + bytes(6 - len(chunk))
        w0 = ((MT_DATA64 << 28) | ((group & 0xF) << 24) | (status << 20)
              | (len(chunk) << 16) | (b[0] << 8) | b[1])
        w1 = (b[2] << 24) | (b[3] << 16) | (b[4] << 8) | b[5]
        packets.append((w0, w1))
    return packets


class Sysex7Assembler:
    """Reassembles SysEx7 packet streams, one buffer per group.

    Packets of different groups may interleave (spec §5.3); a Start
    while a message is open on the same group discards the stale one.
    """

    def __init__(self):
        self._buf: dict[int, bytearray] = {}

    def feed(self, words) -> UmpMessage | None:
        """Feed one MT 0x3 packet; returns the message when complete."""
        w0, w1 = words[0], words[1]
        group = (w0 >> 24) & 0xF
        status = (w0 >> 20) & 0xF
        n = (w0 >> 16) & 0xF
        data = bytes(((w0 >> 8) & 0xFF, w0 & 0xFF, (w1 >> 24) & 0xFF,
                      (w1 >> 16) & 0xFF, (w1 >> 8) & 0xFF, w1 & 0xFF))[:min(n, 6)]
        if status == _SX7_COMPLETE:
            self._buf.pop(group, None)
            return UmpMessage(kind="sysex7", group=group, payload=data)
        if status == _SX7_START:
            self._buf[group] = bytearray(data)
            return None
        buf = self._buf.get(group)
        if buf is None:
            return None  # continuation without start: drop
        buf.extend(data)
        if status == _SX7_END:
            del self._buf[group]
            return UmpMessage(kind="sysex7", group=group, payload=bytes(buf))
        return None


# --- UMP stream messages (MT 0xF, groupless, 128-bit) ---

STREAM_EP_DISCOVERY = 0x00
STREAM_EP_INFO = 0x01
STREAM_DEVICE_IDENTITY = 0x02
STREAM_EP_NAME = 0x03
STREAM_PRODUCT_ID = 0x04
STREAM_CONFIG_REQUEST = 0x05
STREAM_CONFIG_NOTIFY = 0x06
STREAM_FB_DISCOVERY = 0x10
STREAM_FB_INFO = 0x11
STREAM_FB_NAME = 0x12


@dataclass(slots=True)
class StreamMessage:
    """Decoded UMP stream (MT 0xF) packet."""
    status: int
    format: int            # 0 complete, 1 start, 2 continue, 3 end
    fields: dict = field(default_factory=dict)
    text: bytes = b""      # raw text bytes for name/product-id packets


def _decode_stream(words) -> UmpMessage:
    w0 = words[0]
    fmt = (w0 >> 26) & 0x3
    status = (w0 >> 16) & 0x3FF
    m = UmpMessage(kind="stream", status=status, flags=fmt)
    if status == STREAM_EP_INFO:
        m.data1 = (w0 >> 8) & 0xFF          # UMP version major
        m.data2 = w0 & 0xFF                 # UMP version minor
        w1 = words[1]
        m.index = (w1 >> 24) & 0x7F         # number of function blocks
        m.bank_valid = bool(w1 & (1 << 31))  # static function blocks
        m.value = w1 & 0x3                  # protocol caps: b0=MIDI1, b1=MIDI2
        m.attr_data = (w1 >> 8) & 0x3       # JR timestamp caps
    elif status == STREAM_FB_INFO:
        w1 = words[1]
        m.index = (w0 >> 8) & 0x7F          # function block number
        m.bank_valid = bool(w0 & (1 << 15))  # active
        m.attr_type = w0 & 0x3F             # ui hint(2) | midi1(2) | dir(2)
        m.note = (w1 >> 24) & 0xFF          # first group
        m.velocity = (w1 >> 16) & 0xFF      # number of groups
        m.data1 = (w1 >> 8) & 0xFF          # MIDI-CI version
        m.data2 = w1 & 0xFF                 # max sysex8 streams
    elif status in (STREAM_EP_NAME, STREAM_PRODUCT_ID, STREAM_FB_NAME):
        raw = b"".join(w.to_bytes(4, "big") for w in words)
        if status == STREAM_FB_NAME:
            m.index = raw[2]                # function block number
            m.payload = raw[3:16]
        else:
            m.payload = raw[2:16]
        m.payload = m.payload.rstrip(b"\x00")
    elif status in (STREAM_CONFIG_NOTIFY, STREAM_CONFIG_REQUEST):
        m.value = (w0 >> 8) & 0xFF          # protocol (1 or 2)
        m.attr_data = w0 & 0x3              # JR timestamp tx/rx bits
    return m


def endpoint_discovery(filter_bitmap: int = 0x1F,
                       ump_version: tuple[int, int] = (1, 1)) -> tuple:
    """Endpoint Discovery request (ask for everything by default)."""
    w0 = ((MT_STREAM << 28) | (0 << 26) | (STREAM_EP_DISCOVERY << 16)
          | (ump_version[0] << 8) | ump_version[1])
    return (w0, filter_bitmap & 0x1F, 0, 0)


def function_block_discovery(block: int = 0xFF, filter_bitmap: int = 0x3) -> tuple:
    """Function Block Discovery request (0xFF = all blocks)."""
    w0 = ((MT_STREAM << 28) | (0 << 26) | (STREAM_FB_DISCOVERY << 16)
          | ((block & 0xFF) << 8) | (filter_bitmap & 0x3))
    return (w0, 0, 0, 0)
