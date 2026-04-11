"""Tests for MidiDelay plugin (non-threaded aspects)."""

from helpers import make_plugin
from midi_delay import MidiDelay


class TestMidiDelay:
    def test_note_passthrough(self):
        p, h = make_plugin(MidiDelay)
        p._param_values["repeats"] = 0
        p.on_note_on(0, 60, 100)
        assert h.note_ons == [(0, 60, 100)]

    def test_cc_passthrough(self):
        p, h = make_plugin(MidiDelay)
        p.on_cc(0, 1, 64)
        assert h.ccs == [(0, 1, 64)]
