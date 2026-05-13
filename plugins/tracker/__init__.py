"""Tracker — 8-voice step sequencer, single channel, paged.

Lives in the Play panel (SURFACE_KIND = "play"). See the
TrackerBase docstring for the persisted-state shape.

This MVP commit ships the data model + the surface registration so
the plugin appears in the Play carousel; playback engine and
auto-learn recording land in subsequent commits.
"""

from raspimidihub.tracker_base import TrackerBase


class Tracker(TrackerBase):
    NAME = "Tracker"
    DESCRIPTION = "8-voice step sequencer, single channel, paged"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
8 voices step-sequenced, each with its own MIDI output channel. Up to
16 hex-numbered steps per page, up to 16 pages chained linearly with
looping back to page 0.

Per voice cell: Note (3-char pitch / Off / End / hold), Velocity (hex),
CC# (hex or `.`), CC Val (hex). Note and CC events fire independently.

End on any voice's Note column marks the last row of the page; pages
without an End play the full 16 rows. End rows are silent — playback
jumps straight to the next page's row 0 on the same tick. Add Page /
Del Page in the header manage the linear page chain.

CC collisions: when multiple voices on the same row set the same
(channel, CC#), the rightmost voice wins; earlier duplicates drop
before any MIDI is sent. Different channels or CC numbers coexist.

Patterns: 8 numbered slots below the action row, each a full grid
of pages + cells. Tap to switch (queued at the next boundary while
playing, immediate while stopped). Shift+Tap switches now and keeps
the playhead position. Long-press for Overwrite-from-selected /
Clear pattern.

Always-recording: external notes / CCs land at the focused row on the
cursor track (chord notes spread to the next tracks). Pass-through to
OUT means you hear what you're playing once. A note recorded into a
cell auto-advances the cursor one row down; CCs do not. Turning the
Note wheel previews the picked note out the OUT port.

Keyboard: q 2 w 3 e r 5 t 6 y 7 u for note entry (QWERTY + QWERTZ
both work via physical-key position). `o` writes a Note-Off and
auto-advances. `+` / `-` nudge the OCT wheel. Shift+arrows extends
a selection rectangle; the keypad swaps to a TRANSPOSE wheel
(-24..+24) that shifts every real-pitch note in the selection by
N semitones. Space toggles Play / Stop.

Clock master mode: Send Clock (config panel) makes the Tracker run
its own 24-PPQ generator at the configured BPM (40..300) and emit
that clock to OUT — no upstream source needed; downstream gear slaves
off the Tracker. While Send Clock is on, the Tracker ignores any
external clock on the bus.

Transport: Send Transport (config panel) forwards incoming
START / STOP / CONTINUE to OUT, *and* emits its own START / STOP /
CONTINUE when the on-screen Play / Stop buttons fire — so downstream
slaves bar-align with the Tracker whether the transport originated
upstream or inside the Tracker. With both Send Clock and Send
Transport off, the Tracker is silent without an external clock.
"""

    TRACK_COUNT = 8
