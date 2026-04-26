"""Controller — Mixer 8.

Fixed 8-wide layout: 8 knobs / 8 vertical faders / 8 mute buttons.
Defaults to ch 1 / CC 16-39; user can override per cell via the UI's
edit mode (rename, channel, CC, MIDI Learn).

All the cell ↔ CC plumbing lives in ControllerBase; this file just
declares metadata + the LayoutGrid template.
"""

from raspimidihub.controller_base import ControllerBase
from raspimidihub.plugin_api import (
    Button,
    DropPad,
    Fader,
    Knob,
    LayoutCell,
    LayoutGrid,
)


class ControllerMixer8(ControllerBase):
    """8-wide mixer-strip controller: 8 knobs / 8 faders / 8 mutes."""

    NAME = "Controller — Mixer 8"
    DESCRIPTION = "8-wide mixer: 8 knobs / 8 faders / 8 mute buttons (defaults CC 16-39 ch 1)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
8-wide mixer-strip controller. Three rows of 8 cells with default
bindings on channel 1:
  - Row 1: knobs (sends / pan)   -> CC 16..23
  - Row 2: vertical faders        -> CC 24..31
  - Row 3: mute buttons           -> CC 32..39 (0 / 127)

Tap "Edit names" to override the cell label, channel and CC of any
cell, or arm "L" and twist a hardware knob to capture a binding.

Move any UI cell -> the OUT port emits the matching CC. Wire OUT
to a synth or other destination in the matrix.

External CC arriving on the IN port silently updates the matching
on-screen cell (so the UI mirrors what the synth currently has)
without re-emitting on OUT — wire `Synth OUT -> Controller IN` to
keep both sides in sync without feedback loops."""

    params = [
        DropPad("pad", "DROP"),
        LayoutGrid(
            "controller", "",
            cols=8, rows=3,
            labels_param="cell_labels",
            bindings_param="cell_bindings",
            learn_param="cell_learn",
            cells=[
                # Row 1: knobs (sends / pan) — ch 1, CC 16..23.
                *[LayoutCell(Knob(f"k{i}", f"K{i+1}", min=0, max=127, default=64),
                             col=i+1, row=1, channel=0, cc=16+i) for i in range(8)],
                # Row 2: vertical faders (volume) — ch 1, CC 24..31.
                *[LayoutCell(Fader(f"f{i}", f"F{i+1}", min=0, max=127,
                                   default=80, vertical=True),
                             col=i+1, row=2, channel=0, cc=24+i) for i in range(8)],
                # Row 3: mute buttons — ch 1, CC 32..39.
                *[LayoutCell(Button(f"m{i}", f"M{i+1}", color="green"),
                             col=i+1, row=3, channel=0, cc=32+i) for i in range(8)],
            ],
        ),
    ]

    cc_outputs = list(range(16, 40))  # CC 16..39 ch 1
    outputs = ["CC 16..39 on ch 1 — knobs, faders, mute buttons"]
