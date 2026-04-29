"""Controller — FX 6.

6-wide layout: 3 rows of FX knobs / 6 vertical faders / 6 buttons
(5 rows total). Defaults to ch 1 / CC 16-45; overridable per cell.
"""

from raspimidihub.controller_base import ControllerBase
from raspimidihub.plugin_api import (
    Button,
    DropButtonRow,
    Fader,
    Knob,
    LayoutCell,
    LayoutGrid,
    Radio,
)


class ControllerFx6(ControllerBase):
    """6-wide FX controller: 18 knobs / 6 faders / 6 buttons."""

    NAME = "Controller — FX 6"
    DESCRIPTION = "6-wide FX: 18 knobs / 6 faders / 6 buttons (defaults CC 16-45 ch 1)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.1"
    HELP = """\
6-wide FX controller. Five rows of 6 cells with default bindings on
channel 1:
  - Row 1: knobs row A (FX1..FX6)    -> CC 16..21
  - Row 2: knobs row B (FX7..FX12)   -> CC 22..27
  - Row 3: knobs row C (FX13..FX18)  -> CC 28..33
  - Row 4: vertical faders (S1..S6)  -> CC 34..39
  - Row 5: buttons (B1..B6)          -> CC 40..45 (0 / 127)

Tap the EDIT button below the grid to override the cell label,
channel, CC and (for buttons) the on / off CC values; or tap Learn
on a row and twist a hardware knob to capture its binding."""

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
        Radio("bg", "Background", ControllerBase.BG_OPTIONS, default="Default", config_only=True),
        LayoutGrid(
            "controller", "",
            cols=6, rows=5,
            labels_param="cell_labels",
            bindings_param="cell_bindings",
            learn_param="cell_learn",
            cells=[
                # Row 1: knobs A — ch 1, CC 16..21.
                *[LayoutCell(Knob(f"fx{i}", f"FX{i+1}", min=0, max=127, default=64),
                             col=i+1, row=1, channel=0, cc=16+i) for i in range(6)],
                # Row 2: knobs B — ch 1, CC 22..27.
                *[LayoutCell(Knob(f"fx{i+6}", f"FX{i+7}", min=0, max=127, default=64),
                             col=i+1, row=2, channel=0, cc=22+i) for i in range(6)],
                # Row 3: knobs C — ch 1, CC 28..33.
                *[LayoutCell(Knob(f"fx{i+12}", f"FX{i+13}", min=0, max=127, default=64),
                             col=i+1, row=3, channel=0, cc=28+i) for i in range(6)],
                # Row 4: vertical faders — ch 1, CC 34..39.
                *[LayoutCell(Fader(f"s{i}", f"S{i+1}", min=0, max=127,
                                   default=80, vertical=True),
                             col=i+1, row=4, channel=0, cc=34+i) for i in range(6)],
                # Row 5: buttons — ch 1, CC 40..45.
                *[LayoutCell(Button(f"b{i}", f"B{i+1}", color="green"),
                             col=i+1, row=5, channel=0, cc=40+i) for i in range(6)],
            ],
        ),
    ]

    cc_outputs = list(range(16, 46))  # CC 16..45 ch 1
    outputs = ["CC 16..45 on ch 1 — 18 knobs, 6 faders, 6 buttons"]
