"""AppleMIDI (RTP-MIDI) wire protocol: pure parse/build, no I/O.

Implements the subset of RFC 6295 (RTP payload format for MIDI) and
Apple's session exchange protocol needed to interoperate with macOS
Audio MIDI Setup, iOS and rtpmidid. The session/socket lifecycle lives
in network_midi.py; this module is pure functions + small dataclasses
over `struct`, fully unit-testable without sockets.

Wire formats (no RFC exists for the Apple session protocol; layouts
follow Apple's published behaviour as documented by the Wireshark
`applemidi` dissector and the rtpmidid implementation):

Exchange packets (control AND data port), big-endian throughout:

    0xFF 0xFF | cmd(2 ASCII) | version(4)=2 | initiator_token(4) |
    ssrc(4) | name (UTF-8, NUL-terminated, optional)

for cmd in IN (invitation) / OK (accept) / NO (reject) / BY (bye).

    0xFF 0xFF | 'CK' | ssrc(4) | count(1) | pad(3) | ts1(8) ts2(8) ts3(8)

Clock sync, timestamps in 10 kHz units (100 µs). Both ends MUST answer
CK0 with CK1 — macOS drops peers that don't.

    0xFF 0xFF | 'RS' | ssrc(4) | seqnum(4)

Receiver feedback: top 16 bits of seqnum = highest RTP seq received.

RTP-MIDI data packets (data port):

    RTP header (12 B): V=2, PT=0x61, seq(2), ts(4, same 10 kHz clock),
    ssrc(4) | MIDI command section: flags [B J Z P | LEN(4)] (+LEN low
    byte when B=1) | MIDI list | (recovery journal when J=1 — ignored)

Journal policy: we always send J=0 and ignore incoming journals.
Journal-less streams are conformant (RFC 6295 makes journalling a
negotiated property; on wired LAN / local WiFi the loss rates the
journal was designed for don't occur, and the engine's panic +
note-release paths cover a worst-case lost NoteOff). Incoming journals
sit after the LEN-delimited command list, so skipping them is free.
"""

import struct
from dataclasses import dataclass

APPLEMIDI_SIGNATURE = b"\xff\xff"
PROTOCOL_VERSION = 2
RTP_PAYLOAD_TYPE = 0x61
CLOCK_HZ = 10_000  # AppleMIDI CK + RTP timestamps tick at 10 kHz

# Exchange command codes
CMD_INVITATION = b"IN"
CMD_ACCEPT = b"OK"
CMD_REJECT = b"NO"
CMD_BYE = b"BY"
CMD_CLOCK = b"CK"
CMD_FEEDBACK = b"RS"

_EXCHANGE_CMDS = (CMD_INVITATION, CMD_ACCEPT, CMD_REJECT, CMD_BYE)

# MIDI command section flag bits (RFC 6295 §3.1)
_FLAG_B = 0x80  # two-byte (12-bit) length
_FLAG_J = 0x40  # journal present
_FLAG_Z = 0x20  # first command carries a delta time
_FLAG_P = 0x10  # phantom running status


@dataclass
class ExchangePacket:
    command: bytes              # one of IN / OK / NO / BY
    initiator_token: int
    ssrc: int
    name: str | None = None
    version: int = PROTOCOL_VERSION


@dataclass
class ClockSync:
    ssrc: int
    count: int                  # 0, 1 or 2
    ts1: int
    ts2: int
    ts3: int


@dataclass
class Feedback:
    ssrc: int
    seqnum: int                 # raw 32-bit field; top 16 bits = highest seq


@dataclass
class RtpMidiPacket:
    seq: int
    timestamp: int
    ssrc: int
    commands: list[bytes]       # complete MIDI messages / SysEx segments


# --- Session exchange ---

