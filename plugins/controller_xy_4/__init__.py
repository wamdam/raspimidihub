"""Controller — XY 4.

Performance-oriented 4-wide layout with two 2×2 XY pads on top, eight
knobs (two rows of four) in the middle, and four buttons across the
bottom. Defaults on ch 1 / CC 16-31; overridable per cell.

  Row 1-2: [ XY 1 (2×2) ][ XY 2 (2×2) ]
  Row 3:   [ K1 ][ K2 ][ K3 ][ K4 ]
  Row 4:   [ K5 ][ K6 ][ K7 ][ K8 ]
  Row 5:   [ B1 ][ B2 ][ B3 ][ B4 ]
"""

from raspimidihub.controller_base import ControllerBase
from raspimidihub.plugin_api import (
    Button,
    DropButtonRow,
    Knob,
    LayoutCell,
    LayoutGrid,
    Radio,
    XYPad,
)


class ControllerXY4(ControllerBase):
    """Performance controller: 2 XY pads, 8 knobs, 4 buttons."""

    NAME = "Controller — XY 4"
    DESCRIPTION = "Performance: 2 XY pads / 8 knobs / 4 buttons (defaults CC 16-31 ch 1)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Performance controller: 2 large XY pads (2×2 each) on top, 8 knobs
(2 rows of 4) in the middle, 4 buttons across the bottom. Defaults
on channel 1 — the per-cell bindings panel below shows every cell's
CC(s) and lets you change them.

Each XY pad emits two CCs — one per axis — at the same channel by
default. Edit any cell to override its label, channel and CC(s).

Drop buttons (A/B/C/D row at the top): each can be fired by a MIDI
note via its Trigger Note setting in the drop config. When a note
arrives on the IN port and matches a bound button's note, that
button fires — same path as a UI tap. Tap Learn next to the note
wheel to capture the next incoming note. Useful for foot pedals,
external pads, or sequencer-driven drops."""

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
            note_press_param="drop_note_pressing",
        ),
        Radio("bg", "Background", ControllerBase.BG_OPTIONS, default="Default", config_only=True),
        LayoutGrid(
            "controller", "",
            cols=4, rows=5,
            labels_param="cell_labels",
            bindings_param="cell_bindings",
            learn_param="cell_learn",
            cells=[
                # Rows 1-2: two 2x2 XY pads.
                LayoutCell(XYPad("xy1", "XY 1", default_x=64, default_y=64),
                           col=1, row=1, span_cols=2, span_rows=2,
                           channel=0, cc=16, cc_y=17),
                LayoutCell(XYPad("xy2", "XY 2", default_x=64, default_y=64),
                           col=3, row=1, span_cols=2, span_rows=2,
                           channel=0, cc=18, cc_y=19),
                # Row 3: knobs A — CC 20..23.
                *[LayoutCell(Knob(f"k{i}", f"K{i+1}", min=0, max=127, default=64),
                             col=i+1, row=3, channel=0, cc=20+i) for i in range(4)],
                # Row 4: knobs B — CC 24..27.
                *[LayoutCell(Knob(f"k{i+4}", f"K{i+5}", min=0, max=127, default=64),
                             col=i+1, row=4, channel=0, cc=24+i) for i in range(4)],
                # Row 5: buttons — CC 28..31.
                *[LayoutCell(Button(f"b{i}", f"B{i+1}", color="green"),
                             col=i+1, row=5, channel=0, cc=28+i) for i in range(4)],
            ],
        ),
    ]

    cc_outputs = list(range(16, 32))  # CC 16..31 ch 1
    outputs = ["CC 16..31 on ch 1 — 2 XY pads (4 CCs), 8 knobs, 4 buttons"]
