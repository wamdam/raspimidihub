"""Tests for CcSmoother plugin (non-threaded aspects)."""

from helpers import make_plugin
from cc_smoother import CcSmoother


class TestCcSmoother:
    def test_passthrough_non_matching_cc(self):
        p, h = make_plugin(CcSmoother)
        p._param_values["cc_in"] = 1
        p.on_cc(0, 2, 64)
        assert h.ccs == [(0, 2, 64)]

    def test_note_passthrough(self):
        p, h = make_plugin(CcSmoother)
        p.on_note_on(0, 60, 100)
        assert h.note_ons == [(0, 60, 100)]
