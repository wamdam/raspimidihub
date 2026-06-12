"""Tests for the network MIDI manager / exported + mirrored sessions.

Protocol state machines are driven through fake transports — no
sockets, no zeroconf (mocked at the manager boundary, same style as
test_wifi / test_usb_tether)."""

import asyncio

from raspimidihub import apple_midi, network_midi
from raspimidihub.alsa_seq import MidiEventType
from raspimidihub.network_midi import (
    DiscoveredService,
    ExportedSession,
    MirroredSession,
)


class FakeTransport:
    def __init__(self):
        self.sent = []  # (data, addr)

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def close(self):
        pass


class StubManager:
    hostname = "testhub"
    hub_id = "abc123def456"

    def __init__(self):
        self.injected = []   # (ev, source_port)
        self.notified = 0
        self.alsa = None

    def output_event(self, ev, source_port):
        self.injected.append((ev, source_port))

    def notify_changed(self):
        self.notified += 1

    def record_latency(self, name, ms):
        pass


CTRL_ADDR = ("192.0.2.10", 50000)
DATA_ADDR = ("192.0.2.10", 50001)


def make_session():
    mgr = StubManager()
    sess = ExportedSession(mgr, "usb-1-2-aaaa:bbbb", "TX-7")
    sess._control_transport = FakeTransport()
    sess._data_transport = FakeTransport()
    return mgr, sess


def join(sess, ssrc=0x1111, name="peer"):
    """Run the two-phase handshake as the remote initiator."""
    sess.on_control(
        apple_midi.build_exchange(apple_midi.CMD_INVITATION, 7, ssrc, name),
        CTRL_ADDR)
    sess.on_data(
        apple_midi.build_exchange(apple_midi.CMD_INVITATION, 7, ssrc, name),
        DATA_ADDR)
    return sess.participants[ssrc]


class TestResponderHandshake:
    def test_two_phase_invitation(self):
        mgr, sess = make_session()
        sess.on_control(
            apple_midi.build_exchange(apple_midi.CMD_INVITATION, 7, 0x1111, "mac"),
            CTRL_ADDR)
        # OK on the control port, echoing the initiator token
        ok = apple_midi.parse_command(sess._control_transport.sent[0][0])
        assert ok.command == apple_midi.CMD_ACCEPT
        assert ok.initiator_token == 7
        assert ok.ssrc == sess.ssrc
        assert ok.name == "TX-7 @testhub"
        part = sess.participants[0x1111]
        assert not part.connected  # data-port leg still missing

        sess.on_data(
            apple_midi.build_exchange(apple_midi.CMD_INVITATION, 7, 0x1111, "mac"),
            DATA_ADDR)
        ok2 = apple_midi.parse_command(sess._data_transport.sent[0][0])
        assert ok2.command == apple_midi.CMD_ACCEPT
        assert part.connected
        assert part.data_addr == DATA_ADDR

    def test_multiple_participants(self):
        mgr, sess = make_session()
        join(sess, ssrc=0x1111, name="mac")
        join(sess, ssrc=0x2222, name="hub2")
        assert len(sess.participants) == 2
        assert all(p.connected for p in sess.participants.values())

    def test_bye_removes_participant(self):
        mgr, sess = make_session()
        join(sess, ssrc=0x1111)
        sess.on_control(
            apple_midi.build_exchange(apple_midi.CMD_BYE, 0, 0x1111),
            CTRL_ADDR)
        assert 0x1111 not in sess.participants

    def test_clock_sync_answered(self):
        mgr, sess = make_session()
        part = join(sess)
        n_sent = len(sess._data_transport.sent)
        sess.on_data(apple_midi.build_clock_sync(part.ssrc, 0, 12345), DATA_ADDR)
        reply = apple_midi.parse_command(sess._data_transport.sent[n_sent][0])
        assert isinstance(reply, apple_midi.ClockSync)
        assert reply.count == 1
        assert reply.ts1 == 12345
        assert reply.ts2 > 0


