"""Tests for ClockDivider plugin.

The Divider listens to source-routed clock callbacks (on_clock,
on_clock_start, on_clock_continue, on_clock_stop) — those fire only
when CLOCK / START / CONTINUE / STOP arrives at this plugin's own IN
port via the matrix, not from any clock the engine happens to see
elsewhere.
"""

from helpers import make_plugin

from clock_divider import ClockDivider


class TestClockEmission:
    def test_divide_by_2_emits_every_second_tick(self):
        p, h = make_plugin(ClockDivider)
        p._param_values["divide_by"] = 2

        for _ in range(6):
            p.on_clock()

        assert h.sent.count(("clock",)) == 3

    def test_divide_by_4_emits_every_fourth_tick(self):
        p, h = make_plugin(ClockDivider)
        p._param_values["divide_by"] = 4

        for _ in range(12):
            p.on_clock()

        assert h.sent.count(("clock",)) == 3

    def test_does_not_subscribe_to_clock_bus(self):
        """Divider must not declare clock_divisions or feeds_clock_bus —
        otherwise it'd receive global ticks (instead of source-routed
        ticks) or pollute the ClockBus with its own divided output."""
        assert ClockDivider.clock_divisions == []
        assert ClockDivider.feeds_clock_bus is False


class TestTransport:
    def test_start_resets_counter_and_forwards(self):
        p, h = make_plugin(ClockDivider)
        p._param_values["divide_by"] = 4
        p.on_clock()
        p.on_clock()
        h.clear()

        p.on_clock_start()

        assert ("start",) in h.sent
        # counter reset — divide-by-4 needs 4 fresh ticks before the next emit
        for _ in range(3):
            p.on_clock()
        assert ("clock",) not in h.sent
        p.on_clock()
        assert h.sent.count(("clock",)) == 1

    def test_continue_resets_counter_and_forwards(self):
        p, h = make_plugin(ClockDivider)
        p._param_values["divide_by"] = 4
        p.on_clock()
        p.on_clock()
        h.clear()

        p.on_clock_continue()

        assert ("continue",) in h.sent
        for _ in range(3):
            p.on_clock()
        assert ("clock",) not in h.sent
        p.on_clock()
        assert h.sent.count(("clock",)) == 1

    def test_stop_forwards_intact(self):
        p, h = make_plugin(ClockDivider)

        p.on_clock_stop()

        assert ("stop",) in h.sent


class TestPassthrough:
    def test_notes_pass_through(self):
        p, h = make_plugin(ClockDivider)
        p.on_note_on(1, 60, 100)
        p.on_note_off(1, 60)
        assert ("note_on", 1, 60, 100) in h.sent
        assert ("note_off", 1, 60) in h.sent

    def test_cc_passes_through(self):
        p, h = make_plugin(ClockDivider)
        p.on_cc(2, 74, 64)
        assert ("cc", 2, 74, 64) in h.sent

    def test_pitchbend_aftertouch_program_change_pass_through(self):
        p, h = make_plugin(ClockDivider)
        p.on_pitchbend(1, 8192)
        p.on_aftertouch(1, 90)
        p.on_program_change(1, 42)
        assert ("pitchbend", 1, 8192) in h.sent
        assert ("aftertouch", 1, 90) in h.sent
        assert ("program_change", 1, 42) in h.sent
