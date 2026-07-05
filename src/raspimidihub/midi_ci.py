"""MIDI-CI (Capability Inquiry) initiator — M2-101-UM v1.2 subset.

The hub actively identifies connected devices over Universal SysEx:
Discovery (identity: manufacturer / family / model / version +
supported categories) and, when the device supports Property Exchange,
a `DeviceInfo` resource fetch (friendly names). Works over any
bidirectional MIDI link — USB, DIN, virtual — MIDI 2.0 not required.

Split in two layers:
- pure codec (build_* / parse) — unit-testable, no I/O;
- CiSession — a dedicated ALSA seq client that talks point-to-point
  to ONE device at a time (its port pair is subscribed only to the
  inquiry target, never the routed graph, so CI conversations can't
  fan out to innocent destinations — the classic hub hazard).

Per decision D7: the hub's MUID is random per process, device MUIDs
are never persisted; durable identity stays with device_id.py.
"""

import ctypes
import json
import logging
import secrets
import select
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

SYSEX_UNIVERSAL_NONREALTIME = 0x7E
SYSEX_CI_SUBID = 0x0D
CI_VERSION = 0x02          # MIDI-CI v1.2 message format
BROADCAST_MUID = 0x0FFFFFFF
WHOLE_PORT = 0x7F          # device-ID byte: to/from function block

# Sub-ID 2 message codes
MSG_DISCOVERY = 0x70
MSG_DISCOVERY_REPLY = 0x71
MSG_INVALIDATE_MUID = 0x7E
MSG_NAK = 0x7F
MSG_PE_CAPS = 0x30
MSG_PE_CAPS_REPLY = 0x31
MSG_PE_GET = 0x34
MSG_PE_GET_REPLY = 0x35

# Discovery capability-category bits (CI v1.2; bit 0 = deprecated
# protocol negotiation)
CAT_PROFILES = 0x02
CAT_PROPERTY_EXCHANGE = 0x04
CAT_PROCESS_INQUIRY = 0x08

# The hub's manufacturer ID on the wire: 0x7D = educational /
# non-commercial (we are not a registered SysEx vendor).
HUB_MANUFACTURER = (0x7D, 0x00, 0x00)


def new_muid() -> int:
    """Random 28-bit MUID, avoiding the reserved top range."""
    return secrets.randbelow(0x0FFFFF00)


def _u28(value: int) -> bytes:
    return bytes((value >> s) & 0x7F for s in (0, 7, 14, 21))


def _read_u28(b: bytes) -> int:
    return b[0] | (b[1] << 7) | (b[2] << 14) | (b[3] << 21)


def _u14(value: int) -> bytes:
    return bytes(((value & 0x7F), (value >> 7) & 0x7F))


def _read_u14(b: bytes) -> int:
    return b[0] | (b[1] << 7)


def _frame(sub2: int, src_muid: int, dst_muid: int, payload: bytes) -> bytes:
    return bytes((0xF0, SYSEX_UNIVERSAL_NONREALTIME, WHOLE_PORT,
                  SYSEX_CI_SUBID, sub2, CI_VERSION)) \
        + _u28(src_muid) + _u28(dst_muid) + payload + b"\xF7"


def build_discovery_inquiry(src_muid: int) -> bytes:
    payload = (bytes(HUB_MANUFACTURER)
               + _u14(0)            # device family
               + _u14(0)            # family model
               + bytes(4)           # software revision
               + bytes((0x00,))     # our category support (initiator only)
               + _u28(4096)         # max sysex size we accept
               + bytes((0x00,)))    # output path id (v1.2)
    return _frame(MSG_DISCOVERY, src_muid, BROADCAST_MUID, payload)


def build_discovery_reply(src_muid: int, dst_muid: int, *, manufacturer,
                          family: int, model: int, version: bytes,
                          categories: int, max_sysex: int = 512) -> bytes:
    """Responder side — used by the virtual test synth."""
    payload = (bytes(manufacturer) + _u14(family) + _u14(model)
               + bytes(version[:4]).ljust(4, b"\x00")
               + bytes((categories,)) + _u28(max_sysex)
               + bytes((0x00, 0x00)))  # output path id + function block
    return _frame(MSG_DISCOVERY_REPLY, src_muid, dst_muid, payload)


def build_pe_caps_inquiry(src_muid: int, dst_muid: int) -> bytes:
    return _frame(MSG_PE_CAPS, src_muid, dst_muid,
                  bytes((1, 0, 0)))  # 1 simultaneous request; v-major/minor


def build_pe_caps_reply(src_muid: int, dst_muid: int) -> bytes:
    return _frame(MSG_PE_CAPS_REPLY, src_muid, dst_muid, bytes((1, 0, 0)))


