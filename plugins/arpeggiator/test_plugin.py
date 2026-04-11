"""Tests for Arpeggiator plugin (non-threaded aspects)."""

from helpers import make_plugin
from arpeggiator import Arpeggiator


class TestArpeggiator:
    def test_held_notes_tracking(self):
        p, h = make_plugin(Arpeggiator)
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 80)
        assert len(p._held_notes) == 2

    def test_note_off_removes(self):
        p, h = make_plugin(Arpeggiator)
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 80)
        p.on_note_off(0, 60)
        assert len(p._held_notes) == 1

    def test_sorted_notes_up(self):
        p, h = make_plugin(Arpeggiator)
        p._param_values["pattern"] = "up"
        p.on_note_on(0, 67, 100)
        p.on_note_on(0, 60, 80)
        p.on_note_on(0, 64, 90)
        notes = [n for n, v, c in p._sorted_notes]
        assert notes == [60, 64, 67]