class TestReceivePath:
    def test_rtp_note_injected(self):
        mgr, sess = make_session()
        part = join(sess)
        pkt = apple_midi.build_rtp_midi(1, 0, part.ssrc, bytes([0x90, 60, 100]))
        sess.on_data(pkt, DATA_ADDR)
        assert len(mgr.injected) == 1
        ev, port = mgr.injected[0]
        assert ev.type == MidiEventType.NOTEON
        assert port == sess.rx_port

    def test_uninvited_ssrc_ignored(self):
        mgr, sess = make_session()
        join(sess, ssrc=0x1111)
        pkt = apple_midi.build_rtp_midi(1, 0, 0x9999, bytes([0x90, 60, 100]))
        sess.on_data(pkt, DATA_ADDR)
        assert mgr.injected == []

    def test_fragmented_sysex_assembled(self):
        mgr, sess = make_session()
        part = join(sess)
        body = bytes(i & 0x7F for i in range(3000))
        msg = bytes([0xF0]) + body + bytes([0xF7])
        for i, seg in enumerate(apple_midi.sysex_segments(msg, max_segment=1400)):
            sess.on_data(
                apple_midi.build_rtp_midi(i, 0, part.ssrc, seg), DATA_ADDR)
        assert len(mgr.injected) == 1
        ev, _ = mgr.injected[0]
        assert ev.type == MidiEventType.SYSEX
        assert ev.data.ext.len == len(msg)


class TestSendPath:
    def test_fanout_to_connected_only(self):
        mgr, sess = make_session()
        join(sess, ssrc=0x1111)
        join(sess, ssrc=0x2222)
        # A third participant that never completed the data-port leg
        sess.on_control(
            apple_midi.build_exchange(apple_midi.CMD_INVITATION, 9, 0x3333),
            ("192.0.2.99", 4))
        sess._data_transport.sent.clear()
        sess.send_midi(bytes([0xB0, 7, 100]))
        assert len(sess._data_transport.sent) == 2
        rtp = apple_midi.parse_rtp_midi(sess._data_transport.sent[0][0])
        assert rtp.commands == [bytes([0xB0, 7, 100])]
        assert rtp.ssrc == sess.ssrc

    def test_seqnum_increments(self):
        mgr, sess = make_session()
        join(sess)
        sess._data_transport.sent.clear()
        sess.send_midi(b"\xf8")
        sess.send_midi(b"\xf8")
        seqs = [apple_midi.parse_rtp_midi(d).seq
                for d, _ in sess._data_transport.sent]
        assert (seqs[0] + 1) & 0xFFFF == seqs[1]


class TestSysExChunkFraming:
    """ALSA delivers big SysEx dumps as a chunk series; each chunk goes
    on the wire as one RFC 6295 segment without buffering the dump."""

    def test_complete_in_one_chunk(self):
        _, sess = make_session()
        msg = bytes([0xF0, 1, 2, 0xF7])
        assert sess._frame_sysex_chunk(msg) == [msg]

    def test_chunked_stream(self):
        _, sess = make_session()
        first = sess._frame_sysex_chunk(bytes([0xF0, 1, 2]))
        middle = sess._frame_sysex_chunk(bytes([3, 4]))
        last = sess._frame_sysex_chunk(bytes([5, 0xF7]))
        assert first == [bytes([0xF0, 1, 2, 0xF0])]
        assert middle == [bytes([0xF7, 3, 4, 0xF0])]
        assert last == [bytes([0xF7, 5, 0xF7])]
        # And the receiving side reassembles them into the original
        asm = apple_midi.SysExAssembler()
        out = None
        for seg in first + middle + last:
            out = asm.feed(seg)
        assert out == bytes([0xF0, 1, 2, 3, 4, 5, 0xF7])

    def test_midstream_chunk_without_start_dropped(self):
        _, sess = make_session()
        assert sess._frame_sysex_chunk(bytes([3, 4])) == []


def make_discovered(rmh="1", hub="feedface0001", sid="usb-1-2-a:b",
                    name="TX-7 @hub2", host="hub2"):
    txt = {}
    if rmh:
        txt = {"rmh": rmh, "hub": hub, "sid": sid, "host": host,
               "dev": name.rsplit(" @", 1)[0]}
    return DiscoveredService(
        service=f"{name}._apple-midi._udp.local.",
        instance=name,
        host=f"{host}.local",
        addresses=["192.0.2.20"],
        port=5004,
        txt=txt,
    )


