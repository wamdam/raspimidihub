"""Controller — Mixer 8 (Phase 4.2 MVP).

Fixed 8-wide layout: 8 knobs / 8 vertical faders / 8 mute buttons.
First real Controller plugin from §5 of the roadmap. OUT port emits
CC on every cell change; IN port silently updates the matching cell
when an external CC arrives (no re-emit — bidirectional sync without
feedback loops).

Bindings are hard-coded for v1:
  - knobs   k0..k7  -> ch 1, CC 16..23
  - faders  f0..f7  -> ch 1, CC 24..31
  - buttons m0..m7  -> ch 1, CC 32..39 (sent as 0 / 127)

Per-cell rename + per-cell rebind + MIDI Learn land in 4.2.c.
Drop pad lands in 4.2.b.
"""

from raspimidihub.plugin_api import (
    Button,
    DropPad,
    Fader,
    Knob,
    LayoutCell,
    LayoutGrid,
    PluginBase,
)


def _bindings() -> dict[str, tuple[int, int]]:
    """name -> (channel, cc). Channel is 1-based for the spec but we
    pass 0-based to send_cc() to match the rest of the codebase."""
    out = {}
    for i in range(8):
        out[f"k{i}"] = (0, 16 + i)   # ch 1 (0-based 0), CC 16..23
        out[f"f{i}"] = (0, 24 + i)   # ch 1, CC 24..31
        out[f"m{i}"] = (0, 32 + i)   # ch 1, CC 32..39
    return out


class ControllerMixer8(PluginBase):
    """8-wide mixer-strip controller: 8 knobs / 8 faders / 8 mutes."""

    NAME = "Controller — Mixer 8"
    DESCRIPTION = "8-wide mixer: 8 knobs / 8 faders / 8 mute buttons (CC 16-39 ch 1)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
8-wide mixer-strip controller. Three rows of 8 cells:
  - Row 1: knobs (sends / pan)   -> ch 1, CC 16..23
  - Row 2: vertical faders        -> ch 1, CC 24..31
  - Row 3: mute buttons           -> ch 1, CC 32..39 (0 / 127)

Move any UI cell -> the OUT port emits the matching CC. Wire OUT
to a synth or other destination in the matrix.

External CC arriving on the IN port silently updates the matching
on-screen cell (so the UI mirrors what the synth currently has)
without re-emitting on OUT — wire `Synth OUT -> Controller IN` to
keep both sides in sync without feedback loops.

