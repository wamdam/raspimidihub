"""Tests for ClockBus DIVISION_TICKS and transport notification."""

from unittest.mock import MagicMock

from raspimidihub.plugin_host.clock_bus import DIVISION_TICKS, ClockBus


class TestDivisionTicks:
    def test_tick_division_present(self):
        """The "tick" division equals 1 PPQ — fires on every raw clock."""
        assert DIVISION_TICKS["tick"] == 1


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
        instance = self._make_subscribed_instance(bus, ["tick"])

        bus.on_continue()

        instance._tick_queue.put_nowait.assert_called_once_with("_continue")
        assert bus._running is True

    def test_on_start_notifies_and_resets_count(self):
        bus = ClockBus()
        instance = self._make_subscribed_instance(bus, ["tick"])
        bus._tick_count = 42

        bus.on_start()

        assert bus._tick_count == 0
        instance._tick_queue.put_nowait.assert_any_call("_start")

    def test_on_stop_notifies(self):
        bus = ClockBus()
        instance = self._make_subscribed_instance(bus, ["tick"])

        bus.on_stop()

        instance._tick_queue.put_nowait.assert_called_once_with("_stop")
        assert bus._running is False

    def test_on_clock_tick_dispatches_tick_division(self):
        """A subscriber on "tick" should be queued on every clock tick."""
        bus = ClockBus()
        instance = self._make_subscribed_instance(bus, ["tick"])

        for _ in range(3):
            bus.on_clock_tick()

        # 3 ticks → 3 "tick" dispatches
        tick_calls = [c for c in instance._tick_queue.put_nowait.call_args_list
                      if c.args == ("tick",)]
        assert len(tick_calls) == 3
