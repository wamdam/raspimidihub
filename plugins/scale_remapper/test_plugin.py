"""Tests for ScaleRemapper plugin."""

from helpers import make_plugin
from scale_remapper import ScaleRemapper


class TestScaleRemapper:
    def test_c_major_passthrough(self):
        p, h = make_plugin(ScaleRemapper)
        p._param_values["scale"] = "major"
        p._param_values["root"] = 0
        p.on_start()
        p.on_note_on(0, 60, 100)
        assert h.note_ons == [(0, 60, 100)]

    def test_c_major_remap_csharp(self):
        p, h = make_plugin(ScaleRemapper)
        p._param_values["scale"] = "major"
        p._param_values["root"] = 0
        p.on_start()
        p.on_note_on(0, 61, 100)
        note = h.note_ons[0][1]
        assert note in (60, 62)

    def test_chromatic_passthrough(self):
        p, h = make_plugin(ScaleRemapper)
        p._param_values["scale"] = "chromatic"
        p._param_values["root"] = 0
        p.on_start()
        for n in range(128):
            h.clear()
            p.on_note_on(0, n, 100)
            assert h.note_ons == [(0, n, 100)]

    def test_different_root(self):
        p, h = make_plugin(ScaleRemapper)
        p._param_values["scale"] = "major"
        p._param_values["root"] = 2
        p.on_start()
        p.on_note_on(0, 62, 100)
        assert h.note_ons[0][1] == 62
