"""Network MIDI bridge: exports local devices as RTP-MIDI sessions.

Each *exported* device is advertised as its own AppleMIDI session via
mDNS (`_apple-midi._udp`), named "<device> @<hostname>". Anything that
speaks RTP-MIDI can connect — a second RaspiMIDIHub (which mirrors the
session into its routing matrix, phase 3), macOS Audio MIDI Setup, an
iPad, rtpmidid. Multiple participants per session are fine: a Mac and
a peer hub can be connected to the same exported device at once.

Why per-device sessions instead of one tunnel per hub: the export list
*is* the curation step. Exporting one plugin pair gives you a tunnel;
exporting everything gives the peer full per-device routing — and
standard RTP-MIDI clients see each device under its own name for free.

Identity on the wire: sessions carry TXT records `rmh=1`,
`hub=<machine-id prefix>`, `sid=<stable_id>` so a peer hub can tell
"a hub deliberately shared this device" apart from a random Mac
session, skip its own adverts, and key the mirrored device's stable
id (`net-<hub>-<sid>`) on something that survives reboots and
IP/port changes.

Threading: everything runs on the main asyncio loop, like the BLE
bridge and the FilterEngine — UDP datagram callbacks plus one
`loop.add_reader` on the shared ALSA client's fd. MIDI is a few KB/s
per busy device and the per-event work is one parse + one ioctl. If
latency probes ever show pressure, the escalation path is a dedicated
thread with `call_soon_threadsafe` marshalling — measure first.

All exports share ONE hidden ALSA client ("NetworkMIDI", two ports
per session). It is never whitelisted in the engine's scan, so the
plumbing stays invisible in the matrix. Mirrored sessions (phase 3)
get one visible client each, like BLE devices.

The zeroconf dependency (python3-zeroconf, pure python) is imported
lazily; without it the feature reports available=False and the UI
renders a hint, same contract as Bluetooth on BT-less hardware.
"""

import asyncio
import logging
import os
import socket
import time

from . import apple_midi
from .midi_codec import event_to_midi, midi_to_event

log = logging.getLogger(__name__)

SERVICE_TYPE = "_apple-midi._udp.local."
BASE_PORT = 5004          # first control port tried; data port = +1
PORT_RANGE = 200          # how far above BASE_PORT we probe for free pairs

# Apple initiators clock-sync every ~10 s; 60 s of silence = 6 missed
# rounds, safely past WiFi hiccups but quick enough that a vanished
# Mac doesn't haunt the participant list.
PARTICIPANT_TIMEOUT = 60.0
HOUSEKEEPING_INTERVAL = 2.0
MANUAL_PEER_INTERVAL = 30.0
# How often we re-check the set of local IPv4 addresses. zeroconf only
# joins the mDNS multicast group on interfaces that had an address when
# AsyncZeroconf was constructed; an eth0 that comes up *after* start
# (a hub-to-hub cable plugged in later) would otherwise never advertise
# or discover over that link. On a change we re-bind the mDNS stack.
LINK_WATCH_INTERVAL = 5.0
RECONNECT_DELAY = 2.0     # first retry; doubles up to the cap
RECONNECT_DELAY_MAX = 30.0

_T0 = time.monotonic()


def now_ts() -> int:
    """Current time in AppleMIDI's 10 kHz (100 µs) units, anchored at
    process start. Peers only ever use deltas, so the anchor is free."""
    return int((time.monotonic() - _T0) * apple_midi.CLOCK_HZ)


def _zeroconf_availability() -> dict:
    try:
        import zeroconf  # noqa: F401
        return {"available": True, "reason": None}
    except ImportError:
        return {"available": False, "reason": "no-zeroconf"}


def hub_id() -> str:
    """Stable identity of this hub for TXT records: the first 12 hex
    chars of /etc/machine-id (survives reboots and hostname changes);
    hostname as a fallback for odd images."""
    try:
        return open("/etc/machine-id").read().strip()[:12]
    except OSError:
        return socket.gethostname()[:12]


def _pick_reachable_address(addresses: list[str]) -> str:
    """Choose the peer address that shares a subnet with one of our
    interfaces — a peer advertises ALL its addresses (192.168.4.1 for
    its own AP, its ethernet IP, ...) and the first is not necessarily
    routable from here. Falls back to the first address."""
    if len(addresses) <= 1:
        return addresses[0]
    try:
        import ipaddress

        from .wifi import get_all_interfaces
        local_nets = []
        for info in get_all_interfaces():
            if info.get("address") and info.get("netmask"):
                try:
                    local_nets.append(ipaddress.IPv4Network(
                        f"{info['address']}/{info['netmask']}", strict=False))
                except ValueError:
                    pass
        for addr in addresses:
            try:
                ip = ipaddress.IPv4Address(addr)
            except ValueError:
                continue
            if any(ip in net for net in local_nets):
                return addr
    except Exception:
        log.debug("network-midi: address selection failed", exc_info=True)
    return addresses[0]


class _UdpShim(asyncio.DatagramProtocol):
    """Minimal DatagramProtocol that forwards datagrams to a callback."""

    def __init__(self, on_datagram):
        self._on_datagram = on_datagram

    def datagram_received(self, data, addr):
        try:
            self._on_datagram(data, addr)
        except Exception:
            log.exception("network-midi: datagram handler failed")


async def _bind_port_pair(loop, on_control, on_data):
    """Bind an even/odd UDP port pair (AppleMIDI convention: data =
    control + 1), probing upward from BASE_PORT. Returns
    (control_port, control_transport, data_transport)."""
    last_err = None
    for port in range(BASE_PORT, BASE_PORT + PORT_RANGE, 2):
        try:
            ctrl, _ = await loop.create_datagram_endpoint(
                lambda: _UdpShim(on_control), local_addr=("0.0.0.0", port))
        except OSError as e:
            last_err = e
            continue
        try:
            data, _ = await loop.create_datagram_endpoint(
                lambda: _UdpShim(on_data), local_addr=("0.0.0.0", port + 1))
        except OSError as e:
            ctrl.close()
            last_err = e
            continue
        return port, ctrl, data
    raise OSError(f"no free UDP port pair: {last_err}")


