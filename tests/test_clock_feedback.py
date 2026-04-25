"""Tests for the clock-feedback guard in PluginHost.client_feeds_clock_bus.

A plugin's emitted CLOCK should feed the global ClockBus only if the
plugin opts in via `feeds_clock_bus = True` (Master Clock). Default
False — clock-processing plugins (Clock Divider, etc.) must not
pollute the bus's tempo perception with their own transformed output.
"""

from unittest.mock import MagicMock

from raspimidihub.plugin_host.host import PluginHost


def _make_host_with_instance(client_id: int, feeds_clock_bus: bool):
    host = PluginHost.__new__(PluginHost)  # bypass __init__
    host._instances = {}

    instance = MagicMock()
    instance.alsa_client = MagicMock()
    instance.alsa_client.client_id = client_id
    instance.plugin = MagicMock()
    instance.plugin.__class__ = type("FakePlugin", (), {"feeds_clock_bus": feeds_clock_bus})
    host._instances["fake-id"] = instance
    return host


class TestFeedsClockBus:
    def test_pure_generator_feeds_bus(self):
        # Master Clock opts in via feeds_clock_bus = True.
        host = _make_host_with_instance(client_id=129, feeds_clock_bus=True)
        assert host.client_feeds_clock_bus(129) is True

    def test_processor_does_not_feed_bus(self):
        # Clock Divider — default False, doesn't pollute the bus.
        host = _make_host_with_instance(client_id=131, feeds_clock_bus=False)
        assert host.client_feeds_clock_bus(131) is False

    def test_unknown_client_returns_false(self):
        # External hardware client — not a plugin at all. The engine
        # treats non-plugin sources as bus-feeding via the call-site
        # check; this method only tells the truth about plugin clients.
        host = _make_host_with_instance(client_id=131, feeds_clock_bus=True)
        assert host.client_feeds_clock_bus(32) is False
