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
8 voices step-sequenced on a single MIDI channel. Up to 16 hex-numbered
steps per page, up to 16 pages chained linearly with looping back to
page 0.

Per voice cell: Note (3-char pitch / Off / End / hold), Velocity (hex),
CC# (hex or `.`), CC Val (hex). Note and CC events fire independently.

End on voice 1's Note column marks the last row of the page; pages
without an End play the full 16 rows. Add Page / Del Page in the
header manage the linear page chain.

Always-recording: external notes / CCs land at the focused row on the
cursor track (chord notes spread to the next tracks). Pass-through to
OUT means you hear what you're playing once. Turning the Note wheel
previews the picked note out the OUT port.

Sync: Free / Tempo / Transport — same semantics as the Arpeggiator.
"""

    TRACK_COUNT = 8
