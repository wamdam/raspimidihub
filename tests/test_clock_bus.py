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


class TestBarPosition:
    """bar_position() and ticks_until_next_grid() drive Controller drop
    button scheduling. These tests pin down the math so a regression
    in the cycle-relative + grid-quantised behaviour is caught here
    rather than at "user notices the drop fires at the wrong bar"."""

    TPB = 96  # 4/4 at 24 PPQN

    def test_bar_position_at_start(self):
        bus = ClockBus()
        bus._tick_count = 0
        assert bus.bar_position() == (0, 0, self.TPB)

    def test_bar_position_mid_bar(self):
        bus = ClockBus()
        bus._tick_count = 5 * self.TPB + 30  # bar 5, tick 30 of 96
        assert bus.bar_position() == (5, 30, self.TPB)

    def test_ticks_until_next_grid_default_one_bar(self):
        bus = ClockBus()
        bus._tick_count = 5 * self.TPB + 30
        # Next bar from bar 5 mid-bar = beginning of bar 6.
        assert bus.ticks_until_next_grid(1) == self.TPB - 30

    def test_ticks_until_next_grid_4bar_quantises(self):
        """Pressing during bar 5 with 4-bar mode must fire at bar 8
        (next 4-bar grid line), NOT bar 9 (4 bars from now)."""
        bus = ClockBus()
        bus._tick_count = 5 * self.TPB + 30
        ticks = bus.ticks_until_next_grid(4)
        # 4-bar grid lines: 0, 4, 8, 12. Next from bar 5 = 8.
        assert ticks == 8 * self.TPB - (5 * self.TPB + 30)
        assert ticks == 3 * self.TPB - 30

    def test_ticks_until_next_grid_at_grid_line_targets_next_one(self):
        """Pressing exactly on a 4-bar grid line schedules to the NEXT
        one, never to the current tick. A boundary hit is strictly future."""
        bus = ClockBus()
        bus._tick_count = 4 * self.TPB  # exactly on a 4-bar boundary
        assert bus.ticks_until_next_grid(4) == 4 * self.TPB  # next = bar 8

    def test_ticks_until_next_grid_just_before_boundary(self):
        """Pressing 6 ticks before the next 4-bar boundary fires in 6
        ticks — the function must NOT round 'almost there' up to a
        full grid period."""
        bus = ClockBus()
        bus._tick_count = 7 * self.TPB + 90  # bar 7, tick 90 (6 to bar 8)
        assert bus.ticks_until_next_grid(4) == 6

    def test_ticks_until_next_grid_8_and_16_bar(self):
        bus = ClockBus()
        # Bar 5: 8-bar grid lines at 0, 8, 16 → next = 8. 16-bar at 0, 16 → 16.
        bus._tick_count = 5 * self.TPB
        assert bus.ticks_until_next_grid(8) == 3 * self.TPB
        assert bus.ticks_until_next_grid(16) == 11 * self.TPB

    def test_ticks_until_next_grid_clamps_zero_to_one(self):
        """`every_n_bars=0` is nonsensical; treat as 1 (next bar)."""
        bus = ClockBus()
        bus._tick_count = 5 * self.TPB + 30
        assert bus.ticks_until_next_grid(0) == bus.ticks_until_next_grid(1)


class TestQuarterCallback:
    """The on_quarter_callback fires once per musical quarter (24 ticks
    at 24 PPQN). __main__.py wires it to broadcast clock-position SSE
    so frontend drop-button rings can run off the live tick count."""

    def test_callback_fires_on_quarter_boundaries(self):
        bus = ClockBus()
        bus._running = True  # skip the auto-start branch
        calls = []
        bus._on_quarter_callback = lambda tick, tpb, running: calls.append(
            (tick, tpb, running))

        for _ in range(24):
            bus.on_clock_tick()

        # One callback at tick 24 (first quarter complete).
        assert calls == [(24, 96, True)]

    def test_callback_fires_every_24_ticks(self):
        bus = ClockBus()
        bus._running = True
        calls = []
        bus._on_quarter_callback = lambda tick, tpb, running: calls.append(tick)

        for _ in range(96):  # one full bar
            bus.on_clock_tick()

        assert calls == [24, 48, 72, 96]

    def test_callback_silent_until_set(self):
        bus = ClockBus()
        bus._running = True
        # No callback registered → no error, just nothing to call.
        for _ in range(24):
            bus.on_clock_tick()

    def test_callback_exception_swallowed(self):
        """A buggy listener must not break clock dispatch for plugins."""
        bus = ClockBus()
        bus._running = True

        def bad(tick, tpb, running):
            raise RuntimeError("boom")

        bus._on_quarter_callback = bad
        # Should not raise.
        for _ in range(24):
            bus.on_clock_tick()

    def test_callback_fires_on_transport_changes(self):
        """on_start / on_continue / on_stop must each emit a position
        callback so the frontend ring freezes promptly on stop and
        resyncs on start (instead of waiting up to a quarter beat)."""
        bus = ClockBus()
        bus._tick_count = 50  # mid-bar
        calls = []
        bus._on_quarter_callback = lambda tick, tpb, running: calls.append(
            (tick, running))

        bus.on_start()
        # on_start resets tick_count to 0, then calls back with running=True.
        assert calls[-1] == (0, True)

        bus._tick_count = 30
        bus.on_continue()
        assert calls[-1] == (30, True)

        bus._tick_count = 60
        bus.on_stop()
        assert calls[-1] == (60, False)
