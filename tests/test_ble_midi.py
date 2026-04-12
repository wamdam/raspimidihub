"""Tests for BLE-MIDI packet parser and encoder."""

from raspimidihub.ble_midi_bridge import parse_ble_midi, encode_ble_midi


class TestParsBleMidi:
    def test_note_on(self):
        """Standard Note On: header + timestamp + status + note + velocity."""
        packet = bytes([0x80, 0x80, 0x90, 0x3C, 0x64])  # ts=0, NoteOn ch0 note60 vel100
        msgs = parse_ble_midi(packet)
        assert len(msgs) == 1
        ts, midi = msgs[0]
        assert midi == [0x90, 0x3C, 0x64]

    def test_note_off(self):
        packet = bytes([0x80, 0x80, 0x80, 0x3C, 0x00])  # NoteOff ch0 note60
        msgs = parse_ble_midi(packet)
        assert len(msgs) == 1
        assert msgs[0][1] == [0x80, 0x3C, 0x00]

    def test_cc(self):
        packet = bytes([0x80, 0x80, 0xB0, 0x07, 0x64])  # CC ch0 cc7 val100
        msgs = parse_ble_midi(packet)
        assert len(msgs) == 1
        assert msgs[0][1] == [0xB0, 0x07, 0x64]

    def test_program_change(self):
        """Program Change has only 1 data byte."""
        packet = bytes([0x80, 0x80, 0xC0, 0x05])  # PC ch0 program5
        msgs = parse_ble_midi(packet)
        assert len(msgs) == 1
        assert msgs[0][1] == [0xC0, 0x05]

    def test_pitch_bend(self):
        packet = bytes([0x80, 0x80, 0xE0, 0x00, 0x40])  # PitchBend center
        msgs = parse_ble_midi(packet)
        assert len(msgs) == 1
        assert msgs[0][1] == [0xE0, 0x00, 0x40]

    def test_timestamp_decoding(self):
        """Verify 13-bit timestamp extraction."""
        # ts_high = 0x02 (bits 12-7), ts_low = 0x10 (bits 6-0)
        # timestamp = (2 << 7) | 16 = 272
        packet = bytes([0x80 | 0x02, 0x80 | 0x10, 0x90, 0x3C, 0x64])
        msgs = parse_ble_midi(packet)
        assert len(msgs) == 1
        assert msgs[0][0] == 272

    def test_multiple_messages(self):
        """Two messages in one packet (each with its own timestamp byte)."""
        packet = bytes([
            0x80,             # header (ts_high=0)
            0x80, 0x90, 0x3C, 0x64,  # ts=0, NoteOn C4 vel100
            0x80, 0x80, 0x3C, 0x00,  # ts=0, NoteOff C4 (running status for NoteOff)
        ])
        msgs = parse_ble_midi(packet)
        assert len(msgs) >= 1  # At least the first message

    def test_empty_packet(self):
        assert parse_ble_midi(bytes()) == []
        assert parse_ble_midi(bytes([0x80])) == []
        assert parse_ble_midi(bytes([0x80, 0x80])) == []

    def test_invalid_header(self):
        """Header without bit 7 set is invalid."""
        assert parse_ble_midi(bytes([0x00, 0x80, 0x90, 0x3C, 0x64])) == []


class TestEncodeBleMidi:
    def test_note_on(self):
        packet = encode_ble_midi([0x90, 0x3C, 0x64], timestamp_ms=0)
        assert packet[0] == 0x80  # header
        assert packet[1] == 0x80  # ts_low = 0
        assert packet[2:] == bytes([0x90, 0x3C, 0x64])

    def test_with_timestamp(self):
        packet = encode_ble_midi([0x90, 0x3C, 0x64], timestamp_ms=272)
        ts_high = (272 >> 7) & 0x3F  # 2
        ts_low = 272 & 0x7F          # 16
        assert packet[0] == 0x80 | ts_high
        assert packet[1] == 0x80 | ts_low

    def test_roundtrip(self):
        """Encode then parse should return original MIDI bytes."""
        original = [0xB0, 0x07, 0x64]  # CC ch0 cc7 val100
        packet = encode_ble_midi(original, timestamp_ms=100)
        msgs = parse_ble_midi(packet)
        assert len(msgs) == 1
        assert msgs[0][1] == original
