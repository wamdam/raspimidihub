"""Tests for the network MIDI manager / exported sessions.

Protocol state machines are driven through fake transports — no
sockets, no zeroconf (mocked at the manager boundary, same style as
test_wifi / test_usb_tether)."""

from raspimidihub import apple_midi
from raspimidihub.alsa_seq import MidiEventType
from raspimidihub.network_midi import ExportedSession


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


class TestManagerPolicy:
    def test_mirrored_devices_not_exportable(self):
        from raspimidihub.network_midi import NetworkMidiManager

        class FakeRegistry:
            def client_for_stable_id(self, sid):
                return None

        class FakeEngine:
            device_registry = FakeRegistry()
            devices = []

        class FakeConfig:
            data = {"network_midi": {"enabled": True, "exported": []}}

        mgr = NetworkMidiManager(FakeEngine(), FakeConfig(), server=None)
        ok, reason = mgr.is_exportable("net-aaa-usb-1-2-x:y")
        assert not ok
        assert "mirrored" in reason
        # And offline (unknown) devices are rejected too
        ok, reason = mgr.is_exportable("usb-1-2-aaaa:bbbb")
        assert not ok
