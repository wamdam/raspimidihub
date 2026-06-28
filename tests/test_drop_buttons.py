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
#
# Trigger-note semantics mirror the on-screen drop button: a quick press +
# release fires, a hold past 0.5s captures. The fire/capture decision
# happens at note-off (or velocity-0 note-on which the engine routes to
# on_note_off). To test the timing branch deterministically these tests
# patch the `_drop_note_press` press_time directly instead of sleeping.

class TestNoteTrigger:
    def test_short_press_fires_on_note_off(self):
        p = _new(_FakeBus(tick=200))
        p._param_values["drop_notes"] = {"1": 60}
        p._param_values["drop_modes"]["1"] = "bar"
        p._param_values["drop_snapshots"]["1"] = {"f1": 99}
        p.on_note_on(5, 60, 80)
        # Still pending — fire/capture decision is deferred to note-off.
        assert p._param_values["drop_schedule"] is None
        assert "1" in p._drop_note_press
        # Quick release -> fire.
        p.on_note_off(5, 60)
        assert p._param_values["drop_states"]["1"] == "scheduled"
        assert p._param_values["drop_schedule"]["hard"]["button_id"] == 1
        assert "1" not in p._drop_note_press

    def test_long_hold_captures_on_note_off(self):
        # Hold past 0.5s -> capture (no fire). Cell values become the
        # snapshot for that button, exactly like a long-press on the
        # on-screen drop button.
        import time as _t
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_notes"] = {"2": 60}
        p._param_values["f1"] = 42
        p._param_values["b1"] = True
        p.on_note_on(0, 60, 100)
        # Backdate the pending press so the duration check trips capture.
        p._drop_note_press["2"] = _t.monotonic() - 0.6
        p.on_note_off(0, 60)
        # Fire path was NOT taken (no schedule, no fire flash).
        assert p._param_values["drop_schedule"] is None
        # Capture path WAS taken — snapshot holds every bound cell with
        # a current value. Cells the test never poked stay absent
        # (_capture_drop skips None values, see controller_base).
        snap = p._param_values["drop_snapshots"]["2"]
        assert snap == {"f1": 42, "b1": True}
        assert p._param_values["drop_states"]["2"] == "captured"
        assert "2" not in p._drop_note_press

    def test_velocity_zero_routes_to_release_path(self):
        # Velocity-0 note-on is a note-off in MIDI. The engine converts
        # it to on_note_off; on_note_on must NOT add a press for it.
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_notes"] = {"0": 60}
        p._param_values["drop_modes"]["0"] = "bar"
        p._param_values["drop_snapshots"]["0"] = {"f1": 50}
        p.on_note_on(0, 60, 0)
        assert "0" not in p._drop_note_press
        assert p._param_values["drop_schedule"] is None

    def test_note_with_no_match_does_nothing(self):
        # Note 60 with no matching binding leaves nothing pending and
        # nothing scheduled.
        p = _new()
        p._param_values["drop_notes"] = {"0": 36}
        p.on_note_on(0, 60, 80)
        p.on_note_off(0, 60)
        assert p._drop_note_press == {}
        assert p._param_values["drop_schedule"] is None

    def test_unbound_button_short_press_is_silent(self):
        # Snapshot empty -> short press fires _fire_drop which no-ops
        # (no snapshot to fire). State stays idle, no schedule armed.
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_notes"] = {"0": 60}
        p._param_values["drop_snapshots"] = {}
        p.on_note_on(0, 60, 80)
        p.on_note_off(0, 60)
        assert p._param_values["drop_schedule"] is None

    def test_unbound_button_long_hold_captures_first_time(self):
        # Empty snapshot + long hold -> capture populates it, just like
        # the very first long-press on a fresh on-screen button.
        import time as _t
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_notes"] = {"3": 60}
        p._param_values["f1"] = 11
        p.on_note_on(0, 60, 80)
        p._drop_note_press["3"] = _t.monotonic() - 0.6
        p.on_note_off(0, 60)
        assert p._param_values["drop_states"]["3"] == "captured"
        assert p._param_values["drop_snapshots"]["3"]["f1"] == 11

    def test_repeated_note_on_keeps_original_press_time(self):
        # If a noisy MIDI source double-fires note-on without a note-off
        # in between, the second arrival must NOT reset the press timer
        # (which would let an actually-long hold be misread as short).
        import time as _t
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_notes"] = {"0": 60}
        p.on_note_on(0, 60, 80)
        first = p._drop_note_press["0"]
        # Backdate so we'd capture if this arrival is honoured.
        p._drop_note_press["0"] = _t.monotonic() - 0.6
        p.on_note_on(0, 60, 80)  # duplicate
        # Press time still the backdated one (not refreshed by the dup).
        assert p._drop_note_press["0"] != first  # backdated, not refreshed
        assert p._drop_note_press["0"] < _t.monotonic() - 0.55

    def test_note_off_without_press_is_noop(self):
        # Stray note-off (e.g. plugin restarted mid-hold) is ignored.
        p = _new(_FakeBus(tick=0))
        p._param_values["drop_notes"] = {"0": 60}
        p._param_values["drop_snapshots"]["0"] = {"f1": 50}
        p.on_note_off(0, 60)
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


