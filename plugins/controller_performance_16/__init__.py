"""Controller — Performance 16.

4×4 grid of macro knobs + a row of 4 colored scene buttons. Designed
for tablet / phone performance use where you want plenty of macros
in a tight portrait layout.

Defaults to ch 1 / CC 16-35; overridable per cell.
"""

from raspimidihub.controller_base import ControllerBase
from raspimidihub.plugin_api import (
    Button,
    DropPad,
    Knob,
    LayoutCell,
    LayoutGrid,
)


_SCENE_COLORS = ["green", "yellow", "blue", "red"]


class ControllerPerformance16(ControllerBase):
    """4-wide performance controller: 16 macro knobs + 4 scene buttons."""

    NAME = "Controller — Performance 16"
    DESCRIPTION = "4-wide performance: 16 macros + 4 scene buttons (defaults CC 16-35 ch 1)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
4-wide performance controller. Default bindings on channel 1:
  - Rows 1-4: 16 macro knobs (M1..M16) -> CC 16..31
  - Row 5:    4 scene buttons (A B C D) -> CC 32..35 (0 / 127)

Tap "Edit names" to override the cell label, channel and CC of any
cell, or arm "L" and twist a hardware knob to capture a binding.

Move any UI cell -> the OUT port emits the matching CC. Wire OUT
to a synth or destination in the matrix.

External CC arriving on the IN port silently updates the matching
on-screen cell."""

    params = [
        DropPad("pad", "DROP"),
        Button("edit_labels", "Edit names", color="blue"),
        LayoutGrid(
            "controller", "",
            cols=4, rows=5,
            edit_param="edit_labels",
            labels_param="cell_labels",
            bindings_param="cell_bindings",
            learn_param="cell_learn",
            cells=[
                # Rows 1-4: 16 macros, 4 per row, ch 1 CC 16..31.
                *[LayoutCell(
                    Knob(f"m{i}", f"M{i+1}", min=0, max=127, default=64),
                    col=(i % 4) + 1, row=(i // 4) + 1,
                    channel=0, cc=16 + i,
                ) for i in range(16)],
                # Row 5: scene buttons A/B/C/D, ch 1 CC 32..35.
                *[LayoutCell(
                    Button(f"s{i}", chr(ord("A") + i), color=_SCENE_COLORS[i]),
                    col=i + 1, row=5,
                    channel=0, cc=32 + i,
                ) for i in range(4)],
            ],
        ),
    ]

    cc_outputs = list(range(16, 36))  # CC 16..35 ch 1
    outputs = ["CC 16..31 on ch 1 (macros) + CC 32..35 (scenes)"]
