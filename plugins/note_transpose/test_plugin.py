"""Tests for NoteTranspose plugin."""

from helpers import make_plugin
from note_transpose import NoteTranspose


class TestNoteTranspose:
    def test_transpose_up_12(self):
        p, h = make_plugin(NoteTranspose)
        p._param_values["semitones"] = 12
        p.on_note_on(0, 60, 100)
        assert h.note_ons == [(0, 72, 100)]

    def test_transpose_down_12(self):
        p, h = make_plugin(NoteTranspose)
        p._param_values["semitones"] = -12
        p.on_note_on(0, 24, 80)
        assert h.note_ons == [(0, 12, 80)]

    def test_boundary_above_127(self):
        p, h = make_plugin(NoteTranspose)
        p._param_values["semitones"] = 12
        p.on_note_on(0, 120, 100)
        assert h.note_ons == []

    def test_boundary_below_0(self):
        p, h = make_plugin(NoteTranspose)
        p._param_values["semitones"] = -12
        p.on_note_on(0, 5, 100)
        assert h.note_ons == []

    def test_zero_passthrough(self):
        p, h = make_plugin(NoteTranspose)
        p._param_values["semitones"] = 0
        p.on_note_on(0, 60, 100)
        assert h.note_ons == [(0, 60, 100)]

    def test_note_off_transposed(self):
        p, h = make_plugin(NoteTranspose)
        p._param_values["semitones"] = 7
        p.on_note_off(0, 60)
        assert h.note_offs == [(0, 67)]

    def test_cc_passthrough(self):
        p, h = make_plugin(NoteTranspose)
        p.on_cc(0, 1, 64)
        assert h.ccs == [(0, 1, 64)]
