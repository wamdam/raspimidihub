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
  - octave         : int                   — sticky keypad octave
  - rate           : str                   — Arp-style rate (config-only)

Output is always MIDI channel 1; remap downstream via the matrix.
Transport is always external (clock + Start/Stop), so there's no
free-running BPM and no sync-mode picker.

Playback fires note-on / note-off / CC for each voice on every tick
of the configured rate. Auto-learn writes incoming notes / CCs into
the focused (row, voice) and passes them through to OUT.
"""

import threading
import time
from typing import Any

from raspimidihub.plugin_api import (
    PluginBase,
    TrackerGrid,
)

# Pitch order matches the Note wheel on the frontend. MIDI 12 = C-0,
# MIDI 119 = B-9 — same range the 3-char note string can express.
PITCH_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')

# Notes arriving within this window of each other count as one chord
# and are spread across consecutive tracks during recording. ~10 ms
# tolerates wired-keyboard jitter without merging deliberate runs.
_CHORD_WINDOW_S = 0.010


def midi_to_note_str(midi: int) -> str | None:
    """MIDI note number → 3-char tracker note string, or None if the
    pitch is outside the representable range (MIDI 12..127 = C-0..G-9
    — the 3-char rule limits octaves to a single digit, and the top
    octave runs only through G because B-9 would land at MIDI 131)."""
    if not (12 <= midi <= 127):
        return None
    n = midi - 12
    octave = n // 12
    pitch = PITCH_NAMES[n % 12]
    return f"{pitch}-{octave}" if len(pitch) == 1 else f"{pitch}{octave}"


def note_str_to_midi(s: str) -> int | None:
    """3-char tracker note string → MIDI note number, or None for any
    of the sentinels (---/Off/End) or for malformed strings."""
    if not isinstance(s, str) or len(s) != 3:
        return None
    if s in ("---", "Off", "End"):
        return None
    pitch = s[0] if s[1] == "-" else s[:2]
    if pitch not in PITCH_NAMES:
        return None
    try:
        octave = int(s[2])
    except ValueError:
        return None
    return 12 + octave * 12 + PITCH_NAMES.index(pitch)

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
                octave_param="octave",
                rate_param="rate",
                playhead_param="playhead",
            ),
        ]

    def on_start(self) -> None:
        """Initialise the persistent state with one blank page, plus
        playback / recording bookkeeping that lives only at runtime."""
        self._param_values.setdefault(
            "pages",
            [empty_page(self.TRACK_COUNT, self.MAX_ROWS_PER_PAGE)],
        )
        self._param_values.setdefault("current_page", 0)
        self._param_values.setdefault("cursor_row", 0)
        self._param_values.setdefault("cursor_track", 0)
        # cursor_half: which keypad mode the user sees on the focused
        # voice — "note" (Note wheel + Octave wheel + Vel knob) or
        # "cc" (CC# + CC Val). Lets us split the keypad in two so it
        # fits phone width.
        self._param_values.setdefault("cursor_half", "note")
        self._param_values.setdefault("octave", 3)
        self._param_values.setdefault("rate", "1/16")
        # Playhead — broadcast via set_param every step so the
        # frontend can render a `▶` next to the playing row. Stays at
        # {playing: False} until the first tick or transport-start.
        self._param_values.setdefault(
            "playhead", {"page": 0, "row": 0, "playing": False},
        )

        # Cursor + octave + playhead are live-play state — moving
        # them shouldn't mark the routing config dirty.
        self.transient_params = {
            "cursor_row", "cursor_track", "cursor_half", "octave",
            "playhead",
        }

        # Playback bookkeeping. Playhead position is intentionally
        # separate from current_page / cursor_row so editing during a
        # take doesn't reposition the playback (and vice versa).
        self._lock = threading.RLock()
        self._playing = False
        self._play_page = 0
        self._play_row = 0
        # Currently-sounding MIDI note per voice — used to fire the
        # implicit note-off when the next non-`---` cell rolls in.
        self._sounding: list[int | None] = [None] * self.TRACK_COUNT
        # Chord-detection state for record-as-you-play. Notes arriving
        # within _CHORD_WINDOW_S spread across consecutive tracks
        # starting at the focused track. `_chord_page` / `_chord_row`
        # snapshot the cursor at chord-start so all chord notes land
        # on the same row even though the cursor advances right away
        # to the next row (so the next chord goes one step down).
        self._chord_window_start = 0.0
        self._chord_offset = 0
        self._chord_page = 0
        self._chord_row = 0

    # Output is always MIDI channel 1 (0-based: 0). Remap downstream
    # via the matrix if a different channel is needed.
    OUT_CHANNEL = 0

    def on_stop(self) -> None:
        self._silence_all()

    def panic(self) -> None:
        """All notes off on the configured output channel + stop the
        playhead."""
        with self._lock:
            self._playing = False
            self._silence_all()
            # Belt-and-braces: also blanket-clear in case the synth
            # held a note we never tracked (unlikely but cheap).
            for note in range(128):
                try:
                    self.send_note_off(self.OUT_CHANNEL, note)
                except Exception:
                    pass
        self._publish_playhead()

    # ---- Internal: kill every voice's currently-sounding note. ----
    def _silence_all(self) -> None:
        for v_idx, note in enumerate(self._sounding):
            if note is not None:
                try:
                    self.send_note_off(self.OUT_CHANNEL, note)
                except Exception:
                    pass
                self._sounding[v_idx] = None

    # ---- Internal: push the current playhead state to the UI. ----
    def _publish_playhead(self) -> None:
        # Dict literal so SSE serialises cleanly. set_param both stores
        # in _param_values and emits the plugin-param event.
        self.set_param("playhead", {
            "page": self._play_page,
            "row": self._play_row,
            "playing": self._playing,
        })

    # ================================================================
    # Transport — global ClockBus events
    # ================================================================

    def on_transport_start(self) -> None:
        with self._lock:
            self._silence_all()
            self._play_page = 0
            self._play_row = 0
            self._playing = True
        # Fire row 0 right at the Start moment. Without this the first
        # row would sound 1/16 (or whatever rate) late: the ClockBus
        # increments tick_count to 1 on the first MIDI Clock after
        # Start and only fires `on_tick(<division>)` when
        # tick_count % div_ticks == 0 — i.e. on tick 6 for 1/16. So
        # the very first division-tick lands a full step late. Firing
        # row 0 here closes that gap; subsequent on_tick callbacks
        # walk through rows 1, 2, … on time.
        self._advance_step()

    def on_transport_stop(self) -> None:
        with self._lock:
            self._silence_all()
            self._playing = False
        self._publish_playhead()

    def on_transport_continue(self) -> None:
        with self._lock:
            self._playing = True
        self._publish_playhead()

    # ================================================================
    # Tick → step advance
    # ================================================================

    def on_tick(self, division: str) -> None:
        # Strictly transport-driven: clock alone doesn't start the
        # tracker — the user has to send a MIDI Start (which lands
        # in on_transport_start). This avoids the playhead silently
        # marching whenever a clock source happens to be wired in.
        if not self._playing:
            return
        if division != self._param_values.get("rate", "1/16"):
            return
        self._advance_step()

    def _advance_step(self) -> None:
        """Fire the events at (play_page, play_row) and walk the
        playhead forward, looping at the last page.

        End semantics: an `End` on voice 1 means "this row is the
        end-of-page marker — it doesn't play and the page is over."
        When we land on an End row, we immediately jump to the next
        page's row 0 and fire that, all on the same tick — no audible
        gap.

        Bounded by max_iters so a malformed pattern (every page row
        0 = End) stops itself instead of looping forever.

        Publishes the *just-fired* position to the UI so the visual
        ▶ sits on the row whose notes are now sounding, not the row
        about to fire on the next tick."""
        published = None
        with self._lock:
            pages = self._param_values.get("pages") or []
            if not pages:
                return
            if self._play_page >= len(pages):
                self._play_page = 0
                self._play_row = 0

            # Skip End rows; bail out if we somehow cycle through
            # every page without finding a row to play.
            max_iters = len(pages) + 1
            for _ in range(max_iters):
                page = pages[self._play_page]
                rows = (page.get("rows") if isinstance(page, dict) else None) or []
                row = rows[self._play_row] if self._play_row < len(rows) else None

                if isinstance(row, dict):
                    voices = row.get("voices") or []
                    v0 = voices[0] if voices else None
                    if isinstance(v0, dict) and v0.get("note") == "End":
                        # End row — skip without firing. Jump to next
                        # page row 0 and re-evaluate.
                        self._play_page = (self._play_page + 1) % len(pages)
                        self._play_row = 0
                        continue

                # Found a non-End row — fire it.
                played_page = self._play_page
                played_row = self._play_row

                if isinstance(row, dict):
                    voices = row.get("voices") or []
                    for v_idx in range(self.TRACK_COUNT):
                        if v_idx < len(voices) and isinstance(voices[v_idx], dict):
                            self._fire_voice(v_idx, voices[v_idx])

                # Advance for next call.
                if self._play_row + 1 >= self.MAX_ROWS_PER_PAGE:
                    self._play_page = (self._play_page + 1) % len(pages)
                    self._play_row = 0
                else:
                    self._play_row += 1

                published = (played_page, played_row, True)
                break
            else:
                # Cycled every page without fireable content —
                # stop the playhead instead of burning CPU on it.
                self._playing = False
                published = (self._play_page, self._play_row, False)

        # Outside the lock — set_param flows to the SSE writer.
        self.set_param("playhead", {
            "page": published[0], "row": published[1], "playing": published[2],
        })

    def _fire_voice(self, v_idx: int, voice: dict) -> None:
        note = voice.get("note", "---")
        vel = voice.get("vel")
        cc_num = voice.get("cc_num")
        cc_val = voice.get("cc_val")

        # `---` = leave previous note ringing; any other value (Off /
        # End / real pitch) implicitly note-offs the previous one.
        if note != "---":
            prev = self._sounding[v_idx]
            if prev is not None:
                try:
                    self.send_note_off(self.OUT_CHANNEL, prev)
                except Exception:
                    pass
                self._sounding[v_idx] = None

            midi = note_str_to_midi(note)
            if midi is not None:
                v = vel if isinstance(vel, int) else 90
                v = max(1, min(127, int(v)))
                try:
                    self.send_note_on(self.OUT_CHANNEL, midi, v)
                except Exception:
                    pass
                self._sounding[v_idx] = midi

        # CC fires independently — `.` / "--" sentinels mean "no event
        # this step", anything numeric on both columns sends.
        if isinstance(cc_num, int) and isinstance(cc_val, int):
            try:
                self.send_cc(
                    self.OUT_CHANNEL,
                    max(0, min(127, int(cc_num))),
                    max(0, min(127, int(cc_val))),
                )
            except Exception:
                pass

    # ================================================================
    # Recording (auto-learn) + pass-through
    # ================================================================

    def on_note_on(self, channel: int, note: int, velocity: int) -> None:
        # Pass through to OUT first so the user always hears their
        # playing once. Velocity 0 = note-off in the MIDI spec; just
        # forward and let on_note_off handle the symmetric cleanup.
        try:
            self.send_note_on(
                self.OUT_CHANNEL, note, max(1, min(127, int(velocity))),
            )
        except Exception:
            pass
        if velocity <= 0:
            return

        # Chord boundary detection. The first note of a chord captures
        # the current cursor row + page (where chord notes go) and
        # immediately advances the cursor down one step so the next
        # chord lands on the next row. Subsequent chord notes within
        # _CHORD_WINDOW_S keep writing to the captured row.
        now = time.monotonic()
        if now - self._chord_window_start > _CHORD_WINDOW_S:
            self._chord_window_start = now
            self._chord_offset = 0
            self._chord_page = int(self._param_values.get("current_page") or 0)
            self._chord_row = int(self._param_values.get("cursor_row") or 0)
            self._auto_advance_cursor()
        else:
            self._chord_offset += 1

        cur_track = int(self._param_values.get("cursor_track") or 0)
        target = cur_track + self._chord_offset
        if target >= self.TRACK_COUNT:
            return  # excess chord notes drop silently

        note_str = midi_to_note_str(note)
        if note_str is None:
            return
        self._record_voice_field_at(
            self._chord_page, self._chord_row, target,
            {"note": note_str, "vel": max(1, min(127, int(velocity)))},
        )

    def _auto_advance_cursor(self) -> None:
        """Step cursor_row down by 1, wrapping at the page boundary
        (row F → next page row 0; last page wraps to page 0). Both
        cursor_row and current_page broadcast via set_param so the
        frontend cursor moves visibly."""
        pages = self._param_values.get("pages") or []
        page_count = max(1, len(pages))
        cur_row = int(self._param_values.get("cursor_row") or 0)
        cur_page = int(self._param_values.get("current_page") or 0)
        next_row = cur_row + 1
        next_page = cur_page
        if next_row >= self.MAX_ROWS_PER_PAGE:
            next_row = 0
            next_page = (cur_page + 1) % page_count
        if next_row != cur_row:
            self.set_param("cursor_row", next_row)
        if next_page != cur_page:
            self.set_param("current_page", next_page)

    def on_note_off(self, channel: int, note: int) -> None:
        # Pass-through only. Playback emits its own note-offs from
        # the next non-`---` cell or `Off` cell — recording the
        # release would just clutter the row with `Off` entries the
        # user didn't ask for.
        try:
            self.send_note_off(self.OUT_CHANNEL, note)
        except Exception:
            pass

    def on_cc(self, channel: int, cc: int, value: int) -> None:
        try:
            self.send_cc(
                self.OUT_CHANNEL,
                max(0, min(127, int(cc))),
                max(0, min(127, int(value))),
            )
        except Exception:
            pass
        cur_track = int(self._param_values.get("cursor_track") or 0)
        if cur_track >= self.TRACK_COUNT:
            return
        self._record_voice_field(cur_track, {
            "cc_num": max(0, min(127, int(cc))),
            "cc_val": max(0, min(127, int(value))),
        })

    def _record_voice_field(self, track_idx: int, updates: dict[str, Any]) -> None:
        """Convenience wrapper for `_record_voice_field_at` at the
        currently focused (page, row). Used for CC recording where
        the target is always wherever the cursor is right now."""
        cur_page = int(self._param_values.get("current_page") or 0)
        cur_row = int(self._param_values.get("cursor_row") or 0)
        self._record_voice_field_at(cur_page, cur_row, track_idx, updates)

    def _record_voice_field_at(
        self, page_idx: int, row_idx: int, track_idx: int,
        updates: dict[str, Any],
    ) -> None:
        """Mutate `pages[page_idx].rows[row_idx].voices[track_idx]`
        with `updates`. Broadcasts the new `pages` via set_param so
        the UI reflects the recorded value live across browsers.
        Called with an explicit (page, row) so chord notes write to
        the captured chord row even after the cursor has advanced."""
        with self._lock:
            pages = list(self._param_values.get("pages") or [])
            if page_idx >= len(pages):
                return
            page = dict(pages[page_idx])
            rows = list(page.get("rows") or [])
            if row_idx >= len(rows):
                return
            row = dict(rows[row_idx])
            voices = list(row.get("voices") or [])
            if track_idx >= len(voices):
                return
            voice = dict(voices[track_idx])
            voice.update(updates)
            voices[track_idx] = voice
            row["voices"] = voices
            rows[row_idx] = row
            page["rows"] = rows
            pages[page_idx] = page
            self.set_param("pages", pages)
