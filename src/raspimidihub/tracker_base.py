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
  - cursor_half    : str                   — "note" | "cc" keypad slice
  - rate           : str                   — Arp-style rate (config-only)

Output is always MIDI channel 1; remap downstream via the matrix.
Transport is always external (clock + Start/Stop), so there's no
free-running BPM and no sync-mode picker.
"""

from typing import Any

from raspimidihub.plugin_api import (
    PluginBase,
    TrackerGrid,
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
        """Assemble the sequencer UI. Rate lives behind the
        TrackerGrid's `rate_param` pointer — only the inline pulldown
        in the grid header touches it, so there's no separate Radio
        rendered anywhere. Output channel is fixed at MIDI ch 1
        (remap via the matrix if you need it elsewhere)."""
        return [
            TrackerGrid(
                "tracker", "",
                track_count=cls.TRACK_COUNT,
                max_pages=cls.MAX_PAGES,
                max_rows=cls.MAX_ROWS_PER_PAGE,
                pages_param="pages",
                current_page_param="current_page",
                cursor_row_param="cursor_row",
                cursor_track_param="cursor_track",
                cursor_half_param="cursor_half",
                rate_param="rate",
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
        # cursor_half: which keypad mode the user sees on the focused
        # voice — "note" (Note + Vel) or "cc" (CC# + CC Val). Lets us
        # split the keypad in two so it fits phone width.
        self._param_values.setdefault("cursor_half", "note")
        self._param_values.setdefault("rate", "1/16")

        # Cursor state is live-play — moving the cursor shouldn't
        # mark the routing config dirty.
        self.transient_params = {
            "cursor_row", "cursor_track", "cursor_half",
        }

    # Output is always MIDI channel 1 (0-based: 0). Remap downstream
    # via the matrix if a different channel is needed.
    OUT_CHANNEL = 0

    def panic(self) -> None:
        """All notes off on the configured output channel."""
        for note in range(128):
            try:
                self.send_note_off(self.OUT_CHANNEL, note)
            except Exception:
                pass
