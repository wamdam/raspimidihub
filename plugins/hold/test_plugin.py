"""Tests for Hold plugin."""

from helpers import make_plugin

from hold import Hold

RELEASE_NOTE = 108


def _setup():
    p, h = make_plugin(Hold)
    p._param_values["use_release_note"] = True
    p._param_values["release_note"] = RELEASE_NOTE
    return p, h


class TestHold:
    def test_single_note_sustains_after_release(self):
        p, h = _setup()
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)
        assert h.note_ons == [(0, 60, 100)]
        assert h.note_offs == []  # still held

    def test_chord_builds_while_keys_down(self):
        """Pressing multiple keys before releasing any adds them all to the chord."""
        p, h = _setup()
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_note_on(0, 67, 100)
        p.on_note_off(0, 60)
        p.on_note_off(0, 64)
        p.on_note_off(0, 67)
        # All 3 sounding, no note-offs emitted yet
        assert sorted(n for _, n, _ in h.note_ons) == [60, 64, 67]
        assert h.note_offs == []

    def test_new_note_after_full_release_replaces_chord(self):
        p, h = _setup()
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)  # locked with C held
        h.clear()
        p.on_note_on(0, 64, 80)  # fresh note releases C, plays E
        assert h.note_offs == [(0, 60)]
        assert h.note_ons == [(0, 64, 80)]

    def test_new_note_while_keys_still_down_adds_to_chord(self):
        p, h = _setup()
        p.on_note_on(0, 60, 100)  # physical: {60}
        p.on_note_on(0, 64, 100)  # physical: {60, 64} — adds, does NOT replace
        h.clear()
        p.on_note_on(0, 67, 100)  # still BUILDING, add
        assert h.note_offs == []
        assert h.note_ons == [(0, 67, 100)]

    def test_release_note_silences_chord_and_is_swallowed(self):
        p, h = _setup()
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_note_off(0, 60)
        p.on_note_off(0, 64)  # locked, chord sounding
        h.clear()
        p.on_note_on(0, RELEASE_NOTE, 100)
        p.on_note_off(0, RELEASE_NOTE)
        # Release note itself never forwarded; held chord gets note-off
        assert not any(n == RELEASE_NOTE for _, n, _ in h.note_ons)
        assert not any(n == RELEASE_NOTE for _, n in h.note_offs)
        assert sorted(n for _, n in h.note_offs) == [60, 64]

    def test_release_note_disabled(self):
        p, h = _setup()
        p._param_values["use_release_note"] = False
        p.on_note_on(0, RELEASE_NOTE, 100)
        p.on_note_off(0, RELEASE_NOTE)
        # With disabled release note, it behaves as a normal note
        assert h.note_ons == [(0, RELEASE_NOTE, 100)]

    def test_release_note_while_building_still_releases(self):
        p, h = _setup()
        p.on_note_on(0, 60, 100)  # physical C down
        h.clear()
        p.on_note_on(0, RELEASE_NOTE, 100)
        # Should release C even though C is still physically down
        assert h.note_offs == [(0, 60)]
        # Subsequent physical release of C must not emit a new note-off
        h.clear()
        p.on_note_off(0, 60)
        assert h.note_offs == []

    def test_zero_velocity_note_on_treated_as_off(self):
        """Running-status note-off (note_on vel=0) must sustain, not double-release."""
        p, h = _setup()
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 60, 0)  # running-status off
        assert h.note_offs == []  # still held

    def test_on_stop_releases_all(self):
        p, h = _setup()
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_note_off(0, 60)
        p.on_note_off(0, 64)
        h.clear()
        p.on_stop()
        assert sorted(n for _, n in h.note_offs) == [60, 64]

    def test_cc_passes_through(self):
        p, h = _setup()
        p.on_cc(0, 74, 64)
        assert h.ccs == [(0, 74, 64)]

    def test_release_note_learned_mid_press_clears_physical(self):
        """If release_note changes to a note whose note_on was already tracked,
        the paired note_off must still clean up _physical so LOCKED can fire.
        """
        p, h = _setup()
        # Press note 60 as a regular note (release_note is 108).
        p.on_note_on(0, 60, 100)
        # User clicks Learn, release_note param becomes 60.
        p._param_values["release_note"] = 60
        # Release that note — must empty _physical so next fresh press replaces.
        p.on_note_off(0, 60)
        h.clear()
        # New note: previous chord (containing 60) should release, 64 should play.
        p.on_note_on(0, 64, 80)
        assert (0, 60) in h.note_offs
        assert h.note_ons == [(0, 64, 80)]

    def test_transport_stop_releases(self):
        p, h = _setup()
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_note_off(0, 60)
        p.on_note_off(0, 64)
        h.clear()
        p.on_transport_stop()
        assert sorted(n for _, n in h.note_offs) == [60, 64]

    def test_panic_releases(self):
        p, h = _setup()
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)
        h.clear()
        p.panic()
        assert h.note_offs == [(0, 60)]