class TestDiscoveredService:
    def test_hub_session_identity(self):
        svc = make_discovered()
        assert svc.is_hub
        assert svc.stable_id == "net-feedface0001-usb-1-2-a:b"
        assert svc.device_name == "TX-7"
        assert svc.remote_hub == "hub2"

    def test_foreign_session_identity(self):
        svc = make_discovered(rmh="")
        assert not svc.is_hub
        assert svc.stable_id.startswith("net-")
        assert "feedface" not in svc.stable_id
        # Falls back to parsing the instance name
        assert svc.device_name == "TX-7"

    def test_foreign_without_at_suffix(self):
        svc = DiscoveredService(
            service="MacBook._apple-midi._udp.local.",
            instance="MacBook", host="mac.local",
            addresses=["192.0.2.30"], port=5004, txt={})
        assert svc.device_name == "MacBook"
        assert svc.remote_hub == "mac.local"


class FakeAlsa:
    client_id = 142
    handle = None

    def fileno(self):
        return -1

    def close(self):
        pass


def make_mirror():
    mgr = StubManager()
    mgr.lost = []

    async def on_mirror_lost(m):
        mgr.lost.append(m)
    mgr.on_mirror_lost = on_mirror_lost
    mgr.unregister_mirror_device = lambda sid: None
    mirror = MirroredSession(mgr, make_discovered())
    mirror._ctrl_transport = FakeTransport()
    mirror._data_transport = FakeTransport()
    return mgr, mirror


class TestMirroredSession:
    def test_ok_resolves_handshake_future(self):
        async def run():
            _, mirror = make_mirror()
            mirror._ok_future = asyncio.get_event_loop().create_future()
            mirror.on_control(
                apple_midi.build_exchange(
                    apple_midi.CMD_ACCEPT, mirror._token, 0xAAAA, "TX-7 @hub2"),
                ("192.0.2.20", 5004))
            ok = await asyncio.wait_for(mirror._ok_future, 1)
            assert ok.ssrc == 0xAAAA
            assert mirror._remote_ssrc == 0xAAAA
        asyncio.run(run())

    def test_reject_fails_handshake(self):
        async def run():
            _, mirror = make_mirror()
            mirror._ok_future = asyncio.get_event_loop().create_future()
            mirror.on_control(
                apple_midi.build_exchange(
                    apple_midi.CMD_REJECT, mirror._token, 0xAAAA),
                ("192.0.2.20", 5004))
            try:
                await asyncio.wait_for(mirror._ok_future, 1)
                raise AssertionError("expected rejection")
            except ConnectionRefusedError:
                pass
        asyncio.run(run())

    def test_ck1_reply_closes_round_and_takes_latency(self):
        _, mirror = make_mirror()
        ts1 = network_midi.now_ts()  # "we sent CK0 just now"
        mirror._ck_ts1 = ts1
        mirror.on_data(
            apple_midi.build_clock_sync(0xAAAA, 1, ts1, ts1 + 10),
            ("192.0.2.20", 5005))
        ck2 = apple_midi.parse_command(mirror._data_transport.sent[-1][0])
        assert ck2.count == 2
        assert ck2.ts1 == ts1
        assert mirror.latency_ms is not None and mirror.latency_ms >= 0

    def test_peer_initiated_ck0_answered(self):
        _, mirror = make_mirror()
        mirror.on_data(
            apple_midi.build_clock_sync(0xAAAA, 0, 555),
            ("192.0.2.20", 5005))
        ck1 = apple_midi.parse_command(mirror._data_transport.sent[-1][0])
        assert ck1.count == 1
        assert ck1.ts1 == 555

    def test_rtp_injected_through_own_client(self, monkeypatch):
        _, mirror = make_mirror()
        mirror._alsa = FakeAlsa()
        mirror._out_port = 0
        mirror._remote_ssrc = 0xAAAA
        injected = []
        monkeypatch.setattr(network_midi, "_output_event",
                            lambda alsa, ev, port: injected.append((ev, port)))
        mirror.on_data(
            apple_midi.build_rtp_midi(1, 0, 0xAAAA, bytes([0x90, 60, 100])),
            ("192.0.2.20", 5005))
        assert len(injected) == 1
        assert injected[0][0].type == MidiEventType.NOTEON

    def test_bye_reports_lost(self):
        async def run():
            mgr, mirror = make_mirror()
            mirror.on_control(
                apple_midi.build_exchange(apple_midi.CMD_BYE, 0, 0xAAAA),
                ("192.0.2.20", 5004))
            await asyncio.sleep(0)  # let ensure_future run
            assert mgr.lost == [mirror]
        asyncio.run(run())


