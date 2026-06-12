"""Tests for the AppleMIDI / RTP-MIDI wire protocol (apple_midi.py).

Byte layouts follow the Wireshark `applemidi` dissector and RFC 6295;
the spec-derived vectors below are cross-checked against rtpmidid's
packet builders. On-the-wire interop (macOS Audio MIDI Setup,
rtpmidid) is verified in the phase-2 integration pass on hardware.
"""

import struct

from raspimidihub.apple_midi import (
    CMD_ACCEPT,
    CMD_BYE,
    CMD_INVITATION,
    CMD_REJECT,
    ClockSync,
    ExchangePacket,
    Feedback,
    SysExAssembler,
    build_clock_sync,
    build_exchange,
    build_feedback,
    build_rtp_midi,
    parse_command,
    parse_rtp_midi,
    sysex_segments,
)


class TestExchangePackets:
    def test_invitation_roundtrip(self):
        pkt = build_exchange(CMD_INVITATION, 0x12345678, 0xCAFEBABE, "TX-7 @hub")
        parsed = parse_command(pkt)
        assert isinstance(parsed, ExchangePacket)
        assert parsed.command == CMD_INVITATION
        assert parsed.version == 2
        assert parsed.initiator_token == 0x12345678
        assert parsed.ssrc == 0xCAFEBABE
        assert parsed.name == "TX-7 @hub"

    def test_invitation_wire_layout(self):
        """Spec vector: signature, 'IN', version=2, token, ssrc, name+NUL."""
        pkt = build_exchange(CMD_INVITATION, 1, 2, "A")
        assert pkt == bytes.fromhex("ffff494e00000002000000010000000241 00".replace(" ", ""))

    def test_accept_reject_bye(self):
        for cmd in (CMD_ACCEPT, CMD_REJECT, CMD_BYE):
            parsed = parse_command(build_exchange(cmd, 7, 9))
            assert isinstance(parsed, ExchangePacket)
            assert parsed.command == cmd
            assert parsed.name is None

    def test_name_optional_on_parse(self):
        """A bare 16-byte packet (no name) parses with name=None."""
        pkt = build_exchange(CMD_INVITATION, 1, 2)
        assert len(pkt) == 16
        assert parse_command(pkt).name is None

    def test_name_non_utf8_does_not_crash(self):
        pkt = build_exchange(CMD_INVITATION, 1, 2)[:16] + b"\xff\xfe\x00"
        assert parse_command(pkt).name is not None

    def test_truncated_returns_none(self):
        pkt = build_exchange(CMD_INVITATION, 1, 2)
        assert parse_command(pkt[:10]) is None
        assert parse_command(b"") is None
        assert parse_command(b"\xff") is None

    def test_unknown_command_returns_none(self):
        assert parse_command(b"\xff\xffXX" + b"\x00" * 12) is None

    def test_rtp_data_is_not_a_command(self):
        rtp = build_rtp_midi(1, 2, 3, bytes([0x90, 60, 100]))
        assert parse_command(rtp) is None


class TestClockSync:
    def test_roundtrip(self):
        pkt = build_clock_sync(0xAABBCCDD, 1, 10_000, 20_000, 0)
        parsed = parse_command(pkt)
        assert isinstance(parsed, ClockSync)
        assert parsed.ssrc == 0xAABBCCDD
        assert parsed.count == 1
        assert (parsed.ts1, parsed.ts2, parsed.ts3) == (10_000, 20_000, 0)

    def test_wire_layout(self):
        """36 bytes: sig, 'CK', ssrc, count, 3 pad, 3x u64 BE."""
        pkt = build_clock_sync(1, 2, 3, 4, 5)
        assert len(pkt) == 36
        assert pkt[:4] == b"\xff\xffCK"
        assert struct.unpack_from(">I", pkt, 4)[0] == 1
        assert pkt[8] == 2
        assert struct.unpack_from(">QQQ", pkt, 12) == (3, 4, 5)

    def test_latency_math(self):
        """The CK round-trip estimate: ((ts3 - ts1) / 2) in 100 us units."""
        parsed = parse_command(build_clock_sync(1, 2, 10_000, 10_050, 10_100))
        rtt_half_ms = (parsed.ts3 - parsed.ts1) / 2 / 10
        assert rtt_half_ms == 5.0

    def test_truncated(self):
        assert parse_command(build_clock_sync(1, 0, 1)[:20]) is None


