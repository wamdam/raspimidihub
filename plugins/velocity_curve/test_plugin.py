"""Tests for VelocityCurve plugin."""

from helpers import make_plugin
from velocity_curve import VelocityCurve


class TestVelocityCurve:
    def test_linear_passthrough(self):
        p, h = make_plugin(VelocityCurve)
        p.on_note_on(0, 60, 100)
        assert h.note_ons == [(0, 60, 100)]

    def test_custom_curve(self):
        p, h = make_plugin(VelocityCurve)
        curve = list(range(128))
        curve[100] = 50
        p._param_values["curve"] = curve
        p.on_note_on(0, 60, 100)
        assert h.note_ons == [(0, 60, 50)]

    def test_minimum_velocity_1(self):
        p, h = make_plugin(VelocityCurve)
        p._param_values["curve"] = [0] * 128
        p.on_note_on(0, 60, 100)
        assert h.note_ons[0][2] >= 1

    def test_note_off_passthrough(self):
        p, h = make_plugin(VelocityCurve)
        p.on_note_off(0, 60)
        assert h.note_offs == [(0, 60)]