class TestMirrorPolicy:
    def make_manager(self, settings, monkeypatch):
        from raspimidihub.network_midi import NetworkMidiManager

        started = []

        class FakeMirror:
            def __init__(self, manager, svc):
                self.svc = svc
                self.alsa_client_id = 99
                self.stable_id = svc.stable_id
                self.state = "connected"
                self.latency_ms = None

            async def start(self):
                started.append(self.svc.service)

            async def stop(self, send_bye=True):
                pass

        monkeypatch.setattr(network_midi, "MirroredSession", FakeMirror)

        class FakeConfig:
            data = {"network_midi": {"enabled": True, "exported": [],
                                     **settings}}

        mgr = NetworkMidiManager(engine=None, config=FakeConfig(),
                                 server=None)
        return mgr, started

    def test_hub_session_auto_mirrors(self, monkeypatch):
        mgr, started = self.make_manager({}, monkeypatch)
        svc = make_discovered()
        asyncio.run(mgr._apply_mirror_policy(svc))
        assert started == [svc.service]
        assert svc.service in mgr._mirrors

    def test_opt_out_respected(self, monkeypatch):
        svc = make_discovered()
        mgr, started = self.make_manager(
            {"mirror_disabled": [svc.service]}, monkeypatch)
        asyncio.run(mgr._apply_mirror_policy(svc))
        assert started == []

    def test_foreign_not_auto_mirrored(self, monkeypatch):
        mgr, started = self.make_manager({}, monkeypatch)
        svc = make_discovered(rmh="")
        asyncio.run(mgr._apply_mirror_policy(svc))
        assert started == []

    def test_foreign_mirrors_when_added(self, monkeypatch):
        svc = make_discovered(rmh="")
        mgr, started = self.make_manager(
            {"mirrored_foreign": [svc.service]}, monkeypatch)
        asyncio.run(mgr._apply_mirror_policy(svc))
        assert started == [svc.service]

    def test_hub_session_without_sid_skipped(self, monkeypatch):
        mgr, started = self.make_manager({}, monkeypatch)
        svc = make_discovered(sid="")
        asyncio.run(mgr._apply_mirror_policy(svc))
        assert started == []


class TestLifecycle:
    def test_ck_timeout_drops_mirror(self):
        async def run():
            mgr, mirror = make_mirror()
            mirror.state = "connected"
            mirror.CK_INTERVAL = 0.01
            task = asyncio.get_event_loop().create_task(mirror._ck_loop())
            await asyncio.wait_for(task, 2)
            await asyncio.sleep(0)  # let the ensure_future(on_mirror_lost) run
            assert mgr.lost == [mirror]
            # CK0 went out on every round
            cks = [apple_midi.parse_command(d)
                   for d, _ in mirror._data_transport.sent]
            assert all(isinstance(c, apple_midi.ClockSync) and c.count == 0
                       for c in cks)
            assert len(cks) >= mirror.CK_MAX_UNANSWERED
        asyncio.run(run())

    def test_ck_answer_resets_timeout(self):
        async def run():
            _, mirror = make_mirror()
            mirror.state = "connected"
            mirror.CK_INTERVAL = 0.01

            # Auto-answer every CK0 with a matching CK1.
            real_sendto = mirror._data_transport.sendto
            def answering_sendto(data, addr):
                real_sendto(data, addr)
                pkt = apple_midi.parse_command(data)
                if isinstance(pkt, apple_midi.ClockSync) and pkt.count == 0:
                    mirror.on_data(apple_midi.build_clock_sync(
                        0xAAAA, 1, pkt.ts1, pkt.ts1), ("192.0.2.20", 5005))
            mirror._data_transport.sendto = answering_sendto

            task = asyncio.get_event_loop().create_task(mirror._ck_loop())
            await asyncio.sleep(0.08)  # several rounds
            assert not task.done()     # never timed out
            mirror.state = "closed"
            await asyncio.wait_for(task, 1)
        asyncio.run(run())

    def test_reaper_drops_silent_participant(self):
        import time as _time

        from raspimidihub.network_midi import (
            PARTICIPANT_TIMEOUT,
            NetworkMidiManager,
        )

        class FakeConfig:
            data = {"network_midi": {"enabled": True, "exported": []}}

        mgr = NetworkMidiManager(engine=None, config=FakeConfig(), server=None)
        sess = ExportedSession(mgr, "usb-1-2-aaaa:bbbb", "TX-7")
        sess._control_transport = FakeTransport()
        sess._data_transport = FakeTransport()
        mgr._exports["usb-1-2-aaaa:bbbb"] = sess
        part = join(sess, ssrc=0x1111)
        part.last_seq = 42
        now = _time.monotonic()

        # Fresh participant: kept, and RS feedback goes out.
        n_before = len(sess._data_transport.sent)
        mgr._housekeep_once(now)
        assert 0x1111 in sess.participants
        rs = apple_midi.parse_command(sess._data_transport.sent[n_before][0])
        assert isinstance(rs, apple_midi.Feedback)
        assert rs.seqnum >> 16 == 42

        # Silent past the timeout: reaped.
        part.last_rx = now - PARTICIPANT_TIMEOUT - 1
        mgr._housekeep_once(now)
        assert 0x1111 not in sess.participants


