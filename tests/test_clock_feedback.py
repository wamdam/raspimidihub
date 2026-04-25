"""Tests for the clock-feedback guard in PluginHost.is_clock_consumer_client.

Regression: a Clock Divider plugin's OUT port is auto-subscribed to the
engine's monitor port (because plugin OUT ports advertise READ cap), so
its emitted clock used to feed back into the ClockBus and double-count
the divider's own _n. Pure generators like Master Clock should still
feed the bus.
"""

from unittest.mock import MagicMock

from raspimidihub.plugin_host.host import PluginHost


def _make_host_with_instance(client_id: int, clock_divisions: list[str]):
    host = PluginHost.__new__(PluginHost)  # bypass __init__
    host._instances = {}

    instance = MagicMock()
    instance.alsa_client = MagicMock()
    instance.alsa_client.client_id = client_id
    instance.plugin = MagicMock()
    instance.plugin.__class__ = type("FakePlugin", (), {"clock_divisions": clock_divisions})
    host._instances["fake-id"] = instance
    return host


class TestClockConsumerDetection:
    def test_clock_consumer_returns_true_for_subscribed_plugin(self):
        host = _make_host_with_instance(client_id=131, clock_divisions=["tick"])
        assert host.is_clock_consumer_client(131) is True

    def test_pure_generator_returns_false(self):
        # Master Clock subscribes to no divisions — it generates, doesn't consume.
        host = _make_host_with_instance(client_id=129, clock_divisions=[])
        assert host.is_clock_consumer_client(129) is False

    def test_unknown_client_returns_false(self):
        # External hardware client — not a plugin at all.
        host = _make_host_with_instance(client_id=131, clock_divisions=["tick"])
        assert host.is_clock_consumer_client(32) is False

    def test_consumer_with_musical_division_also_blocked(self):
        # Any non-empty clock_divisions counts as consumer (Arpeggiator-style).
        host = _make_host_with_instance(client_id=130, clock_divisions=["1/8", "1/16"])
        assert host.is_clock_consumer_client(130) is True
