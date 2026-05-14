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
  - track_ch_0..N  : int                   — per-track output channel (1..16)
  - send_clock     : bool                  — Tracker = clock master: emit
                                              24 PPQ at the internal BPM and
                                              drive own playhead from it
  - send_transport : bool                  — forward incoming START/STOP/
                                              CONTINUE to OUT, and emit own
                                              START/STOP when the on-screen
                                              Play / Stop button fires
  - bpm            : int                   — internal BPM (40..300) used when
                                              send_clock is on
  - cmd_play / cmd_stop : bool             — manual transport signals from
                                              the play-page header buttons

Each voice fires on its own configured channel — defaults all 1, the
config card on the device-detail panel lets the user remap any track
to a different channel. Multi-channel chords + per-track CC routing
work just by setting different channels per track.

Clock-master mode. With `send_clock` on, the Tracker schedules its
own 24-PPQ clock burst via send_clock_at(), the host's ClockBus
loops that back as on_tick at the configured rate, and downstream
gear sees the same clock on the OUT port. External clock on the bus
is ignored while Send Clock is on (option-1 "Send Clock wins").
With Send Clock off, on_tick is driven by whatever external clock
is wired in — no Send Clock, no clock source = no playback.

Playback fires note-on / note-off / CC for each voice on every tick
of the configured rate. Auto-learn writes incoming notes / CCs into
the focused (row, voice) and passes them through to OUT.
"""

import threading
import time
from typing import Any

from raspimidihub.plugin_api import (
    Button,
    ChannelSelect,
    Group,
    NoteSelect,
    PluginBase,
    TrackerGrid,
    Wheel,
)

# Pitch order matches the Note wheel on the frontend. MIDI 12 = C-0,
# MIDI 119 = B-9 — same range the 3-char note string can express.
PITCH_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')

# Chord recording is gated by held notes, not by a time window: the
# chord stays open while any recorded note is still held. This stale
# timeout is only the safety net for a missed note-off — after this
# much idle time the next note-on starts a fresh chord regardless of
# what the held set claims, so recording recovers from drift without
# a transport cycle.
_CHORD_STALE_TIMEOUT_S = 2.0

# Pre-roll on the manual Play button: defers the actual transport
# start by this many seconds so the first row's note-ons clear ALSA's
# output queue before the next clock tick silences them. Without it,
# row 0 audibly plays shorter than subsequent rows (cold-queue
# effect). External Start (e.g. from a wired clock master) bypasses
# the pre-roll — that path is already aligned to upstream timing.
_PLAY_PREROLL_S = 0.050

# How long a wheel/keyboard preview note rings before auto-releasing.
# Long enough to be audibly identifiable, short enough that scrolling
# the wheel quickly doesn't pile up zombie notes.
_PREVIEW_DURATION_S = 0.30


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
    # When the Tracker's own send_clock toggle is on, its emitted
    # 24-PPQ clock should loop back through the host ClockBus to
    # drive on_tick. The class-level flag is True; the runtime
    # generator thread is what actually emits (only while the
    # `send_clock` param is on), so this opt-in is harmless when
    # the toggle is off.
    feeds_clock_bus = True

    # Subclass overrides; the base ships an 8-voice default.
    TRACK_COUNT = 8
    MAX_PAGES = 16
    MAX_ROWS_PER_PAGE = 16
    PATTERN_COUNT = 8

    # Internal clock generator (used in clock-master mode).
    _CLOCK_TAG = 0xC10C  # tag for cancel_scheduled
    _CLOCK_LOOKAHEAD_S = 0.5  # how far ahead we pre-schedule ticks

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
        """Assemble the sequencer UI:

          - TrackerGrid: the play-surface UI. Has `play_only=True` so
            the device-detail config panel doesn't render the grid +
            keypad (the user can't usefully play sequences from a
            modal config card anyway).
          - "Track Channels" group: 8 ChannelSelect entries (one per
            voice), config_only so they only appear in the device-
            detail panel — not on the play surface.
          - "Send Clock + Transport" toggle: when on, forwards
            incoming CLOCK / START / STOP / CONTINUE to OUT.

        `cmd_play` / `cmd_stop` are sibling state params declared on
        the TrackerGrid (so schema_param_keys tracks them) but never
        rendered as a Param — they're trigger-style booleans the
        play-page header writes to via onChange. on_param_change
        catches them and fires the local transport handlers."""
        params: list = [
            TrackerGrid(
                "tracker", "",
                track_count=cls.TRACK_COUNT,
                max_pages=cls.MAX_PAGES,
                max_rows=cls.MAX_ROWS_PER_PAGE,
                pattern_count=cls.PATTERN_COUNT,
                pages_param="pages",
                current_page_param="current_page",
                cursor_row_param="cursor_row",
                cursor_track_param="cursor_track",
                cursor_half_param="cursor_half",
                octave_param="octave",
                rate_param="rate",
                playhead_param="playhead",
                track_channels_param="track_channels",
                cmd_play_param="cmd_play",
                cmd_stop_param="cmd_stop",
                send_clock_param="send_clock",
                note_preview_param="note_preview",
                patterns_param="patterns",
                selected_pattern_param="selected_pattern",
                queued_pattern_param="queued_pattern",
                pattern_status_param="pattern_status",
                cmd_pattern_select_param="cmd_pattern_select",
            ),
            Group("Track Channels", [
                ChannelSelect(f"track_ch_{i}", f"T{i + 1}",
                              default=1, config_only=True)
                for i in range(cls.TRACK_COUNT)
            ], config_only=True),
            # Auto Ch.: which incoming MIDI channel keeps the historic
            # cursor-relative recording (chord notes spread across
            # consecutive tracks from the cursor). Other channels route
            # by track-channel match. 0 = Off (everything routes by
            # match; unmatched channels are dropped).
            Wheel("auto_ch", "Auto Ch.",
                  min=0, max=16, default=0,
                  labels=["Off"] + [str(i) for i in range(1, 17)],
                  config_only=True),
            Button("send_clock", "Send Clock",
                   default=False, color="green", config_only=True),
            # BPM is only meaningful when send_clock is on. The
            # frontend hides it via `visible_when` so the config
            # panel doesn't show a dead wheel.
            Wheel("bpm", "BPM", min=40, max=300, default=120,
                  config_only=True, visible_when=("send_clock", True)),
            Button("send_transport", "Send Transport",
                   default=False, color="green", config_only=True),
            # Pattern control channel: when set to 1..16, incoming notes
            # on that channel never record or pass through — instead each
            # configured pattern_note_N triggers a pattern switch (queued
            # to the next page-0 boundary while playing, immediate while
            # stopped). 0 = Off, no interception.
            Wheel("pattern_ctrl_ch", "Pattern Ctrl Ch",
                  min=0, max=16, default=0,
                  labels=["Off"] + [str(i) for i in range(1, 17)],
                  config_only=True),
            Group("Pattern Notes", [
                NoteSelect(f"pattern_note_{i}", f"P{i + 1}",
                           default=36 + i, config_only=True)
                for i in range(cls.PATTERN_COUNT)
            ], config_only=True,
                visible_when=("pattern_ctrl_ch", list(range(1, 17)))),
        ]
        return params

    def on_start(self) -> None:
        """Initialise the persistent state with one blank page, plus
        playback / recording bookkeeping that lives only at runtime."""
        # Pattern bank. New installs get N empty patterns. Configs
        # saved before patterns existed have just `pages` -- migrate
        # them into patterns[0], with slots 1..N-1 empty.
        if "patterns" not in self._param_values:
            legacy_pages = self._param_values.get("pages")
            slot0 = legacy_pages if legacy_pages else [
                empty_page(self.TRACK_COUNT, self.MAX_ROWS_PER_PAGE),
            ]
            self._param_values["patterns"] = [slot0] + [
                [empty_page(self.TRACK_COUNT, self.MAX_ROWS_PER_PAGE)]
                for _ in range(self.PATTERN_COUNT - 1)
            ]
        self._param_values.setdefault("selected_pattern", 0)
        # `queued_pattern`: -1 = no queue; otherwise index of pattern
        # to swap into on the next page-0 row-0 boundary.
        self._param_values.setdefault("queued_pattern", -1)
        self._param_values["cmd_pattern_select"] = None

        # `pages` is always a mirror of patterns[selected_pattern].
        # Edits write to `pages`; on_param_change keeps the patterns
        # array in sync.
        sel = int(self._param_values.get("selected_pattern", 0))
        sel = max(0, min(self.PATTERN_COUNT - 1, sel))
        self._param_values["selected_pattern"] = sel
        self._param_values["pages"] = list(
            self._param_values["patterns"][sel],
        )
        self._param_values["pattern_status"] = self._compute_pattern_status()

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
        # frontend can render a `▶` next to the playing row. Always
        # reset to {playing: False} on plugin (re)start; a saved
        # config could carry playing:True from a mid-play save and
        # we don't want the Play button to read green when the
        # engine's actual _playing state is False.
        self._param_values["playhead"] = {"page": 0, "row": 0, "playing": False}
        # Manual transport signals from the play-page header buttons.
        # Frontend sets to True; on_param_change resets to False.
        self._param_values.setdefault("cmd_play", False)
        self._param_values.setdefault("cmd_stop", False)
        # Clock master + transport-forwarding toggles. Old configs
        # carry a single `send_clock` that meant "forward CLOCK +
        # START / STOP / CONTINUE". Migration: old True → BOTH
        # send_clock (now: generate own clock) AND send_transport
        # are on. Old False → both off. New installs start both off.
        # `send_transport` may not exist in old configs; setdefault
        # only mirrors the legacy meaning when send_clock is True.
        if "send_transport" not in self._param_values:
            self._param_values["send_transport"] = bool(
                self._param_values.get("send_clock"),
            )
        self._param_values.setdefault("send_clock", False)
        self._param_values.setdefault("bpm", 120)
        # Note-preview signal: frontend writes a MIDI note number when
        # the user picks a pitch on the Note wheel or types one on
        # the keyboard; the plugin fires send_note_on (with auto-
        # release) so the user hears what they're entering. -1 = idle.
        self._param_values.setdefault("note_preview", -1)
        # Per-track channels default to 1.
        for i in range(self.TRACK_COUNT):
            self._param_values.setdefault(f"track_ch_{i}", 1)
        # Pattern control channel + 8 trigger notes default to off / C1..G1.
        self._param_values.setdefault("pattern_ctrl_ch", 0)
        for i in range(self.PATTERN_COUNT):
            self._param_values.setdefault(f"pattern_note_{i}", 36 + i)

        # Cursor + octave + playhead + cmd signals are live-play
        # state — moving them shouldn't mark the routing config dirty.
        # queued_pattern / pattern_status / cmd_pattern_select are
        # transient too: queued is a runtime intent (cleared on the
        # next boundary), status is derived from `patterns`, and
        # cmd_* is a one-shot trigger.
        self.transient_params = {
            "cursor_row", "cursor_track", "cursor_half", "octave",
            "playhead", "cmd_play", "cmd_stop", "note_preview",
            "queued_pattern", "pattern_status", "cmd_pattern_select",
        }

        # Note-preview state: a single sounding preview note (replaces
        # itself on each new wheel tick) with a threading.Timer to
        # auto-release after _PREVIEW_DURATION_S so the synth doesn't
        # ring forever.
        self._preview: tuple[int, int] | None = None
        self._preview_timer: threading.Timer | None = None

        # Last so on_param_change can guard against saved-config
        # replay: restore_instances() set_params each saved param on
        # the main thread BEFORE this plugin thread runs on_start, so
        # any saved trigger value (cmd_play=True from a mid-play
        # save, etc.) would re-fire its action on every restart.
        # _initialized stays False during that replay window;
        # on_param_change just no-ops until on_start completes.
        self._initialized = True

        # Playback bookkeeping. Playhead position is intentionally
        # separate from current_page / cursor_row so editing during a
        # take doesn't reposition the playback (and vice versa).
        # _record_page / _record_row track the just-fired row so
        # incoming MIDI during playback lands on the row whose notes
        # are currently sounding (live record), instead of wherever
        # the user's edit cursor happens to sit.
        self._lock = threading.RLock()
        self._playing = False
        self._play_page = 0
        self._play_row = 0
        self._record_page = 0
        self._record_row = 0
        # Set true whenever the play position transitions to page 0
        # row 0 by wrapping (last-row-of-last-page, or End-on-last-
        # page). Used to consume `queued_pattern` exactly at the
        # natural pattern boundary. Cleared after the consume.
        self._just_wrapped = False
        # Currently-sounding MIDI note per voice — used to fire the
        # implicit note-off when the next non-`---` cell rolls in.
        self._sounding: list[int | None] = [None] * self.TRACK_COUNT
        # Chord-detection state for record-as-you-play. The chord
        # window is gated by held notes, NOT by a time window: a chord
        # stays open as long as ANY recorded note is still held, and a
        # new chord only starts when all keys are released and the
        # next note-on arrives. This matches the natural musical model
        # (chord = simultaneous-ish notes) far better than a fixed
        # millisecond window — a slow-played chord still records as a
        # chord, and a fast arpeggio still records as a sequence.
        #
        # `_held_recording_keys` is the SET of (channel, note) pairs
        # currently held that were accepted for recording. Empty set
        # = next note-on opens a new chord. Same row/page snapshot is
        # reused across the chord so the user can advance the cursor
        # one step on chord-start and have all in-flight chord notes
        # still land on the original row. The per-channel offset dict
        # tracks polyphonic spread within one chord across multiple
        # matching tracks or in Auto-Ch cursor-spread mode.
        #
        # `_chord_last_event_t` + `_CHORD_STALE_TIMEOUT_S` are a
        # safety net: if a note-off goes missing (USB hiccup,
        # keyboard quirk), the held set could stay non-empty
        # forever. After `_CHORD_STALE_TIMEOUT_S` seconds of total
        # silence on note-on/off the set is force-cleared on the
        # next note-on so recording can recover without a transport
        # cycle.
        self._held_recording_keys: set[tuple[int, int]] = set()
        self._chord_offset_by_ch: dict[int, int] = {}
        self._chord_last_event_t = 0.0
        self._chord_page = 0
        self._chord_row = 0

        # Clock-master generator bookkeeping. Thread spawns on
        # demand the first time send_clock turns on (or on_start
        # if a restored config already had it set).
        self._gen_running = False
        self._gen_thread: threading.Thread | None = None
        self._gen_next_tick_monotonic: float | None = None
        if self._param_values.get("send_clock"):
            self._start_clock_generator()

        # Manual-Play pre-roll timer (see _PLAY_PREROLL_S). Holds the
        # threading.Timer that will fire on_transport_start ~50 ms
        # after the user taps Play; cleared when the start fires or
        # when Stop / panic / unload cancels it first.
        self._preroll_timer: threading.Timer | None = None

    def on_stop(self) -> None:
        self._stop_clock_generator()
        self._cancel_play_preroll()
        self._silence_all()
        self._held_recording_keys.clear()
        self._chord_offset_by_ch.clear()

    def panic(self) -> None:
        """All notes off across every per-track channel + stop the
        playhead. Belt-and-braces: also blanket-clears every channel
        a track is currently configured on, in case the synth held a
        note we never tracked."""
        with self._lock:
            self._playing = False
            self._silence_all()
            channels = {self._track_channel(i) for i in range(self.TRACK_COUNT)}
            for ch in channels:
                for note in range(128):
                    try:
                        self.send_note_off(ch, note)
                    except Exception:
                        pass
        self._cancel_play_preroll()
        self._held_recording_keys.clear()
        self._chord_offset_by_ch.clear()
        self._publish_playhead()

    # ---- Per-track output channel ----
    # 0-based MIDI channel for the given voice index. Reads from the
    # `track_ch_<i>` ChannelSelect param; defaults to 0 (channel 1)
    # if the param is missing or out of range.
    def _track_channel(self, v_idx: int) -> int:
        raw = self._param_values.get(f"track_ch_{v_idx}", 1)
        try:
            return max(0, min(15, int(raw) - 1))
        except (TypeError, ValueError):
            return 0

    # ---- Internal: kill every voice's currently-sounding note. ----
    # `_sounding[i]` carries `(midi_note, channel)` so we can send the
    # note-off on whichever channel the note was actually started on,
    # even if the user has since reassigned that voice's channel.
    def _silence_all(self) -> None:
        for v_idx, sounding in enumerate(self._sounding):
            if sounding is not None:
                note, ch = sounding
                try:
                    self.send_note_off(ch, note)
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

    def _schedule_play_preroll(self) -> None:
        """Manual-Play entry point. Defers on_transport_start by
        _PLAY_PREROLL_S so the first row's note-ons leave ALSA's
        output queue before the next clock tick. Without it, the
        very first MIDI byte after a cold queue takes longer to
        flush than subsequent bytes — the audible duration of row 0
        is then shorter than later rows because its note-off arrives
        on time while its note-on was delayed.

        External Start (e.g. an upstream sequencer) bypasses this and
        goes straight into on_transport_start — that path is already
        aligned to the upstream clock and adding a pre-roll would
        introduce desync."""
        self._cancel_play_preroll()
        timer = threading.Timer(_PLAY_PREROLL_S, self.on_transport_start)
        timer.daemon = True
        self._preroll_timer = timer
        timer.start()

    def _cancel_play_preroll(self) -> None:
        if self._preroll_timer is not None:
            try:
                self._preroll_timer.cancel()
            except Exception:
                pass
            self._preroll_timer = None

    def on_transport_start(self) -> None:
        # Any in-flight pre-roll has just fired (or this was reached
        # by an external Start) — either way drop the reference.
        self._preroll_timer = None
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
        # Emit our own MIDI Start to OUT so downstream slaves
        # bar-align with the Tracker. Honoured by both clock-master
        # mode (send_clock on) and pure-forward mode (send_transport
        # on without send_clock). Hardware-driven Starts route in via
        # on_clock_start and are forwarded there.
        if self._param_values.get("send_transport"):
            try:
                self.send_start()
            except Exception:
                pass

    def on_transport_stop(self) -> None:
        # Cancel any in-flight Play pre-roll so a fast Play→Stop tap
        # doesn't leak a delayed start through the timer.
        self._cancel_play_preroll()
        with self._lock:
            self._silence_all()
            self._playing = False
        self._held_recording_keys.clear()
        self._chord_offset_by_ch.clear()
        self._publish_playhead()
        if self._param_values.get("send_transport"):
            try:
                self.send_stop()
            except Exception:
                pass

    def on_transport_continue(self) -> None:
        with self._lock:
            self._playing = True
        self._publish_playhead()
        if self._param_values.get("send_transport"):
            try:
                self.send_continue()
            except Exception:
                pass

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

        End semantics: `End` on *any* voice of a row means "this row
        is the end-of-page marker — it doesn't play and the page is
        over." When we land on an End row, we immediately jump to
        the next page's row 0 and fire that, all on the same tick —
        no audible gap.

        Bounded by max_iters so a malformed pattern (every page row
        0 = End) stops itself instead of looping forever.

        Publishes the *just-fired* position to the UI so the visual
        ▶ sits on the row whose notes are now sounding, not the row
        about to fire on the next tick.

        ## CC collision algorithm (rightmost voice wins, per channel)

        A row can carry up to TRACK_COUNT CC events — one per voice
        cell. With per-track channels, a CC# is only a "duplicate"
        when both the channel AND the CC number match. Two voices on
        different channels setting CC 7 are independent events; both
        fire. Two voices on the same channel setting CC 7 collapse —
        the rightmost (highest-indexed) voice wins; the earlier
        duplicate is dropped before any MIDI is sent.

        Why rightmost: the voice columns flow left-to-right in the
        cell view; the user reads them as a stack where later columns
        override earlier ones. It also matches the synth's natural
        last-write-wins behaviour without flooding the wire with the
        intermediate values.

        Implementation:

          1. Fire every voice's *note* events first (notes are
             per-voice and don't collide).
          2. Walk the row's voices left-to-right and collect each
             (channel, cc_num) → cc_val into a dict. Dict assignment
             overwrites, so by the end of the loop each (channel,
             cc_num) pair holds the rightmost value set on that
             (channel, cc_num) for the row.
          3. Fire one `send_cc` per surviving entry."""
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
                    # End on ANY voice triggers the skip — lets the
                    # user place the End marker on whichever track
                    # they're already editing without having to jump
                    # back to T1 first.
                    is_end_row = any(
                        isinstance(v, dict) and v.get("note") == "End"
                        for v in voices
                    )
                    if is_end_row:
                        # End row — skip without firing. Jump to next
                        # page row 0 and re-evaluate.
                        new_page = (self._play_page + 1) % len(pages)
                        if new_page == 0:
                            self._just_wrapped = True
                        self._play_page = new_page
                        self._play_row = 0
                        continue

                # Found a non-End row — fire it.
                played_page = self._play_page
                played_row = self._play_row
                # Live recording target — incoming notes / CCs land
                # on the row whose events are now sounding.
                self._record_page = played_page
                self._record_row = played_row

                if isinstance(row, dict):
                    voices = row.get("voices") or []
                    # Pass 1: per-voice notes (no collisions).
                    for v_idx in range(self.TRACK_COUNT):
                        if v_idx < len(voices) and isinstance(voices[v_idx], dict):
                            self._fire_voice_note(v_idx, voices[v_idx])
                    # Pass 2: collect CCs left-to-right keyed by
                    # (channel, cc_num) so different-channel voices
                    # with the same CC# both fire; only same-channel
                    # duplicates collapse. See docstring.
                    pending_cc: dict[tuple[int, int], int] = {}
                    for v_idx in range(self.TRACK_COUNT):
                        if v_idx >= len(voices):
                            break
                        voice = voices[v_idx]
                        if not isinstance(voice, dict):
                            continue
                        cn = voice.get("cc_num")
                        cv = voice.get("cc_val")
                        if isinstance(cn, int) and isinstance(cv, int):
                            ch = self._track_channel(v_idx)
                            pending_cc[(ch, cn)] = cv
                    for (ch, cc_num), cc_val in pending_cc.items():
                        try:
                            self.send_cc(
                                ch,
                                max(0, min(127, cc_num)),
                                max(0, min(127, cc_val)),
                            )
                        except Exception:
                            pass

                # Advance for next call.
                if self._play_row + 1 >= self.MAX_ROWS_PER_PAGE:
                    new_page = (self._play_page + 1) % len(pages)
                    if new_page == 0:
                        self._just_wrapped = True
                    self._play_page = new_page
                    self._play_row = 0
                else:
                    self._play_row += 1

                published = (played_page, played_row, True)
                break
            else:
                # Cycled every page without fireable content (e.g. a
                # single page with End on row 0, used as a "muted"
                # placeholder during live edits). Keep the playhead
                # alive — emit nothing this tick, leave _playing on so
                # the user can drop a note into a cell and have it pick
                # up on the next clock without re-pressing Play. Queued
                # pattern switches still fire because _just_wrapped was
                # set inside the End-skip loop.
                published = (self._play_page, self._play_row, True)

            # Consume any queued pattern switch -- we only swap on a
            # natural pattern boundary (page 0 row 0 reached by wrap).
            # The next on_tick will fire row 0 of the new pattern.
            if self._just_wrapped and self._queued_pattern_idx() >= 0:
                target = self._queued_pattern_idx()
                self._switch_pattern(target,
                                     reset_cursor=True, reset_playhead=False)
                self._set_queued_pattern(-1)
            self._just_wrapped = False

        # Outside the lock — set_param flows to the SSE writer.
        self.set_param("playhead", {
            "page": published[0], "row": published[1], "playing": published[2],
        })

    def _fire_voice_note(self, v_idx: int, voice: dict) -> None:
        """Note-only firing for one voice on the current row. CCs are
        handled separately in `_advance_step` so same-(channel, CC#)
        duplicates across voices collapse to one event (rightmost
        wins).

        Note-off uses the channel the previous note was *started* on,
        not the voice's currently-configured channel — if the user
        retargeted the voice between note-on and note-off, sending
        the off to the new channel would leave the original synth
        ringing forever."""
        note = voice.get("note", "---")
        vel = voice.get("vel")

        # `---` = leave previous note ringing; any other value (Off /
        # End / real pitch) implicitly note-offs the previous one.
        if note == "---":
            return
        prev = self._sounding[v_idx]
        if prev is not None:
            prev_note, prev_ch = prev
            try:
                self.send_note_off(prev_ch, prev_note)
            except Exception:
                pass
            self._sounding[v_idx] = None

        midi = note_str_to_midi(note)
        if midi is None:
            return
        v = vel if isinstance(vel, int) else 90
        v = max(1, min(127, int(v)))
        ch = self._track_channel(v_idx)
        try:
            self.send_note_on(ch, midi, v)
        except Exception:
            pass
        self._sounding[v_idx] = (midi, ch)

    # ================================================================
    # Recording (auto-learn) + pass-through
    # ================================================================

    def _resolve_targets(self, channel: int) -> tuple[list[int], bool]:
        """Return (target_tracks, is_auto) for an incoming MIDI byte
        on `channel` (0-based, matching what on_note_on receives).

        - is_auto=True: the channel matches `auto_ch` — the historic
          cursor-relative recording applies, spreading from
          `cursor_track` across consecutive tracks up to T8.
        - is_auto=False: direct routing — every track whose configured
          `track_ch_i` matches the incoming channel, in T1→T8 order.
          A chord on this channel fills these tracks in order; only
          one match means subsequent chord-window notes overwrite the
          same cell (last-wins, no special case).

        Empty list = no recording, no pass-through.
        """
        auto_ch = int(self._param_values.get("auto_ch") or 0)
        if auto_ch != 0 and (channel + 1) == auto_ch:
            cur_track = int(self._param_values.get("cursor_track") or 0)
            return list(range(cur_track, self.TRACK_COUNT)), True
        matched = [
            i for i in range(self.TRACK_COUNT)
            if self._track_channel(i) == channel
        ]
        return matched, False

    def on_note_on(self, channel: int, note: int, velocity: int) -> None:
        # Pattern control channel: when configured (1..16), notes on this
        # channel are reserved for pattern switching. A press whose note
        # matches one of the configured pattern_note_N values queues a
        # switch (or fires immediately when stopped, via _handle_pattern_
        # command's "tap" mode). All events on the channel are swallowed —
        # no recording, no pass-through, regardless of whether the note
        # matched a slot.
        ctrl_ch = int(self._param_values.get("pattern_ctrl_ch") or 0)
        if ctrl_ch != 0 and (channel + 1) == ctrl_ch:
            if velocity > 0:
                for i in range(self.PATTERN_COUNT):
                    if int(self._param_values.get(f"pattern_note_{i}") or -1) == note:
                        self._handle_pattern_command({"pattern": i, "mode": "tap"})
                        break
            return

        # Channel-driven routing. Auto Ch. → cursor-spread (historic
        # behaviour). Other channels → matching tracks. Unmatched
        # → drop both recording AND pass-through, so the tracker is
        # silent on channels the user hasn't bound to anything.
        targets, _is_auto = self._resolve_targets(channel)
        if not targets:
            return

        # Pass through to OUT on the first target's configured channel.
        # In Auto Ch. mode this is `cursor_track`'s channel — keeps
        # the historic "monitor on the focused voice's destination"
        # behaviour. In direct-routing mode the first target's
        # channel equals the incoming channel, so pass-through is
        # transparent.
        out_ch = self._track_channel(targets[0])
        try:
            self.send_note_on(out_ch, note, max(1, min(127, int(velocity))))
        except Exception:
            pass
        # MIDI: note-on with velocity 0 is a note-off. Discard the
        # key from the held set so a keyboard that uses this idiom
        # (no real note-off byte) doesn't leave the chord open.
        now = time.monotonic()
        if velocity <= 0:
            self._held_recording_keys.discard((channel, note))
            self._chord_last_event_t = now
            return

        # Stale-set recovery: if too much time has passed since the
        # last note-on/off, treat the held set as drift and clear it.
        # Without this guard a missing note-off (USB hiccup, keyboard
        # quirk) would keep the chord open forever and every later
        # recording would land on the same anchored row.
        if (self._held_recording_keys
                and now - self._chord_last_event_t > _CHORD_STALE_TIMEOUT_S):
            self._held_recording_keys.clear()
            self._chord_offset_by_ch.clear()
        self._chord_last_event_t = now

        # New chord = nothing held. Capture the target row + page
        # (one row per chord across ALL channels), reset per-channel
        # offsets, and — when stopped — step the cursor one row so
        # the next chord lands on the next row.
        #
        # Two recording modes for the row/page snapshot:
        #   - PLAYING: row = currently-sounding row (_record_row).
        #     Cursor doesn't move; live-record snaps to the beat.
        #   - STOPPED: row = cursor row. Cursor auto-advances once
        #     per chord (step record).
        if not self._held_recording_keys:
            self._chord_offset_by_ch.clear()
            with self._lock:
                if self._playing:
                    self._chord_page = self._record_page
                    self._chord_row = self._record_row
                else:
                    self._chord_page = int(self._param_values.get("current_page") or 0)
                    self._chord_row = int(self._param_values.get("cursor_row") or 0)
            if not self._playing:
                self._auto_advance_cursor()

        self._held_recording_keys.add((channel, note))

        offset = self._chord_offset_by_ch.get(channel, 0)
        self._chord_offset_by_ch[channel] = offset + 1
        if offset >= len(targets):
            return  # polyphony deeper than matching tracks: drop

        target = targets[offset]
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
        # Pattern control channel: drop note-offs too (the channel is
        # reserved — no pass-through, no held-key bookkeeping).
        ctrl_ch = int(self._param_values.get("pattern_ctrl_ch") or 0)
        if ctrl_ch != 0 and (channel + 1) == ctrl_ch:
            return

        # Symmetric with on_note_on: pass-through on the first
        # routing target's channel. Recording doesn't write
        # release events (playback emits note-offs from the next
        # non-`---` cell or an explicit `Off`).
        targets, _ = self._resolve_targets(channel)
        # Drop the key from the held set even on unmatched channels:
        # if the routing config changed between note-on and note-off
        # (e.g. user re-targeted a track mid-press), we still want
        # the chord to close properly when all keys are released.
        self._held_recording_keys.discard((channel, note))
        self._chord_last_event_t = time.monotonic()
        if not targets:
            return
        try:
            self.send_note_off(self._track_channel(targets[0]), note)
        except Exception:
            pass

    def on_cc(self, channel: int, cc: int, value: int) -> None:
        # Pattern control channel reserves the whole channel — drop CCs too.
        ctrl_ch = int(self._param_values.get("pattern_ctrl_ch") or 0)
        if ctrl_ch != 0 and (channel + 1) == ctrl_ch:
            return

        # Routing mirrors on_note_on but CCs never spread — they
        # always land on the first matching track. Auto Ch. → that's
        # cursor_track; direct routing → first track configured for
        # this channel; unmatched → drop record + pass-through.
        targets, _ = self._resolve_targets(channel)
        if not targets:
            return
        target = targets[0]
        out_ch = self._track_channel(target)
        try:
            self.send_cc(out_ch, max(0, min(127, int(cc))),
                         max(0, min(127, int(value))))
        except Exception:
            pass
        payload = {
            "cc_num": max(0, min(127, int(cc))),
            "cc_val": max(0, min(127, int(value))),
        }
        # Live record while playing — write to the now-sounding row.
        # When stopped, write to the cursor row (no auto-advance for
        # CCs — they're streamed and would walk the cursor away).
        if self._playing:
            with self._lock:
                page_idx = self._record_page
                row_idx = self._record_row
        else:
            page_idx = int(self._param_values.get("current_page") or 0)
            row_idx = int(self._param_values.get("cursor_row") or 0)
        self._record_voice_field_at(page_idx, row_idx, target, payload)

    # ================================================================
    # Clock + transport routing
    #
    # Two independent toggles:
    #   - send_clock     : Tracker = clock master. Internal generator
    #                       (started in _start_clock_generator) emits
    #                       24-PPQ clock at the configured BPM via
    #                       send_clock_at(); the host's ClockBus
    #                       loops that back as on_tick to drive the
    #                       playhead. Incoming clock is dropped
    #                       below (option-1: "Send Clock wins").
    #   - send_transport : Forward incoming START / STOP / CONTINUE
    #                       to OUT, and emit own START / STOP /
    #                       CONTINUE when the on-screen Play / Stop
    #                       button fires (see on_transport_*).
    # ================================================================

    def on_clock(self) -> None:
        # In clock-master mode we generate our own clock; suppressing
        # incoming clock here avoids double-emitting when an external
        # source is also wired in. Otherwise plain drop -- send_clock
        # is the only way to emit clock to OUT now.
        return

    def on_clock_start(self) -> None:
        if self._param_values.get("send_transport"):
            try:
                self.send_start()
            except Exception:
                pass

    def on_clock_stop(self) -> None:
        if self._param_values.get("send_transport"):
            try:
                self.send_stop()
            except Exception:
                pass

    def on_clock_continue(self) -> None:
        if self._param_values.get("send_transport"):
            try:
                self.send_continue()
            except Exception:
                pass

    # ---- Clock-master generator thread ----
    def _start_clock_generator(self) -> None:
        if self._gen_running:
            return
        self._gen_running = True
        self._gen_next_tick_monotonic = None
        self._gen_thread = threading.Thread(
            target=self._clock_refill_loop, daemon=True,
        )
        self._gen_thread.start()

    def _stop_clock_generator(self) -> None:
        if not self._gen_running:
            return
        self._gen_running = False
        try:
            self.cancel_scheduled(self._CLOCK_TAG)
        except Exception:
            pass
        self._gen_next_tick_monotonic = None

    def _clock_refill_loop(self) -> None:
        """Schedule 24-PPQ clock ticks `LOOKAHEAD_S` ahead of wall-
        clock time when send_clock is on. Mirrors the Master Clock
        plugin's refill loop -- send_clock_at() drops the tick into
        the ALSA queue with sub-millisecond jitter; the Python
        sleep here only governs how often the queue is topped up."""
        while self._gen_running:
            bpm = self._param_values.get("bpm")
            try:
                bpm = max(40, min(300, int(bpm or 120)))
            except (TypeError, ValueError):
                bpm = 120
            interval = 60.0 / bpm / 24.0
            now = time.monotonic()
            if (self._gen_next_tick_monotonic is None
                    or self._gen_next_tick_monotonic < now):
                self._gen_next_tick_monotonic = now + 0.001
            target = now + self._CLOCK_LOOKAHEAD_S
            while (self._gen_running
                   and self._gen_next_tick_monotonic < target):
                try:
                    self.send_clock_at(
                        self._gen_next_tick_monotonic, self._CLOCK_TAG,
                    )
                except Exception:
                    pass
                self._gen_next_tick_monotonic += interval
            time.sleep(self._CLOCK_LOOKAHEAD_S * 0.5)

    # ================================================================
    # Manual transport — Play / Stop buttons in the play-page header
    # ================================================================

    def on_param_change(self, name: str, value: Any) -> None:
        # Guard against config-restore replay. restore_instances()
        # synchronously set_params each saved param on the main
        # thread BEFORE the plugin thread runs on_start; without
        # this guard, a saved cmd_play=True (from a mid-play save)
        # would re-fire on every plugin restart. on_start sets
        # _initialized=True at the end, so legitimate user clicks
        # that arrive AFTER boot still work.
        if not getattr(self, "_initialized", False):
            return
        # Trigger-style booleans the play-page header writes via
        # onChange. We fire the local transport handler then reset
        # the bool to False (broadcasts back to all clients).
        if name == "cmd_play" and value:
            self._schedule_play_preroll()
            self.set_param("cmd_play", False)
        elif name == "cmd_stop" and value:
            self.on_transport_stop()
            self.set_param("cmd_stop", False)
        elif name == "note_preview" and isinstance(value, int) and 0 <= value <= 127:
            self._preview_fire(value)
            self.set_param("note_preview", -1)
        elif name == "pages":
            # Edits to the live grid mirror through to the storage
            # array, so the selected pattern keeps its content. The
            # helper also refreshes pattern_status in case the slot
            # flipped empty <-> non-empty. (Internal pages mutations
            # in live-record paths call the helper directly.)
            self._mirror_pages_to_selected_pattern(value)
        elif name == "patterns":
            # Restored configs land here: the host's _restore_instances
            # runs on_start first (which seeds pattern_status against
            # empty patterns), then set_param("patterns", saved) — and
            # without this branch, only the selected slot ever got its
            # status refreshed (via the "pages" mirror). All other
            # non-empty slots stayed flagged empty and rendered
            # dashed-outline despite holding data. Recompute the
            # whole status array from the incoming `value` (not from
            # _param_values, which the host already mirrors but in-
            # process callers might not) so every slot's highlight
            # matches the loaded content.
            if isinstance(value, list):
                status = [not self._is_empty_pattern(p) for p in value]
                self.set_param("pattern_status", status)
        elif name == "cmd_pattern_select" and isinstance(value, dict):
            self._handle_pattern_command(value)
            # Reset the trigger so a re-tap of the same slot fires.
            self.set_param("cmd_pattern_select", None)
        elif name == "send_clock":
            # Spin the internal generator up / down. The generator
            # thread is the only thing that calls send_clock_at, so
            # toggling here cleanly starts / stops the OUT emission
            # AND the loopback that drives our own playhead.
            if value:
                self._start_clock_generator()
            else:
                self._stop_clock_generator()
        elif name == "bpm" and self._gen_running:
            # Drop the rest of the pre-scheduled burst and re-anchor
            # at the new tempo; the refill loop picks up from now.
            try:
                self.cancel_scheduled(self._CLOCK_TAG)
            except Exception:
                pass
            self._gen_next_tick_monotonic = None

    # ================================================================
    # Pattern bank -- 8 stored grids per Tracker, with one selected
    # (= what `pages` mirrors) and (optionally) one queued for the
    # next page-0 row-0 boundary.
    # ================================================================

    def _mirror_pages_to_selected_pattern(self, pages: list) -> None:
        """Write the live `pages` value into patterns[selected]. The
        on_param_change("pages", ...) mirror only catches external
        (API) writes; internal mutations (live recording, chord
        spread) call self.set_param("pages", ...) which doesn't
        fire on_param_change, so we need to mirror manually."""
        sel = int(self._param_values.get("selected_pattern", 0))
        patterns = list(self._param_values.get("patterns") or [])
        if 0 <= sel < len(patterns):
            patterns[sel] = pages
            self._param_values["patterns"] = patterns
            self._refresh_pattern_status_slot(sel)

    def _queued_pattern_idx(self) -> int:
        v = self._param_values.get("queued_pattern", -1)
        try:
            return int(v)
        except (TypeError, ValueError):
            return -1

    def _set_queued_pattern(self, idx: int) -> None:
        self.set_param("queued_pattern", int(idx))

    def _empty_pages(self) -> list:
        return [empty_page(self.TRACK_COUNT, self.MAX_ROWS_PER_PAGE)]

    def _is_empty_pattern(self, pages: list) -> bool:
        """A pattern is 'empty' iff it's exactly one default page with
        every voice cell at default values. Multi-page or any non-
        default cell means non-empty."""
        if not isinstance(pages, list) or len(pages) != 1:
            return False
        page = pages[0]
        if not isinstance(page, dict):
            return False
        rows = page.get("rows") or []
        if len(rows) != self.MAX_ROWS_PER_PAGE:
            return False
        empty_v = empty_voice()
        for row in rows:
            if not isinstance(row, dict):
                continue
            voices = row.get("voices") or []
            for v in voices:
                if not isinstance(v, dict):
                    continue
                for key, default in empty_v.items():
                    if v.get(key, default) != default:
                        return False
        return True

    def _compute_pattern_status(self) -> list:
        patterns = self._param_values.get("patterns") or []
        return [not self._is_empty_pattern(p) for p in patterns]

    def _refresh_pattern_status_slot(self, idx: int) -> None:
        """Recompute pattern_status[idx] and broadcast if it changed.
        Cheaper than recomputing all 8 on every cell edit."""
        patterns = self._param_values.get("patterns") or []
        if not (0 <= idx < len(patterns)):
            return
        status = list(self._param_values.get("pattern_status") or [])
        # Pad if status is shorter than patterns (defensive).
        while len(status) < len(patterns):
            status.append(False)
        new = not self._is_empty_pattern(patterns[idx])
        if status[idx] != new:
            status[idx] = new
            self.set_param("pattern_status", status)

    def _switch_pattern(self, idx: int,
                        reset_cursor: bool, reset_playhead: bool) -> None:
        """Load pattern `idx` into the live view.

        `reset_cursor` -- send cursor to (0, 0). Used by stopped+tap
            and queued (playing+tap-on-boundary) switches.
        `reset_playhead` -- send the playhead to (0, 0). Used by
            stopped+tap. NOT used by a queued switch (the playhead is
            already at (0, 0) by virtue of the wrap that triggered the
            consume). NOT used by Shift+Tap (the caller positions the
            playhead with the fallback rule).
        """
        idx = max(0, min(self.PATTERN_COUNT - 1, int(idx)))
        patterns = list(self._param_values.get("patterns") or [])
        if not (0 <= idx < len(patterns)):
            return
        # Deep-ish copy: a new list of references to the page dicts is
        # enough -- edits go through _record_voice_field_at which
        # always replaces the rows / voices on the way down, never
        # mutates in place.
        new_pages = list(patterns[idx])
        self.set_param("selected_pattern", idx)
        # set_param("pages", ...) will trigger our own on_param_change
        # mirror-back, but `patterns[idx]` is already what we're
        # writing, so the mirror is a no-op other than a status
        # refresh -- which is also a no-op. Safe.
        self.set_param("pages", new_pages)
        if reset_cursor:
            self.set_param("current_page", 0)
            self.set_param("cursor_row", 0)
        if reset_playhead:
            with self._lock:
                self._play_page = 0
                self._play_row = 0
                self._record_page = 0
                self._record_row = 0

    def _clone_pattern(self, src: int, dst: int) -> None:
        """Copy patterns[src] into patterns[dst]. Pages are duplicated
        by value (rows + voices) so subsequent edits on either slot
        don't bleed into the other."""
        src = max(0, min(self.PATTERN_COUNT - 1, int(src)))
        dst = max(0, min(self.PATTERN_COUNT - 1, int(dst)))
        if src == dst:
            return
        patterns = list(self._param_values.get("patterns") or [])
        if not (0 <= src < len(patterns) and 0 <= dst < len(patterns)):
            return
        import copy
        patterns[dst] = copy.deepcopy(patterns[src])
        self._param_values["patterns"] = patterns
        # If we just cloned into the currently-selected slot, refresh
        # the live `pages` mirror too.
        if dst == int(self._param_values.get("selected_pattern", 0)):
            self.set_param("pages", list(patterns[dst]))
        self._refresh_pattern_status_slot(dst)

    def _clear_pattern(self, idx: int) -> None:
        idx = max(0, min(self.PATTERN_COUNT - 1, int(idx)))
        patterns = list(self._param_values.get("patterns") or [])
        if not (0 <= idx < len(patterns)):
            return
        patterns[idx] = self._empty_pages()
        self._param_values["patterns"] = patterns
        if idx == int(self._param_values.get("selected_pattern", 0)):
            self.set_param("pages", list(patterns[idx]))
            self.set_param("current_page", 0)
            self.set_param("cursor_row", 0)
        self._refresh_pattern_status_slot(idx)

    def _handle_pattern_command(self, cmd: dict) -> None:
        """Dispatch a pattern-row interaction from the UI.

        cmd shape: {"pattern": int 0..N-1, "mode": str}
        modes:
          - "tap"   -- stopped: switch + cursor to (0,0); playing: queue
          - "shift" -- switch immediately, preserve playhead with the
                       page-0 row-current+1 fallback
          - "clone" -- copy currently-selected pattern into target
          - "clear" -- empty the target pattern
        """
        try:
            idx = int(cmd.get("pattern"))
        except (TypeError, ValueError):
            return
        mode = cmd.get("mode")
        if not (0 <= idx < self.PATTERN_COUNT):
            return

        if mode == "clone":
            sel = int(self._param_values.get("selected_pattern", 0))
            self._clone_pattern(sel, idx)
            return
        if mode == "clear":
            self._clear_pattern(idx)
            return

        sel = int(self._param_values.get("selected_pattern", 0))
        if mode == "tap":
            if not self._playing:
                # Stopped + tap: switch view immediately, cursor +
                # playhead both reset to (0, 0). Tapping the already-
                # selected slot is a no-op other than the cursor jump
                # -- which is the documented "cursor → (0,0) when
                # stopped + tap" behaviour.
                self._switch_pattern(idx, reset_cursor=True,
                                     reset_playhead=True)
                # Cancel any prior queue (it's meaningless now).
                self._set_queued_pattern(-1)
            else:
                # Playing + tap: queue. The switch fires on the next
                # natural page-0 row-0 boundary. Tapping the playing
                # slot cancels the queue (lets the user undo a
                # mistaken queue).
                if idx == sel:
                    self._set_queued_pattern(-1)
                else:
                    self._set_queued_pattern(idx)
        elif mode == "shift":
            # Shift+Tap: immediate switch.
            patterns = self._param_values.get("patterns") or []
            if not (0 <= idx < len(patterns)):
                return
            target_pages = patterns[idx]
            if not self._playing:
                # Stopped variant -- same as plain tap.
                self._switch_pattern(idx, reset_cursor=True,
                                     reset_playhead=True)
                self._set_queued_pattern(-1)
                return
            # Decide the new playhead position before switching.
            with self._lock:
                cur_page = self._play_page
                cur_row = self._play_row
                if cur_page < len(target_pages):
                    # Target has this page; keep (page, row).
                    new_page, new_row = cur_page, cur_row
                else:
                    # Target is shorter -- jump to page 0, same row
                    # index (the row that would have fired next).
                    new_page, new_row = 0, cur_row % self.MAX_ROWS_PER_PAGE
            # Switch view (no cursor reset, no playhead reset --
            # we'll position it manually below).
            self._switch_pattern(idx, reset_cursor=False,
                                 reset_playhead=False)
            with self._lock:
                self._play_page = new_page
                self._play_row = new_row
            self._set_queued_pattern(-1)
            self._publish_playhead()

    # ---- Note preview (wheel / keyboard typing → audible OUT) ----
    def _preview_fire(self, midi: int) -> None:
        """Fire a brief note-on for the picked note out the focused
        track's channel, then schedule the matching note-off after
        _PREVIEW_DURATION_S. Fast successive calls cancel the prior
        preview so the synth never accumulates zombies."""
        # Cancel any in-flight preview release first.
        if self._preview_timer is not None:
            try:
                self._preview_timer.cancel()
            except Exception:
                pass
            self._preview_timer = None
        if self._preview is not None:
            prev_note, prev_ch = self._preview
            try:
                self.send_note_off(prev_ch, prev_note)
            except Exception:
                pass
            self._preview = None

        cur_track = int(self._param_values.get("cursor_track") or 0)
        ch = self._track_channel(cur_track)
        try:
            self.send_note_on(ch, midi, 90)
        except Exception:
            return
        self._preview = (midi, ch)
        self._preview_timer = threading.Timer(
            _PREVIEW_DURATION_S, self._preview_release,
        )
        # Daemon=True so a stray timer doesn't keep the process alive.
        self._preview_timer.daemon = True
        self._preview_timer.start()

    def _preview_release(self) -> None:
        if self._preview is None:
            return
        note, ch = self._preview
        try:
            self.send_note_off(ch, note)
        except Exception:
            pass
        self._preview = None
        self._preview_timer = None

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
            # Live-recorded edits don't go through on_param_change
            # (set_param is internal-only), so the patterns[] mirror
            # would miss them. Sync explicitly so a pattern switch +
            # switch-back preserves what was just recorded.
            self._mirror_pages_to_selected_pattern(pages)