def build_pe_get(src_muid: int, dst_muid: int, request_id: int,
                 resource: str) -> bytes:
    header = json.dumps({"resource": resource},
                        separators=(",", ":")).encode("ascii")
    payload = (bytes((request_id,)) + _u14(len(header)) + header
               + _u14(1) + _u14(1) + _u14(0))  # 1 chunk of 1, no data
    return _frame(MSG_PE_GET, src_muid, dst_muid, payload)


def build_pe_get_reply(src_muid: int, dst_muid: int, request_id: int,
                       body: bytes, status: int = 200) -> bytes:
    header = json.dumps({"status": status},
                        separators=(",", ":")).encode("ascii")
    payload = (bytes((request_id,)) + _u14(len(header)) + header
               + _u14(1) + _u14(1) + _u14(len(body)) + body)
    return _frame(MSG_PE_GET_REPLY, src_muid, dst_muid, payload)


@dataclass(slots=True)
class CiMessage:
    sub2: int
    version: int
    src_muid: int
    dst_muid: int
    payload: bytes
    # Discovery-reply fields
    manufacturer: tuple = ()
    family: int = 0
    model: int = 0
    device_version: tuple = ()
    categories: int = 0
    max_sysex: int = 0
    # PE fields
    request_id: int = 0
    header: dict = field(default_factory=dict)
    num_chunks: int = 0
    chunk_num: int = 0
    data: bytes = b""


def parse(frame: bytes) -> CiMessage | None:
    """Parse one complete SysEx frame (with or without F0/F7 framing).
    Returns None for anything that isn't MIDI-CI or is malformed —
    replies come from arbitrary firmware, so never raise."""
    try:
        b = bytes(frame)
        if b[:1] == b"\xF0":
            b = b[1:]
        if b[-1:] == b"\xF7":
            b = b[:-1]
        if len(b) < 13 or b[0] != SYSEX_UNIVERSAL_NONREALTIME \
                or b[2] != SYSEX_CI_SUBID:
            return None
        m = CiMessage(sub2=b[3], version=b[4],
                      src_muid=_read_u28(b[5:9]), dst_muid=_read_u28(b[9:13]),
                      payload=b[13:])
        p = m.payload
        if m.sub2 in (MSG_DISCOVERY, MSG_DISCOVERY_REPLY) and len(p) >= 16:
            m.manufacturer = tuple(p[0:3])
            m.family = _read_u14(p[3:5])
            m.model = _read_u14(p[5:7])
            m.device_version = tuple(p[7:11])
            m.categories = p[11]
            m.max_sysex = _read_u28(p[12:16])
        elif m.sub2 in (MSG_PE_GET, MSG_PE_GET_REPLY) and len(p) >= 3:
            m.request_id = p[0]
            hlen = _read_u14(p[1:3])
            hdr = p[3:3 + hlen]
            rest = p[3 + hlen:]
            try:
                m.header = json.loads(hdr.decode("ascii", errors="replace"))
            except (ValueError, UnicodeDecodeError):
                m.header = {}
            if len(rest) >= 6:
                m.num_chunks = _read_u14(rest[0:2])
                m.chunk_num = _read_u14(rest[2:4])
                dlen = _read_u14(rest[4:6])
                m.data = rest[6:6 + dlen]
        return m
    except (IndexError, ValueError):
        return None