def _output_event(alsa, ev, source_port: int) -> None:
    """Emit `ev` from `source_port` of `alsa` to all subscribers —
    the network→ALSA injection used by exports and mirrors alike."""
    from ctypes import pointer

    from .alsa_seq import (
        SND_SEQ_ADDRESS_SUBSCRIBERS,
        SND_SEQ_QUEUE_DIRECT,
        snd_seq_event_output_direct,
    )
    ev.source.client = alsa.client_id
    ev.source.port = source_port
    ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
    ev.dest.port = 0
    ev.queue = SND_SEQ_QUEUE_DIRECT
    try:
        snd_seq_event_output_direct(alsa.handle, pointer(ev))
    except Exception as e:
        log.debug("network-midi: ALSA inject failed: %s", e)


class _SysExChunkFramer:
    """Frames raw ALSA SysEx chunks as RFC 6295 segments. ALSA
    delivers large dumps as a series of SYSEX events whose payloads
    concatenate to F0 … F7; segment framing maps onto that stream
    directly (F0/F7 opener, F0 = to-be-continued, F7 = final), so
    chunks go on the wire as they arrive — no buffering the dump.
    Chunks are device/driver-sized (typically ≤ 256 B), well under
    MTU; a complete-in-one chunk still gets split when oversized."""

    def __init__(self):
        self._open = False

    def frame(self, chunk: bytes) -> list[bytes]:
        if not chunk:
            return []
        if not self._open:
            if chunk[0] != 0xF0:
                return []  # mid-stream chunk with no start seen — drop
            if chunk[-1] == 0xF7:
                return apple_midi.sysex_segments(chunk)
            self._open = True
            return [chunk + b"\xf0"]
        if chunk[-1] == 0xF7:
            self._open = False
            return [b"\xf7" + chunk]
        return [b"\xf7" + chunk + b"\xf0"]


class _Participant:
    """One remote endpoint connected to an ExportedSession."""

    def __init__(self, ssrc: int, name: str | None, control_addr):
        self.ssrc = ssrc
        self.name = name or "?"
        self.control_addr = control_addr
        self.data_addr = None          # set by the data-port invitation
        self.last_rx = time.monotonic()
        self.last_seq = 0
        self.sysex_rx = apple_midi.SysExAssembler()

    @property
    def connected(self) -> bool:
        return self.data_addr is not None


class ExportedSession:
    """Responder side of one exported device: a UDP port pair, an
    mDNS advert, and tx/rx ports on the manager's shared ALSA client
    kernel-subscribed to the real device."""

    def __init__(self, manager, stable_id: str, device_name: str):
        self._manager = manager
        self.stable_id = stable_id
        self.device_name = device_name
        self.ssrc = int.from_bytes(os.urandom(4), "big")
        self.control_port = -1
        self._control_transport = None
        self._data_transport = None
        self.tx_port = -1              # writable: receives the device's output
        self.rx_port = -1              # readable: source for injected input
        self.participants: dict[int, _Participant] = {}
        self._seqnum = int.from_bytes(os.urandom(2), "big")
        self._sysex_tx = _SysExChunkFramer()
        self._service_info = None      # zeroconf ServiceInfo while registered

    @property
    def service_name(self) -> str:
        return f"{self.device_name} @{self._manager.hostname}"

    # --- lifecycle ---

    async def start(self, device) -> None:
        """Bind sockets, create+subscribe ALSA ports, register mDNS.
        `device` is the engine's MidiDevice for the exported client."""
        loop = asyncio.get_event_loop()
        alsa = self._manager.alsa
        self.tx_port = alsa.create_port(f"tx:{self.stable_id}", writable=True)
        self.rx_port = alsa.create_port(f"rx:{self.stable_id}", readable=True)
        try:
            for p in device.input_ports:
                alsa.subscribe(device.client_id, p.port_id,
                               alsa.client_id, self.tx_port)
            for p in device.output_ports:
                alsa.subscribe(alsa.client_id, self.rx_port,
                               device.client_id, p.port_id)

            self.control_port, self._control_transport, self._data_transport = \
                await _bind_port_pair(loop, self.on_control, self.on_data)

            await self._manager.register_service(self)
        except Exception:
            await self.stop(send_bye=False)
            raise
        log.info("network-midi: exporting '%s' on UDP %d/%d",
                 self.service_name, self.control_port, self.control_port + 1)

    async def stop(self, send_bye: bool = True) -> None:
        """Tear down: BY to participants, mDNS goodbye, sockets, ports.
        Deleting the ALSA ports drops their subscriptions with them."""
        if send_bye and self._control_transport:
            for part in list(self.participants.values()):
                try:
                    self._control_transport.sendto(
                        apple_midi.build_exchange(
                            apple_midi.CMD_BYE, 0, self.ssrc),
                        part.control_addr)
                except Exception:
                    pass
        self.participants.clear()
        await self._manager.unregister_service(self)
        for transport in (self._control_transport, self._data_transport):
            if transport:
                transport.close()
        self._control_transport = self._data_transport = None
        alsa = self._manager.alsa
        for port in (self.tx_port, self.rx_port):
            if port >= 0 and alsa:
                try:
                    alsa.delete_port(port)
                except Exception:
                    log.warning("network-midi: port cleanup failed", exc_info=True)
        self.tx_port = self.rx_port = -1

    # --- session protocol (responder role) ---

    def on_control(self, data: bytes, addr) -> None:
        pkt = apple_midi.parse_command(data)
        if isinstance(pkt, apple_midi.ExchangePacket):
            if pkt.command == apple_midi.CMD_INVITATION:
                part = self.participants.get(pkt.ssrc)
                if part is None:
                    part = _Participant(pkt.ssrc, pkt.name, addr)
                    self.participants[pkt.ssrc] = part
                part.control_addr = addr
                self._control_transport.sendto(
                    apple_midi.build_exchange(
                        apple_midi.CMD_ACCEPT, pkt.initiator_token,
                        self.ssrc, self.service_name), addr)
                self._manager.notify_changed()
            elif pkt.command == apple_midi.CMD_BYE:
                if self.participants.pop(pkt.ssrc, None):
                    log.info("network-midi: '%s' left %s",
                             pkt.name or pkt.ssrc, self.service_name)
                    self._manager.notify_changed()
        elif isinstance(pkt, apple_midi.ClockSync):
            self._on_clock(pkt, addr, self._control_transport)

    def on_data(self, data: bytes, addr) -> None:
        pkt = apple_midi.parse_command(data)
        if isinstance(pkt, apple_midi.ExchangePacket):
            if pkt.command == apple_midi.CMD_INVITATION:
                part = self.participants.get(pkt.ssrc)
                if part is None:
                    # Data-port IN without a control-port IN first —
                    # tolerate it (some stacks reconnect this way).
                    part = _Participant(pkt.ssrc, pkt.name, addr)
                    self.participants[pkt.ssrc] = part
                part.data_addr = addr
                self._data_transport.sendto(
                    apple_midi.build_exchange(
                        apple_midi.CMD_ACCEPT, pkt.initiator_token,
                        self.ssrc, self.service_name), addr)
                log.info("network-midi: '%s' joined %s",
                         part.name, self.service_name)
                self._manager.notify_changed()
            elif pkt.command == apple_midi.CMD_BYE:
                if self.participants.pop(pkt.ssrc, None):
                    self._manager.notify_changed()
            return
        if isinstance(pkt, apple_midi.ClockSync):
            self._on_clock(pkt, addr, self._data_transport)
            return
        if isinstance(pkt, apple_midi.Feedback):
            return  # we keep no journal, nothing to trim

        rtp = apple_midi.parse_rtp_midi(data)
        if rtp is None:
            return
        part = self.participants.get(rtp.ssrc)
        if part is None:
            return  # not invited — ignore
        t0 = time.monotonic()
        part.last_rx = t0
        part.last_seq = rtp.seq
        for cmd in rtp.commands:
            if cmd and cmd[0] in (0xF0, 0xF7):
                complete = part.sysex_rx.feed(cmd)
                if complete:
                    self._inject(complete)
            else:
                self._inject(cmd)
        self._manager.record_latency("net_midi_rx",
                                     (time.monotonic() - t0) * 1000.0)

    def _on_clock(self, ck: apple_midi.ClockSync, addr, transport) -> None:
        """Always answer CK0 with CK1 — macOS drops peers that don't.
        CK2 closes the round; we don't initiate as responder."""
        part = self.participants.get(ck.ssrc)
        if part:
            part.last_rx = time.monotonic()
        if ck.count == 0 and transport:
            transport.sendto(apple_midi.build_clock_sync(
                self.ssrc, 1, ck.ts1, now_ts()), addr)

    # --- MIDI bridging ---

    def _inject(self, msg: bytes) -> None:
        """Network → ALSA: source the event from our rx port; the
        kernel subscription rx → device delivers it."""
        ev = midi_to_event(msg)
        if ev is None:
            return
        self._manager.output_event(ev, self.rx_port)

    def send_midi(self, midi: bytes, is_sysex_chunk: bool = False) -> None:
        """ALSA → network: fan one MIDI message (or one raw ALSA SysEx
        chunk) out to all connected participants."""
        if not self._data_transport:
            return
        segments = (self._sysex_tx.frame(midi) if is_sysex_chunk
                    else [midi])
        for seg in segments:
            self._seqnum = (self._seqnum + 1) & 0xFFFF
            pkt = apple_midi.build_rtp_midi(self._seqnum, now_ts(),
                                            self.ssrc, seg)
            for part in self.participants.values():
                if part.data_addr:
                    self._data_transport.sendto(pkt, part.data_addr)

    def _frame_sysex_chunk(self, chunk: bytes) -> list[bytes]:
        return self._sysex_tx.frame(chunk)

    def status(self) -> dict:
        return {
            "stable_id": self.stable_id,
            "name": self.service_name,
            "port": self.control_port,
            "participants": [
                {"name": p.name, "ssrc": p.ssrc,
                 "addr": p.control_addr[0] if p.control_addr else None,
                 "connected": p.connected}
                for p in self.participants.values()
            ],
        }


