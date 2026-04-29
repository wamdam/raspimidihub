"""Drop-button server-side behaviour: schedule shapes (synced vs free),
fade interpolation per 1/16 tick, note-trigger via incoming MIDI.

These tests don't run the asyncio plugin host — they construct a
ControllerBase subclass directly and poke its `_param_values` as the
host would. The clock bus is a small fake exposing `_tick_count` and
`_ticks_per_bar`."""

from __future__ import annotations

from raspimidihub.controller_base import ControllerBase
from raspimidihub.plugin_api import (
    Button,
    DropButtonRow,
    Fader,
    Knob,
    LayoutCell,
    LayoutGrid,
)


class _FakeBus:
    """Stand-in for ClockBus — only the bits ControllerBase reads."""
    def __init__(self, tick=0, tpb=96):
        self._tick_count = tick
        self._ticks_per_bar = tpb

    def ticks_until_next_grid(self, n):
        cur_bar = self._tick_count // self._ticks_per_bar
        next_grid_bar = ((cur_bar // n) + 1) * n
        return next_grid_bar * self._ticks_per_bar - self._tick_count


class _C(ControllerBase):
    """Minimal controller with two faders, one knob, one button.
    Sched modes 'bar' (1 bar) and '4bar' (4 bars). 4 drop buttons."""
    NAME = "TestCtrl"
    params = [
        DropButtonRow(
            "drops", "DROPS",
            count=ControllerBase.DROP_BUTTON_COUNT,
            states_param="drop_states",
            snapshots_param="drop_snapshots",
            modes_param="drop_modes",
            labels_param="drop_labels",
            schedule_param="drop_schedule",
            sync_param="drop_sync",
            fade_param="drop_fade",
            notes_param="drop_notes",
        ),
        LayoutGrid(
            "g", "",
            cols=4, rows=1,
            labels_param="cell_labels",
            bindings_param="cell_bindings",
            learn_param="cell_learn",
            cells=[
                LayoutCell(Fader("f1", "F1", min=0, max=127, default=0,
                                 vertical=True), col=1, row=1, channel=0, cc=10),
                LayoutCell(Fader("f2", "F2", min=0, max=127, default=0,
                                 vertical=True), col=2, row=1, channel=0, cc=11),
                LayoutCell(Knob("k1", "K1", min=0, max=127, default=0),
                           col=3, row=1, channel=0, cc=12),
                LayoutCell(Button("b1", "B1", color="green"),
                           col=4, row=1, channel=0, cc=13),
            ],
        ),
    ]


def _new(bus=None):
    """Instantiate the controller, run on_start, attach a recording stub
    for send_cc + clock_bus accessor."""
    p = _C()
    p._notify_param_change = None  # not needed for these tests
    p.on_start()
    p._sent: list[tuple[int, int, int]] = []
    p.send_cc = lambda ch, cc, v: p._sent.append((ch, cc, v))
    if bus is not None:
        p._clock_bus = bus
    return p


# --- Schedule shape ----------------------------------------------------------
#
# drop_schedule is `{fade: <slot>|None, hard: <slot>|None}` (or None when both
# are empty). Each slot carries the {button_id, set_at_tick, fire_at_tick,
# cycle_start_tick, every_n_bars, progress, synced} payload. A button's slot
# identity is decided by its `drop_fade` flag at press time.

class TestFireDropSyncMode:
    def test_synced_quantizes_to_next_4bar_grid(self):
        # Press at tick 281 (= bar 2 + 89 ticks, with tpb=96). Mode 4bar.
        # Next 4-bar grid line is bar 4 = tick 384. So fire_at=384,
        # cycle_start=384-384=0, set_at=281. Hard slot (fade=False default).
        p = _new(_FakeBus(tick=281))
        p._param_values["drop_modes"]["1"] = "4bar"
        p._param_values["drop_snapshots"]["1"] = {"f1": 64}
        p._fire_drop("1")
        sched = p._param_values["drop_schedule"]
        assert sched["fade"] is None
        slot = sched["hard"]
        assert slot["button_id"] == 1
        assert slot["set_at_tick"] == 281
        assert slot["fire_at_tick"] == 384
        assert slot["cycle_start_tick"] == 0
        assert slot["every_n_bars"] == 4
        assert slot["synced"] is True

    def test_synced_pressed_on_grid_fires_at_next_grid(self):
        # Press exactly on a 4-bar grid line — fire goes to the NEXT one,
        # not the current. Cycle starts at the upcoming grid.
        p = _new(_FakeBus(tick=384))  # bar 4, exactly on the grid
        p._param_values["drop_modes"]["0"] = "4bar"
        p._param_values["drop_snapshots"]["0"] = {"f1": 100}
        p._fire_drop("0")
        slot = p._param_values["drop_schedule"]["hard"]
        assert slot["fire_at_tick"] == 768   # bar 8
        assert slot["cycle_start_tick"] == 384


class TestFireDropFreeMode:
    def test_free_starts_fresh_countdown_from_press(self):
        # sync=False: ignores the grid, fires N bars after press.
        p = _new(_FakeBus(tick=200))
        p._param_values["drop_modes"]["2"] = "2bar"
        p._param_values["drop_sync"]["2"] = False
        p._param_values["drop_snapshots"]["2"] = {"f1": 50}
        p._fire_drop("2")
        slot = p._param_values["drop_schedule"]["hard"]
        assert slot["set_at_tick"] == 200
        assert slot["fire_at_tick"] == 200 + 2 * 96  # = 392
        assert slot["cycle_start_tick"] == 200       # fresh countdown
        assert slot["every_n_bars"] == 2
        assert slot["synced"] is False

    def test_free_progress_starts_at_zero(self):
        p = _new(_FakeBus(tick=200))
        p._param_values["drop_modes"]["0"] = "bar"
        p._param_values["drop_sync"]["0"] = False
        p._param_values["drop_snapshots"]["0"] = {"f1": 50}
        p._fire_drop("0")
        # Synced mode would jump in at the cycle's mid-point progress;
        # free mode always starts at 0.
        assert p._param_values["drop_schedule"]["hard"]["progress"] == 0.0


# --- Fade interpolation ------------------------------------------------------

class TestFadeInterpolation:
    def test_capture_start_values_at_press(self):
        # Fade interpolates from start (cell value at press time) → snapshot.
        p = _new(_FakeBus(tick=0))
        p._param_values["f1"] = 20
        p._param_values["f2"] = 40
        p._param_values["drop_modes"]["0"] = "bar"
        p._param_values["drop_fade"]["0"] = True
        p._param_values["drop_snapshots"]["0"] = {"f1": 100, "f2": 0}
        p._fire_drop("0")
        starts = p._drop_fade_start["0"]
        assert starts == {"f1": 20, "f2": 40}

    def test_step_fade_lerps_continuous_cells(self):
        p = _new(_FakeBus(tick=0))
        p._param_values["f1"] = 0
        p._param_values["drop_modes"]["0"] = "bar"
        p._param_values["drop_fade"]["0"] = True
        p._param_values["drop_snapshots"]["0"] = {"f1": 80}
        p._fire_drop("0")
        # At progress=0.5 the fader should be lerp-ed to 40.
        p._step_fade("0", 0.5)
        assert p._param_values["f1"] == 40
        # CC was emitted on channel 0, cc 10, value 40.
        assert (0, 10, 40) in p._sent

    def test_step_fade_emits_only_when_int_value_crosses(self):
        p = _new(_FakeBus(tick=0))
        p._param_values["f1"] = 0
        p._param_values["drop_modes"]["0"] = "bar"
        p._param_values["drop_fade"]["0"] = True
        p._param_values["drop_snapshots"]["0"] = {"f1": 100}
        p._fire_drop("0")
        # First step: progress=0.001 → lerp value=0 (rounds to 0). Same as
        # start, no emit.
        p._sent.clear()
        p._step_fade("0", 0.001)
        assert p._sent == []
        # Step to progress=0.05 → value=5. Emit.
        p._step_fade("0", 0.05)
        assert (0, 10, 5) in p._sent
        # Step again with same progress — no new emit (last_emit dedup).
        p._sent.clear()
        p._step_fade("0", 0.05)
        assert p._sent == []

    def test_buttons_in_snapshot_are_not_faded(self):
        # Cell-buttons (on/off) can't fade; they're skipped during
        # interpolation and snap at fire via _apply_snapshot.
        p = _new(_FakeBus(tick=0))
        p._param_values["b1"] = 0
        p._param_values["drop_modes"]["0"] = "bar"
        p._param_values["drop_fade"]["0"] = True
        p._param_values["drop_snapshots"]["0"] = {"b1": 1}  # toggle on
        p._fire_drop("0")
        p._sent.clear()
        p._step_fade("0", 0.5)
        # No CC emitted for the button mid-fade.
        assert p._sent == []
        # Button cell value untouched mid-fade.
        assert p._param_values["b1"] == 0

    def test_fade_state_cleared_on_cancel(self):
        p = _new(_FakeBus(tick=0))
        p._param_values["f1"] = 0
        p._param_values["drop_modes"]["0"] = "bar"
        p._param_values["drop_fade"]["0"] = True
        p._param_values["drop_snapshots"]["0"] = {"f1": 60}
        p._fire_drop("0")
        assert "0" in p._drop_fade_start
        p._cancel_drop("0")
        assert "0" not in p._drop_fade_start
        assert "0" not in p._drop_fade_last_emit


# --- Note trigger ------------------------------------------------------------

class TestNoteTrigger:
    def test_note_fires_matching_button(self):
        # Server's job: lookup drop_notes for an exact match and fire.
        # Learn (capturing the note) lives in the frontend now —
        # PluginNoteSelect listens to midi-activity SSE and writes the
        # note back via the normal param-change flow.
        p = _new(_FakeBus(tick=200))
        p._param_values["drop_notes"] = {"1": 60}
        p._param_values["drop_modes"]["1"] = "bar"
        p._param_values["drop_snapshots"]["1"] = {"f1": 99}
        p.on_note_on(5, 60, 80)
        assert p._param_values["drop_states"]["1"] == "scheduled"
        assert p._param_values["drop_schedule"]["hard"]["button_id"] == 1

    def test_note_with_no_match_does_nothing(self):
        p = _new()
        p._param_values["drop_notes"] = {"0": 36}
        p.on_note_on(0, 60, 80)
        assert p._param_values["drop_schedule"] is None

    def test_unbound_button_is_not_fired_by_a_random_match(self):
        # Even if the note matches, an empty snapshot means there's
        # nothing to fire — silently ignored.
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_notes"] = {"0": 60}
        p._param_values["drop_snapshots"] = {}
        p.on_note_on(0, 60, 80)
        assert p._param_values["drop_schedule"] is None

    def test_velocity_zero_is_ignored(self):
        # MIDI convention: note-on with velocity 0 = note-off — must
        # not fire any matching button.
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_notes"] = {"0": 60}
        p._param_values["drop_modes"]["0"] = "bar"
        p._param_values["drop_snapshots"]["0"] = {"f1": 50}
        p.on_note_on(0, 60, 0)
        assert p._param_values["drop_schedule"] is None


# --- Dual-slot scheduling ---------------------------------------------------
#
# A fade-mode button schedules into the `fade` slot; a non-fade ("hard") button
# schedules into the `hard` slot. Both slots can be active simultaneously.
# Pressing the same button cancels its slot. Pressing another button targeting
# the same slot replaces that slot's contents (other slot untouched). When the
# hard slot fires, any in-flight fade slot is cancelled (drop wins over fade).

class TestDualSlotScheduling:
    def test_fade_and_hard_run_side_by_side(self):
        # Press fade-button 0, then hard-button 1. Both are scheduled.
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_modes"] = {"0": "bar", "1": "bar", "2": "bar", "3": "bar"}
        p._param_values["drop_fade"] = {"0": True, "1": False, "2": False, "3": False}
        p._param_values["drop_snapshots"]["0"] = {"f1": 80}
        p._param_values["drop_snapshots"]["1"] = {"f2": 30}
        p._fire_drop("0")
        p._fire_drop("1")
        sched = p._param_values["drop_schedule"]
        assert sched["fade"]["button_id"] == 0
        assert sched["hard"]["button_id"] == 1
        assert p._param_values["drop_states"]["0"] == "scheduled"
        assert p._param_values["drop_states"]["1"] == "scheduled"

    def test_hard_press_replaces_hard_slot_keeps_fade(self):
        # Two hard-mode buttons can't coexist; the second press evicts
        # the first. The fade slot is untouched.
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_modes"] = {"0": "bar", "1": "bar", "2": "bar", "3": "bar"}
        p._param_values["drop_fade"] = {"0": True, "1": False, "2": False, "3": False}
        p._param_values["drop_snapshots"]["0"] = {"f1": 80}
        p._param_values["drop_snapshots"]["1"] = {"f1": 60}
        p._param_values["drop_snapshots"]["2"] = {"f1": 40}
        p._fire_drop("0")  # fade slot
        p._fire_drop("1")  # hard slot
        p._fire_drop("2")  # hard slot — evicts 1
        sched = p._param_values["drop_schedule"]
        assert sched["fade"]["button_id"] == 0
        assert sched["hard"]["button_id"] == 2
        assert p._param_values["drop_states"]["1"] == "captured"
        assert p._param_values["drop_states"]["2"] == "scheduled"

    def test_same_button_press_cancels_its_slot_only(self):
        # Pressing the same fade button while it's scheduled cancels
        # the fade slot, leaving the hard slot untouched.
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_modes"] = {"0": "bar", "1": "bar", "2": "bar", "3": "bar"}
        p._param_values["drop_fade"] = {"0": True, "1": False, "2": False, "3": False}
        p._param_values["drop_snapshots"]["0"] = {"f1": 80}
        p._param_values["drop_snapshots"]["1"] = {"f2": 30}
        p._fire_drop("0")
        p._fire_drop("1")
        p._fire_drop("0")  # same button → cancel fade
        sched = p._param_values["drop_schedule"]
        assert sched["fade"] is None
        assert sched["hard"]["button_id"] == 1
        assert p._param_values["drop_states"]["0"] == "captured"
        assert p._param_values["drop_states"]["1"] == "scheduled"

    def test_cancelling_last_slot_collapses_schedule_to_none(self):
        # Wire shape: when both slots empty, drop_schedule is None.
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_modes"]["0"] = "bar"
        p._param_values["drop_snapshots"]["0"] = {"f1": 50}
        p._fire_drop("0")
        p._cancel_drop("0")
        assert p._param_values["drop_schedule"] is None


class TestHardFireCancelsFade:
    def test_hard_slot_fire_cancels_pending_fade(self):
        # Fade slot scheduled at fire_at=192 (2 bars), hard slot at
        # fire_at=96 (1 bar). At tick 96 the hard slot fires; the fade
        # slot should be wiped, and its button bumped back to captured.
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_modes"] = {"0": "2bar", "1": "bar", "2": "bar", "3": "bar"}
        p._param_values["drop_fade"] = {"0": True, "1": False, "2": False, "3": False}
        p._param_values["drop_sync"] = {"0": False, "1": False, "2": False, "3": False}
        p._param_values["drop_snapshots"]["0"] = {"f1": 80}
        p._param_values["drop_snapshots"]["1"] = {"f1": 30}
        p._param_values["f1"] = 0
        p._fire_drop("0")
        p._fire_drop("1")
        # Advance time to just past the hard fire boundary.
        p._clock_bus._tick_count = 96
        p.on_tick("1/16")
        sched = p._param_values["drop_schedule"]
        # Hard fired → its slot cleared; fade also cancelled → schedule None.
        assert sched is None
        assert p._param_values["drop_states"]["0"] == "captured"  # fade evicted
        assert p._param_values["drop_states"]["1"] == "captured"  # hard fired
        # Hard's snapshot landed on f1.
        assert p._param_values["f1"] == 30
        # Fade interpolation was torn down.
        assert "0" not in p._drop_fade_start
        assert "0" not in p._drop_fade_last_emit

    def test_fade_slot_fire_does_not_touch_hard_slot(self):
        # Inverse of the above: fade fires first, hard keeps running.
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_modes"] = {"0": "bar", "1": "2bar", "2": "bar", "3": "bar"}
        p._param_values["drop_fade"] = {"0": True, "1": False, "2": False, "3": False}
        p._param_values["drop_sync"] = {"0": False, "1": False, "2": False, "3": False}
        p._param_values["drop_snapshots"]["0"] = {"f1": 80}
        p._param_values["drop_snapshots"]["1"] = {"f2": 30}
        p._param_values["f1"] = 0
        p._param_values["f2"] = 0
        p._fire_drop("0")  # fade fires at tick 96
        p._fire_drop("1")  # hard fires at tick 192
        p._clock_bus._tick_count = 96
        p.on_tick("1/16")
        sched = p._param_values["drop_schedule"]
        assert sched["fade"] is None
        assert sched["hard"]["button_id"] == 1
        assert p._param_values["f1"] == 80         # fade landed
        assert p._param_values["f2"] == 0          # hard not yet fired