class TestHoldToggleNotes:
    """Toggle Notes mode: each note latches independently, second press releases."""

    def _setup_toggle(self):
        p, h = make_plugin(Hold)
        p._param_values["use_release_note"] = True
        p._param_values["release_note"] = RELEASE_NOTE
        p._param_values["toggle_notes"] = True
        return p, h

    def test_first_press_plays_and_holds(self):
        p, h = self._setup_toggle()
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)  # physical release ignored
        assert h.note_ons == [(0, 60, 100)]
        assert h.note_offs == []

    def test_second_press_of_same_note_releases(self):
        p, h = self._setup_toggle()
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)
        h.clear()
        p.on_note_on(0, 60, 100)  # second press → off
        assert h.note_offs == [(0, 60)]
        assert h.note_ons == []

    def test_third_press_re_latches(self):
        """Off → on → off → on must alternate cleanly."""
        p, h = self._setup_toggle()
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)  # released
        h.clear()
        p.on_note_on(0, 60, 80)
        assert h.note_ons == [(0, 60, 80)]
        assert h.note_offs == []

    def test_different_notes_are_independent(self):
        p, h = self._setup_toggle()
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)
        p.on_note_on(0, 64, 100)
        p.on_note_off(0, 64)
        h.clear()
        # Release only 60 — 64 must stay
        p.on_note_on(0, 60, 100)
        assert h.note_offs == [(0, 60)]
        # 64 still latched: pressing it once more releases it
        p.on_note_on(0, 64, 100)
        assert (0, 64) in h.note_offs

    def test_zero_velocity_note_on_ignored(self):
        """Running-status note-off must not flip the latch."""
        p, h = self._setup_toggle()
        p.on_note_on(0, 60, 100)  # latched on
        h.clear()
        p.on_note_on(0, 60, 0)    # running-status off — ignore
        assert h.note_ons == []
        assert h.note_offs == []

    def test_physical_note_off_ignored(self):
        """The keyboard releasing the key must not unlatch the note."""
        p, h = self._setup_toggle()
        p.on_note_on(0, 60, 100)
        h.clear()
        p.on_note_off(0, 60)
        assert h.note_offs == []  # still latched

    def test_release_note_silences_all_latched(self):
        p, h = self._setup_toggle()
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)
        p.on_note_on(0, 64, 100)
        p.on_note_off(0, 64)
        p.on_note_on(0, 67, 100)
        p.on_note_off(0, 67)
        h.clear()
        p.on_note_on(0, RELEASE_NOTE, 100)
        p.on_note_off(0, RELEASE_NOTE)
        assert sorted(n for _, n in h.note_offs) == [60, 64, 67]
        assert not any(n == RELEASE_NOTE for _, n, _ in h.note_ons)

    def test_panic_releases_toggled(self):
        p, h = self._setup_toggle()
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        h.clear()
        p.panic()
        assert sorted(n for _, n in h.note_offs) == [60, 64]

    def test_on_stop_releases_toggled(self):
        p, h = self._setup_toggle()
        p.on_note_on(0, 60, 100)
        h.clear()
        p.on_stop()
        assert h.note_offs == [(0, 60)]

    def test_transport_stop_releases_toggled(self):
        p, h = self._setup_toggle()
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        h.clear()
        p.on_transport_stop()
        assert sorted(n for _, n in h.note_offs) == [60, 64]


class TestHoldModeSwitch:
    """Flipping the Toggle notes button mid-session must not leave stuck notes."""

    def test_toggle_on_releases_chord_latch_notes(self):
        p, h = make_plugin(Hold)
        p._param_values["use_release_note"] = True
        p._param_values["release_note"] = RELEASE_NOTE
        # Chord-latch (default off): play & release to leave a held chord.
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        p.on_note_off(0, 60)
        p.on_note_off(0, 64)
        h.clear()
        # Flip the mode.
        p._param_values["toggle_notes"] = True
        p.on_param_change("toggle_notes", True)
        assert sorted(n for _, n in h.note_offs) == [60, 64]
        # And toggle mode now works clean — no leftover state.
        h.clear()
        p.on_note_on(0, 72, 100)
        p.on_note_off(0, 72)
        assert h.note_ons == [(0, 72, 100)]

    def test_toggle_off_releases_toggle_mode_notes(self):
        p, h = make_plugin(Hold)
        p._param_values["use_release_note"] = True
        p._param_values["release_note"] = RELEASE_NOTE
        p._param_values["toggle_notes"] = True
        p.on_note_on(0, 60, 100)
        p.on_note_on(0, 64, 100)
        h.clear()
        # Flip off — toggled notes must be released so chord-latch mode
        # doesn't inherit a phantom "held" state.
        p._param_values["toggle_notes"] = False
        p.on_param_change("toggle_notes", False)
        assert sorted(n for _, n in h.note_offs) == [60, 64]

    def test_chord_latch_mode_unchanged_when_toggle_off(self):
        """Sanity: existing chord-latch behavior remains intact."""
        p, h = make_plugin(Hold)
        p._param_values["use_release_note"] = True
        p._param_values["release_note"] = RELEASE_NOTE
        # toggle_notes defaults False — confirm by leaving it untouched.
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)
        assert h.note_ons == [(0, 60, 100)]
        assert h.note_offs == []
