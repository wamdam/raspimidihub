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


class TestRateTrigger:
    """Trigger Note: notes in [base, base+15) set the rate radio AND
    are consumed (not arpeggiated). When the toggle is off, those
    same notes should join the held-notes set normally."""

    def test_trigger_off_notes_arpeggiate(self):
        p, _ = make_plugin(Arpeggiator)
        p._param_values["rate_trigger"] = False
        p._param_values["rate_base"] = 24
        p.on_note_on(0, 24, 100)  # would be a trigger if enabled
        assert len(p._held_notes) == 1
        assert p.get_param("rate") == "1/8"  # default unchanged

    def test_trigger_on_consumes_and_sets_rate(self):
        p, _ = make_plugin(Arpeggiator)
        p._param_values["rate_trigger"] = True
        p._param_values["rate_base"] = 24
        # Base = first rate ("4/1")
        p.on_note_on(0, 24, 100)
        assert p._held_notes == [], "trigger note must not be arpeggiated"
        assert p.get_param("rate") == "4/1"
        # +5 semitones → index 5 in _RATE_OPTIONS = "1/1T"
        p.on_note_on(0, 29, 100)
        assert p.get_param("rate") == "1/1T"
        # Note-off in trigger range is also consumed
        p.on_note_off(0, 24)
        assert p._held_notes == []

    def test_trigger_on_passes_through_out_of_range(self):
        p, _ = make_plugin(Arpeggiator)
        p._param_values["rate_trigger"] = True
        p._param_values["rate_base"] = 24
        # Base+15 = first note OUTSIDE the trigger range
        p.on_note_on(0, 39, 100)
        assert len(p._held_notes) == 1
        assert p.get_param("rate") == "1/8"
        # And below base
        p.on_note_on(0, 23, 100)
        assert len(p._held_notes) == 2
        assert p.get_param("rate") == "1/8"
