"""Tests for ClockBus transport notification."""

from unittest.mock import MagicMock

from raspimidihub.plugin_host.clock_bus import ClockBus


class TestTransportNotification:
    def _make_subscribed_instance(self, bus, divisions):
        instance = MagicMock()
        instance.running = True
        instance._tick_queue = MagicMock()
        instance._tick_pipe = None
        bus.subscribe(instance, divisions)
        return instance

    def test_on_continue_notifies_subscribers(self):
        bus = ClockBus()
        instance = self._make_subscribed_instance(bus, ["1/16"])

        bus.on_continue()

        instance._tick_queue.put_nowait.assert_called_once_with("_continue")
        assert bus._running is True

    def test_on_start_notifies_and_resets_count(self):
        bus = ClockBus()
        instance = self._make_subscribed_instance(bus, ["1/16"])
        bus._tick_count = 42

        bus.on_start()

        assert bus._tick_count == 0
        instance._tick_queue.put_nowait.assert_any_call("_start")

    def test_on_stop_notifies(self):
        bus = ClockBus()
        instance = self._make_subscribed_instance(bus, ["1/16"])

        bus.on_stop()

        instance._tick_queue.put_nowait.assert_called_once_with("_stop")
        assert bus._running is False
