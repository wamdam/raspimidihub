"""Tests for NoteSplitter plugin."""

from helpers import make_plugin
from note_splitter import NoteSplitter


class TestNoteSplitter:
    def test_below_split(self):
        p, h = make_plugin(NoteSplitter)
        p._param_values["split_point"] = 60
        p._param_values["lower_ch"] = 1
        p._param_values["lower_transpose"] = 0
        p.on_note_on(0, 48, 100)
        assert h.note_ons == [(0, 48, 100)]

    def test_above_split(self):
        p, h = make_plugin(NoteSplitter)
        p._param_values["split_point"] = 60
        p._param_values["upper_ch"] = 2
        p._param_values["upper_transpose"] = 0
        p.on_note_on(0, 72, 100)
        assert h.note_ons[0][0] == 1  # channel 2 = index 1

    def test_transpose(self):
        p, h = make_plugin(NoteSplitter)
        p._param_values["split_point"] = 60
        p._param_values["lower_ch"] = 1
        p._param_values["lower_transpose"] = 12
        p.on_note_on(0, 48, 100)
        assert h.note_ons[0][1] == 60

    def test_transpose_boundary(self):
        p, h = make_plugin(NoteSplitter)
        p._param_values["split_point"] = 60
        p._param_values["lower_ch"] = 1
        p._param_values["lower_transpose"] = 48
        p.on_note_on(0, 50, 100)  # 50 + 48 = 98, ok
        assert len(h.note_ons) >= 1
