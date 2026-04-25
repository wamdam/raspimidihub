"""Tests for UiDemo plugin — smoke tests only (no real MIDI processing)."""

from helpers import make_plugin

from ui_demo import UiDemo


class TestUiDemo:
    def test_start_stop_clean(self):
        """on_start/on_stop run without exceptions."""
        p, h = make_plugin(UiDemo)
        # make_plugin already called on_start; just confirm on_stop is clean.
        p.on_stop()

    def test_no_audible_output(self):
        """Demo plugin must not emit notes, CC, or clock — wiring is silent."""
        p, h = make_plugin(UiDemo)
        p.on_note_on(0, 60, 100)
        p.on_note_off(0, 60)
        p.on_cc(0, 1, 64)
        p.on_pitchbend(0, 8192)
        p.on_aftertouch(0, 100)
        p.on_program_change(0, 5)
        p.on_stop()
        assert h.sent == [], f"UI Demo emitted unexpected MIDI: {h.sent}"

    def test_panic_is_noop(self):
        """panic() must not raise and must not emit anything."""
        p, h = make_plugin(UiDemo)
        p.panic()
        p.on_stop()
        assert h.sent == []

    def test_default_params_present(self):
        """Every declared param has a default value — schema is wired up."""
        p, h = make_plugin(UiDemo)
        for key in ("wheel_basic", "fader_h", "toggle_a", "radio_short",
                    "step_count", "steps", "curve", "note_pick", "ch_pick",
                    "button_green"):
            assert key in p._param_values
        p.on_stop()