class DiscoveredService:
    """One RTP-MIDI session seen via mDNS (hub export or foreign)."""

    def __init__(self, service: str, instance: str, host: str,
                 addresses: list[str], port: int, txt: dict[str, str],
                 via_manual: str | None = None):
        self.service = service        # full mDNS instance name
        self.instance = instance      # without the service-type suffix
        self.host = host              # advertising host (server record)
        self.addresses = addresses
        self.port = port              # control port; data = +1
        self.txt = txt
        # Set when the entry came from polling a manually-added peer
        # (no mDNS path); holds that peer's configured host string so
        # the poller can retract its own entries when the peer drops.
        self.via_manual = via_manual

    @property
    def is_hub(self) -> bool:
        return self.txt.get("rmh") == "1"

    @property
    def hub(self) -> str:
        return self.txt.get("hub", "")

    @property
    def sid(self) -> str:
        return self.txt.get("sid", "")

    @property
    def device_name(self) -> str:
        """Bare device name — the matrix group header carries the hub,
        so the 9-char row budget isn't wasted on '@hostname'."""
        if self.txt.get("dev"):
            return self.txt["dev"]
        if " @" in self.instance:
            return self.instance.rsplit(" @", 1)[0]
        return self.instance

    @property
    def remote_hub(self) -> str:
        if self.txt.get("host"):
            return self.txt["host"]
        if " @" in self.instance:
            return self.instance.rsplit(" @", 1)[1]
        return self.host or "network"

    @property
    def stable_id(self) -> str:
        """Survives reboots and IP/port changes on both ends: keyed on
        the peer's machine-id + the device's stable id over there. A
        foreign session has neither — its mDNS instance name is the
        most stable thing it offers."""
        if self.is_hub and self.sid:
            return f"net-{self.hub}-{self.sid}"
        slug = "".join(c if c.isalnum() else "-" for c in self.instance)
        return f"net-{slug}"


