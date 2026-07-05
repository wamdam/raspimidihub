"""Tests for VelocityEqualizer plugin."""

from helpers import make_plugin

from velocity_equalizer import VelocityEqualizer


class TestVelocityEqualizer:
    def test_fixed_mode(self):
        p, h = make_plugin(VelocityEqualizer)
        p._param_values["mode"] = "fixed"
        p._param_values["fixed_vel"] = 100
        p.on_note_on(0, 60, 50)
        assert [(c, n, int(v)) for c, n, v in h.note_ons] == [(0, 60, 100)]

    def test_compress_mode(self):
        p, h = make_plugin(VelocityEqualizer)
        p._param_values["mode"] = "compress"
        p._param_values["out_min"] = 60
        p._param_values["out_max"] = 120
        p.on_note_on(0, 60, 127)
        vel = h.note_ons[0][2]
        # float trajectory; the 1.0 projection must stay in range
        assert 60 <= int(vel) <= 120

    def test_compress_zero_velocity(self):
        p, h = make_plugin(VelocityEqualizer)
        p._param_values["mode"] = "compress"
        p._param_values["out_min"] = 60
        p._param_values["out_max"] = 120
        p.on_note_on(0, 60, 0)
        vel = h.note_ons[0][2]
        assert int(vel) == 60