class TestManualPeers:
    def make_manager(self, monkeypatch, peers=("10.0.0.2",)):
        from raspimidihub.network_midi import NetworkMidiManager

        started = []

        class FakeMirror:
            def __init__(self, manager, svc):
                self.svc = svc
                self.alsa_client_id = 99
                self.stable_id = svc.stable_id
                self.state = "connected"
                self.latency_ms = None

            async def start(self):
                started.append(self.svc.service)

            async def stop(self, send_bye=True):
                pass

        monkeypatch.setattr(network_midi, "MirroredSession", FakeMirror)

        class FakeConfig:
            data = {"network_midi": {"enabled": True, "exported": [],
                                     "manual_peers": list(peers)}}

        mgr = NetworkMidiManager(engine=None, config=FakeConfig(), server=None)
        return mgr, started

    @staticmethod
    def peer_status(hub_id="feedface0002"):
        return {
            "available": True, "hub_id": hub_id, "hostname": "hub2",
            "_addr": "10.0.0.2",
            "exports": [{"stable_id": "usb-9-9-c:d", "name": "JX-3P @hub2",
                         "port": 5006, "participants": []}],
        }

    def test_peer_exports_mirror(self, monkeypatch):
        mgr, started = self.make_manager(monkeypatch)
        asyncio.run(mgr._integrate_peer_status("10.0.0.2", self.peer_status()))
        assert len(started) == 1
        svc = next(iter(mgr._discovered.values()))
        assert svc.via_manual == "10.0.0.2"
        assert svc.stable_id == "net-feedface0002-usb-9-9-c:d"

    def test_own_hub_skipped(self, monkeypatch):
        mgr, started = self.make_manager(monkeypatch)
        asyncio.run(mgr._integrate_peer_status(
            "10.0.0.2", self.peer_status(hub_id=mgr.hub_id)))
        assert started == []
        assert mgr._discovered == {}

    def test_peer_down_retracts_entries(self, monkeypatch):
        mgr, started = self.make_manager(monkeypatch)
        asyncio.run(mgr._integrate_peer_status("10.0.0.2", self.peer_status()))
        assert len(mgr._discovered) == 1
        asyncio.run(mgr._integrate_peer_status("10.0.0.2", None))
        assert mgr._discovered == {}
        assert mgr._mirrors == {}

    def test_mdns_entry_not_overwritten(self, monkeypatch):
        mgr, started = self.make_manager(monkeypatch)
        svc = make_discovered(hub="feedface0002", sid="usb-9-9-c:d",
                              name="JX-3P @hub2", host="hub2")
        mgr._discovered[svc.service] = svc  # mDNS-owned (via_manual=None)
        asyncio.run(mgr._integrate_peer_status("10.0.0.2", self.peer_status()))
        assert mgr._discovered[svc.service] is svc
        # And the poller's retraction pass must not touch it either
        asyncio.run(mgr._integrate_peer_status("10.0.0.2", None))
        assert svc.service in mgr._discovered


class TestManagerPolicy:
    def test_mirrored_devices_not_exportable(self):
        from raspimidihub.network_midi import NetworkMidiManager

        class FakeRegistry:
            def client_for_stable_id(self, sid):
                return None

        class FakeEngine:
            device_registry = FakeRegistry()
            devices = []

            def on_change(self, cb):
                pass

        class FakeConfig:
            data = {"network_midi": {"enabled": True, "exported": []}}

        mgr = NetworkMidiManager(FakeEngine(), FakeConfig(), server=None)
        ok, reason = mgr.is_exportable("net-aaa-usb-1-2-x:y")
        assert not ok
        assert "mirrored" in reason
        # And offline (unknown) devices are rejected too
        ok, reason = mgr.is_exportable("usb-1-2-aaaa:bbbb")
        assert not ok