class MirroredSession:
    """Initiator side of one mirrored remote session: its own visible
    ALSA client (the _BleDevice pattern — the device in the matrix IS
    this client), an AppleMIDI handshake to the remote port pair, and
    a CK clock-sync task that doubles as the liveness probe."""

    HANDSHAKE_TIMEOUT = 3.0
    HANDSHAKE_RETRIES = 3
    CK_INTERVAL = 10.0
    CK_MAX_UNANSWERED = 3   # ~30 s of dead air → declare the peer gone

    def __init__(self, manager, svc: DiscoveredService):
        self._manager = manager
        self.svc = svc
        self.stable_id = svc.stable_id
        self.device_name = svc.device_name
        self.remote_hub = svc.remote_hub
        self.state = "idle"            # idle/connecting/connected/closed
        self.latency_ms: float | None = None
        self.ssrc = int.from_bytes(os.urandom(4), "big")
        self._token = int.from_bytes(os.urandom(4), "big")
        self._alsa = None              # own visible client while connected
        self._out_port = -1            # readable: remote's output enters here
        self._in_port = -1             # writable: matrix routes into here
        self._ctrl_transport = None
        self._data_transport = None
        # A peer advertises ALL its addresses (its AP, ethernet, ...);
        # blindly taking the first can pick one we can't reach.
        addr = _pick_reachable_address(svc.addresses)
        self._remote_ctrl = (addr, svc.port)
        self._remote_data = (addr, svc.port + 1)
        self._ok_future: asyncio.Future | None = None
        self._remote_ssrc: int | None = None
        self._ck_task = None
        self._ck_ts1 = 0
        self._ck_answered = False
        self._seqnum = int.from_bytes(os.urandom(2), "big")
        self._sysex_rx = apple_midi.SysExAssembler()
        self._sysex_tx = _SysExChunkFramer()
        self.last_rx = time.monotonic()

    @property
    def alsa_client_id(self) -> int | None:
        return self._alsa.client_id if self._alsa else None

    # --- lifecycle ---

    async def start(self) -> None:
        """Bind a local port pair, run the two-phase invitation, then
        surface the remote device as a local ALSA client."""
        loop = asyncio.get_event_loop()
        self.state = "connecting"
        _, self._ctrl_transport, self._data_transport = \
            await _bind_port_pair(loop, self.on_control, self.on_data)
        try:
            await self._invite(self._ctrl_transport, self._remote_ctrl)
            await self._invite(self._data_transport, self._remote_data)
        except Exception:
            await self.stop(send_bye=False)
            raise

        from .alsa_seq import AlsaSeq
        self._alsa = AlsaSeq(self.device_name, default_ports=False)
        self._out_port = self._alsa.create_port("OUT", readable=True)
        self._in_port = self._alsa.create_port("IN", writable=True)
        loop.add_reader(self._alsa.fileno(), self._on_alsa_readable)
        # Creating the client fires CLIENT_START — the engine's
        # debounced hotplug rescan picks the device up from there.

        self.state = "connected"
        self._ck_task = loop.create_task(self._ck_loop())
        log.info("network-midi: mirroring '%s' from %s (%s:%d)",
                 self.device_name, self.remote_hub, *self._remote_ctrl)

    async def _invite(self, transport, remote) -> None:
        """Send IN and await the OK on one port (control, then data)."""
        loop = asyncio.get_event_loop()
        for _attempt in range(self.HANDSHAKE_RETRIES):
            self._ok_future = loop.create_future()
            transport.sendto(
                apple_midi.build_exchange(
                    apple_midi.CMD_INVITATION, self._token, self.ssrc,
                    f"{self._manager.hostname}"),
                remote)
            try:
                await asyncio.wait_for(self._ok_future,
                                       self.HANDSHAKE_TIMEOUT)
                return
            except asyncio.TimeoutError:
                continue
        raise TimeoutError(f"no OK from {remote[0]}:{remote[1]}")

    async def stop(self, send_bye: bool = True) -> None:
        self.state = "closed"
        if self._ck_task:
            self._ck_task.cancel()
            self._ck_task = None
        if send_bye and self._ctrl_transport:
            try:
                self._ctrl_transport.sendto(
                    apple_midi.build_exchange(
                        apple_midi.CMD_BYE, self._token, self.ssrc),
                    self._remote_ctrl)
            except Exception:
                pass
        for transport in (self._ctrl_transport, self._data_transport):
            if transport:
                transport.close()
        self._ctrl_transport = self._data_transport = None
        if self._alsa:
            try:
                asyncio.get_event_loop().remove_reader(self._alsa.fileno())
            except (OSError, ValueError, RuntimeError):
                pass
            self._manager.unregister_mirror_device(self.stable_id)
            # Closing the client fires CLIENT_EXIT → matrix rescan;
            # saved connections to the stable id stay pending.
            self._alsa.close()
            self._alsa = None

    # --- session protocol (initiator role) ---

    def on_control(self, data: bytes, addr) -> None:
        self._on_session_packet(data, addr, self._ctrl_transport)

    def on_data(self, data: bytes, addr) -> None:
        pkt = apple_midi.parse_command(data)
        if pkt is not None:
            self._on_session_packet(data, addr, self._data_transport)
            return
        rtp = apple_midi.parse_rtp_midi(data)
        if rtp is None or rtp.ssrc != self._remote_ssrc_guard(rtp.ssrc):
            return
        t0 = time.monotonic()
        self.last_rx = t0
        for cmd in rtp.commands:
            if cmd and cmd[0] in (0xF0, 0xF7):
                complete = self._sysex_rx.feed(cmd)
                if complete:
                    self._inject(complete)
            else:
                self._inject(cmd)
        self._manager.record_latency("net_midi_rx",
                                     (time.monotonic() - t0) * 1000.0)

    def _remote_ssrc_guard(self, ssrc: int) -> int:
        """The mirror talks to exactly one responder; accept its ssrc
        once seen, ignore strays. (The OK packet told us the ssrc, but
        some stacks renumber between handshake and data.)"""
        if getattr(self, "_remote_ssrc", None) is None:
            self._remote_ssrc = ssrc
        return self._remote_ssrc

    def _on_session_packet(self, data: bytes, addr, transport) -> None:
        pkt = apple_midi.parse_command(data)
        if isinstance(pkt, apple_midi.ExchangePacket):
            if pkt.command == apple_midi.CMD_ACCEPT:
                self._remote_ssrc = pkt.ssrc
                if self._ok_future and not self._ok_future.done():
                    self._ok_future.set_result(pkt)
            elif pkt.command == apple_midi.CMD_REJECT:
                if self._ok_future and not self._ok_future.done():
                    self._ok_future.set_exception(
                        ConnectionRefusedError(pkt.name or "rejected"))
            elif pkt.command == apple_midi.CMD_BYE:
                log.info("network-midi: peer closed '%s'", self.device_name)
                asyncio.ensure_future(self._manager.on_mirror_lost(self))
        elif isinstance(pkt, apple_midi.ClockSync):
            self.last_rx = time.monotonic()
            if pkt.count == 0 and transport:
                # Peer-initiated round: answer like a responder.
                transport.sendto(apple_midi.build_clock_sync(
                    self.ssrc, 1, pkt.ts1, now_ts()), addr)
            elif pkt.count == 1 and transport:
                # Our round coming back: close it + take the latency.
                ts3 = now_ts()
                transport.sendto(apple_midi.build_clock_sync(
                    self.ssrc, 2, pkt.ts1, pkt.ts2, ts3), addr)
                if pkt.ts1 == self._ck_ts1:
                    self.latency_ms = (ts3 - pkt.ts1) / 2 / 10
                    self._ck_answered = True

    async def _ck_loop(self) -> None:
        """Initiator clock sync every CK_INTERVAL — keeps macOS happy
        and doubles as the liveness probe: a cable pull or peer
        power-cut gives no BY, only silence. After CK_MAX_UNANSWERED
        rounds the manager tears the mirror down (matrix shows the
        device offline) and starts the backoff reconnect."""
        unanswered = 0
        while self.state == "connected":
            self._ck_ts1 = now_ts()
            self._ck_answered = False
            if self._data_transport:
                self._data_transport.sendto(
                    apple_midi.build_clock_sync(self.ssrc, 0, self._ck_ts1),
                    self._remote_data)
            await asyncio.sleep(self.CK_INTERVAL)
            if self._ck_answered:
                unanswered = 0
                continue
            unanswered += 1
            if unanswered >= self.CK_MAX_UNANSWERED:
                log.info("network-midi: '%s' unreachable (%d CK rounds), "
                         "dropping mirror", self.device_name, unanswered)
                asyncio.ensure_future(self._manager.on_mirror_lost(self))
                return

    # --- MIDI bridging ---

    def _inject(self, msg: bytes) -> None:
        ev = midi_to_event(msg)
        if ev is not None and self._alsa:
            _output_event(self._alsa, ev, self._out_port)

    def _on_alsa_readable(self) -> None:
        from .alsa_seq import MidiEventType
        while True:
            ev = self._alsa.read_event() if self._alsa else None
            if ev is None:
                return
            if ev.dest.port != self._in_port:
                continue
            midi = event_to_midi(ev)
            if midi is None or not self._data_transport:
                continue
            segments = (self._sysex_tx.frame(midi)
                        if ev.type == MidiEventType.SYSEX else [midi])
            for seg in segments:
                self._seqnum = (self._seqnum + 1) & 0xFFFF
                self._data_transport.sendto(
                    apple_midi.build_rtp_midi(self._seqnum, now_ts(),
                                              self.ssrc, seg),
                    self._remote_data)

    def status(self) -> dict:
        return {
            "service": self.svc.service,
            "stable_id": self.stable_id,
            "name": self.device_name,
            "remote_hub": self.remote_hub,
            "state": self.state,
            "latency_ms": self.latency_ms,
        }


