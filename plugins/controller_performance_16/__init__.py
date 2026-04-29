"""Controller — Performance 16.

4×4 grid of macro knobs + a row of 4 colored scene buttons. Designed
for tablet / phone performance use where you want plenty of macros
in a tight portrait layout.

Defaults to ch 1 / CC 16-35; overridable per cell.
"""

from raspimidihub.controller_base import ControllerBase
from raspimidihub.plugin_api import (
    Button,
    DropButtonRow,
    Knob,
    LayoutCell,
    LayoutGrid,
    Radio,
)

_SCENE_COLORS = ["green", "yellow", "blue", "red"]


class ControllerPerformance16(ControllerBase):
    """4-wide performance controller: 16 macro knobs + 4 scene buttons."""

    NAME = "Controller — Performance 16"
    DESCRIPTION = "4-wide performance: 16 macros + 4 scene buttons (defaults CC 16-35 ch 1)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
4-wide performance controller: 16 macro knobs (4×4) plus a row of
4 colored scene buttons. Defaults on channel 1 — the per-cell
bindings panel below shows every cell's CC and lets you change it.

Tap "Edit names" to override a cell's label, channel and CC, or
arm "L" and twist a hardware knob to capture a binding.

Move any UI cell -> the OUT port emits the matching CC. Wire OUT
to a synth or destination in the matrix. External CC arriving on
the IN port silently updates the matching on-screen cell.

Drop buttons (A/B/C/D row at the top): each can be fired by a MIDI
note via its Trigger Note setting in the drop config. When a note
arrives on the IN port and matches a bound button's note, that
button fires — same path as a UI tap. Tap Learn next to the note
wheel to capture the next incoming note. Use it to drive drops
from a foot pedal, external pad, or sequencer."""

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
            cols=4, rows=5,
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
