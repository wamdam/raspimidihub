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
  - recv_transport : bool                  — when on (default) incoming
                                              transport from a clock master /
                                              another instrument starts, stops
                                              and continues the playhead; when
                                              off, only the on-screen Play /
                                              Stop buttons drive it
  - bpm            : int                   — internal BPM (40..300) used when
                                              send_clock is on
  - cmd_play / cmd_stop : bool             — manual transport signals from
                                              the play-page header buttons
  - trigger_mode   : int 0..3              — how Pt. Ctrl Ch trigger notes
                                              behave: 0 Switch (queue/immediate
                                              pattern select, the default),
                                              1 One-shot, 2 Hold, 3 Toggle.
                                              Modes 1..3 launch the pattern
                                              from row 0 on the next clock step
                                              without a transport Start.

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
from dataclasses import dataclass
from typing import Any

from raspimidihub.clock_gen import ScheduledClockGenerator
from raspimidihub.plugin_api import (
    Button,
    ChannelSelect,
    Group,
    NoteSelect,
    PluginBase,
    StructuralParam,
    Wheel,
)


@dataclass
class TrackerGrid(StructuralParam):
    """Tracker-style sequencer grid: 16 hex-numbered step rows × 1..8
    voice columns, paged up to 16 pages, with an always-visible
    data-entry keypad below.

    Structural element (no value of its own) — actual sequencer state
    lives in sibling auxiliary params named here. Lives next to
    TrackerBase rather than in plugin_api.py because every field is
    specific to this one plugin's UI shape; plugin_api.py exposes the
    `StructuralParam` base so it can walk this generically without
    naming the plugin.

    `pages_param`: list of page dicts. Each page is
      `{"rows": [{"voices": [VoiceCell × N]}, ...]}`
      where VoiceCell is
      `{"note": str, "vel": int|str, "cc_num": int|str, "cc_val": int|str}`.
    `current_page_param`: int (0..MAX_PAGES-1) — visible page.
    `cursor_row_param`, `cursor_track_param`: ints — edit-cursor focus.
    `octave_param`: int (0..9) — sticky octave on the keypad.
    """
    name: str
    label: str
    track_count: int = 8
    max_pages: int = 16
    max_rows: int = 16
    pages_param: str | None = None
    current_page_param: str | None = None
    cursor_row_param: str | None = None
    cursor_track_param: str | None = None
    cursor_half_param: str | None = None
    octave_param: str | None = None
    rate_param: str | None = None
    playhead_param: str | None = None  # {page, row, playing} broadcast per step
    track_channels_param: str | None = None  # base name; per-track lookup as <name>_<idx>
    cmd_play_param: str | None = None  # bool, frontend → backend trigger
    cmd_stop_param: str | None = None  # bool, frontend → backend trigger
    send_clock_param: str | None = None  # bool, latching toggle
    note_preview_param: str | None = None  # int (MIDI note), frontend → backend trigger
    # Pattern bank -- 8 stored grids per Tracker instance, with one
    # currently selected + (optionally) one queued for the next
    # boundary. See TrackerBase / PatternRow for the full flow.
    patterns_param: str | None = None               # list[list[Page]]: stored grids
    selected_pattern_param: str | None = None       # int 0..N-1
    queued_pattern_param: str | None = None         # int 0..N-1 or -1 (none)
    pattern_status_param: str | None = None         # list[bool]: has-content per slot
    cmd_pattern_select_param: str | None = None     # dict {pattern, mode}, frontend → backend
    pattern_count: int = 8

    def to_dict(self) -> dict:
        d = {
            "type": "trackergrid",
            # `play_only` is a hint to the renderparam dispatcher: the
            # tracker grid + keypad only make sense on the play
            # surface (not the device-detail config card), so the
            # frontend skips it when displayCtx.playOnly is false.
            "play_only": True,
            "name": self.name,
            "label": self.label,
            "track_count": self.track_count,
            "max_pages": self.max_pages,
            "max_rows": self.max_rows,
            "pattern_count": self.pattern_count,
        }
        for attr in ("pages_param", "current_page_param", "cursor_row_param",
                     "cursor_track_param", "cursor_half_param",
                     "octave_param", "rate_param", "playhead_param",
                     "track_channels_param", "cmd_play_param",
                     "cmd_stop_param", "send_clock_param",
                     "note_preview_param", "patterns_param",
                     "selected_pattern_param", "queued_pattern_param",
                     "pattern_status_param", "cmd_pattern_select_param"):
            v = getattr(self, attr)
            if v:
                d[attr] = v
        return d

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

    # ALSA-queue scheduled tag for the clock-master generator's
    # pre-emitted burst. Distinct from other plugins' tags via the
    # 0xC10C magic so cancel_scheduled() drops only our ticks.
    _CLOCK_TAG = 0xC10C

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
            Button("send_transport", "Send Trnsp.",
                   default=False, color="green", config_only=True),
            # Receive transport: when on (default), incoming transport
            # from the global clock bus (a clock master or another
            # instrument's START / STOP / CONTINUE) drives this
            # Tracker's playhead. When off, the Tracker ignores foreign
            # transport and only its own Play / Stop buttons (and the
            # launch trigger modes) start it -- useful for a Tracker
            # that should free-run on a shared clock without being
            # started/stopped by the rest of the rig.
            Button("recv_transport", "Rcv Trnsp.",
                   default=True, color="green", config_only=True),
            # Pattern control channel: when set to 1..16, incoming notes
            # on that channel never record or pass through — instead each
            # configured pattern_note_N triggers a pattern switch (queued
            # to the next page-0 boundary while playing, immediate while
            # stopped). 0 = Off, no interception.
            Wheel("pattern_ctrl_ch", "Pt. Ctrl Ch",
                  min=0, max=16, default=0,
                  labels=["Off"] + [str(i) for i in range(1, 17)],
                  config_only=True),
            # How a trigger note on the control channel behaves:
            #   Switch   — historic pattern-select (queue while playing,
            #              immediate while stopped). The default; old
            #              configs upgrade to this so nothing changes.
            #   One-shot — launch the pattern from row 0 on the next
            #              clock step, play once through, then stop.
            #   Hold     — launch while the key is held (looping), stop
            #              on release.
            #   Toggle   — launch on press, stop on a second press.
            # One-shot / Hold / Toggle drive the playhead straight from
            # incoming clock without a transport Start, so a key press
            # fires the phrase wherever you are in the song.
            Wheel("trigger_mode", "Trigger Mode",
                  min=0, max=3, default=0,
                  labels=["Switch", "One-shot", "Hold", "Toggle"],
                  config_only=True,
                  visible_when=("pattern_ctrl_ch", list(range(1, 17)))),
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
        # Receive transport: default on so existing configs (which
        # predate the toggle) keep responding to external transport
        # exactly as before.
        self._param_values.setdefault("recv_transport", True)
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
        # Trigger mode: 0 = Switch (historic). Old configs predate this
        # key, so setdefault keeps their behaviour identical.
        self._param_values.setdefault("trigger_mode", 0)

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
        # Pattern-launch state (One-shot / Hold / Toggle trigger modes).
        # Independent of `_playing` (which is transport-driven): a launch
        # advances the playhead straight off incoming clock. `_launch_note`
        # remembers the control-channel note that started it so Hold mode
        # can stop on the matching release. `_launch_oneshot_ending` defers
        # the One-shot stop by one tick so the final row keeps a full step
        # of ring before its note-off — see _advance_step.
        self._launch_active = False
        self._launch_note: int | None = None
        self._launch_oneshot_ending = False
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
        # Recording state. Two distinct models depending on transport:
        #
        # STOPPED = step record. Notes held together form a chord: the
        # window is gated by held notes, not a time window — a chord
        # stays open as long as ANY note is held, and a new chord only
        # starts once all keys release. The whole chord lands on the
        # cursor row (one row/page snapshot reused across the chord)
        # spread across consecutive tracks, and the cursor advances one
        # step per chord. `_chord_offset_by_ch` tracks that per-channel
        # track spread; `_chord_page/_chord_row` hold the snapshot.
        #
        # PLAYING = live record. The chord-to-one-row model does NOT
        # apply: each note-on records where the playhead is at the
        # moment it arrives (`_record_page/_record_row`), so a melody
        # lands on the beats it was played on. Notes that arrive within
        # the SAME step still spread across consecutive tracks via
        # `_live_offset_by_ch`, which `_advance_step` resets every time
        # the playhead moves to a new row. Note-offs are recorded too:
        # `_held_recording_keys` maps each held (channel, note) to the
        # track its note-on landed on (or None if it wasn't recorded)
        # so the matching release can write an explicit `Off` to that
        # same cell, capturing duration.
        #
        # `_held_recording_keys` doubles as the chord-gate when stopped
        # (non-empty = a chord is open). `_chord_last_event_t` +
        # `_CHORD_STALE_TIMEOUT_S` are a safety net: if a note-off goes
        # missing (USB hiccup, keyboard quirk) the held map could stay
        # non-empty forever, so it's force-cleared on the next note-on
        # after that much silence.
        self._held_recording_keys: dict[tuple[int, int], int | None] = {}
        self._chord_offset_by_ch: dict[int, int] = {}
        self._live_offset_by_ch: dict[int, int] = {}
        self._chord_last_event_t = 0.0
        self._chord_page = 0
        self._chord_row = 0

        # Clock-master generator. Wraps the shared ScheduledClockGenerator
        # helper so the refill thread + the BPM-change re-anchor logic
        # match the Master Clock plugin. start() is a no-op if send_clock
        # is off; we always call it on_start to keep the lifecycle simple.
        self._clock_gen = ScheduledClockGenerator(
            self, bpm_getter=lambda: self._param_values.get("bpm"),
            tag=self._CLOCK_TAG,
        )
        if self._param_values.get("send_clock"):
            self._clock_gen.start()

        # Manual-Play pre-roll timer (see _PLAY_PREROLL_S). Holds the
        # threading.Timer that will fire _begin_playback ~50 ms
        # after the user taps Play; cleared when the start fires or
        # when Stop / panic / unload cancels it first.
        self._preroll_timer: threading.Timer | None = None

    def on_stop(self) -> None:
        self._clock_gen.stop()
        self._cancel_play_preroll()
        self._launch_active = False
        self._launch_note = None
        self._launch_oneshot_ending = False
        self._silence_all()
        self._held_recording_keys.clear()
        self._chord_offset_by_ch.clear()
        self._live_offset_by_ch.clear()

    def panic(self) -> None:
        """All notes off across every per-track channel + stop the
        playhead. Belt-and-braces: also blanket-clears every channel
        a track is currently configured on, in case the synth held a
        note we never tracked."""
        with self._lock:
            self._playing = False
            self._launch_active = False
            self._launch_note = None
            self._launch_oneshot_ending = False
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
        self._live_offset_by_ch.clear()
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

    # ---- Internal: is the playhead advancing right now? ----
    # True when transport is running OR a pattern launch (One-shot /
    # Hold / Toggle) is in flight. on_tick advances on either; the UI
    # ▶ indicator and Play-button green follow this.
    def _is_running(self) -> bool:
        return self._playing or self._launch_active

    # ---- Internal: push the current playhead state to the UI. ----
    def _publish_playhead(self) -> None:
        # Dict literal so SSE serialises cleanly. set_param both stores
        # in _param_values and emits the plugin-param event.
        self.set_param("playhead", {
            "page": self._play_page,
            "row": self._play_row,
            "playing": self._is_running(),
        })

    # ================================================================
    # Transport — global ClockBus events
    # ================================================================

    def _schedule_play_preroll(self) -> None:
        """Manual-Play entry point. Defers _begin_playback by
        _PLAY_PREROLL_S so the first row's note-ons leave ALSA's
        output queue before the next clock tick. Without it, the
        very first MIDI byte after a cold queue takes longer to
        flush than subsequent bytes — the audible duration of row 0
        is then shorter than later rows because its note-off arrives
        on time while its note-on was delayed.

        External Start (e.g. an upstream sequencer) bypasses this and
        goes straight into _begin_playback via on_transport_start —
        that path is already aligned to the upstream clock and adding
        a pre-roll would introduce desync. The pre-roll target is
        _begin_playback (not on_transport_start) so the Play button
        always starts the playhead regardless of the Rcv Trnsp.
        toggle, which only gates *external* transport."""
        self._cancel_play_preroll()
        timer = threading.Timer(_PLAY_PREROLL_S, self._begin_playback)
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

    # External transport (ClockBus broadcast from a clock master or
    # another instrument). Gated by Rcv Trnsp.: when off, the Tracker
    # ignores foreign START / STOP / CONTINUE entirely and is driven
    # only by its own Play / Stop buttons and the launch trigger modes.
    # The buttons call the _*_playback cores directly, bypassing this
    # gate.
    def on_transport_start(self) -> None:
        if not self._param_values.get("recv_transport", True):
            return
        self._begin_playback()

    def on_transport_stop(self) -> None:
        if not self._param_values.get("recv_transport", True):
            return
        self._end_playback()

    def on_transport_continue(self) -> None:
        if not self._param_values.get("recv_transport", True):
            return
        self._resume_playback()

    # ---- Playback cores (used by both external transport and the
    # on-screen Play / Stop buttons). ----
    def _begin_playback(self) -> None:
        # Any in-flight pre-roll has just fired (or this was reached
        # by an external Start) — either way drop the reference.
        self._preroll_timer = None
        with self._lock:
            self._silence_all()
            self._play_page = 0
            self._play_row = 0
            self._playing = True
            # A fresh transport start supersedes any in-flight launch.
            self._launch_active = False
            self._launch_note = None
            self._launch_oneshot_ending = False
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

    def _end_playback(self) -> None:
        # Cancel any in-flight Play pre-roll so a fast Play→Stop tap
        # doesn't leak a delayed start through the timer.
        self._cancel_play_preroll()
        with self._lock:
            self._silence_all()
            self._playing = False
            self._launch_active = False
            self._launch_note = None
            self._launch_oneshot_ending = False
        self._held_recording_keys.clear()
        self._chord_offset_by_ch.clear()
        self._live_offset_by_ch.clear()
        self._publish_playhead()
        if self._param_values.get("send_transport"):
            try:
                self.send_stop()
            except Exception:
                pass

    def _resume_playback(self) -> None:
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
        # Transport-driven OR launch-driven. Transport (a MIDI Start)
        # starts the whole sequence from the top; a pattern launch
        # (One-shot / Hold / Toggle trigger) advances the playhead off
        # the same clock without a Start. Plain clock with neither
        # active leaves the playhead parked — no silent marching.
        if not (self._playing or self._launch_active):
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
        # One-shot launch that completed its last loop on the previous
        # tick: the final row has now had its full step of ring time,
        # so release it and stop instead of restarting the pattern.
        ended = False
        with self._lock:
            if self._launch_oneshot_ending:
                self._launch_oneshot_ending = False
                self._launch_active = False
                self._launch_note = None
                self._silence_all()
                self._just_wrapped = False
                ended = True
                end_page, end_row = self._play_page, self._play_row
        if ended:
            self.set_param("playhead", {
                "page": end_page, "row": end_row,
                "playing": self._is_running(),
            })
            return

        published = None
        with self._lock:
            # One-shot launches stop at the pattern's natural end; other
            # modes (and transport play) loop.
            oneshot = self._launch_active and int(
                self._param_values.get("trigger_mode") or 0) == 1
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
                            if oneshot:
                                # One-shot reached the end via an End
                                # marker. The last real row fired on the
                                # previous tick, and the End row sits in
                                # the slot where its note-off naturally
                                # lands — so release + stop now rather
                                # than wrapping to row 0.
                                self._launch_active = False
                                self._launch_note = None
                                self._silence_all()
                                self._play_page = 0
                                self._play_row = 0
                                published = (0, 0, False)
                                break
                        self._play_page = new_page
                        self._play_row = 0
                        continue

                # Found a non-End row — fire it.
                played_page = self._play_page
                played_row = self._play_row
                # Live recording target — incoming notes / CCs land
                # on the row whose events are now sounding. Moving to a
                # new row resets the live-record track spread so the
                # next note-on starts at this row's first target rather
                # than continuing the previous row's chord spread.
                self._record_page = played_page
                self._record_row = played_row
                self._live_offset_by_ch.clear()

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
                        if oneshot:
                            # Last row just fired; let it ring one more
                            # step, then stop on the next tick instead
                            # of looping (the ending-guard at the top
                            # of _advance_step does the actual stop).
                            self._launch_oneshot_ending = True
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
                        mode = int(self._param_values.get("trigger_mode") or 0)
                        if mode == 0:
                            # Switch — historic queue/immediate select.
                            self._handle_pattern_command(
                                {"pattern": i, "mode": "tap"})
                        else:
                            # One-shot / Hold / Toggle — launch the
                            # pattern off incoming clock.
                            self._launch_trigger(i, note, mode)
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
        now = time.monotonic()
        # MIDI: a note-on with velocity 0 is a note-off. Pass it
        # through as a real note-off (not a velocity-1 note-on, which
        # would strand the note on the synth) and route it into the
        # same release-recording path as an explicit note-off.
        if velocity <= 0:
            try:
                self.send_note_off(out_ch, note)
            except Exception:
                pass
            self._record_live_note_off(channel, note)
            self._chord_last_event_t = now
            return
        try:
            self.send_note_on(out_ch, note, max(1, min(127, int(velocity))))
        except Exception:
            pass

        # Stale-set recovery: if too much time has passed since the
        # last note-on/off, treat the held map as drift and clear it.
        # Without this guard a missing note-off (USB hiccup, keyboard
        # quirk) would keep the chord open forever and every later
        # recording would land on the same anchored row.
        if (self._held_recording_keys
                and now - self._chord_last_event_t > _CHORD_STALE_TIMEOUT_S):
            self._held_recording_keys.clear()
            self._chord_offset_by_ch.clear()
            self._live_offset_by_ch.clear()
        self._chord_last_event_t = now

        if self._playing:
            # LIVE RECORD: the note lands where the playhead is right
            # now. Notes arriving within the same step spread across
            # consecutive tracks (the spread is reset per step in
            # _advance_step); the cursor is not touched.
            self._live_record_note_on(channel, note, velocity, targets)
            return

        # STOPPED = step record. A new chord (nothing held) snapshots
        # the cursor row, resets the per-channel spread, and advances
        # the cursor one row so the next chord lands below. Notes held
        # together reuse that snapshot and spread across tracks.
        if not self._held_recording_keys:
            self._chord_offset_by_ch.clear()
            self._chord_page = int(self._param_values.get("current_page") or 0)
            self._chord_row = int(self._param_values.get("cursor_row") or 0)
            self._auto_advance_cursor()

        offset = self._chord_offset_by_ch.get(channel, 0)
        self._chord_offset_by_ch[channel] = offset + 1
        note_str = midi_to_note_str(note)
        rec_track = (targets[offset]
                     if offset < len(targets) and note_str is not None
                     else None)
        # Held-map membership gates the chord; the track value is unused
        # when stopped (offs are only recorded while playing).
        self._held_recording_keys[(channel, note)] = rec_track
        if rec_track is None:
            return
        self._record_voice_field_at(
            self._chord_page, self._chord_row, rec_track,
            {"note": note_str, "vel": max(1, min(127, int(velocity)))},
        )

    def _live_record_note_on(
        self, channel: int, note: int, velocity: int, targets: list[int],
    ) -> None:
        """Record one note-on at the current playhead row while playing.
        Tracks arriving in the same step spread across `targets` via
        `_live_offset_by_ch` (reset per step in _advance_step). The
        chosen track is stashed in `_held_recording_keys` so the
        matching note-off can write its `Off` to the same cell."""
        with self._lock:
            page_idx = self._record_page
            row_idx = self._record_row
            offset = self._live_offset_by_ch.get(channel, 0)
            self._live_offset_by_ch[channel] = offset + 1
        note_str = midi_to_note_str(note)
        rec_track = (targets[offset]
                     if offset < len(targets) and note_str is not None
                     else None)
        self._held_recording_keys[(channel, note)] = rec_track
        if rec_track is None:
            return
        self._record_voice_field_at(
            page_idx, row_idx, rec_track,
            {"note": note_str, "vel": max(1, min(127, int(velocity)))},
        )

    def _record_live_note_off(self, channel: int, note: int) -> None:
        """Close a held note. Always drops the key from the held map
        (so the step-record chord closes when stopped); additionally,
        while playing, writes an explicit `Off` to the track the
        note-on landed on, at the current playhead row — capturing the
        note's duration. The `Off` is only written into an empty (`---`)
        cell so it never clobbers a note just played on that
        track/row (a new note implies the previous one's end anyway)."""
        rec_track = self._held_recording_keys.pop((channel, note), None)
        if not self._playing or rec_track is None:
            return
        with self._lock:
            page_idx = self._record_page
            row_idx = self._record_row
            cur = None
            pages = self._param_values.get("pages") or []
            if page_idx < len(pages):
                page = pages[page_idx]
                rows = page.get("rows") if isinstance(page, dict) else None
                if rows and row_idx < len(rows):
                    row = rows[row_idx]
                    voices = row.get("voices") if isinstance(row, dict) else None
                    if (voices and rec_track < len(voices)
                            and isinstance(voices[rec_track], dict)):
                        cur = voices[rec_track].get("note")
        if cur != NOTE_HOLD:
            return
        self._record_voice_field_at(page_idx, row_idx, rec_track,
                                    {"note": NOTE_OFF})

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
        # reserved — no pass-through, no held-key bookkeeping). The one
        # exception is Hold mode, where releasing the trigger key that
        # started the active launch stops it.
        ctrl_ch = int(self._param_values.get("pattern_ctrl_ch") or 0)
        if ctrl_ch != 0 and (channel + 1) == ctrl_ch:
            if (int(self._param_values.get("trigger_mode") or 0) == 2
                    and self._launch_active and note == self._launch_note):
                self._launch_stop()
            return

        # Symmetric with on_note_on: pass-through on the first routing
        # target's channel. _record_live_note_off closes the held key
        # (so the step-record chord closes when stopped) and, while
        # playing, writes an `Off` to the track the note-on landed on
        # so the recorded note gets its real duration. It pops the key
        # even on unmatched channels: if the routing config changed
        # between note-on and note-off (e.g. the user re-targeted a
        # track mid-press), the chord must still close on release.
        targets, _ = self._resolve_targets(channel)
        self._record_live_note_off(channel, note)
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
    #   - send_clock     : Tracker = clock master. The shared
    #                       ScheduledClockGenerator helper emits
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
            # Manual Stop bypasses the Rcv Trnsp. gate -- the button
            # always stops the playhead.
            self._end_playback()
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
            # Spin the shared clock generator up / down. The generator
            # is the only thing that calls send_clock_at, so toggling
            # here cleanly starts / stops the OUT emission AND the
            # loopback that drives our own playhead.
            if value:
                self._clock_gen.start()
            else:
                self._clock_gen.stop()
        elif name == "bpm":
            # Drop the rest of the pre-scheduled burst and re-anchor
            # at the new tempo; the refill loop picks up from now.
            # No-op when the generator isn't running.
            self._clock_gen.reanchor()

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

    # ================================================================
    # Pattern launch -- One-shot / Hold / Toggle trigger modes.
    #
    # Where Switch mode selects which pattern the transport playhead
    # walks (queued to the next bar while playing), a launch drives the
    # playhead directly off incoming clock without a transport Start and
    # rewinds the pattern to row 0 so it fires from the top on the next
    # step -- the "start wherever I am, in sync" behaviour. Monophonic:
    # a new trigger replaces whatever was in flight.
    # ================================================================

    def _launch_trigger(self, idx: int, note: int, mode: int) -> None:
        """Dispatch a control-channel trigger for launch modes
        (mode 1 One-shot, 2 Hold, 3 Toggle). Toggle stops when the
        already-launched slot is pressed again; every other press
        (re)starts the launch on `idx`."""
        if (mode == 3 and self._launch_active
                and idx == int(self._param_values.get("selected_pattern", -1))):
            self._launch_stop()
            return
        self._launch_start(idx, note)

    def _launch_start(self, idx: int, note: int) -> None:
        """Load pattern `idx` into the live view, rewind its playhead to
        row 0, and mark a launch active. The cursor is left where the
        user had it (reset_cursor=False) so launching doesn't disturb
        editing. The next on_tick at the configured rate fires row 0 --
        that one-step wait IS the quantize-to-the-next-step start."""
        with self._lock:
            self._silence_all()
            self._launch_oneshot_ending = False
        self._switch_pattern(idx, reset_cursor=False, reset_playhead=True)
        with self._lock:
            self._launch_active = True
            self._launch_note = note
        self._publish_playhead()

    def _launch_stop(self) -> None:
        """End the active launch: silence sounding voices and park the
        playhead. Note-offs go out so nothing rings on the synth."""
        with self._lock:
            self._launch_active = False
            self._launch_note = None
            self._launch_oneshot_ending = False
            self._silence_all()
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
