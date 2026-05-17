"""Tests for the Latency plugin."""

import time

from helpers import make_plugin

from latency import Latency


def _last_when(scheduled: list[tuple]) -> float:
    """Return the `when_monotonic` value of the most recent scheduled event."""
    # All scheduled tuples start with (kind, when, ...). See PluginHarness.
    return scheduled[-1][1]


class TestLatency:
    def test_note_on_scheduled_with_delay(self):
        p, h = make_plugin(Latency)
        p._param_values["delay_ms"] = 50
        t0 = time.monotonic()
        p.on_note_on(0, 60, 100)
        # One scheduled note_on, no immediate send.
        assert h.sent == []
        assert len(h.scheduled) == 1
        kind, when, ch, note, vel, tag = h.scheduled[0]
        assert (kind, ch, note, vel) == ("note_on", 0, 60, 100)
        assert tag == 1
        # The schedule offset should be ~50ms ahead of monotonic at call time.
        assert 0.045 <= when - t0 <= 0.080

    def test_note_off_reuses_note_on_delay(self):
        """If delay_ms changes between on and off, note_off must reuse the
        on's delay so the pair can't reorder and strand the note."""
        p, h = make_plugin(Latency)
        p._param_values["delay_ms"] = 50
        p.on_note_on(0, 60, 100)
        when_on = _last_when(h.scheduled)
        # Live fader move to a smaller delay.
        p._param_values["delay_ms"] = 10
        t_off = time.monotonic()
        p.on_note_off(0, 60)
        when_off = _last_when(h.scheduled)
        # note_off must use the same +50ms offset, not +10ms.
        assert when_off - t_off >= 0.045
        # And the off can't land before the on.
        assert when_off >= when_on

    def test_cc_pitchbend_aftertouch_pc_all_scheduled(self):
        p, h = make_plugin(Latency)
        p._param_values["delay_ms"] = 20
        p.on_cc(0, 7, 100)
        p.on_pitchbend(0, 8192)
        p.on_aftertouch(0, 64)
        p.on_program_change(0, 5)
        kinds = [ev[0] for ev in h.scheduled]
        assert kinds == ["cc", "pitchbend", "aftertouch", "program_change"]
        # None of the delayable events landed on the immediate path.
        assert h.sent == []
        # All carry the latency tag so panic can clear them.
        for ev in h.scheduled:
            assert ev[-1] == 1

    def test_clock_and_transport_immediate(self):
        """Clock + transport bypass the delay — they must hit send_* now,
        not send_*_at later. Delaying clock would shift the downstream
        synth's own sequencer and defeat the point of the plugin."""
        p, h = make_plugin(Latency)
        p._param_values["delay_ms"] = 50
        p.on_clock()
        p.on_clock_start()
        p.on_clock_stop()
        p.on_clock_continue()
        kinds = [ev[0] for ev in h.sent]
        assert kinds == ["clock", "start", "stop", "continue"]
        assert h.scheduled == []

    def test_panic_cancels_pending_and_clears_state(self):
        p, h = make_plugin(Latency)
        p._param_values["delay_ms"] = 50
        p.on_note_on(0, 60, 100)
        assert (0, 60) in p._note_delay
        p.panic()
        assert h.cancelled_tags == [1]
        assert p._note_delay == {}

    def test_on_stop_also_cancels(self):
        p, h = make_plugin(Latency)
        p._param_values["delay_ms"] = 50
        p.on_note_on(0, 60, 100)
        p.on_stop()
        assert h.cancelled_tags == [1]
        assert p._note_delay == {}

    def test_delay_none_falls_back_to_default(self):
        """Defensive: if delay_ms is somehow None, default to 10ms instead
        of crashing on the arithmetic."""
        p, h = make_plugin(Latency)
        p._param_values["delay_ms"] = None
        t0 = time.monotonic()
        p.on_note_on(0, 60, 100)
        when = _last_when(h.scheduled)
        assert 0.005 <= when - t0 <= 0.040
