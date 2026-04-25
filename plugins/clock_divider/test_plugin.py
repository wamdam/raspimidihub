"""Tests for ClockDivider plugin."""

from helpers import make_plugin

from clock_divider import ClockDivider


class TestClockEmission:
    def test_divide_by_2_emits_every_second_tick(self):
        p, h = make_plugin(ClockDivider)
        p._param_values["divide_by"] = 2

        for _ in range(6):
            p.on_tick("tick")

        assert h.sent.count(("clock",)) == 3

    def test_divide_by_4_emits_every_fourth_tick(self):
        p, h = make_plugin(ClockDivider)
        p._param_values["divide_by"] = 4

        for _ in range(12):
            p.on_tick("tick")

        assert h.sent.count(("clock",)) == 3

    def test_other_divisions_ignored(self):
        p, h = make_plugin(ClockDivider)

        for _ in range(10):
            p.on_tick("1/16")

        assert ("clock",) not in h.sent


class TestTransport:
    def test_start_resets_counter_and_forwards(self):
        p, h = make_plugin(ClockDivider)
        p._param_values["divide_by"] = 4
        p.on_tick("tick")
        p.on_tick("tick")
        h.clear()

        p.on_transport_start()

        assert ("start",) in h.sent
        # counter reset — divide-by-4 needs 4 fresh ticks before the next emit
        for _ in range(3):
            p.on_tick("tick")
        assert ("clock",) not in h.sent
        p.on_tick("tick")
        assert h.sent.count(("clock",)) == 1

    def test_continue_resets_counter_and_forwards(self):
        p, h = make_plugin(ClockDivider)
        p._param_values["divide_by"] = 4
        p.on_tick("tick")
        p.on_tick("tick")
        h.clear()

        p.on_transport_continue()

        assert ("continue",) in h.sent
        for _ in range(3):
            p.on_tick("tick")
        assert ("clock",) not in h.sent
        p.on_tick("tick")
        assert h.sent.count(("clock",)) == 1

    def test_stop_forwards_intact(self):
        p, h = make_plugin(ClockDivider)

        p.on_transport_stop()

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