class NetworkMidiManager:
    """Owns the export list, the shared ALSA client, zeroconf
    registration and (phase 3) discovery/mirroring."""

    def __init__(self, engine, config, server):
        self._engine = engine
        self._config = config
        self._server = server
        self._exports: dict[str, ExportedSession] = {}
        self._mirrors: dict[str, MirroredSession] = {}      # by service name
        self._discovered: dict[str, DiscoveredService] = {}  # by service name
        self._alsa = None              # shared hidden client, created on start
        self._aiozc = None             # AsyncZeroconf while running
        self._browser = None           # AsyncServiceBrowser while running
        self._loop = None
        self._started = False
        self._notify_task = None
        self._housekeeping_task = None
        self._manual_peers_task = None
        self._link_watch_task = None
        self._reconnect_tasks: dict[str, asyncio.Task] = {}
        self.hub_id = hub_id()
        # Hotplug reconcile: exported device unplugged → its session
        # leaves the network; replugged → it comes back. The callback
        # registers once for the manager's lifetime and no-ops while
        # the feature is off.
        if engine is not None:
            engine.on_change(self._on_engine_change)

    def _on_engine_change(self) -> None:
        if self._started and self._loop is not None:
            self._loop.create_task(self.resync_exports())

    # --- properties / availability ---

    @property
    def hostname(self) -> str:
        return socket.gethostname()

    @property
    def alsa(self):
        return self._alsa

    @property
    def settings(self) -> dict:
        return self._config.data.get("network_midi", {})

    def availability(self) -> dict:
        return _zeroconf_availability()

    def is_exportable(self, stable_id: str) -> tuple[bool, str | None]:
        """Loop protection + sanity: mirrored devices must never be
        re-exported, and the device must currently be online."""
        if stable_id.startswith("net-"):
            return False, "mirrored devices cannot be exported"
        if self._device_for(stable_id) is None:
            return False, "device is offline"
        return True, None

    # --- lifecycle ---

    async def start(self) -> None:
        """Bring the feature up if enabled in config. Safe to call
        again after set_enabled() toggles."""
        if self._started or not self.settings.get("enabled"):
            return
        if not self.availability()["available"]:
            log.info("network-midi: zeroconf not installed, feature off")
            return
        from zeroconf import IPVersion
        from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

        from .alsa_seq import AlsaSeq

        self._loop = asyncio.get_event_loop()
        self._aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        self._alsa = AlsaSeq("NetworkMIDI", default_ports=False)
        self._loop.add_reader(self._alsa.fileno(), self._on_alsa_readable)
        self._started = True
        await self.resync_exports()
        # Browse for other hubs' (and foreign) RTP-MIDI sessions. The
        # handler may fire on zeroconf's own thread — marshal onto the
        # loop unconditionally; call_soon_threadsafe is loop-thread-safe
        # in both directions.
        self._browser = AsyncServiceBrowser(
            self._aiozc.zeroconf, SERVICE_TYPE,
            handlers=[self._on_service_state])
        self._housekeeping_task = self._loop.create_task(self._housekeeping())
        self._manual_peers_task = self._loop.create_task(
            self._poll_manual_peers())
        self._link_watch_task = self._loop.create_task(self._watch_links())
        log.info("network-midi: up (hub id %s)", self.hub_id)

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        for task in (self._housekeeping_task, self._manual_peers_task,
                     self._link_watch_task, *self._reconnect_tasks.values()):
            if task:
                task.cancel()
        self._housekeeping_task = self._manual_peers_task = None
        self._link_watch_task = None
        self._reconnect_tasks.clear()
        if self._browser:
            try:
                await self._browser.async_cancel()
            except Exception:
                pass
            self._browser = None
        for mirror in list(self._mirrors.values()):
            await mirror.stop()
        self._mirrors.clear()
        self._discovered.clear()
        for sess in list(self._exports.values()):
            await sess.stop()
        self._exports.clear()
        if self._alsa:
            try:
                asyncio.get_event_loop().remove_reader(self._alsa.fileno())
            except (OSError, ValueError):
                pass
            self._alsa.close()
            self._alsa = None
        if self._aiozc:
            await self._aiozc.async_close()
            self._aiozc = None
        log.info("network-midi: down")

    async def set_enabled(self, enabled: bool) -> None:
        """Flip the master switch (config mutation + asave is the API
        handler's job, same split as the WiFi endpoints)."""
        if enabled:
            # Direct-cable story: make sure eth0 self-assigns a
            # 169.254.x.x when no DHCP answers (blocking nmcli work,
            # off-loop).
            from .wifi import ensure_eth_link_local
            await asyncio.to_thread(ensure_eth_link_local)
            await self.start()
        else:
            await self.stop()
        self.notify_changed()

    async def set_export(self, stable_id: str, exported: bool) -> None:
        """Create/destroy the session for one device. The config list
        is mutated by the API handler; this manages live state only."""
        if exported and self._started and stable_id not in self._exports:
            device = self._device_for(stable_id)
            if device is None:
                return  # offline: resync_exports picks it up on hotplug
            await self._create_session(stable_id, device)
        elif not exported and stable_id in self._exports:
            await self._exports.pop(stable_id).stop()
        self.notify_changed()

    async def resync_exports(self) -> None:
        """Reconcile live sessions against config + device presence:
        called at start and (phase 4) on every hotplug change."""
        if not self._started:
            return
        wanted = set(self.settings.get("exported", []))
        for stable_id in list(self._exports):
            if stable_id not in wanted or self._device_for(stable_id) is None:
                # Unexported, or device unplugged — a session with no
                # device behind it is a lie; take it off the network.
                await self._exports.pop(stable_id).stop()
                self.notify_changed()
        for stable_id in wanted - set(self._exports):
            device = self._device_for(stable_id)
            if device is not None:
                await self._create_session(stable_id, device)
                self.notify_changed()

    async def _create_session(self, stable_id: str, device) -> None:
        info = self._engine.device_registry.get_by_stable_id(stable_id)
        name = (info.name if info else None) or device.name
        sess = ExportedSession(self, stable_id, name)
        try:
            await sess.start(device)
        except Exception:
            log.exception("network-midi: export of %s failed", stable_id)
            return
        self._exports[stable_id] = sess

    def _device_for(self, stable_id: str):
        client_id = self._engine.device_registry.client_for_stable_id(stable_id)
        if client_id is None:
            return None
        for dev in self._engine.devices:
            if dev.client_id == client_id:
                return dev
        return None

    # --- zeroconf ---

    async def register_service(self, sess: ExportedSession) -> None:
        if not self._aiozc:
            return
        from zeroconf import ServiceInfo
        addresses = [socket.inet_aton(a) for a in await self._local_addresses()]
        sess._service_info = ServiceInfo(
            SERVICE_TYPE,
            f"{sess.service_name}.{SERVICE_TYPE}",
            port=sess.control_port,
            addresses=addresses,
            # SRV target = the hub's real mDNS hostname. Without it,
            # python-zeroconf defaults the SRV host to the *instance
            # name*, which avahi-based resolvers (rtpmidid, most Linux
            # clients) fail to resolve — they time out and never
            # connect. avahi-daemon on the hub answers A queries for
            # this name per-interface, so clients also get an address
            # that is actually reachable from where they ask.
            server=f"{self.hostname}.local.",
            properties={"rmh": "1", "hub": self.hub_id,
                        "sid": sess.stable_id, "host": self.hostname,
                        "dev": sess.device_name},
        )
        await self._aiozc.async_register_service(sess._service_info)

    async def unregister_service(self, sess: ExportedSession) -> None:
        if self._aiozc and sess._service_info:
            try:
                await self._aiozc.async_unregister_service(sess._service_info)
            except Exception:
                log.warning("network-midi: mDNS unregister failed", exc_info=True)
        sess._service_info = None

    async def _local_addresses(self) -> list[str]:
        """All local IPv4 addresses worth advertising. Shells out via
        wifi.get_all_interfaces (blocking) — off-loop."""
        from .wifi import get_all_interfaces
        infos = await asyncio.to_thread(get_all_interfaces)
        return [i["address"] for i in infos if i.get("address")]

    # --- link watcher (re-bind mDNS when an interface comes up late) ---

    async def _watch_links(self) -> None:
        """Re-bind the mDNS stack whenever the set of local IPv4
        addresses changes. zeroconf joins the multicast group only on
        the interfaces present when AsyncZeroconf was built, so an eth0
        brought up after start (a hub-to-hub cable plugged in later)
        would otherwise stay mDNS-dark until a manual toggle. Manual
        peers ride plain unicast and are unaffected — this closes the
        mDNS-only gap."""
        try:
            prev = set(await self._local_addresses())
        except Exception:
            prev = set()
        while self._started:
            await asyncio.sleep(LINK_WATCH_INTERVAL)
            prev = await self._check_links(prev)

    async def _check_links(self, prev: set[str]) -> set[str]:
        """One address-set comparison. Returns the set to compare
        against next time. Re-binds mDNS when a non-empty set differs
        from the last one. An empty reading (every link momentarily
        down) is ignored — we keep `prev` so the address's return is
        seen as a change and triggers a re-bind then."""
        try:
            cur = set(await self._local_addresses())
        except Exception:
            return prev
        if not cur:
            return prev
        if cur != prev:
            log.info("network-midi: local addresses changed %s -> %s; "
                     "re-binding mDNS", sorted(prev), sorted(cur))
            await self._rebind_mdns()
        return cur

    async def _rebind_mdns(self) -> None:
        """Recreate the zeroconf instance + browser so it re-enumerates
        interfaces (joining the multicast group on any newly-up link),
        then re-advertise every live export with the current addresses.
        RTP sessions, mirrors, ALSA and participants keep running — only
        the mDNS sockets are recycled. The fresh browser re-discovers
        peers (Added/Updated refresh `_discovered`; `_apply_mirror_policy`
        is idempotent, so live mirrors are not doubled)."""
        if not self._started:
            return
        from zeroconf import IPVersion
        from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf
        if self._browser:
            try:
                await self._browser.async_cancel()
            except Exception:
                pass
            self._browser = None
        if self._aiozc:
            try:
                await self._aiozc.async_close()
            except Exception:
                pass
            self._aiozc = None
        self._aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        for sess in self._exports.values():
            sess._service_info = None
            try:
                await self.register_service(sess)
            except Exception:
                log.warning("network-midi: re-advertise of %s failed",
                            sess.service_name, exc_info=True)
        self._browser = AsyncServiceBrowser(
            self._aiozc.zeroconf, SERVICE_TYPE,
            handlers=[self._on_service_state])
        log.info("network-midi: mDNS re-bound on %d interface address(es)",
                 len(await self._local_addresses()))

    # --- ALSA → network dispatch ---

    def _on_alsa_readable(self) -> None:
        """Drain the shared client: events landing on a session's tx
        port are the exported device's output — encode + fan out."""
        by_tx = {s.tx_port: s for s in self._exports.values()}
        while True:
            ev = self._alsa.read_event() if self._alsa else None
            if ev is None:
                return
            sess = by_tx.get(ev.dest.port)
            if sess is None:
                continue
            from .alsa_seq import MidiEventType
            midi = event_to_midi(ev)
            if midi is None:
                continue
            sess.send_midi(midi, is_sysex_chunk=ev.type == MidiEventType.SYSEX)

    def output_event(self, ev, source_port: int) -> None:
        """Network → ALSA: emit `ev` from `source_port` to subscribers
        (the kernel subscription delivers it to the exported device)."""
        if self._alsa:
            _output_event(self._alsa, ev, source_port)

    # --- discovery / mirroring ---

    def _on_service_state(self, zeroconf, service_type, name, state_change):
        """zeroconf browser callback — may fire on zeroconf's thread;
        marshal onto the loop (call_soon_threadsafe is safe from the
        loop thread too)."""
        if self._loop is None:
            return
        change = getattr(state_change, "name", str(state_change))
        if change in ("Added", "Updated"):
            self._loop.call_soon_threadsafe(
                lambda: self._loop.create_task(self._service_added(name)))
        elif change == "Removed":
            self._loop.call_soon_threadsafe(
                lambda: self._loop.create_task(self._service_removed(name)))

    async def _service_added(self, name: str) -> None:
        if not self._started or not self._aiozc:
            return
        info = await self._aiozc.async_get_service_info(SERVICE_TYPE, name,
                                                        3000)
        if info is None or info.port is None:
            return
        txt = {}
        for k, v in (info.properties or {}).items():
            if v is None:
                continue
            key = k.decode() if isinstance(k, bytes) else k
            txt[key] = v.decode() if isinstance(v, bytes) else v
        svc = DiscoveredService(
            service=name,
            instance=name.removesuffix("." + SERVICE_TYPE),
            host=(info.server or "").rstrip("."),
            addresses=list(info.parsed_addresses()),
            port=info.port,
            txt=txt,
        )
        if svc.hub == self.hub_id:
            return  # our own advert echoing back
        if svc.sid.startswith("net-"):
            return  # a hub erroneously exporting a mirror — never chain
        self._discovered[name] = svc
        await self._apply_mirror_policy(svc)
        self.notify_changed()

    async def _service_removed(self, name: str) -> None:
        self._discovered.pop(name, None)
        mirror = self._mirrors.pop(name, None)
        if mirror:
            await mirror.stop(send_bye=False)
        self.notify_changed()

    async def _apply_mirror_policy(self, svc: DiscoveredService) -> None:
        """Hub sessions auto-mirror (the export list over there is the
        deliberate share); foreign sessions (Macs, DAWs) only when the
        user added them — a Mac's advert is not an invitation, and a
        studio WLAN full of DAWs must not flood the matrix."""
        if svc.service in self._mirrors:
            return
        if svc.is_hub:
            want = (bool(svc.sid)
                    and svc.service not in
                    self.settings.get("mirror_disabled", []))
        else:
            want = svc.service in self.settings.get("mirrored_foreign", [])
        if not want or not svc.addresses:
            return
        mirror = MirroredSession(self, svc)
        try:
            await mirror.start()
        except Exception as e:
            log.warning("network-midi: mirroring '%s' failed: %s",
                        svc.instance, e)
            return
        self._mirrors[svc.service] = mirror

    async def set_mirrored(self, service: str, mirrored: bool) -> None:
        """Apply a mirror/unmirror decision (config lists are mutated
        by the API handler, same split as exports)."""
        if mirrored:
            svc = self._discovered.get(service)
            if svc:
                await self._apply_mirror_policy(svc)
        else:
            mirror = self._mirrors.pop(service, None)
            if mirror:
                await mirror.stop()
        self.notify_changed()

    async def on_mirror_lost(self, mirror) -> None:
        """Peer sent BY, or went silent past the CK timeout: drop the
        live session (matrix shows the device offline, saved
        connections stay pending) and retry with backoff while the
        service is still listed — mDNS `remove_service` is what
        finally stops the retries."""
        if self._mirrors.get(mirror.svc.service) is mirror:
            self._mirrors.pop(mirror.svc.service)
        await mirror.stop(send_bye=False)
        self._schedule_reconnect(mirror.svc.service)
        self.notify_changed()

    def _schedule_reconnect(self, service: str) -> None:
        if not self._started or service in self._reconnect_tasks:
            return

        async def reconnect():
            delay = RECONNECT_DELAY
            try:
                while self._started:
                    await asyncio.sleep(delay)
                    if (service not in self._discovered
                            or service in self._mirrors):
                        return
                    await self._apply_mirror_policy(self._discovered[service])
                    if service in self._mirrors:
                        self.notify_changed()
                        return
                    delay = min(delay * 2, RECONNECT_DELAY_MAX)
            finally:
                self._reconnect_tasks.pop(service, None)

        self._reconnect_tasks[service] = self._loop.create_task(reconnect())

    # --- housekeeping (reaper + receiver feedback) ---

    async def _housekeeping(self) -> None:
        while self._started:
            await asyncio.sleep(HOUSEKEEPING_INTERVAL)
            self._housekeep_once(time.monotonic())

    def _housekeep_once(self, now: float) -> None:
        """Per-export upkeep: reap participants that went silent (a
        vanished Mac sends no BY) and send RS receiver feedback so
        journal-keeping senders can trim their journals (we send no
        journal ourselves; RS is cheap good citizenship)."""
        for sess in self._exports.values():
            for ssrc, part in list(sess.participants.items()):
                if now - part.last_rx > PARTICIPANT_TIMEOUT:
                    log.info("network-midi: reaping silent "
                             "participant '%s' from %s",
                             part.name, sess.service_name)
                    del sess.participants[ssrc]
                    self.notify_changed()
                elif (part.data_addr and part.last_seq
                      and sess._data_transport):
                    sess._data_transport.sendto(
                        apple_midi.build_feedback(sess.ssrc,
                                                  part.last_seq),
                        part.data_addr)

    # --- manual peers (no-mDNS fallback) ---

    async def _poll_manual_peers(self) -> None:
        """Reach configured peers over plain HTTP: a routed LAN can
        swallow multicast, but the peer's own status endpoint lists
        its exports with everything mDNS would have told us. Entries
        synthesized here flow through the same mirror policy; an
        mDNS-discovered duplicate simply overwrites (same service
        key), so dual-path discovery stays consistent."""
        while self._started:
            for host in list(self.settings.get("manual_peers", [])):
                try:
                    status = await asyncio.to_thread(
                        self._fetch_peer_status, host)
                except Exception as e:
                    log.debug("network-midi: peer %s unreachable: %s",
                              host, e)
                    status = None
                await self._integrate_peer_status(host, status)
            await asyncio.sleep(MANUAL_PEER_INTERVAL)

    @staticmethod
    def _fetch_peer_status(host: str) -> dict:
        import json
        import urllib.request
        addr = socket.gethostbyname(host)
        with urllib.request.urlopen(
                f"http://{host}/api/network-midi", timeout=5) as resp:
            status = json.loads(resp.read())
        status["_addr"] = addr
        return status

    async def _integrate_peer_status(self, host: str,
                                     status: dict | None) -> None:
        fresh: set[str] = set()
        if status and status.get("available") and \
                status.get("hub_id") != self.hub_id:
            for export in status.get("exports", []):
                name = export.get("name") or ""
                if not name or not export.get("port"):
                    continue
                service = f"{name}.{SERVICE_TYPE}"
                fresh.add(service)
                if service in self._discovered and \
                        self._discovered[service].via_manual is None:
                    continue  # mDNS path owns this entry
                svc = DiscoveredService(
                    service=service,
                    instance=name,
                    host=status.get("hostname", host),
                    addresses=[status["_addr"]],
                    port=export["port"],
                    txt={"rmh": "1", "hub": status.get("hub_id", ""),
                         "sid": export.get("stable_id", ""),
                         "host": status.get("hostname", host),
                         "dev": name.rsplit(" @", 1)[0]},
                    via_manual=host,
                )
                if svc.sid.startswith("net-"):
                    continue  # never chain mirrors
                known = service in self._discovered
                self._discovered[service] = svc
                await self._apply_mirror_policy(svc)
                if not known:
                    self.notify_changed()
        # Retract this peer's stale entries (export gone or peer down);
        # entries the mDNS browser owns are left to its TTL handling.
        for service, svc in list(self._discovered.items()):
            if svc.via_manual == host and service not in fresh:
                await self._service_removed(service)

    def unregister_mirror_device(self, stable_id: str) -> None:
        self._engine.device_registry.unregister_network_device(stable_id)

    def service_for(self, key: str):
        """Resolve a service by mDNS name or mirrored stable_id —
        the API accepts either (Settings rows carry the service name,
        matrix header menus carry the stable id)."""
        if key in self._discovered:
            return self._discovered[key]
        for svc in self._discovered.values():
            if svc.stable_id == key:
                return svc
        return None

    def get_mirror_client_ids(self) -> set[int]:
        return {m.alsa_client_id for m in self._mirrors.values()
                if m.alsa_client_id is not None}

    def get_mirrors(self) -> list:
        return [m for m in self._mirrors.values()
                if m.alsa_client_id is not None]

    def hub_name_for_stable_id(self, stable_id: str) -> str:
        """Best-effort group label for an offline mirrored device:
        the peer's hostname while it is discovered, else the hub-id
        segment of the stable id (`net-<hub>-…`)."""
        parts = stable_id.split("-", 2)
        hub = parts[1] if len(parts) > 2 else ""
        for svc in self._discovered.values():
            if svc.hub == hub:
                return svc.remote_hub
        return hub or "offline hub"

    # --- status / SSE ---

    def record_latency(self, name: str, ms: float) -> None:
        """Feed the Sys Info latency stats (worst-case per second).
        Keeps the thread-a-session escalation decision data-driven:
        if this number ever grows under load, move the bridging off
        the main loop — measure first (module docstring)."""
        if self._server is not None:
            self._server.record_latency(name, ms)

    def notify_changed(self) -> None:
        """Debounced `network-midi-changed` SSE — the Settings page
        re-fetches GET /api/network-midi on any of them."""
        if self._notify_task and not self._notify_task.done():
            return
        async def _send():
            await asyncio.sleep(0.5)
            await self._server.send_sse("network-midi-changed", {})
        try:
            self._notify_task = asyncio.get_event_loop().create_task(_send())
        except RuntimeError:
            pass  # no loop (tests constructing the manager standalone)

    def status(self) -> dict:
        hubs: dict[str, dict] = {}
        foreign: list[dict] = []
        for svc in self._discovered.values():
            mirror = self._mirrors.get(svc.service)
            entry = {
                "service": svc.service,
                "stable_id": svc.stable_id,
                "name": svc.device_name,
                "addr": svc.addresses[0] if svc.addresses else None,
                "port": svc.port,
                "mirrored": mirror is not None,
                "state": mirror.state if mirror else "discovered",
                "latency_ms": mirror.latency_ms if mirror else None,
            }
            if svc.is_hub:
                hub = hubs.setdefault(svc.hub, {
                    "hub": svc.hub, "host": svc.remote_hub, "sessions": []})
                hub["sessions"].append(entry)
            else:
                foreign.append(entry)
        for hub in hubs.values():
            hub["sessions"].sort(key=lambda s: s["name"].lower())
        return {
            "available": True,
            "enabled": bool(self.settings.get("enabled")),
            "running": self._started,
            "hostname": self.hostname,
            "hub_id": self.hub_id,
            "exported": list(self.settings.get("exported", [])),
            "exports": [s.status() for s in self._exports.values()],
            "hubs": sorted(hubs.values(), key=lambda h: h["host"].lower()),
            "foreign": sorted(foreign, key=lambda s: s["name"].lower()),
            "manual_peers": list(self.settings.get("manual_peers", [])),
        }