def parse_command(data: bytes) -> ExchangePacket | ClockSync | Feedback | None:
    """Parse a session packet (anything starting 0xFF 0xFF). Returns
    None for RTP data packets, truncated input and unknown commands."""
    if len(data) < 4 or data[:2] != APPLEMIDI_SIGNATURE:
        return None
    cmd = data[2:4]

    if cmd in _EXCHANGE_CMDS:
        if len(data) < 16:
            return None
        version, token, ssrc = struct.unpack_from(">III", data, 4)
        name = None
        if len(data) > 16:
            raw = data[16:].split(b"\x00", 1)[0]
            try:
                name = raw.decode("utf-8")
            except UnicodeDecodeError:
                name = raw.decode("utf-8", "replace")
        return ExchangePacket(cmd, token, ssrc, name, version)

    if cmd == CMD_CLOCK:
        if len(data) < 36:
            return None
        ssrc, count = struct.unpack_from(">IB", data, 4)
        ts1, ts2, ts3 = struct.unpack_from(">QQQ", data, 12)
        return ClockSync(ssrc, count, ts1, ts2, ts3)

    if cmd == CMD_FEEDBACK:
        if len(data) < 12:
            return None
        ssrc, seqnum = struct.unpack_from(">II", data, 4)
        return Feedback(ssrc, seqnum)

    return None


def build_exchange(command: bytes, initiator_token: int, ssrc: int,
                   name: str | None = None) -> bytes:
    """Build an IN / OK / NO / BY packet."""
    if command not in _EXCHANGE_CMDS:
        raise ValueError(f"not an exchange command: {command!r}")
    pkt = APPLEMIDI_SIGNATURE + command + struct.pack(
        ">III", PROTOCOL_VERSION, initiator_token & 0xFFFFFFFF,
        ssrc & 0xFFFFFFFF)
    if name is not None:
        pkt += name.encode("utf-8") + b"\x00"
    return pkt


def build_clock_sync(ssrc: int, count: int, ts1: int, ts2: int = 0,
                     ts3: int = 0) -> bytes:
    return (APPLEMIDI_SIGNATURE + CMD_CLOCK
            + struct.pack(">IB3x", ssrc & 0xFFFFFFFF, count)
            + struct.pack(">QQQ", ts1 & 0xFFFFFFFFFFFFFFFF,
                          ts2 & 0xFFFFFFFFFFFFFFFF,
                          ts3 & 0xFFFFFFFFFFFFFFFF))


def build_feedback(ssrc: int, seqnum: int) -> bytes:
    """`seqnum` is the highest received RTP sequence number; it rides
    in the top 16 bits of the 32-bit field (Apple's layout)."""
    return (APPLEMIDI_SIGNATURE + CMD_FEEDBACK
            + struct.pack(">II", ssrc & 0xFFFFFFFF,
                          (seqnum & 0xFFFF) << 16))


# --- RTP-MIDI data packets ---

def build_rtp_midi(seq: int, timestamp: int, ssrc: int,
                   command: bytes, marker: bool = True) -> bytes:
    """Build an RTP-MIDI packet carrying a single MIDI command (or one
    SysEx segment). One command per packet: at MIDI data rates latency
    beats batching, and it sidesteps delta-time encoding entirely
    (Z=0, no journal, no running status across packets)."""
    n = len(command)
    if n > 0x0FFF:
        raise ValueError(f"MIDI command section too long: {n}")
    header = struct.pack(
        ">BBHII", 0x80, (0x80 if marker else 0) | RTP_PAYLOAD_TYPE,
        seq & 0xFFFF, timestamp & 0xFFFFFFFF, ssrc & 0xFFFFFFFF)
    if n <= 0x0F:
        section = bytes([n]) + command
    else:
        section = bytes([_FLAG_B | (n >> 8), n & 0xFF]) + command
    return header + section


def parse_rtp_midi(data: bytes) -> RtpMidiPacket | None:
    """Parse an RTP-MIDI packet into complete MIDI commands. Running
    status and delta times within the packet are resolved; everything
    after the LEN-delimited command list (the journal, when J=1) is
    ignored by design. SysEx segments are returned raw (F0…/F7…
    framing intact) for SysExAssembler to stitch."""
    if len(data) < 13:
        return None
    b0, b1 = data[0], data[1]
    if b0 >> 6 != 2 or (b1 & 0x7F) != RTP_PAYLOAD_TYPE:
        return None
    seq, timestamp, ssrc = struct.unpack_from(">HII", data, 2)
    off = 12 + 4 * (b0 & 0x0F)  # skip CSRCs (never seen in practice)
    if off >= len(data):
        return None

    flags = data[off]
    off += 1
    length = flags & 0x0F
    if flags & _FLAG_B:
        if off >= len(data):
            return None
        length = (length << 8) | data[off]
        off += 1
    midi_list = data[off:off + length]
    if len(midi_list) < length:
        return None  # truncated packet

    commands = _parse_midi_list(midi_list, first_has_delta=bool(flags & _FLAG_Z))
    return RtpMidiPacket(seq, timestamp, ssrc, commands)


