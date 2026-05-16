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
    DESCRIPTION = "6-wide FX: 18 knobs / 6 faders / 6 buttons"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.1"
    HELP = """\
6-wide FX controller: 18 knobs (3 rows of 6) / 6 vertical faders /
6 buttons. Defaults on channel 1 — the per-cell bindings panel
below shows every cell's CC and lets you change it.

Tap the EDIT button below the grid to override a cell's label,
channel, CC and (for buttons) the on / off CC values; or tap Learn
on a row and twist a hardware knob to capture its binding.

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
            cols=6, rows=5,
            labels_param="cell_labels",
            bindings_param="cell_bindings",
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
