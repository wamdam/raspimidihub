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
        p._param_values["pattern"] = 0  # "up"
        p.on_note_on(0, 67, 100)
        p.on_note_on(0, 60, 80)
        p.on_note_on(0, 64, 90)
        notes = [n for n, v, c in p._sorted_notes]
        assert notes == [60, 64, 67]


class TestChannelFilters:
    """Arp Ch: 0=Any (no filter); 1-16 restricts which incoming notes
    count as arpeggiate input."""

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


class TestSustainPedal:
    """CC 64 ≥ 64 turns the arp into a temporary Hold: keys you
    release stay arping; new keys stack. CC 64 < 64 drops every note
    that isn't physically held right now."""

    def test_release_without_pedal_drops(self):
        p, _ = make_plugin(Arpeggiator)
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)
        assert p._held_notes == []

    def test_release_with_pedal_keeps_note(self):
        p, _ = make_plugin(Arpeggiator)
        p.on_note_on(0, 60, 100)
        p.on_cc(0, 64, 127)  # pedal down
        p.on_note_off(0, 60)
        assert len(p._held_notes) == 1, "sustain should hold the note"
        assert (0, 60) not in p._physically_pressed

    def test_pedal_release_drops_unheld(self):
        p, _ = make_plugin(Arpeggiator)
        p.on_note_on(0, 60, 100)
        p.on_cc(0, 64, 127)  # pedal down
        p.on_note_off(0, 60)  # release: sustained
        p.on_cc(0, 64, 0)     # pedal up: drops the unheld note
        assert p._held_notes == []

    def test_pedal_release_keeps_physically_held(self):
        p, _ = make_plugin(Arpeggiator)
        p.on_note_on(0, 60, 100)
        p.on_cc(0, 64, 127)
        p.on_note_off(0, 60)
        p.on_note_on(0, 64, 100)  # currently physically held
        p.on_cc(0, 64, 0)
        held_notes = [n for n, _, _ in p._held_notes]
        assert held_notes == [64]

    def test_repress_dedup(self):
        # Pressing the same key twice (without release) shouldn't
        # double-up in held_notes — used to, before sustain support
        # was added; the dedupe also fixes that pre-existing quirk.
        p, _ = make_plugin(Arpeggiator)
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 60, 100)
        assert len(p._held_notes) == 1

    def test_cc_64_respects_arp_channel_filter(self):
        p, _ = make_plugin(Arpeggiator)
        p._param_values["arp_channel"] = 1  # user-ch 1 = ALSA 0
        p.on_note_on(0, 60, 100)
        p.on_cc(7, 64, 127)  # off-channel pedal → no-op
        assert not p._sustain_active
        p.on_cc(0, 64, 127)  # on-channel pedal → engages
        assert p._sustain_active


class TestFeature2NewNotePlaysNext:
    """When a key is added mid-cycle, the very next _advance plays
    that new note (not whatever the original cycle would have hit)."""

    def test_up_seeks_to_new_note(self):
        p, _ = make_plugin(Arpeggiator)
        p._param_values["pattern"] = 0  # "up"
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_note_on(0, 67, 100)
        # After 3 notes, _arp_step points at the most recent (G, sorted_idx=2)
        assert p._arp_step == 2
        # Add D (62) mid-cycle: sorted becomes [60, 62, 64, 67]; idx of 62 is 1
        p.on_note_on(0, 62, 100)
        assert p._arp_step == 1

    def test_down_seeks_to_new_note(self):
        p, _ = make_plugin(Arpeggiator)
        p._param_values["pattern"] = 1  # "down"
        p._param_values["octaves"] = 1
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        # sorted [60, 64], reversed [64, 60]; new note 67 (sorted_idx=2 of [60,64,67])
        # → reversed_idx = 1*3 - 1 - 2 = 0
        p.on_note_on(0, 67, 100)
        assert p._arp_step == 0

    def test_as_played_seeks_to_appended(self):
        p, _ = make_plugin(Arpeggiator)
        p._param_values["pattern"] = 4  # "as-played"
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_note_on(0, 62, 100)  # appended last
        assert p._arp_step == 2


