"""Controller — FX 6.

Middle-ground 6-wide layout: 6 knobs / 6 vertical faders / 6 buttons.
Defaults to ch 1 / CC 16-33; overridable per cell.
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


class ControllerFx6(ControllerBase):
    """6-wide FX controller: 6 knobs / 6 faders / 6 buttons."""

    NAME = "Controller — FX 6"
    DESCRIPTION = "6-wide FX: 6 knobs / 6 faders / 6 buttons (defaults CC 16-33 ch 1)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
6-wide FX controller. Default bindings on channel 1:
  - Row 1: 6 FX knobs (FX1..FX6)   -> CC 16..21
  - Row 2: 6 vertical faders (S1..S6) -> CC 22..27
  - Row 3: 6 buttons (B1..B6)      -> CC 28..33 (0 / 127)

Tap "Edit names" to override the cell label, channel and CC of any
cell, or arm "L" and twist a hardware knob to capture a binding."""

    params = [
        DropPad("pad", "DROP"),
        Button("edit_labels", "Edit names", color="blue"),
        LayoutGrid(
            "controller", "",
            cols=6, rows=3,
            edit_param="edit_labels",
            labels_param="cell_labels",
            bindings_param="cell_bindings",
            learn_param="cell_learn",
            cells=[
                # Row 1: 6 FX knobs, ch 1 CC 16..21.
                *[LayoutCell(Knob(f"fx{i}", f"FX{i+1}", min=0, max=127, default=64),
                             col=i+1, row=1, channel=0, cc=16+i) for i in range(6)],
                # Row 2: 6 vertical faders, ch 1 CC 22..27.
                *[LayoutCell(Fader(f"s{i}", f"S{i+1}", min=0, max=127,
                                   default=80, vertical=True),
                             col=i+1, row=2, channel=0, cc=22+i) for i in range(6)],
                # Row 3: 6 buttons, ch 1 CC 28..33.
                *[LayoutCell(Button(f"b{i}", f"B{i+1}", color="green"),
                             col=i+1, row=3, channel=0, cc=28+i) for i in range(6)],
            ],
        ),
    ]

    cc_outputs = list(range(16, 34))  # CC 16..33 ch 1
    outputs = ["CC 16..33 on ch 1 — FX knobs, faders, buttons"]