# --- Pre-tick CC scheduling --------------------------------------------------
#
# The CC bytes for a drop's snapshot must arrive at the destination synth
# BEFORE tick 0 of the new bar (otherwise the bar's first downbeat plays
# in the old mute state). Both hard and fade slots pre-schedule their
# snapshot via the ALSA queue at fire_at_monotonic - DROP_FIRE_LEAD_S; if
# the clock period EMA isn't ready yet the slot falls back to an
# immediate _apply_snapshot at fire moment.

class _ClockedFakeBus(_FakeBus):
    """FakeBus that also exposes tick_to_monotonic so pre-schedule fires."""
    def __init__(self, tick=0, tpb=96, period=0.020833):
        super().__init__(tick=tick, tpb=tpb)
        self._period = period

    def tick_to_monotonic(self, tick):
        # Linear forecast from now. Tests don't care about the actual
        # monotonic origin, only that a non-None float comes back so the
        # pre-schedule path is taken.
        return 1000.0 + (tick - self._tick_count) * self._period


def _new_with_queue(bus=None):
    p = _new(bus=bus)
    p._scheduled: list[tuple[float, int, int, int, int]] = []
    p.send_cc_at = (lambda when, ch, cc, v, tag=0:
                    p._scheduled.append((when, ch, cc, v, tag)))
    p.cancel_scheduled = lambda tag: None
    return p


