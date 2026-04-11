"""Tests for MasterClock plugin."""

from helpers import make_plugin
from master_clock import MasterClock


class TestMasterClock:
    def test_play_sends_start(self):
        p, h = make_plugin(MasterClock)
        p.on_param_change("play", True)
        assert ("start",) in h.sent

    def test_stop_sends_stop(self):
        p, h = make_plugin(MasterClock)
        p.on_param_change("play", True)
        h.clear()
        p.on_param_change("play", False)
        assert ("stop",) in h.sent
