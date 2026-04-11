"""Tests for VelocityEqualizer plugin."""

from helpers import make_plugin
from velocity_equalizer import VelocityEqualizer


class TestVelocityEqualizer:
    def test_fixed_mode(self):
        p, h = make_plugin(VelocityEqualizer)
        p._param_values["mode"] = "fixed"
        p._param_values["fixed_vel"] = 100
        p.on_note_on(0, 60, 50)
        assert h.note_ons == [(0, 60, 100)]

    def test_compress_mode(self):
        p, h = make_plugin(VelocityEqualizer)
        p._param_values["mode"] = "compress"
        p._param_values["out_min"] = 60
        p._param_values["out_max"] = 120
        p.on_note_on(0, 60, 127)
        vel = h.note_ons[0][2]
        assert 60 <= vel <= 120

    def test_compress_zero_velocity(self):
        p, h = make_plugin(VelocityEqualizer)
        p._param_values["mode"] = "compress"
        p._param_values["out_min"] = 60
        p._param_values["out_max"] = 120
        p.on_note_on(0, 60, 0)
        vel = h.note_ons[0][2]
        assert vel == 60