class TestPreScheduledSnapshot:
    def test_hard_pre_schedules_button_cc_ahead_of_bar(self):
        # Button mute snapshot must hit the ALSA queue 8 ms before the
        # bar boundary, not on/after it.
        bus = _ClockedFakeBus(tick=0)
        p = _new_with_queue(bus)
        p._param_values["drop_modes"] = {"0": "bar", "1": "bar", "2": "bar", "3": "bar"}
        p._param_values["drop_fade"] = {"0": False}
        p._param_values["drop_sync"] = {"0": False}
        # Snapshot mutes b1 (button on CC 13).
        p._param_values["drop_snapshots"]["0"] = {"b1": 1}
        p._param_values["b1"] = 0
        p._fire_drop("0")
        # One scheduled CC for b1, fired at fire_at - lead.
        assert len(p._scheduled) == 1
        when, ch, cc, val, _tag = p._scheduled[0]
        assert (ch, cc, val) == (0, 13, 127)  # button "on" → CC 127
        # fire_at = now+96 ticks, lead = 8 ms; period = 20.833 ms/tick.
        expected = 1000.0 + 96 * 0.020833 - 0.008
        assert abs(when - expected) < 1e-6
        # Slot remembers it was pre-scheduled.
        slot = p._param_values["drop_schedule"]["hard"]
        assert slot["pre_scheduled"] is True

    def test_fade_pre_schedules_discrete_snapshot_too(self):
        # Regression: fade mode used to leave button/xypad snapshots
        # un-scheduled, so the mute didn't apply until tick 0 of the
        # new bar fired — too late to be heard on the downbeat.
        bus = _ClockedFakeBus(tick=0)
        p = _new_with_queue(bus)
        p._param_values["drop_modes"] = {"0": "bar", "1": "bar", "2": "bar", "3": "bar"}
        p._param_values["drop_fade"] = {"0": True}
        p._param_values["drop_sync"] = {"0": False}
        p._param_values["drop_snapshots"]["0"] = {"b1": 1}
        p._param_values["b1"] = 0
        p._fire_drop("0")
        # Pre-schedule must have fired for fade just like for hard.
        assert len(p._scheduled) == 1
        slot = p._param_values["drop_schedule"]["fade"]
        assert slot["pre_scheduled"] is True

    def test_fire_moment_skips_resend_when_pre_scheduled(self):
        # When pre-scheduled, _tick_slot at fire_at_tick must only flip
        # the on-screen state — sending the CC again would double up.
        bus = _ClockedFakeBus(tick=0)
        p = _new_with_queue(bus)
        p._param_values["drop_modes"] = {"0": "bar", "1": "bar", "2": "bar", "3": "bar"}
        p._param_values["drop_fade"] = {"0": False}
        p._param_values["drop_sync"] = {"0": False}
        p._param_values["drop_snapshots"]["0"] = {"b1": 1}
        p._param_values["b1"] = 0
        p._fire_drop("0")
        p._sent.clear()  # ignore any incidental send_cc calls
        bus._tick_count = 96
        p.on_tick("1/16")
        # State flipped, no fresh send_cc.
        assert p._param_values["b1"] == 1
        assert p._sent == []

    def test_fallback_to_apply_snapshot_when_clock_not_ready(self):
        # When tick_to_monotonic returns None (only one tick observed so
        # far → no period EMA), pre-schedule is skipped. At fire moment
        # the CC must still be emitted — falling back to state-only
        # would leave the synth in the old mute state forever.
        bus = _FakeBus(tick=0)  # no tick_to_monotonic at all
        p = _new_with_queue(bus)
        p._param_values["drop_modes"] = {"0": "bar", "1": "bar", "2": "bar", "3": "bar"}
        p._param_values["drop_fade"] = {"0": False}
        p._param_values["drop_sync"] = {"0": False}
        p._param_values["drop_snapshots"]["0"] = {"b1": 1}
        p._param_values["b1"] = 0
        p._fire_drop("0")
        assert p._scheduled == []  # nothing pre-scheduled
        slot = p._param_values["drop_schedule"]["hard"]
        assert slot["pre_scheduled"] is False
        bus._tick_count = 96
        p.on_tick("1/16")
        # CC was emitted at fire moment via the immediate-send fallback.
        assert (0, 13, 127) in p._sent


# --- Dirty gating: firing a drop is performance, not an edit -----------------
#
# A drop-button *press* (fire / cancel) is a momentary action edge, like a
# Tracker pattern launch — it must NOT paint the Routing asterisk or churn
# the autosave. *Capturing* a drop writes drop_snapshots (real saved config)
# and still dirties. The fake notify below mirrors the host's
# PluginHost._on_param_change gating so we test the end-to-end consequence.

def _wire_dirty(p):
    state = {"dirty": False, "calls": []}

    def notify(name, value, persist=True):
        state["calls"].append((name, persist))
        if persist and name not in p.transient_params:
            state["dirty"] = True

    p._notify_param_change = notify
    return state


def test_drops_param_is_transient():
    p = _new()
    assert "drops" in p.transient_params
    # …but the captured snapshot is NOT (capturing is a real edit).
    assert "drop_snapshots" not in p.transient_params


def test_firing_a_drop_does_not_dirty():
    p = _new()
    # Pre-seed a snapshot directly (not via set_param) so the fire itself
    # is the only thing under test; immediately-mode fires on press.
    p._param_values["drop_snapshots"]["1"] = {"f1": 64}
    p._param_values["drop_modes"]["1"] = "immediately"
    state = _wire_dirty(p)
    # Replicate the host: deliver the press, then run the handler.
    p.set_param("drops", {"action": "fire", "button_id": 1})
    p.on_param_change("drops", {"action": "fire", "button_id": 1})
    assert state["dirty"] is False


def test_capturing_a_drop_dirties():
    p = _new()
    p._param_values["f1"] = 100  # something to snapshot
    state = _wire_dirty(p)
    p.set_param("drops", {"action": "capture", "button_id": 1})
    p.on_param_change("drops", {"action": "capture", "button_id": 1})
    # Capture wrote drop_snapshots (non-transient) → real edit → dirty.
    assert state["dirty"] is True
    assert p._param_values["drop_snapshots"].get("1") == {"f1": 100}
