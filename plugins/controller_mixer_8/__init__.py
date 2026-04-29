"""Controller — Mixer 8.

Fixed 8-wide layout: 3 rows of knobs / 8 vertical faders / 8
buttons (5 rows total). Defaults on ch 1; user can override per cell
via the UI's edit mode (rename, channel, CC, MIDI Learn).

All the cell ↔ CC plumbing lives in ControllerBase; this file just
declares metadata + the LayoutGrid template.
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


class ControllerMixer8(ControllerBase):
    """8-wide mixer-strip controller: 8 knobs / 8 faders / 8 mutes."""

    NAME = "Controller — Mixer 8"
    DESCRIPTION = "8-wide mixer: 24 knobs / 8 faders / 8 buttons (defaults CC 16-55 ch 1)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.2"
    HELP = """\
8-wide mixer-strip controller: 24 knobs (3 rows of 8) / 8 vertical
faders / 8 buttons. Defaults on channel 1 — the per-cell bindings
panel below shows every cell's CC and lets you change it.

Tap the EDIT button below the grid to override a cell's label,
channel and CC, or arm "L" and twist a hardware knob to capture a
binding.

Move any UI cell -> the OUT port emits the matching CC. Wire OUT
to a synth or other destination in the matrix.

External CC arriving on the IN port silently updates the matching
on-screen cell (so the UI mirrors what the synth currently has)
without re-emitting on OUT — wire `Synth OUT -> Controller IN` to
keep both sides in sync without feedback loops.

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
        ),
        Radio("bg", "Background", ControllerBase.BG_OPTIONS, default="Default", config_only=True),
        LayoutGrid(
            "controller", "",
            cols=8, rows=5,
            labels_param="cell_labels",
            bindings_param="cell_bindings",
            learn_param="cell_learn",
            cells=[
                # Row 1: knobs A — ch 1, CC 16..23.
                *[LayoutCell(Knob(f"k{i}", f"K{i+1}", min=0, max=127, default=64),
                             col=i+1, row=1, channel=0, cc=16+i) for i in range(8)],
                # Row 2: knobs B — ch 1, CC 24..31.
                *[LayoutCell(Knob(f"k{i+8}", f"K{i+9}", min=0, max=127, default=64),
                             col=i+1, row=2, channel=0, cc=24+i) for i in range(8)],
                # Row 3: knobs C — ch 1, CC 32..39.
                *[LayoutCell(Knob(f"k{i+16}", f"K{i+17}", min=0, max=127, default=64),
                             col=i+1, row=3, channel=0, cc=32+i) for i in range(8)],
                # Row 4: vertical faders (volume) — ch 1, CC 40..47.
                *[LayoutCell(Fader(f"f{i}", f"F{i+1}", min=0, max=127,
                                   default=80, vertical=True),
                             col=i+1, row=4, channel=0, cc=40+i) for i in range(8)],
                # Row 5: buttons — ch 1, CC 48..55.
                *[LayoutCell(Button(f"m{i}", f"B{i+1}", color="green"),
                             col=i+1, row=5, channel=0, cc=48+i) for i in range(8)],
            ],
        ),
    ]

    cc_outputs = list(range(16, 56))  # CC 16..55 ch 1
    outputs = ["CC 16..55 on ch 1 — 24 knobs, 8 faders, 8 buttons"]
