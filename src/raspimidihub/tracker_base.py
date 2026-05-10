"""Shared base class for §6 sequencer plugins ("Tracker" family).

Each subclass declares NAME / DESCRIPTION / HELP and (optionally)
overrides TRACK_COUNT. The full UI — TrackerGrid + always-visible
data-entry keypad below it — is built by `_build_params()` so all
sequencer subclasses get the same shape without copy-paste.

Persistent state lives in `_param_values`:
  - pages          : list[Page]            — see TrackerGrid docstring
  - current_page   : int                   — visible/edit page
  - cursor_row     : int                   — edit cursor row
  - cursor_track   : int                   — edit cursor voice
  - octave         : int                   — sticky keypad octave
  - channel        : int (1..16)           — single output channel
  - rate           : str                   — Arp-style rate
  - sync_mode      : str                   — free / tempo / transport
  - bpm            : int                   — used in free mode
  - show_tracks    : int (2 / 4 / 8)       — keypad-side viewport size
"""

from typing import Any

from raspimidihub.plugin_api import (
    ChannelSelect,
    Group,
    PluginBase,
    Radio,
    TrackerGrid,
    Wheel,
)

# Same rate set as the Arpeggiator — keeps the project's clock idiom
# uniform. Tracker uses these to drive step advance.
RATE_OPTIONS = [
    "4/1", "4/1T", "2/1", "2/1T", "1/1", "1/1T",
    "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T",
    "1/16", "1/16T", "1/32",
]

# Note-column sentinels. Stored verbatim in JSON.
NOTE_HOLD = "---"     # leave previous note ringing on this voice
NOTE_OFF = "Off"      # explicit note-off
NOTE_END = "End"      # voice-1-only: end-of-page marker

# CC-column sentinels.
CC_HOLD = "--"        # leave wheel value unchanged
CC_NONE = "."         # no CC event this step (only valid on cc_num)


def empty_voice() -> dict[str, Any]:
    """A voice cell with no note, no vel, no CC pair."""
    return {
        "note": NOTE_HOLD,
        "vel": CC_HOLD,
        "cc_num": CC_NONE,
        "cc_val": CC_HOLD,
    }


def empty_row(track_count: int) -> dict[str, Any]:
    return {"voices": [empty_voice() for _ in range(track_count)]}


def empty_page(track_count: int, max_rows: int) -> dict[str, Any]:
    return {"rows": [empty_row(track_count) for _ in range(max_rows)]}


class TrackerBase(PluginBase):
    """Common params + state plumbing for sequencer surfaces."""

    SURFACE_KIND = "play"

    # Subclass overrides; the base ships an 8-voice default.
    TRACK_COUNT = 8
    MAX_PAGES = 16
    MAX_ROWS_PER_PAGE = 16

    inputs = [
        "Notes (recorded into focused row at the cursor track + neighbours)",
        "CC (recorded into focused track only)",
        "Clock", "Transport (Start / Stop / Continue)",
    ]
    outputs = ["Notes on configured channel", "CCs on configured channel"]

    clock_divisions = list(RATE_OPTIONS)

    # Built lazily so subclasses can adjust TRACK_COUNT first.
    params: list = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.params = cls._build_params()

    @classmethod
    def _build_params(cls) -> list:
        """Assemble the standard sequencer config + tracker UI."""
        return [
            Group("Transport", [
                ChannelSelect("channel", "Out Ch", default=1),
                Radio("rate", "Rate", RATE_OPTIONS, default="1/16"),
                Radio("sync_mode", "Sync",
                      ["free", "tempo", "transport"], default="transport"),
                Wheel("bpm", "BPM", min=40, max=300, default=120,
                      visible_when=("sync_mode", "free")),
                Radio("show_tracks", "Show",
                      ["2", "4", "8"], default="4"),
            ]),
            TrackerGrid(
                "tracker", "",
                track_count=cls.TRACK_COUNT,
                max_pages=cls.MAX_PAGES,
                max_rows=cls.MAX_ROWS_PER_PAGE,
                pages_param="pages",
                current_page_param="current_page",
                cursor_row_param="cursor_row",
                cursor_track_param="cursor_track",
                octave_param="octave",
            ),
        ]

    def on_start(self) -> None:
        """Initialise the persistent state with one blank page."""
        self._param_values.setdefault(
            "pages",
            [empty_page(self.TRACK_COUNT, self.MAX_ROWS_PER_PAGE)],
        )
        self._param_values.setdefault("current_page", 0)
        self._param_values.setdefault("cursor_row", 0)
        self._param_values.setdefault("cursor_track", 0)
        self._param_values.setdefault("octave", 3)

        # Cursor + octave are live-play state — moving them shouldn't
        # mark the routing config dirty.
        self.transient_params = {"cursor_row", "cursor_track", "octave"}

    def panic(self) -> None:
        """All notes off on the configured output channel."""
        ch = max(0, (self._param_values.get("channel", 1) or 1) - 1)
        for note in range(128):
            try:
                self.send_note_off(ch, note)
            except Exception:
                pass
