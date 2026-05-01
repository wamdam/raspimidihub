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


class TestChannelFilters:
    """Arp Ch / Ctrl Ch: 0=Any (no filter); 1-16 restricts which
    incoming notes count as arpeggiate input vs rate-trigger input."""

    def test_arp_channel_any_accepts_all(self):
        p, _ = make_plugin(Arpeggiator)
        p._param_values["arp_channel"] = 0  # Any
        p.on_note_on(0, 60, 100)
        p.on_note_on(7, 64, 100)
        p.on_note_on(15, 67, 100)
        assert len(p._held_notes) == 3

    def test_arp_channel_filters_to_one(self):
        p, _ = make_plugin(Arpeggiator)
        p._param_values["arp_channel"] = 2  # user-ch 2 = ALSA 1
        p.on_note_on(0, 60, 100)  # wrong channel — drops
        p.on_note_on(1, 64, 100)  # match → joins held
        p.on_note_on(7, 67, 100)  # wrong channel — drops
        assert len(p._held_notes) == 1
        assert p._held_notes[0][0] == 64

    def test_arp_channel_filter_symmetric_on_note_off(self):
        # A note that didn't make it onto the held list (wrong ch)
        # must not be searched for on note-off either — would fall
        # through to the held-notes filter for a no-op anyway, but
        # the early-return keeps the lock contention minimal.
        p, _ = make_plugin(Arpeggiator)
        p._param_values["arp_channel"] = 1  # user-ch 1 = ALSA 0
        p.on_note_on(0, 60, 100)
        p.on_note_off(7, 60)  # different channel — must not affect list
        assert len(p._held_notes) == 1

    def test_control_channel_separates_trigger_from_arp(self):
        # The interesting use case: arp_channel=1, control_channel=16
        # → ch1 notes arpeggiate, ch16 notes flip Rate, even when the
        # same note is played on both.
        p, _ = make_plugin(Arpeggiator)
        p._param_values["arp_channel"] = 1   # ALSA 0
        p._param_values["control_channel"] = 16  # ALSA 15
        p._param_values["rate_trigger"] = True
        p._param_values["rate_base"] = 60
        # Same note 60 on both channels:
        p.on_note_on(0, 60, 100)   # ch1, in trigger range BUT not on ctrl ch → arpeggiates
        assert len(p._held_notes) == 1
        assert p.get_param("rate") == "1/8"  # unchanged
        p.on_note_on(15, 60, 100)  # ch16, in trigger range, on ctrl ch → flips Rate
        assert len(p._held_notes) == 1, "ctrl-ch trigger must not also arpeggiate"
        assert p.get_param("rate") == "4/1"

    def test_control_channel_any_with_arp_channel_set(self):
        # Ctrl=Any (default) + arp filtered: trigger notes work on
        # any channel but arp input only on the chosen channel.
        p, _ = make_plugin(Arpeggiator)
        p._param_values["arp_channel"] = 1
        p._param_values["control_channel"] = 0  # Any
        p._param_values["rate_trigger"] = True
        p._param_values["rate_base"] = 60
        p.on_note_on(7, 62, 100)  # off arp ch + in trigger range → flips Rate, no arp
        assert len(p._held_notes) == 0
        assert p.get_param("rate") == "2/1"