class TestFeedback:
    def test_roundtrip(self):
        parsed = parse_command(build_feedback(0x11223344, 0x0FA0))
        assert isinstance(parsed, Feedback)
        assert parsed.ssrc == 0x11223344
        # seqnum rides in the top 16 bits
        assert parsed.seqnum >> 16 == 0x0FA0


class TestRtpMidi:
    def test_note_on_roundtrip(self):
        pkt = build_rtp_midi(100, 12345, 0xDEADBEEF, bytes([0x90, 60, 100]))
        parsed = parse_rtp_midi(pkt)
        assert parsed is not None
        assert parsed.seq == 100
        assert parsed.timestamp == 12345
        assert parsed.ssrc == 0xDEADBEEF
        assert parsed.commands == [bytes([0x90, 60, 100])]

    def test_wire_layout(self):
        """V=2, marker+PT=0x61, seq, ts, ssrc, len-flagbyte, command."""
        pkt = build_rtp_midi(1, 2, 3, bytes([0xB0, 7, 100]))
        assert pkt[0] == 0x80          # V=2, no padding, no extension, 0 CSRC
        assert pkt[1] == 0xE1          # marker | 0x61
        assert struct.unpack_from(">H", pkt, 2)[0] == 1
        assert struct.unpack_from(">I", pkt, 4)[0] == 2
        assert struct.unpack_from(">I", pkt, 8)[0] == 3
        assert pkt[12] == 3            # B=0 J=0 Z=0 P=0, len=3
        assert pkt[13:] == bytes([0xB0, 7, 100])

    def test_no_marker_accepted(self):
        pkt = build_rtp_midi(1, 2, 3, bytes([0x90, 60, 1]), marker=False)
        assert pkt[1] == 0x61
        assert parse_rtp_midi(pkt).commands == [bytes([0x90, 60, 1])]

    def test_long_section_uses_b_flag(self):
        """Sections > 15 bytes need the two-byte (12-bit) length."""
        sysex = bytes([0xF0]) + bytes(40) + bytes([0xF7])
        pkt = build_rtp_midi(1, 2, 3, sysex)
        assert pkt[12] & 0x80          # B flag
        length = ((pkt[12] & 0x0F) << 8) | pkt[13]
        assert length == len(sysex)
        assert parse_rtp_midi(pkt).commands == [sysex]

    def test_multi_command_with_delta_times(self):
        """Foreign senders batch commands with delta times; we must
        resolve them (and discard the timing)."""
        midi_list = bytes([
            0x90, 60, 100,        # first command, Z=0 -> no delta
            0x10,                 # delta time (one byte, MSB clear)
            0x80, 60, 0,          # second command
        ])
        pkt = bytes([0x80, 0xE1]) + struct.pack(">HII", 5, 0, 1) \
            + bytes([len(midi_list)]) + midi_list
        parsed = parse_rtp_midi(pkt)
        assert parsed.commands == [bytes([0x90, 60, 100]), bytes([0x80, 60, 0])]

    def test_running_status(self):
        midi_list = bytes([
            0x90, 60, 100,
            0x00,                 # delta
            62, 100,              # running status NoteOn
            0x00,                 # delta
            64, 100,
        ])
        pkt = bytes([0x80, 0x61]) + struct.pack(">HII", 5, 0, 1) \
            + bytes([len(midi_list)]) + midi_list
        parsed = parse_rtp_midi(pkt)
        assert parsed.commands == [bytes([0x90, 60, 100]),
                                   bytes([0x90, 62, 100]),
                                   bytes([0x90, 64, 100])]

    def test_z_flag_first_delta(self):
        midi_list = bytes([0x20, 0xB0, 1, 2])  # leading delta, then CC
        pkt = bytes([0x80, 0x61]) + struct.pack(">HII", 5, 0, 1) \
            + bytes([0x20 | len(midi_list)]) + midi_list  # Z flag set
        assert parse_rtp_midi(pkt).commands == [bytes([0xB0, 1, 2])]

    def test_multibyte_delta_time(self):
        midi_list = bytes([
            0x90, 60, 100,
            0x81, 0x80, 0x00,     # 3-byte delta (VLQ, MSB continuation)
            0x80, 60, 0,
        ])
        pkt = bytes([0x80, 0x61]) + struct.pack(">HII", 5, 0, 1) \
            + bytes([len(midi_list)]) + midi_list
        assert parse_rtp_midi(pkt).commands == [bytes([0x90, 60, 100]),
                                                bytes([0x80, 60, 0])]

    def test_journal_after_list_is_ignored(self):
        """J=1: bytes after the LEN-delimited list are journal — skip."""
        midi_list = bytes([0x90, 60, 100])
        journal = bytes([0x12, 0x34, 0x56, 0x78])  # arbitrary journal blob
        pkt = bytes([0x80, 0x61]) + struct.pack(">HII", 5, 0, 1) \
            + bytes([0x40 | len(midi_list)]) + midi_list + journal  # J flag
        parsed = parse_rtp_midi(pkt)
        assert parsed.commands == [bytes([0x90, 60, 100])]

    def test_realtime_in_list(self):
        midi_list = bytes([0xF8, 0x00, 0x90, 60, 100])
        pkt = bytes([0x80, 0x61]) + struct.pack(">HII", 5, 0, 1) \
            + bytes([len(midi_list)]) + midi_list
        assert parse_rtp_midi(pkt).commands == [b"\xf8", bytes([0x90, 60, 100])]

    def test_sysex_complete_in_one(self):
        sysex = bytes([0xF0, 0x43, 0x10, 0x01, 0xF7])
        pkt = build_rtp_midi(1, 0, 1, sysex)
        assert parse_rtp_midi(pkt).commands == [sysex]

    def test_not_rtp_returns_none(self):
        assert parse_rtp_midi(b"") is None
        assert parse_rtp_midi(b"\x00" * 16) is None  # V=0
        # Wrong payload type
        pkt = bytearray(build_rtp_midi(1, 2, 3, bytes([0x90, 60, 1])))
        pkt[1] = 0x60
        assert parse_rtp_midi(bytes(pkt)) is None

    def test_truncated_list_returns_none(self):
        pkt = build_rtp_midi(1, 2, 3, bytes([0x90, 60, 100]))
        assert parse_rtp_midi(pkt[:-1]) is None

    def test_oversized_command_raises(self):
        import pytest
        with pytest.raises(ValueError):
            build_rtp_midi(1, 2, 3, bytes(0x1000))

    def test_seq_and_ts_wrap(self):
        pkt = build_rtp_midi(0x1FFFF, 0x1FFFFFFFF, 0x1FFFFFFFF, b"\xf8")
        parsed = parse_rtp_midi(pkt)
        assert parsed.seq == 0xFFFF
        assert parsed.timestamp == 0xFFFFFFFF
        assert parsed.ssrc == 0xFFFFFFFF