Cell renaming and per-cell rebinding land in a follow-up. For v1
the bindings are fixed and printed above."""

    _BINDINGS = _bindings()

    params = [
        DropPad("pad", "DROP"),
        Button("edit_labels", "Edit names", color="blue"),
        LayoutGrid(
            "controller", "",
            cols=8, rows=3,
            edit_param="edit_labels",
            labels_param="cell_labels",
            cells=[
                # Row 1: knobs (sends / pan).
                *[LayoutCell(Knob(f"k{i}", f"K{i+1}", min=0, max=127, default=64),
                             col=i+1, row=1) for i in range(8)],
                # Row 2: vertical faders (volume).
                *[LayoutCell(Fader(f"f{i}", f"F{i+1}", min=0, max=127,
                                   default=80, vertical=True),
                             col=i+1, row=2) for i in range(8)],
                # Row 3: mute buttons.
                *[LayoutCell(Button(f"m{i}", f"M{i+1}", color="green"),
                             col=i+1, row=3) for i in range(8)],
            ],
        ),
    ]

    cc_outputs = list(range(16, 40))  # CC 16..39 ch 1
    inputs = ["CC (bidirectional sync — silent UI updates, no re-emit)"]
    outputs = ["CC 16..39 on ch 1 — knobs, faders, mute buttons"]

    def on_start(self):
        """Initialise non-schema state on first start (and after restore)."""
        self._param_values.setdefault("cell_labels", {})

    def on_param_change(self, name, value):
        """User moved a UI cell -> emit the matching CC. Or drop-pad
        fired -> handle the snapshot action."""
        if name == "pad":
            self._handle_pad_action(value)
            return
        binding = self._BINDINGS.get(name)
        if binding is None:
            return
        ch, cc = binding
        if isinstance(value, bool):
            cc_val = 127 if value else 0
        elif isinstance(value, int):
            cc_val = max(0, min(127, value))
        else:
            return
        self.send_cc(ch, cc, cc_val)

    # --- Drop pad ---

    def _handle_pad_action(self, action):
        """Dispatch on the DropPad action value sent by the UI.
        After processing, reset `pad` to 'captured' (if a snapshot
        exists) or 'idle'."""
        if action == "fire":
            self._fire_snapshot()
        elif action == "capture":
            self._capture_snapshot()
        else:
            return  # 'idle' / 'captured' echoed back from server, no-op
        new_state = "captured" if self._param_values.get("pad_snapshot") else "idle"
        self.set_param("pad", new_state)

    def _capture_snapshot(self):
        """Read every bound cell's current value into pad_snapshot."""
        snap = {}
        for cell_name in self._BINDINGS:
            v = self._param_values.get(cell_name)
            if v is not None:
                snap[cell_name] = v
        self._param_values["pad_snapshot"] = snap

    def _fire_snapshot(self):
        """Re-emit each captured CC + snap on-screen cells to the
        captured value. No-op if no snapshot has been taken yet."""
        snap = self._param_values.get("pad_snapshot") or {}
        if not snap:
            return
        for cell_name, v in snap.items():
            binding = self._BINDINGS.get(cell_name)
            if binding is None:
                continue
            ch, cc = binding
            if isinstance(v, bool):
                cc_val = 127 if v else 0
            elif isinstance(v, int):
                cc_val = max(0, min(127, v))
            else:
                continue
            self.send_cc(ch, cc, cc_val)
            # Snap UI to captured value (set + notify, no re-emit
            # since on_param_change is bypassed by direct write).
            if self._param_values.get(cell_name) != v:
                self._param_values[cell_name] = v
                if self._notify_param_change:
                    try:
                        self._notify_param_change(cell_name, v)
                    except Exception:
                        pass

    def on_cc(self, channel, cc, value):
        """Bidirectional sync: external CC silently updates the matching
        cell. Does NOT re-emit on OUT (no feedback loops)."""
        for name, (ch, cn) in self._BINDINGS.items():
            if ch != channel or cn != cc:
                continue
            # Translate the incoming CC value to the cell's value type.
            if name.startswith("m"):
                new_val = value >= 64
            else:
                new_val = value
            # Direct write + notify, bypassing on_param_change so we
            # don't immediately re-emit our own input.
            if self._param_values.get(name) == new_val:
                return
            self._param_values[name] = new_val
            if self._notify_param_change:
                try:
                    self._notify_param_change(name, new_val)
                except Exception:
                    pass
            return

    # No-op handlers for the other event types — Controller only cares
    # about CC. Note / pitchbend / aftertouch / pgm / clock pass right
    # through unprocessed (the matrix routes them however it's wired).

    def on_note_on(self, channel, note, velocity): pass
    def on_note_off(self, channel, note): pass
    def on_pitchbend(self, channel, value): pass
    def on_aftertouch(self, channel, value): pass
    def on_program_change(self, channel, program): pass

    def panic(self):
        """Reset all cells to default values + emit corresponding CCs."""
        for name, (ch, cc) in self._BINDINGS.items():
            cur = self._param_values.get(name)
            default = False if name.startswith("m") else 64
            if cur == default:
                continue
            self._param_values[name] = default
            cc_val = 127 if default is True else (0 if default is False else default)
            self.send_cc(ch, cc, cc_val)
            if self._notify_param_change:
                try:
                    self._notify_param_change(name, default)
                except Exception:
                    pass
