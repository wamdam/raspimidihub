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