class TestSysExSegmentation:
    def test_small_message_single_segment(self):
        msg = bytes([0xF0, 1, 2, 3, 0xF7])
        assert sysex_segments(msg) == [msg]

    def test_fragmentation_roundtrip(self):
        body = bytes(i & 0x7F for i in range(5000))
        msg = bytes([0xF0]) + body + bytes([0xF7])
        segs = sysex_segments(msg, max_segment=1400)
        assert len(segs) > 1
        assert segs[0][0] == 0xF0 and segs[0][-1] == 0xF0
        for mid in segs[1:-1]:
            assert mid[0] == 0xF7 and mid[-1] == 0xF0
        assert segs[-1][0] == 0xF7 and segs[-1][-1] == 0xF7
        assert all(len(s) <= 1400 for s in segs)

        asm = SysExAssembler()
        out = None
        for seg in segs:
            out = asm.feed(seg)
        assert out == msg

    def test_invalid_message_raises(self):
        import pytest
        with pytest.raises(ValueError):
            sysex_segments(bytes([0x43, 0x10]))


class TestSysExAssembler:
    def test_single_complete(self):
        asm = SysExAssembler()
        msg = bytes([0xF0, 0x43, 0xF7])
        assert asm.feed(msg) == msg

    def test_cancellation_resets(self):
        asm = SysExAssembler()
        assert asm.feed(bytes([0xF0, 1, 2, 0xF0])) is None
        assert asm.feed(bytes([0xF7, 3, 0xF4])) is None      # cancel
        # Next complete message works normally
        msg = bytes([0xF0, 9, 0xF7])
        assert asm.feed(msg) == msg

    def test_continuation_without_start_dropped(self):
        asm = SysExAssembler()
        assert asm.feed(bytes([0xF7, 1, 2, 0xF7])) is None

    def test_new_start_resets_pending(self):
        asm = SysExAssembler()
        assert asm.feed(bytes([0xF0, 1, 0xF0])) is None
        assert asm.feed(bytes([0xF0, 5, 0xF7])) == bytes([0xF0, 5, 0xF7])