class TestProgrammedMode:
    """Programmed pattern: each keypress writes the next-to-fire slot;
    slots persist across release; pedal-release clears unheld slots."""

    def _setup_programmed(self, step_count=4):
        p, _ = make_plugin(Arpeggiator)
        p._param_values["pattern"] = 5  # "programmed"
        p._param_values["step_count"] = step_count
        p._ensure_slots()
        return p

    def test_first_press_lands_in_slot_0(self):
        p = self._setup_programmed()
        p.on_note_on(0, 60, 100)
        assert p._step_slots[0] == (60, 100, 0)
        # Write head moved on; play head still at the populated slot
        assert p._next_slot_to_play == 0
        assert p._write_slot == 1

    def test_chord_spread_consecutive_slots(self):
        p = self._setup_programmed(step_count=4)
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_note_on(0, 67, 100)
        notes = [s[0] if s else None for s in p._step_slots]
        assert notes == [60, 64, 67, None]

    def test_release_keeps_slot_while_other_held(self):
        p = self._setup_programmed()
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_note_off(0, 60)  # 64 still held — slots persist
        assert p._step_slots[0] == (60, 100, 0)
        assert p._step_slots[1] == (64, 100, 0)

    def test_release_keeps_slot_with_sustain(self):
        p = self._setup_programmed()
        p.on_note_on(0, 60, 100)
        p.on_cc(0, 64, 127)  # pedal down
        p.on_note_off(0, 60)
        assert p._step_slots[0] == (60, 100, 0)

    def test_release_all_clears_when_no_sustain(self):
        # Once the user has released every key AND sustain is off,
        # the programmed sequence ends — slots clear so the arp
        # silences instead of looping the captured pattern forever.
        p = self._setup_programmed()
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_note_off(0, 60)
        p.on_note_off(0, 64)
        assert all(s is None for s in p._step_slots)

    def test_release_clears_despite_stale_physically_pressed(self):
        # Regression: in real chains the (channel, note) pair we record
        # in _physically_pressed can drift out of sync with the keyboard
        # — a note-on may arrive whose paired note-off never reaches
        # the plugin (channel filter / rate-trigger toggled mid-press,
        # bridge dropping an event, channel_map changing mid-press, …).
        # The leaked entry is invisible to the user but pins the
        # "all released" gate forever, so every subsequent fresh
        # press-then-release leaves the slot ringing. Verify that the
        # gate doesn't trust a stale entry that no surviving slot
        # actually references.
        p = self._setup_programmed()
        # Inject a stale entry: (0, 99) is pressed-but-no-slot.
        p._physically_pressed[(0, 99)] = 100
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)
        assert all(s is None for s in p._step_slots), \
            "stale _physically_pressed entry must not pin the slots"

    def test_pedal_release_clears_unheld_slots(self):
        p = self._setup_programmed()
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_cc(0, 64, 127)  # pedal down
        p.on_note_off(0, 60)  # release C (sustained)
        # E still physically held; pedal up → C clears, E stays
        p.on_cc(0, 64, 0)
        assert p._step_slots[0] is None
        assert p._step_slots[1] == (64, 100, 0)

    def test_overwrite_skips_disabled_step(self):
        p = self._setup_programmed(step_count=4)
        # Disable step 1: presses should land 0, 2, 3 (skipping 1).
        p._param_values["steps"] = [
            {"on": True, "offset": 0},
            {"on": False, "offset": 0},
            {"on": True, "offset": 0},
            {"on": True, "offset": 0},
        ]
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_note_on(0, 67, 100)
        notes = [s[0] if s else None for s in p._step_slots]
        assert notes == [60, None, 64, 67]
