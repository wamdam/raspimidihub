"""Tests for the SndSeqEvent <-> raw MIDI codec (midi_codec.py)."""

import ctypes

from raspimidihub.alsa_seq import (
    SND_SEQ_EVENT_LENGTH_VARIABLE,
    MidiEventType,
    SndSeqEvent,
)
from raspimidihub.midi_codec import event_to_midi, midi_to_event


def _roundtrip(msg: bytes) -> bytes | None:
    ev = midi_to_event(msg)
    assert ev is not None, f"midi_to_event rejected {msg.hex()}"
    return event_to_midi(ev)


class TestRoundtrips:
    def test_note_on(self):
        assert _roundtrip(bytes([0x91, 60, 100])) == bytes([0x91, 60, 100])

    def test_note_off(self):
        assert _roundtrip(bytes([0x80, 60, 0])) == bytes([0x80, 60, 0])

    def test_poly_pressure(self):
        assert _roundtrip(bytes([0xA3, 60, 50])) == bytes([0xA3, 60, 50])

    def test_cc(self):
        assert _roundtrip(bytes([0xB5, 7, 127])) == bytes([0xB5, 7, 127])

    def test_program_change(self):
        assert _roundtrip(bytes([0xC2, 42])) == bytes([0xC2, 42])

    def test_channel_pressure(self):
        assert _roundtrip(bytes([0xD0, 99])) == bytes([0xD0, 99])

    def test_pitch_bend(self):
        # center = 0x2000 -> LSB 0x00, MSB 0x40
        assert _roundtrip(bytes([0xE0, 0x00, 0x40])) == bytes([0xE0, 0x00, 0x40])
        assert _roundtrip(bytes([0xEF, 0x7F, 0x7F])) == bytes([0xEF, 0x7F, 0x7F])

    def test_realtime(self):
        for status in (0xF8, 0xFA, 0xFB, 0xFC, 0xFE):
            assert _roundtrip(bytes([status])) == bytes([status])

    def test_song_position(self):
        assert _roundtrip(bytes([0xF2, 0x10, 0x02])) == bytes([0xF2, 0x10, 0x02])

    def test_sysex(self):
        msg = bytes([0xF0, 0x43, 0x10, 0x7F, 0x00, 0xF7])
        ev = midi_to_event(msg)
        assert ev.type == MidiEventType.SYSEX
        assert ev.flags & SND_SEQ_EVENT_LENGTH_VARIABLE
        assert ev.data.ext.len == len(msg)
        assert event_to_midi(ev) == msg


class TestMidiToEvent:
    def test_channel_extraction(self):
        ev = midi_to_event(bytes([0x9A, 60, 100]))
        assert ev.type == MidiEventType.NOTEON
        assert ev.data.note.channel == 0x0A

    def test_pitch_bend_value(self):
        # ALSA convention is SIGNED bend: wire max 0x3FFF → +8191,
        # wire center 0x2000 → 0, wire min 0 → −8192.
        ev = midi_to_event(bytes([0xE0, 0x7F, 0x7F]))
        assert ev.data.control.value == 8191
        ev = midi_to_event(bytes([0xE0, 0x00, 0x40]))
        assert ev.data.control.value == 0
        ev = midi_to_event(bytes([0xE0, 0x00, 0x00]))
        assert ev.data.control.value == -8192

    def test_pitch_bend_encode_signed(self):
        from helpers import make_event
        ev = make_event(MidiEventType.PITCHBEND)
        for signed, wire in ((0, (0x00, 0x40)), (-8192, (0x00, 0x00)),
                             (8191, (0x7F, 0x7F)), (4096, (0x00, 0x60))):
            ev.data.control.value = signed
            out = event_to_midi(ev)
            assert (out[1], out[2]) == wire, signed

    def test_incomplete_sysex_rejected(self):
        assert midi_to_event(bytes([0xF0, 1, 2])) is None

    def test_sysex_buffer_keepalive(self):
        """The ctypes payload buffer must stay alive on the event."""
        ev = midi_to_event(bytes([0xF0, 1, 2, 0xF7]))
        assert hasattr(ev, "_sysex_buf")
        assert ctypes.string_at(ev.data.ext.ptr, ev.data.ext.len) == \
            bytes([0xF0, 1, 2, 0xF7])

    def test_garbage_rejected(self):
        assert midi_to_event(b"") is None
        assert midi_to_event(bytes([0x40, 0x40])) is None  # data byte first
        assert midi_to_event(bytes([0xF5])) is None         # undefined

    def test_truncated_voice_rejected(self):
        assert midi_to_event(bytes([0x90, 60])) is None


class TestEventToMidi:
    def test_unknown_type_returns_none(self):
        ev = SndSeqEvent()
        ev.type = 200  # not a MidiEventType
        assert event_to_midi(ev) is None

    def test_tick_has_no_wire_form(self):
        ev = SndSeqEvent()
        ev.type = MidiEventType.TICK
        assert event_to_midi(ev) is None

    def test_empty_sysex_returns_none(self):
        ev = SndSeqEvent()
        ev.type = MidiEventType.SYSEX
        assert event_to_midi(ev) is None

    def test_data_bytes_masked_to_7bit(self):
        """Out-of-range values from buggy senders are clamped to the
        wire's 7-bit fields rather than corrupting the status byte."""
        ev = SndSeqEvent()
        ev.type = MidiEventType.CONTROLLER
        ev.data.control.channel = 3
        ev.data.control.param = 0x87       # > 127
        ev.data.control.value = 0xFF
        out = event_to_midi(ev)
        assert out == bytes([0xB3, 0x07, 0x7F])
