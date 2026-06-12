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


class _UdpShim(asyncio.DatagramProtocol):
    """Minimal DatagramProtocol that forwards datagrams to a callback."""

    def __init__(self, on_datagram):
        self._on_datagram = on_datagram

    def datagram_received(self, data, addr):
        try:
            self._on_datagram(data, addr)
        except Exception:
            log.exception("network-midi: datagram handler failed")


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
        self._tx_sysex_open = False
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

            # Even/odd UDP port pair; probe upward from the base.
            base = BASE_PORT
            last_err = None
            for port in range(base, base + PORT_RANGE, 2):
                try:
                    ctrl, _ = await loop.create_datagram_endpoint(
                        lambda: _UdpShim(self.on_control),
                        local_addr=("0.0.0.0", port))
                except OSError as e:
                    last_err = e
                    continue
                try:
                    data, _ = await loop.create_datagram_endpoint(
                        lambda: _UdpShim(self.on_data),
                        local_addr=("0.0.0.0", port + 1))
                except OSError as e:
                    ctrl.close()
                    last_err = e
                    continue
                self.control_port = port
                self._control_transport = ctrl
                self._data_transport = data
                break
            if self.control_port < 0:
                raise OSError(f"no free UDP port pair: {last_err}")

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
        part.last_rx = time.monotonic()
        part.last_seq = rtp.seq
        for cmd in rtp.commands:
            if cmd and cmd[0] in (0xF0, 0xF7):
                complete = part.sysex_rx.feed(cmd)
                if complete:
                    self._inject(complete)
            else:
                self._inject(cmd)

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
        segments = (self._frame_sysex_chunk(midi) if is_sysex_chunk
                    else [midi])
        for seg in segments:
            self._seqnum = (self._seqnum + 1) & 0xFFFF
            pkt = apple_midi.build_rtp_midi(self._seqnum, now_ts(),
                                            self.ssrc, seg)
            for part in self.participants.values():
                if part.data_addr:
                    self._data_transport.sendto(pkt, part.data_addr)

    def _frame_sysex_chunk(self, chunk: bytes) -> list[bytes]:
        """Frame a raw ALSA SysEx chunk as RFC 6295 segment(s). ALSA
        delivers large dumps as a series of SYSEX events whose payloads
        concatenate to F0 … F7; segment framing maps onto that stream
        directly (F0/F7 opener, F0 = to-be-continued, F7 = final), so
        chunks go on the wire as they arrive — no buffering the dump.
        Chunks are device/driver-sized (typically ≤ 256 B), well under
        MTU; a complete-in-one chunk still gets split when oversized."""
        if not chunk:
            return []
        if not self._tx_sysex_open:
            if chunk[0] != 0xF0:
                return []  # mid-stream chunk with no start seen — drop
            if chunk[-1] == 0xF7:
                return apple_midi.sysex_segments(chunk)
            self._tx_sysex_open = True
            return [chunk + b"\xf0"]
        if chunk[-1] == 0xF7:
            self._tx_sysex_open = False
            return [b"\xf7" + chunk]
        return [b"\xf7" + chunk + b"\xf0"]

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


class NetworkMidiManager:
    """Owns the export list, the shared ALSA client, zeroconf
    registration and (phase 3) discovery/mirroring."""

    def __init__(self, engine, config, server):
        self._engine = engine
        self._config = config
        self._server = server
        self._exports: dict[str, ExportedSession] = {}
        self._alsa = None              # shared hidden client, created on start
        self._aiozc = None             # AsyncZeroconf while running
        self._started = False
        self._notify_task = None
        self.hub_id = hub_id()

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
        from zeroconf.asyncio import AsyncZeroconf

        from .alsa_seq import AlsaSeq

        self._aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        self._alsa = AlsaSeq("NetworkMIDI", default_ports=False)
        asyncio.get_event_loop().add_reader(
            self._alsa.fileno(), self._on_alsa_readable)
        self._started = True
        await self.resync_exports()
        log.info("network-midi: up (hub id %s)", self.hub_id)

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
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
            properties={"rmh": "1", "hub": self.hub_id,
                        "sid": sess.stable_id},
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
        if not self._alsa:
            return
        from ctypes import pointer

        from .alsa_seq import (
            SND_SEQ_ADDRESS_SUBSCRIBERS,
            SND_SEQ_QUEUE_DIRECT,
            snd_seq_event_output_direct,
        )
        ev.source.client = self._alsa.client_id
        ev.source.port = source_port
        ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
        ev.dest.port = 0
        ev.queue = SND_SEQ_QUEUE_DIRECT
        try:
            snd_seq_event_output_direct(self._alsa.handle, pointer(ev))
        except Exception as e:
            log.debug("network-midi: ALSA inject failed: %s", e)

    # --- status / SSE ---

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
        return {
            "available": True,
            "enabled": bool(self.settings.get("enabled")),
            "running": self._started,
            "hostname": self.hostname,
            "hub_id": self.hub_id,
            "exported": list(self.settings.get("exported", [])),
            "exports": [s.status() for s in self._exports.values()],
        }