class SysexAccumulator:
    """Reassemble ALSA SYSEX event chunks into complete F0..F7 frames."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        frames = []
        for byte in chunk:
            if byte == 0xF0:
                self._buf = bytearray((0xF0,))
            elif self._buf:
                self._buf.append(byte)
                if byte == 0xF7:
                    frames.append(bytes(self._buf))
                    self._buf = bytearray()
        return frames


class CiSession:
    """Point-to-point MIDI-CI initiator over a dedicated seq client.

    One inquiry at a time (internal lock); the port pair is subscribed
    to exactly one device for the duration of the inquiry and torn
    down afterwards. Runs blocking (select-based) — call from a worker
    thread, never the asyncio loop.
    """

    def __init__(self):
        from .alsa_seq import AlsaSeq
        self._seq = AlsaSeq("RaspiMIDIHub CI", default_ports=False)
        self._port = self._seq.create_port("ci", readable=True, writable=True)
        self._lock = threading.Lock()
        self.muid = new_muid()

    @property
    def client_id(self) -> int:
        return self._seq.client_id

    def close(self) -> None:
        self._seq.close()

    def _send_sysex(self, data: bytes, dst_client: int, dst_port: int) -> None:
        from .alsa_seq import (
            SND_SEQ_EVENT_LENGTH_VARIABLE,
            SND_SEQ_QUEUE_DIRECT,
            MidiEventType,
            SndSeqEvent,
            snd_seq_event_output_direct,
        )
        buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        ev = SndSeqEvent()
        ev.type = MidiEventType.SYSEX
        ev.flags = SND_SEQ_EVENT_LENGTH_VARIABLE
        ev.source.client = self._seq.client_id
        ev.source.port = self._port
        ev.dest.client = dst_client
        ev.dest.port = dst_port
        ev.queue = SND_SEQ_QUEUE_DIRECT
        ev.data.ext.len = len(data)
        ev.data.ext.ptr = ctypes.cast(buf, ctypes.c_void_p)
        snd_seq_event_output_direct(self._seq.handle, ctypes.pointer(ev))

    def _read_frames(self, acc: SysexAccumulator) -> list[bytes]:
        from .alsa_seq import MidiEventType
        frames = []
        while True:
            ev = self._seq.read_event()
            if ev is None:
                break
            if ev.type != int(MidiEventType.SYSEX):
                continue
            chunk = ctypes.string_at(ev.data.ext.ptr, ev.data.ext.len)
            frames.extend(acc.feed(chunk))
        return frames

    def _await_reply(self, sub2: int, timeout: float,
                     acc: SysexAccumulator) -> CiMessage | None:
        fd = self._seq.fileno()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            readable, _, _ = select.select([fd], [], [], remaining)
            if not readable:
                return None
            for frame in self._read_frames(acc):
                m = parse(frame)
                if m and m.sub2 == sub2 and m.dst_muid in (self.muid,
                                                           BROADCAST_MUID):
                    return m

    def inquire(self, dst_client: int, in_port: int, out_port: int,
                timeout: float = 2.0, fetch_device_info: bool = True) -> dict | None:
        """Run Discovery (+ optional PE DeviceInfo) against one device.

        in_port: the device's receiving port (we send there);
        out_port: the device's sending port (we listen there).
        Returns a result dict or None if the device didn't answer.
        """
        with self._lock:
            try:
                self._seq.subscribe(dst_client, out_port,
                                    self._seq.client_id, self._port)
            except OSError:
                return None
            try:
                return self._inquire_locked(dst_client, in_port, timeout,
                                            fetch_device_info)
            finally:
                try:
                    self._seq.unsubscribe(dst_client, out_port,
                                          self._seq.client_id, self._port)
                except OSError:
                    pass

    def _inquire_locked(self, dst_client: int, in_port: int, timeout: float,
                        fetch_device_info: bool) -> dict | None:
        acc = SysexAccumulator()
        reply = None
        for _attempt in range(2):  # single retry per FSD-10
            self._send_sysex(build_discovery_inquiry(self.muid),
                             dst_client, in_port)
            reply = self._await_reply(MSG_DISCOVERY_REPLY, timeout, acc)
            if reply is not None:
                break
        if reply is None:
            return None

        result = {
            "manufacturer": "".join(f"{b:02X}" for b in reply.manufacturer),
            "family": reply.family,
            "model": reply.model,
            "version": ".".join(str(b) for b in reply.device_version),
            "categories": {
                "profiles": bool(reply.categories & CAT_PROFILES),
                "property_exchange": bool(reply.categories & CAT_PROPERTY_EXCHANGE),
                "process_inquiry": bool(reply.categories & CAT_PROCESS_INQUIRY),
            },
            "max_sysex": reply.max_sysex,
        }

        if fetch_device_info and (reply.categories & CAT_PROPERTY_EXCHANGE):
            dev_muid = reply.src_muid
            self._send_sysex(build_pe_caps_inquiry(self.muid, dev_muid),
                             dst_client, in_port)
            if self._await_reply(MSG_PE_CAPS_REPLY, timeout, acc) is not None:
                self._send_sysex(build_pe_get(self.muid, dev_muid, 1,
                                              "DeviceInfo"),
                                 dst_client, in_port)
                chunks: dict[int, bytes] = {}
                total = 1
                deadline = time.monotonic() + timeout + 1.0
                while time.monotonic() < deadline:
                    m = self._await_reply(MSG_PE_GET_REPLY,
                                          deadline - time.monotonic(), acc)
                    if m is None or m.request_id != 1:
                        break
                    chunks[m.chunk_num] = m.data
                    total = max(1, m.num_chunks)
                    if len(chunks) >= total:
                        break
                if len(chunks) >= total and sum(map(len, chunks.values())) <= 8192:
                    body = b"".join(chunks[i] for i in sorted(chunks))
                    try:
                        result["device_info"] = json.loads(
                            body.decode("ascii", errors="replace"))
                    except ValueError:
                        pass
        return result
