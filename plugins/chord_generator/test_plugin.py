"""Tests for ChordGenerator plugin."""

from helpers import make_plugin
from chord_generator import ChordGenerator


class TestChordGenerator:
    def test_major_chord(self):
        p, h = make_plugin(ChordGenerator)
        p._param_values["chord"] = "major"
        p._param_values["inversion"] = "root"
        p._param_values["vel_scale"] = 100
        p.on_note_on(0, 60, 100)
        notes = sorted(n for _, n, _ in h.note_ons)
        assert notes == [60, 64, 67]

    def test_minor_chord(self):
        p, h = make_plugin(ChordGenerator)
        p._param_values["chord"] = "minor"
        p._param_values["inversion"] = "root"
        p._param_values["vel_scale"] = 100
        p.on_note_on(0, 60, 100)
        notes = sorted(n for _, n, _ in h.note_ons)
        assert notes == [60, 63, 67]

    def test_velocity_scaling(self):
        p, h = make_plugin(ChordGenerator)
        p._param_values["chord"] = "power"
        p._param_values["inversion"] = "root"
        p._param_values["vel_scale"] = 50
        p.on_note_on(0, 60, 100)
        vels = {n: v for _, n, v in h.note_ons}
        assert vels[60] == 100
        assert vels[67] == 50

    def test_note_off_releases_all(self):
        p, h = make_plugin(ChordGenerator)
        p._param_values["chord"] = "major"
        p._param_values["inversion"] = "root"
        p._param_values["vel_scale"] = 90
        p.on_note_on(0, 60, 100)
        h.clear()
        p.on_note_off(0, 60)
        off_notes = sorted(n for _, n in h.note_offs)
        assert off_notes == [60, 64, 67]

    def test_boundary_notes_above_127(self):
        p, h = make_plugin(ChordGenerator)
        p._param_values["chord"] = "octave"
        p._param_values["inversion"] = "root"
        p._param_values["vel_scale"] = 100
        p.on_note_on(0, 120, 100)
        notes = sorted(n for _, n, _ in h.note_ons)
        assert 120 in notes
        assert 132 not in notes

    def test_first_inversion(self):
        p, h = make_plugin(ChordGenerator)
        p._param_values["chord"] = "major"
        p._param_values["inversion"] = "1st"
        p._param_values["vel_scale"] = 100
        p.on_note_on(0, 60, 100)
        notes = sorted(n for _, n, _ in h.note_ons)
        assert notes == [64, 67, 72]
