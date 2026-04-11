"""Tests for Panic plugin."""

from helpers import make_plugin
from panic import Panic


class TestPanic:
    def test_trigger_sends_all_notes_off(self):
        p, h = make_plugin(Panic)
        p.on_param_change("trigger", True)
        cc120s = [(ch, cc, v) for ch, cc, v in h.ccs if cc == 120]
        cc123s = [(ch, cc, v) for ch, cc, v in h.ccs if cc == 123]
        assert len(cc120s) == 16
        assert len(cc123s) == 16
        assert all(v == 0 for _, _, v in cc120s)

    def test_cc_trigger(self):
        p, h = make_plugin(Panic)
        p._param_values["trigger_cc"] = 64
        p.on_cc(0, 64, 127)
        assert len(h.ccs) >= 32
