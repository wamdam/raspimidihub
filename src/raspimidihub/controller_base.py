"""Shared base class for §5 Controller plugins.

Each Controller template (Mixer 8, Performance 16, FX 6, …) is a thin
subclass that just declares NAME / DESCRIPTION / HELP and a `params`
list containing one LayoutGrid + the standard DropButtonRow siblings.
All the cell ↔ CC plumbing lives here:

  - on_param_change → emit CC for the cell's effective binding
  - on_cc → MIDI Learn capture (if armed) or bidirectional sync
  - drop button capture / fire / schedule across every bound cell
  - panic resets every cell to its declared default + emits the CC

The plugin loader filters discovered classes by `__module__` so this
base — even though it's a `PluginBase` subclass — is *not* picked up
as a plugin in its own right.
"""

import time
from typing import Any

from raspimidihub.plugin_api import LayoutGrid, PluginBase

# Hold duration past which a trigger-note press becomes a capture
# instead of a fire. Mirrors LONG_PRESS_MS = 500 in dropbuttonrow.js
# so the on-screen button and an external keyboard / pedal binding
# behave identically.
_NOTE_LONG_PRESS_S = 0.5


class ControllerBase(PluginBase):
    """Common cell/binding/drop-button logic for §5 Controller templates.

    Subclasses override metadata (NAME / DESCRIPTION / HELP / VERSION /
    AUTHOR) and `params`. `params` MUST contain exactly one LayoutGrid
    whose cells declare `channel` and `cc` defaults; the LayoutGrid
    SHOULD point at sibling params named `cell_labels`, `cell_bindings`,
    `cell_learn`, plus a `DropButtonRow` (whose auxiliary params are
    `drop_states`, `drop_snapshots`, `drop_modes`, `drop_labels`,
    `drop_schedule`) for full functionality."""

    inputs = ["CC (bidirectional sync — silent UI updates, no re-emit)"]
    outputs = ["CC per cell — see HELP for default channel/cc bindings"]

    # Eight predefined dark backgrounds the user can pick per instance.
    # Strings are user-facing; the JS lower-cases them to derive a
    # `.bg-<name>` class on the Controller page surface.
    BG_OPTIONS = ["Default", "Navy", "Forest", "Wine", "Plum", "Teal", "Sienna", "Slate"]

    # Number of drop buttons on every Controller. Mirrored by the
    # DropButtonRow's `count` attribute in the schema.
    DROP_BUTTON_COUNT = 4

    # Allowed mode values per button. Wheel UI exposes these in
    # left-to-right order. The bar-modes are musical-grid-quantised
    # (NOT "wait N bars"): pressing during bar 5 with mode='4bar'
    # fires at bar 8 (the next 4-bar downbeat), not bar 9.
    DROP_MODES = ("immediately", "bar", "2bar", "4bar", "8bar", "16bar")
    DROP_MODE_GRID_BARS = {"bar": 1, "2bar": 2, "4bar": 4, "8bar": 8, "16bar": 16}

    # Drop-button auxiliary params that represent live-play state, NOT
    # config: drop_states cycles through fire/capture/idle on every
    # press; drop_schedule holds whatever fire is currently scheduled;
    # drop_note_pressing is an SSE flag for the on-screen press-fill
    # animation while a trigger note is held; cell_learn is a transient
    # "next CC binds this cell" toggle. Captured snapshots, modes,
    # labels, sync/fade flags, trigger-note bindings, theme, cell
    # rename/rebind ARE config and stay outside this set.
    _DROP_TRANSIENT_PARAMS = frozenset({
        "drop_states", "drop_schedule", "drop_note_pressing", "cell_learn",
    })

    def on_start(self):
        """Initialise non-schema state on first start (and after restore).

        Subclasses can override; if they do, they should call
        `super().on_start()` so the cached lookups stay populated."""
        # Populate the dirty-skip set: drop-state transients plus every
        # cell value param (k0..kN, f0..fN, m0..mN, x0..xN). Faders /
        # knobs / XY positions move during normal play and shouldn't
        # paint the Routing asterisk; only cell renames + rebinds +
        # drop-button settings + bg should.
        transient = set(self._DROP_TRANSIENT_PARAMS)
        for p in self.params:
            if isinstance(p, LayoutGrid):
                for cell in p.cells:
                    transient.add(cell.param.name)
        self.transient_params = transient

        self._param_values.setdefault("cell_labels", {})
        self._param_values.setdefault("cell_bindings", {})
        self._param_values.setdefault("cell_learn", "")
        self._param_values.setdefault("bg", "Default")
        # Per-button drop state. Keys are stringified ids (0..N-1) so
        # the dicts round-trip cleanly through JSON.
        self._param_values.setdefault("drop_snapshots", {})
        self._param_values.setdefault("drop_modes",
                                       {str(i): "immediately"
                                        for i in range(self.DROP_BUTTON_COUNT)})
        self._param_values.setdefault("drop_labels",
                                       {str(i): chr(ord("A") + i)
                                        for i in range(self.DROP_BUTTON_COUNT)})
        # Per-button polish flags. `sync` defaults to true (current
        # behaviour: quantize to the next bar/4-bar/etc. grid line);
        # `fade` defaults to false (current behaviour: hard snap on
        # fire). `notes` is the optional MIDI note that fires this
        # button when received on the controller's IN port. `note_learn`
        # is a transient sid telling on_note_on "the next note is the
        # trigger for THIS button" — UI sets it when the user taps the
        # Learn pill, server clears it the moment a note arrives.
        self._param_values.setdefault("drop_sync",
                                       {str(i): True
                                        for i in range(self.DROP_BUTTON_COUNT)})
        self._param_values.setdefault("drop_fade",
                                       {str(i): False
                                        for i in range(self.DROP_BUTTON_COUNT)})
        # -1 = "Off" (the default). The server's on_note_on check
        # `bound == int(note)` never matches for -1 since incoming
        # MIDI notes are 0..127, so the wheel can sit on Off without
        # any guard logic.
        self._param_values.setdefault("drop_notes",
                                       {str(i): -1
                                        for i in range(self.DROP_BUTTON_COUNT)})
        # Per-button "trigger note currently held" flag, broadcast
        # over SSE so the on-screen drop button can run the same
        # press-fill animation that a touch long-press shows. Reset
        # to all-False on every restart — a held note across a
        # service restart can't survive anyway.
        self._param_values["drop_note_pressing"] = {
            str(i): False for i in range(self.DROP_BUTTON_COUNT)
        }
        # Fade animation runs from start_values → snapshot. start is
        # captured at press time (current cell readings), kept transient
        # in `_drop_fade_start` (instance attr — not persisted, gone on
        # service restart since a fade can't survive that anyway). Last
        # emitted CC value per cell goes in `_drop_fade_last_emit` so
        # we only push CCs when the integer value crosses, keeping the
        # 1/16-cadence fade traffic bounded.
        self._drop_fade_start: dict[str, dict] = {}
        self._drop_fade_last_emit: dict[str, dict] = {}
        # Pending trigger-note presses: sid -> press time (monotonic).
        # Populated on note-on, drained on note-off. The held duration
        # decides fire (short) vs capture (long), same as the on-screen
        # drop button. Transient — service restart drops in-flight holds.
        self._drop_note_press: dict[str, float] = {}
        # Derived: button is 'captured' iff its snapshot is non-empty,
        # else 'idle'. Scheduled state is layered on by _handle_drop_action.
        snaps = self._param_values["drop_snapshots"]
        self._param_values["drop_states"] = {
            str(i): ("captured" if snaps.get(str(i)) else "idle")
            for i in range(self.DROP_BUTTON_COUNT)
        }
        # Controller-wide schedule reference. None when nothing is
        # pending; otherwise `{fade: <slot>|None, hard: <slot>|None}`
        # where each slot is `{button_id, set_at_tick, fire_at_tick,
        # cycle_start_tick, every_n_bars, progress, synced}`. Two slots
        # so a fade-mode button can run alongside a hard-drop button —
        # if the hard slot fires, any in-flight fade is cancelled
        # (drop wins over a pending fade). Pressing the same button
        # again cancels its slot. Pressing another button that maps to
        # the same slot replaces the slot's contents.
        self._param_values["drop_schedule"] = None
        # Action signal sent FROM the UI to the server: {action, button_id}.
        # Reset to {"action": "idle"} after handling.
        self._param_values["drops"] = {"action": "idle"}
        # Derived from the schema once per instance.
        self._defaults: dict[str, tuple[int, int]] = {}
        self._defaults_y: dict[str, int] = {}  # XY-pad Y-axis CC
        self._defaults_y_channel: dict[str, int] = {}  # XY-pad Y-axis channel (if separate)
        self._cell_types: dict[str, str] = {}
        self._cell_default_values: dict[str, Any] = {}
        for p in self.__class__.params:
            if isinstance(p, LayoutGrid):
                for c in p.cells:
                    name = c.param.name
                    if c.channel is not None and c.cc is not None:
                        self._defaults[name] = (c.channel, c.cc)
                    if c.cc_y is not None:
                        self._defaults_y[name] = c.cc_y
                    if c.channel_y is not None:
                        self._defaults_y_channel[name] = c.channel_y
                    self._cell_types[name] = type(c.param).__name__.lower()
                    if hasattr(c.param, "default"):
                        self._cell_default_values[name] = c.param.default
                    elif type(c.param).__name__.lower() == "xypad":
                        self._cell_default_values[name] = {
                            "x": getattr(c.param, "default_x", 0),
                            "y": getattr(c.param, "default_y", 0),
                        }

    # --- Helpers ---

    # Default on / off CC values for button cells. The user can override
    # both per cell via the edit-mode UI (e.g. on=64, off=0 for a partial
    # toggle, or 0/127 to invert the polarity).
    _BUTTON_DEFAULT_ON = 127
    _BUTTON_DEFAULT_OFF = 0

    def _effective_binding(self, cell_name: str) -> dict | None:
        """Return a dict `{channel, cc, [on, off for buttons], [cc_y for
        xypads]}` with the user's per-cell override layered over the
        schema's default. Only complete overrides take effect — partial
        dicts fall back to the schema."""
        default = self._defaults.get(cell_name)
        if default is None:
            return None
        ch, cc = default
        cell_type = self._cell_types.get(cell_name, "")
        is_button = cell_type == "button"
        is_xypad = cell_type == "xypad"
        binding: dict = {"channel": ch, "cc": cc}
        if is_button:
            binding["on"] = self._BUTTON_DEFAULT_ON
            binding["off"] = self._BUTTON_DEFAULT_OFF
        if is_xypad:
            if cell_name in self._defaults_y:
                binding["cc_y"] = self._defaults_y[cell_name]
            # Y channel defaults to X channel unless the schema or
            # an override sets it otherwise.
            binding["channel_y"] = self._defaults_y_channel.get(cell_name, ch)
        ov = (self._param_values.get("cell_bindings") or {}).get(cell_name)
        if isinstance(ov, dict):
            if isinstance(ov.get("channel"), int):
                binding["channel"] = ov["channel"]
            if isinstance(ov.get("cc"), int):
                binding["cc"] = ov["cc"]
            if is_button:
                if isinstance(ov.get("on"), int):
                    binding["on"] = max(0, min(127, ov["on"]))
                if isinstance(ov.get("off"), int):
                    binding["off"] = max(0, min(127, ov["off"]))
            if is_xypad:
                if isinstance(ov.get("cc_y"), int):
                    binding["cc_y"] = max(0, min(127, ov["cc_y"]))
                if isinstance(ov.get("channel_y"), int):
                    binding["channel_y"] = max(0, min(15, ov["channel_y"]))
        return binding

    def _cell_value_to_cc(self, cell_name: str, value: Any, binding: dict) -> int | None:
        """Translate a cell's stored value to a 0..127 CC byte."""
        if self._cell_types.get(cell_name) == "button":
            return binding["on"] if bool(value) else binding["off"]
        if isinstance(value, bool):
            return 127 if value else 0
        if isinstance(value, int):
            return max(0, min(127, value))
        return None

    def _store_cc_into_cell(self, cell_name: str, cc_value: int, binding: dict) -> Any:
        """Translate an incoming CC byte into the right Python type for
        a cell's stored value. For buttons, "closer to on or off?" wins —
        so it works whether the user picks 0/127 or e.g. 0/64."""
        if self._cell_types.get(cell_name) == "button":
            on = binding.get("on", self._BUTTON_DEFAULT_ON)
            off = binding.get("off", self._BUTTON_DEFAULT_OFF)
            return abs(cc_value - on) < abs(cc_value - off)
        return cc_value

    # --- Event handlers ---

    def on_param_change(self, name, value):
        """User moved a cell -> emit its CC, OR drop button fired -> dispatch."""
        if name == "drops":
            self._handle_drop_action(value)
            return
        binding = self._effective_binding(name)
        if binding is None:
            return
        if self._cell_types.get(name) == "xypad":
            self._emit_xypad(value, binding)
            return
        cc_val = self._cell_value_to_cc(name, value, binding)
        if cc_val is None:
            return
        self.send_cc(binding["channel"], binding["cc"], cc_val)

    def _emit_xypad(self, value: Any, binding: dict) -> None:
        """Emit X (channel, cc) and Y (channel_y, cc_y) CCs for an xypad
        cell whose stored value is a `{"x": int, "y": int}` dict."""
        if not isinstance(value, dict):
            return
        ch = binding["channel"]
        x = value.get("x")
        if isinstance(x, int):
            self.send_cc(ch, binding["cc"], max(0, min(127, x)))
        cc_y = binding.get("cc_y")
        y = value.get("y")
        if cc_y is not None and isinstance(y, int):
            ch_y = binding.get("channel_y", ch)
            self.send_cc(ch_y, cc_y, max(0, min(127, y)))

    def on_cc(self, channel, cc, value):
        """MIDI Learn capture (if armed for a cell), else bidirectional
        sync — silently update the matching cell, no OUT re-emit."""
        learn_target = self._param_values.get("cell_learn") or ""
        # XY pads have two independent axes — the learn target encodes
        # which one with a ":x" / ":y" suffix; bare cell name = X axis
        # (the legacy single-axis pads pick this branch unchanged).
        learn_cell = learn_target
        learn_axis = "x"
        if ":" in learn_target:
            learn_cell, _, suffix = learn_target.partition(":")
            if suffix in ("x", "y"):
                learn_axis = suffix
        if learn_cell and learn_cell in self._defaults:
            bindings = dict(self._param_values.get("cell_bindings") or {})
            # Layer the captured axis on top of whatever was there;
            # preserve every other field (the OTHER axis, on/off pair,
            # spring config, ...) so toggling Learn doesn't blow away
            # unrelated config.
            prev = dict(bindings.get(learn_cell) or {})
            if learn_axis == "y":
                prev["channel_y"] = channel
                prev["cc_y"] = cc
            else:
                prev["channel"] = channel
                prev["cc"] = cc
            bindings[learn_cell] = prev
            self.set_param("cell_bindings", bindings)
            self.set_param("cell_learn", "")
            return
        for name in self._defaults:
            binding = self._effective_binding(name)
            if binding is None:
                continue
            cell_type = self._cell_types.get(name, "")
            if cell_type == "xypad":
                # Match either axis on its own (channel, cc); update only
                # that axis in the cell's {x, y} dict. Other axis stays
                # where it was. X uses (channel, cc); Y uses
                # (channel_y, cc_y), where channel_y falls back to
                # channel when not set explicitly.
                axis = None
                if binding["channel"] == channel and binding["cc"] == cc:
                    axis = "x"
                elif (binding.get("channel_y", binding["channel"]) == channel
                      and binding.get("cc_y") == cc):
                    axis = "y"
                if axis is None:
                    continue
                cur = self._param_values.get(name)
                if not isinstance(cur, dict):
                    cur = {"x": 0, "y": 0}
                if cur.get(axis) == value:
                    return
                new_val = {**cur, axis: value}
                self._param_values[name] = new_val
                if self._notify_param_change:
                    try:
                        self._notify_param_change(name, new_val)
                    except Exception:
                        pass
                return
            if binding["channel"] != channel or binding["cc"] != cc:
                continue
            new_val = self._store_cc_into_cell(name, value, binding)
            if self._param_values.get(name) == new_val:
                return
            self._param_values[name] = new_val
            if self._notify_param_change:
                try:
                    self._notify_param_change(name, new_val)
                except Exception:
                    pass
            return

    # Pass-through silence for the other event types — the matrix routes
    # them however the user's wired the plugin's IN port.
    def on_note_on(self, channel, note, velocity):
        """Match an incoming note against the drop_notes bindings and
        record the press time. The actual fire-vs-capture decision waits
        for note-off so a held note can capture (≥0.5s) the same way a
        long-press on the on-screen button does, while a quick tap fires
        (<0.5s). Note channel is ignored — a drop trigger is a global
        "any incoming note=N talks to button X" binding, since the
        typical use case is a single foot pedal or pad on whatever
        channel it happens to be on. Re-arrival while already pressed is
        ignored so the original press_time wins. The Learn flow lives in
        the frontend (PluginNoteSelect listens to midi-activity SSE),
        same pattern as Hold Arp's release_note."""
        if velocity <= 0:  # note-on with velocity 0 = note-off in MIDI
            return
        notes = self._param_values.get("drop_notes") or {}
        for sid, bound in notes.items():
            if bound == int(note):
                if sid not in self._drop_note_press:
                    self._drop_note_press[sid] = time.monotonic()
                    # Broadcast "this button is now held" so the UI
                    # can run the press-fill animation.
                    pressing = dict(self._param_values.get("drop_note_pressing") or {})
                    pressing[sid] = True
                    self.set_param("drop_note_pressing", pressing)
                break

    def on_note_off(self, channel, note):
        """Resolve a pending trigger-note press: <0.5s -> fire, >=0.5s
        -> capture. Mirrors the on-screen button's tap-vs-long-press
        gesture. Note-off without a matching pending press is ignored."""
        notes = self._param_values.get("drop_notes") or {}
        for sid, bound in notes.items():
            if bound != int(note):
                continue
            press_time = self._drop_note_press.pop(sid, None)
            if press_time is None:
                return
            # Clear the pressing flag so the UI's press-fill animation
            # ends — regardless of whether we're about to fire or capture.
            pressing = dict(self._param_values.get("drop_note_pressing") or {})
            if pressing.get(sid):
                pressing[sid] = False
                self.set_param("drop_note_pressing", pressing)
            held = time.monotonic() - press_time
            if held >= _NOTE_LONG_PRESS_S:
                self._capture_drop(sid)
            else:
                self._fire_drop(sid)
            return
    def on_pitchbend(self, channel, value): pass
    def on_aftertouch(self, channel, value): pass
    def on_program_change(self, channel, program): pass

    # --- Drop buttons ---

    def _handle_drop_action(self, value):
        """Dispatch a drop-button action. `value` shape:
        `{action: 'fire'|'capture'|'cancel', button_id: 0..N-1}`.
        After handling, reset `drops` to {action: 'idle'}."""
        if not isinstance(value, dict):
            return
        action = value.get("action")
        bid = value.get("button_id")
        if action in ("fire", "capture", "cancel") and isinstance(bid, int):
            sid = str(bid)
            if 0 <= bid < self.DROP_BUTTON_COUNT:
                if action == "capture":
                    self._capture_drop(sid)
                elif action == "fire":
                    self._fire_drop(sid)
                elif action == "cancel":
                    self._cancel_drop(sid)
        # Reset the action signal so the next press is a fresh edge.
        self.set_param("drops", {"action": "idle"})

    def _capture_drop(self, sid: str) -> None:
        """Snapshot every bound cell's current value into drop[sid]."""
        snap = {}
        for cell_name in self._defaults:
            v = self._param_values.get(cell_name)
            if v is not None:
                snap[cell_name] = v
        snaps = dict(self._param_values.get("drop_snapshots") or {})
        snaps[sid] = snap
        self.set_param("drop_snapshots", snaps)
        states = dict(self._param_values.get("drop_states") or {})
        # If this button was scheduled, capturing replaces its snapshot
        # but keeps it scheduled — fire still happens at the planned bar.
        if states.get(sid) != "scheduled":
            states[sid] = "captured"
            self.set_param("drop_states", states)

    def _schedule_slots(self) -> dict:
        """Read drop_schedule as a {fade, hard} dict, normalising the
        None-when-empty wire form so callers can always do `slots[k]`."""
        s = self._param_values.get("drop_schedule")
        if not s:
            return {"fade": None, "hard": None}
        return {"fade": s.get("fade"), "hard": s.get("hard")}

    def _write_schedule(self, slots: dict) -> None:
        """Persist {fade, hard} slots, collapsing to None when both empty."""
        if slots["fade"] is None and slots["hard"] is None:
            self.set_param("drop_schedule", None)
        else:
            self.set_param("drop_schedule",
                           {"fade": slots["fade"], "hard": slots["hard"]})

    def _fire_drop(self, sid: str) -> None:
        """Press semantics:
        - if THIS button is currently scheduled (in either slot), cancel.
        - else, the button's mode decides:
          - immediately: fire now.
          - bar / 4bar: schedule into our slot. Slot is `fade` if the
            button has fade=True, else `hard`. The OTHER slot keeps
            running so a fade and a hard drop can be in flight at once.
            If our slot is already occupied by a different button, that
            other button is bumped back to captured.
        - empty (no snapshot): no-op.
        """
        states = dict(self._param_values.get("drop_states") or {})
        if states.get(sid) == "scheduled":
            self._cancel_drop(sid)
            return
        snap = (self._param_values.get("drop_snapshots") or {}).get(sid)
        if not snap:
            return  # nothing captured
        modes = self._param_values.get("drop_modes") or {}
        mode = modes.get(sid, "immediately")
        if mode == "immediately":
            self._apply_snapshot(snap)
            # Brief 'firing' flash then back to captured.
            states[sid] = "firing"
            self.set_param("drop_states", states)
            states[sid] = "captured"
            self.set_param("drop_states", states)
            return
        # Schedule at the next bar / 4-bar boundary.
        bus = self._plugin_clock_bus()
        if bus is None:
            # No clock running — fall back to immediate fire so the
            # drop still works even without a master clock.
            self._apply_snapshot(snap)
            states[sid] = "captured"
            self.set_param("drop_states", states)
            return
        every_n_bars = self.DROP_MODE_GRID_BARS.get(mode, 1)
        try:
            now_tick = bus._tick_count  # lock-free read; arithmetic only
            tpb = bus._ticks_per_bar
        except AttributeError:
            self._apply_snapshot(snap)
            return

        sync = bool((self._param_values.get("drop_sync") or {}).get(sid, True))
        fade = bool((self._param_values.get("drop_fade") or {}).get(sid, False))
        slot_key = "fade" if fade else "hard"

        if sync:
            # Quantize to the next bar boundary on the musical grid
            # (1 = every bar; 4/8/16 = every 4/8/16-bar downbeat).
            # NOT "wait N bars" — pressing during bar 5 with mode='4bar'
            # fires at bar 8, not bar 9.
            ticks_left = bus.ticks_until_next_grid(every_n_bars)
            fire_at_tick = now_tick + ticks_left
            # Cycle-relative ring: idle ring runs in lockstep with the
            # music; on press the scheduled ring picks up at the
            # current cycle position so it doesn't visually restart.
            cycle_total = every_n_bars * tpb
            cycle_start_tick = fire_at_tick - cycle_total
        else:
            # Free mode: press starts a fresh N-bar countdown from now.
            # No cycle synchronisation — every press takes the same time
            # regardless of where the music is. Ring starts at 0 and
            # fills over exactly the press-to-fire window.
            cycle_total = every_n_bars * tpb
            fire_at_tick = now_tick + cycle_total
            cycle_start_tick = now_tick

        # Bump anything already in OUR slot. The other slot is left
        # alone — fade and hard run side by side.
        slots = self._schedule_slots()
        bumped = slots[slot_key]
        if bumped:
            other_sid = str(bumped["button_id"])
            states[other_sid] = "captured" if (
                self._param_values.get("drop_snapshots") or {}).get(other_sid) else "idle"
            self._drop_fade_start.pop(other_sid, None)
            self._drop_fade_last_emit.pop(other_sid, None)
            # The bumped button's pre-scheduled CCs (if any) must be
            # cancelled so they don't fire alongside the new schedule.
            self.cancel_scheduled(self._drop_tag_for(other_sid))
        states[sid] = "scheduled"
        self.set_param("drop_states", states)

        # Pre-schedule the snapshot CCs via the ALSA queue ahead of the
        # bar boundary, so the new state is in effect before any
        # downbeat event lands at the destination synth. Hard slot only
        # — fade still steps per-tick (Phase 2/3 migration). Skip if
        # the clock-bus mapping isn't ready yet (no ticks observed) —
        # _tick_slot will still _apply_snapshot at fire moment as a
        # safety net.
        if not fade:
            tick_to_monotonic = getattr(bus, "tick_to_monotonic", None)
            if callable(tick_to_monotonic):
                fire_at_monotonic = tick_to_monotonic(fire_at_tick)
                if fire_at_monotonic is not None:
                    self._schedule_snapshot(
                        snap, fire_at_monotonic, self._drop_tag_for(sid))

        # If fade is enabled, capture the CURRENT cell values so the
        # fade interpolates from where we are now (not from where the
        # cycle started or from the snapshot). On press near the end
        # of a synced cycle there's only a small remaining window —
        # the fade just runs faster, hitting the snapshot at fire.
        if fade:
            self._drop_fade_start[sid] = {
                cell: self._param_values.get(cell)
                for cell in snap
                if self._param_values.get(cell) is not None
            }
            self._drop_fade_last_emit[sid] = {}
        else:
            self._drop_fade_start.pop(sid, None)
            self._drop_fade_last_emit.pop(sid, None)

        progress = round((now_tick - cycle_start_tick) / max(1, cycle_total), 2)
        slots[slot_key] = {
            "button_id": int(sid),
            "set_at_tick": now_tick,
            "fire_at_tick": fire_at_tick,
            "cycle_start_tick": cycle_start_tick,
            "every_n_bars": every_n_bars,
            "progress": progress,
            "synced": sync,
        }
        self._write_schedule(slots)

    def _cancel_drop(self, sid: str) -> None:
        slots = self._schedule_slots()
        bid = int(sid)
        touched = False
        for k in ("fade", "hard"):
            if slots[k] and slots[k].get("button_id") == bid:
                slots[k] = None
                touched = True
        if not touched:
            return
        self._write_schedule(slots)
        # Pull any pre-scheduled CCs for this button out of the ALSA queue
        # so they don't fire after the user cancelled.
        self.cancel_scheduled(self._drop_tag_for(sid))
        states = dict(self._param_values.get("drop_states") or {})
        snaps = self._param_values.get("drop_snapshots") or {}
        states[sid] = "captured" if snaps.get(sid) else "idle"
        self.set_param("drop_states", states)
        self._drop_fade_start.pop(sid, None)
        self._drop_fade_last_emit.pop(sid, None)

    def _apply_snapshot(self, snap: dict) -> None:
        """Re-emit each captured CC + snap on-screen cells to the
        captured value. Used for immediate-fire ("Now" mode) and the
        no-clock fallback. Bar-quantised fires schedule the CCs ahead
        of time via _schedule_snapshot and only run the state side at
        fire moment via _apply_snapshot_state_only."""
        for cell_name, v in snap.items():
            binding = self._effective_binding(cell_name)
            if binding is None:
                continue
            if self._cell_types.get(cell_name) == "xypad":
                self._emit_xypad(v, binding)
            else:
                cc_val = self._cell_value_to_cc(cell_name, v, binding)
                if cc_val is None:
                    continue
                self.send_cc(binding["channel"], binding["cc"], cc_val)
            self._apply_snapshot_cell_state(cell_name, v)

    def _apply_snapshot_cell_state(self, cell_name: str, v) -> None:
        """Update the on-screen cell value for a single snapshot entry
        without re-emitting MIDI. Called at fire moment when the CCs
        have already been delivered via the ALSA queue."""
        if self._param_values.get(cell_name) != v:
            self._param_values[cell_name] = v
            if self._notify_param_change:
                try:
                    self._notify_param_change(cell_name, v)
                except Exception:
                    pass

    def _apply_snapshot_state_only(self, snap: dict) -> None:
        """Mirror the on-screen cells to the snapshot without sending CCs.
        Used after a scheduled-fire, when the CCs already went out via
        the ALSA queue ahead of the bar boundary."""
        for cell_name, v in snap.items():
            self._apply_snapshot_cell_state(cell_name, v)

    # Lead time (seconds) we schedule snapshot CCs ahead of the bar
    # boundary so the new state is in effect before the first audible
    # event of the next bar (e.g. a kick on beat 1). 8 ms covers the
    # typical Pi → ALSA → USB-MIDI → synth path with comfortable
    # headroom; small enough that we never flip into the previous bar.
    DROP_FIRE_LEAD_S = 0.008

    def _drop_tag_for(self, sid: str) -> int:
        """Per-button ALSA-queue event tag (1..127). 0 = no tag.
        Stable across reboots and re-schedules so cancel finds them."""
        try:
            return (int(sid) % 127) + 1
        except (ValueError, TypeError):
            return 0

    def _schedule_snapshot(self, snap: dict, fire_at_monotonic: float,
                           tag: int) -> None:
        """Pre-schedule each snapshot CC for ALSA-queue delivery a few
        ms before the bar boundary. State update happens at fire_at_tick
        in _tick_slot; the CCs themselves arrive at the synth ahead of
        any beat-1 event."""
        when = fire_at_monotonic - self.DROP_FIRE_LEAD_S
        for cell_name, v in snap.items():
            binding = self._effective_binding(cell_name)
            if binding is None:
                continue
            ctype = self._cell_types.get(cell_name)
            if ctype == "xypad":
                if not isinstance(v, dict):
                    continue
                ch = binding["channel"]
                if isinstance(v.get("x"), int):
                    self.send_cc_at(when, ch, binding["cc"],
                                    max(0, min(127, v["x"])), tag)
                cc_y = binding.get("cc_y")
                if cc_y is not None and isinstance(v.get("y"), int):
                    ch_y = binding.get("channel_y", ch)
                    self.send_cc_at(when, ch_y, cc_y,
                                    max(0, min(127, v["y"])), tag)
            else:
                cc_val = self._cell_value_to_cc(cell_name, v, binding)
                if cc_val is None:
                    continue
                self.send_cc_at(when, binding["channel"],
                                binding["cc"], cc_val, tag)

    def _plugin_clock_bus(self):
        """Return the host's ClockBus or None if not yet wired. Set by
        the plugin host on _start_instance."""
        return getattr(self, "_clock_bus", None)

    # --- Clock-bus hooks (drives the schedule countdown) ---

    # Subscribe to 1/16 ticks for progress updates (16 ticks/bar at
    # 24 PPQN... wait that's wrong). 1/16 = every 6 ticks at 24 PPQN.
    # 96/6 = 16 progress updates per bar — smooth enough for the
    # circular border, light enough for SSE.
    clock_divisions = ["1/16"]

    def on_tick(self, division: str) -> None:
        """Drive the scheduled-drop countdown for both slots. Also lets
        subclasses hook other divisions if they override."""
        if division != "1/16":
            return
        slots = self._schedule_slots()
        if slots["fade"] is None and slots["hard"] is None:
            return
        bus = self._plugin_clock_bus()
        if bus is None:
            return
        now_tick = bus._tick_count

        # Step the hard slot first. If it fires this tick, any in-flight
        # fade slot is cancelled — the hard drop wins over a pending
        # fade (per design: pressing a hard drop after a fade should
        # cut the fade short and snap to the hard target).
        new_hard, hard_fired = self._tick_slot(slots["hard"], now_tick, fade=False)
        new_fade = slots["fade"]
        if hard_fired and new_fade is not None:
            fade_sid = str(new_fade["button_id"])
            self._drop_fade_start.pop(fade_sid, None)
            self._drop_fade_last_emit.pop(fade_sid, None)
            st = dict(self._param_values.get("drop_states") or {})
            snaps = self._param_values.get("drop_snapshots") or {}
            st[fade_sid] = "captured" if snaps.get(fade_sid) else "idle"
            self.set_param("drop_states", st)
            new_fade = None
        else:
            new_fade, _ = self._tick_slot(new_fade, now_tick, fade=True)

        before = (slots["fade"], slots["hard"])
        after = (new_fade, new_hard)
        if before != after:
            self._write_schedule({"fade": new_fade, "hard": new_hard})

    def _tick_slot(self, slot: dict | None, now_tick: int, *, fade: bool):
        """Advance one slot. Returns `(new_slot_or_None, fired_bool)`.
        `fade=True` means run the fade lerp on each step."""
        if slot is None:
            return None, False
        set_at = slot.get("set_at_tick", now_tick)
        fire_at = slot.get("fire_at_tick", now_tick)
        sid = str(slot.get("button_id"))

        if now_tick >= fire_at:
            # Land the snapshot. For hard slots the CCs were pre-scheduled
            # via the ALSA queue (delivered ahead of the bar by
            # DROP_FIRE_LEAD_S so the new state is in effect before any
            # downbeat); only the on-screen state needs to flip here.
            # Fade slots still emit per-tick, so the final landing here
            # IS the only place the exact target value is sent.
            snap = (self._param_values.get("drop_snapshots") or {}).get(sid)
            self._drop_fade_start.pop(sid, None)
            self._drop_fade_last_emit.pop(sid, None)
            states = dict(self._param_values.get("drop_states") or {})
            if snap:
                if fade:
                    self._apply_snapshot(snap)
                else:
                    self._apply_snapshot_state_only(snap)
            states[sid] = "firing"
            self.set_param("drop_states", states)
            states[sid] = "captured" if snap else "idle"
            self.set_param("drop_states", states)
            return None, True

        total = max(1, fire_at - set_at)
        prog = max(0.0, min(1.0, (now_tick - set_at) / total))

        # Fade interpolation runs every 1/16 boundary while the fade
        # slot is active. For each continuous cell we lerp current
        # value from start → snapshot proportional to progress, and
        # emit a CC only when the integer value has crossed since last
        # emit — keeps fade traffic bounded (one CC per integer step
        # per cell, so a 0→127 fade is 127 emits regardless of fade
        # duration). Buttons (on/off) and XY pads stay discrete and
        # land at fire_at via _apply_snapshot.
        if fade:
            self._step_fade(sid, prog)

        new_slot = dict(slot)
        new_slot["progress"] = round(prog, 2)
        return new_slot, False

    def _step_fade(self, sid: str, progress: float) -> None:
        """Interpolate continuous cells toward the snapshot. Called from
        on_tick when sched.fade is set."""
        snap = (self._param_values.get("drop_snapshots") or {}).get(sid)
        if not snap:
            return
        starts = self._drop_fade_start.get(sid)
        if starts is None:
            return
        last_emit = self._drop_fade_last_emit.setdefault(sid, {})
        for cell, target in snap.items():
            cell_type = self._cell_types.get(cell, "")
            if cell_type in ("button", "xypad"):
                # Discrete — snap at fire_at via _apply_snapshot, no fade.
                continue
            start = starts.get(cell)
            if start is None or start == target:
                continue
            # Linear interpolation, clamped to int. The cell's stored
            # value is an int for knobs/faders/wheels.
            cur = int(round(start + (target - start) * progress))
            # Skip if we'd be emitting either the start value (already
            # the live state, redundant) or the same int we just sent.
            if last_emit.get(cell, start) == cur:
                continue
            binding = self._effective_binding(cell)
            if binding is None:
                continue
            cc_val = self._cell_value_to_cc(cell, cur, binding)
            if cc_val is not None:
                self.send_cc(binding["channel"], binding["cc"], cc_val)
            last_emit[cell] = cur
            self._param_values[cell] = cur
            if self._notify_param_change:
                try:
                    self._notify_param_change(cell, cur)
                except Exception:
                    pass

    # --- Panic ---

    def panic(self):
        """Reset every cell to its declared default + emit the CC."""
        for name in self._defaults:
            binding = self._effective_binding(name)
            if binding is None:
                continue
            default = self._cell_default_values.get(name, 0)
            if self._param_values.get(name) == default:
                continue
            self._param_values[name] = default
            if self._cell_types.get(name) == "xypad":
                self._emit_xypad(default, binding)
            else:
                cc_val = self._cell_value_to_cc(name, default, binding)
                if cc_val is not None:
                    self.send_cc(binding["channel"], binding["cc"], cc_val)
            if self._notify_param_change:
                try:
                    self._notify_param_change(name, default)
                except Exception:
                    pass
