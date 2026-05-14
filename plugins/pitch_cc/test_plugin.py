"""Tests for Pitch CC plugin."""

from helpers import make_plugin

from pitch_cc import PitchCC


def _setup(base_note=60, out_cc=49, base_val=64):
    p, h = make_plugin(PitchCC)
    p._param_values["base_note"] = base_note
    p._param_values["out_cc"] = out_cc
    p._param_values["base_cc_value"] = base_val
    return p, h


class TestPitchCC:
    def test_base_note_emits_base_cc_value(self):
        p, h = _setup()
        p.on_note_on(0, 60, 100)
        # CC first, then note. Both on the incoming channel.
        assert h.ccs == [(0, 49, 64)]
        assert h.note_ons == [(0, 60, 100)]

    def test_cc_emitted_before_note_on(self):
        """Order matters: synths like Volca Sample latch pitch at trigger."""
        p, h = _setup()
        p.on_note_on(0, 72, 100)
        # h.sent is the full ordered list of every emitted event.
        kinds = [e[0] for e in h.sent]
        assert kinds == ["cc", "note_on"], f"expected cc before note_on, got {kinds}"

    def test_pitch_shift_up_one_semitone(self):
        p, h = _setup()
        p.on_note_on(0, 61, 100)
        assert h.ccs == [(0, 49, 65)]

    def test_pitch_shift_down_one_semitone(self):
        p, h = _setup()
        p.on_note_on(0, 59, 100)
        assert h.ccs == [(0, 49, 63)]

    def test_clamp_low(self):
        """A note far below the base clamps at 0, not negative."""
        p, h = _setup(base_note=60, base_val=10)
        p.on_note_on(0, 24, 100)  # 10 + (24 - 60) = -26 → 0
        assert h.ccs == [(0, 49, 0)]
        assert h.note_ons == [(0, 24, 100)]

    def test_clamp_high(self):
        p, h = _setup(base_note=60, base_val=120)
        p.on_note_on(0, 100, 100)  # 120 + 40 = 160 → 127
        assert h.ccs == [(0, 49, 127)]

    def test_note_off_forwards_without_cc(self):
        p, h = _setup()
        p.on_note_off(0, 64)
        assert h.ccs == []
        assert h.note_offs == [(0, 64)]

    def test_velocity_preserved(self):
        p, h = _setup()
        p.on_note_on(0, 60, 73)
        assert h.note_ons == [(0, 60, 73)]

    def test_velocity_zero_treated_as_note_off(self):
        """Running-status note-off must NOT emit a pitch CC."""
        p, h = _setup()
        p.on_note_on(0, 60, 0)
        assert h.ccs == []
        assert h.note_offs == [(0, 60)]
        assert h.note_ons == []

    def test_cc_passes_through(self):
        p, h = _setup()
        p.on_cc(0, 7, 80)
        assert h.ccs == [(0, 7, 80)]
        assert h.note_ons == []

    def test_pitchbend_passes_through(self):
        p, h = _setup()
        p.on_pitchbend(0, 8192)
        assert any(e[0] == "pitchbend" for e in h.sent)

    def test_channel_preserved(self):
        """Plugin output goes out on the incoming channel — the connection
        decides the destination, the plugin doesn't rewrite the channel."""
        p, h = _setup()
        p.on_note_on(9, 64, 100)
        assert h.ccs == [(9, 49, 68)]
        assert h.note_ons == [(9, 64, 100)]

    def test_changing_base_note_shifts_anchor(self):
        p, h = _setup(base_note=60, base_val=64)
        # Change the base note mid-session — next press anchors on the new one.
        p._param_values["base_note"] = 48
        p.on_note_on(0, 48, 100)
        assert h.ccs == [(0, 49, 64)]
        h.clear()
        p.on_note_on(0, 50, 100)
        assert h.ccs == [(0, 49, 66)]