def _data_len(status: int) -> int | None:
    """Data bytes following a (non-SysEx) status byte; None = unknown."""
    if 0x80 <= status <= 0xBF or 0xE0 <= status <= 0xEF:
        return 2
    if 0xC0 <= status <= 0xDF:
        return 1
    return {0xF1: 1, 0xF2: 2, 0xF3: 1, 0xF6: 0,
            0xF8: 0, 0xF9: 0, 0xFA: 0, 0xFB: 0,
            0xFC: 0, 0xFE: 0, 0xFF: 0}.get(status)


def _skip_delta(buf: bytes, i: int) -> int:
    """Skip a variable-length delta time (1-4 bytes, MSB = continue).
    We forward events immediately (same decision as the BLE bridge),
    so the value itself is discarded."""
    for _ in range(4):
        if i >= len(buf):
            return i
        more = buf[i] & 0x80
        i += 1
        if not more:
            break
    return i


def _parse_midi_list(buf: bytes, first_has_delta: bool) -> list[bytes]:
    commands: list[bytes] = []
    i = 0
    running: int | None = None
    first = True
    while i < len(buf):
        if not first or first_has_delta:
            i = _skip_delta(buf, i)
            if i >= len(buf):
                break
        first = False

        b = buf[i]
        if b in (0xF0, 0xF7):
            # SysEx segment: opener F0 (start) or F7 (continuation),
            # runs until F0 (more to come), F7 (final) or F4 (cancel).
            j = i + 1
            while j < len(buf) and buf[j] not in (0xF0, 0xF7, 0xF4):
                j += 1
            if j >= len(buf):
                # Unterminated segment — malformed, drop the rest.
                break
            commands.append(buf[i:j + 1])
            i = j + 1
            running = None
            continue

        if b & 0x80:
            status = b
            i += 1
            if status < 0xF0:
                running = status
            elif status < 0xF8:
                running = None  # system common clears running status
        elif running is not None:
            status = running
        else:
            break  # data byte with no status to apply — malformed

        n = _data_len(status)
        if n is None or i + n > len(buf):
            break
        commands.append(bytes([status]) + buf[i:i + n])
        i += n
    return commands


# --- SysEx (de)fragmentation, RFC 6295 §3.2 ---

def sysex_segments(message: bytes, max_segment: int = 1400) -> list[bytes]:
    """Split a complete SysEx message (F0 … F7) into RFC 6295 segments:
    first `F0 … F0`, middle `F7 … F0`, final `F7 … F7`. A message that
    fits returns as-is. `max_segment` bounds the payload per segment
    (framing bytes included) to stay under typical Ethernet MTU."""
    if len(message) < 2 or message[0] != 0xF0 or message[-1] != 0xF7:
        raise ValueError("not a complete SysEx message")
    if len(message) <= max_segment:
        return [message]
    body = message[1:-1]
    chunk = max_segment - 2  # room for the two framing bytes
    segments = []
    for i in range(0, len(body), chunk):
        part = body[i:i + chunk]
        first = i == 0
        last = i + chunk >= len(body)
        segments.append(bytes([0xF0 if first else 0xF7]) + part
                        + bytes([0xF7 if last else 0xF0]))
    return segments


class SysExAssembler:
    """Reassembles RFC 6295 SysEx segments into complete F0 … F7
    messages. One instance per remote stream (segments of different
    messages never interleave within a stream)."""

    def __init__(self):
        self._buf: bytearray | None = None

    def feed(self, segment: bytes) -> bytes | None:
        """Feed one segment; returns the complete message when the
        final segment arrives, else None. A cancelled (F4-terminated)
        or out-of-sequence segment resets the assembler."""
        if len(segment) < 2:
            return None
        opener, closer = segment[0], segment[-1]
        body = segment[1:-1]

        if closer == 0xF4:  # cancellation
            self._buf = None
            return None
        if opener == 0xF0:
            self._buf = bytearray(body)  # new message (implicitly resets)
        elif opener == 0xF7 and self._buf is not None:
            self._buf.extend(body)
        else:
            self._buf = None  # continuation without a start — drop
            return None

        if closer == 0xF7:
            msg = bytes([0xF0]) + bytes(self._buf) + bytes([0xF7])
            self._buf = None
            return msg
        return None
