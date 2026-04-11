"""Tests for CcLfo plugin (non-threaded aspects)."""

from helpers import make_plugin
from cc_lfo import CcLfo


class TestCcLfo:
    def test_default_params(self):
        p, h = make_plugin(CcLfo)
        assert p._param_values["wave"] == "sine"
        assert p._param_values["cc_num"] == 1
