"""Cartesian — a René-style 2D sequencer that voices a held note.

Lives on the Play tab next to the Arpeggiator, Euclidean and Tracker
(SURFACE_KIND = "play"). Instead of a linear step row it arranges its
cells in a square grid (2×2 … 4×4) traversed by two independent clocks:

  X clock — the *step* pulse. Each X tick fires the next cell along the
            chosen Path (Rows / Cols / Diagonal / Knight / Spiral in /
            Spiral out / Random).
  Y clock — the *inversion* pulse. Each Y tick advances the inversion
            lap, re-voicing the whole grid one chord-inversion further
            up (or down — the Inversion wheel is bidirectional). With X
            fast and Y slow you sweep a chord that slowly climbs through
            its inversions.

Pitch model: arp-like. A note held on Play Ch is the **root**; the grid
plays `root + cell-offset` (the cell offsets are semitone intervals, not
absolute notes), so the whole figure transposes with the played note.
Harmony has two modes: **Chordal** (the played note is the tonic and
Scale just sets the chord quality, which transposes with the note) and
**Diatonic** (Root + Scale define a key; the played note picks a degree
and the voicing is harmonised in-key, so playing the third gives a
iii-chord, the fifth a V-chord, etc.).

Fill: the Fill Voicing wheel stamps the grid with a chord/voicing
(Unison / 5th / Triad / 7th / Scale), scale-aware (the Scale wheel
decides major/minor thirds & sevenths). The chord tones climb across
the cells (``offset = chord_tone(x + y + inversion)``) so a 4×4 already
reads as a ladder of inversions.

  Fill = Live  — Voicing / Scale / Size / Inversion act immediately
                 (all CC-bindable) and re-stamp the offsets. on/off and
                 accents are preserved, so you keep your rhythm + accent
                 mask and sweep only the harmony with one knob + one
                 held note. The Y clock animates inversions live.
  Fill = Latch — the grid is frozen: stamp once with Apply, then hand-
                 edit per-cell offsets freely. The Y-clock inversion
                 sweep is paused (the grid plays exactly as edited).

Fill Ch: a second channel for *recording* offsets — hold notes and each
one writes its interval (relative to the first note of the gesture) into
the next cell along the Path, programmed-Arp style. Touching the Fill Ch
flips the surface to Latch so the recording isn't overwritten.

Time model: clock-consuming. Free / tempo / transport like the Arp.
"""

import threading
import time

from raspimidihub import slot_bank
from raspimidihub.plugin_api import (
    Button,
    CartesianGrid,
    ChannelSelect,
    Group,
    Knob,
    NoteSelect,
    PatternStrip,
    PluginBase,
    Radio,
    Wheel,
)
from raspimidihub.scales import SCALES

# Raw 24-PPQN ticks per rate (mirrors the Arp / Euclidean so a hardware
# CC wired for those drives this plugin's rates identically).
_RATE_RAW_TICKS = {
    "4/1": 384, "2/1": 192, "1/1": 96, "1/2": 48,
    "1/4": 24, "1/8": 12, "1/16": 6, "1/32": 3,
    "4/1T": 256, "2/1T": 128, "1/1T": 64, "1/2T": 32,
    "1/4T": 16, "1/8T": 8, "1/16T": 4,
}
_RATE_FREE_MULT = {
    "4/1": 16, "2/1": 8, "1/1": 4, "1/2": 2,
    "1/4": 1, "1/8": 0.5, "1/16": 0.25, "1/32": 0.125,
    "4/1T": 32 / 3, "2/1T": 16 / 3, "1/1T": 8 / 3, "1/2T": 4 / 3,
    "1/4T": 2 / 3, "1/8T": 1 / 3, "1/16T": 1 / 6,
}

# Tag for every scheduled note-off this plugin emits — disjoint from the
# Arp's _ARP_TAG = 1 and Euclidean's _EUC_TAG = 2.
_CART_TAG = 3

_RATE_OPTIONS = [
    "4/1", "4/1T", "2/1", "2/1T", "1/1", "1/1T",
    "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T",
    "1/16", "1/16T", "1/32",
]
_DEFAULT_X_RATE = _RATE_OPTIONS.index("1/16")
_DEFAULT_Y_RATE = _RATE_OPTIONS.index("1/4")

# `chromatic` last so the wheel reads major→…→chromatic (matches the
# Euclidean plugin's ordering).
_SCALE_OPTIONS = [
    "major", "minor", "dorian", "mixolydian", "pentatonic",
    "blues", "harmonic m", "whole tone", "chromatic",
]
assert set(_SCALE_OPTIONS) == set(SCALES.keys()), (
    f"_SCALE_OPTIONS drifted from SCALES: {set(_SCALE_OPTIONS) ^ set(SCALES.keys())}")

# Fill Voicing ladder — each rung is a list of *scale-degree indices*
# (0 = root, 2 = third, 4 = fifth, 6 = seventh). The degree → semitone
# mapping is taken from the active Scale, so a Triad is major on a major
# scale and minor on a minor scale with no extra wiring. The order walks
# up the overtone series (fifth before third), so the wheel sweeps from
# thin to rich.
_VOICING_OPTIONS = ["Unison", "5th", "Triad", "7th", "Scale"]
_VOICING_DEGREES = {
    0: [0],                    # unison (climbs in octaves)
    1: [0, 4],                 # root + fifth (power)
    2: [0, 2, 4],              # root + third + fifth (triad)
    3: [0, 2, 4, 6],           # + seventh
    4: [0, 1, 2, 3, 4, 5, 6],  # full scale run
}

_PATH_OPTIONS = [
    "Rows →", "Cols ↓", "Diagonal", "Knight",
    "Spiral in", "Spiral out", "Random",
]

_SIZES = [2, 3, 4]  # grid side lengths the Size wheel offers
_STORAGE = 4        # fixed storage width (16 cells); active sub-grid ≤ this
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#",
               "G", "G#", "A", "A#", "B"]


def _scale_degree_semitone(intervals: list[int], degree: int) -> int:
    """Semitone offset of scale `degree` (wrapping octaves for degrees
    that exceed the scale length)."""
    n = len(intervals)
    if n == 0:
        return 0
    return intervals[degree % n] + 12 * (degree // n)


def _path_cells(side: int, mode: str) -> list[tuple[int, int]]:
    """Ordered list of (x, y) for the active `side × side` grid under
    the given Path mode. `Random` returns row-major here; the runner
    picks a random cell per step instead of following this order."""
    cells = [(x, y) for y in range(side) for x in range(side)]
    if mode == "Cols ↓":
        return [(x, y) for x in range(side) for y in range(side)]
    if mode == "Diagonal":
        return sorted(cells, key=lambda c: (c[0] + c[1], c[0]))
    if mode == "Knight":
        # Deterministic knight-ish tour: repeatedly hop (+1 col, +2 row)
        # wrapping mod side, collecting unseen cells; append any misses
        # in row order so every cell is always visited exactly once.
        order: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        x = y = 0
        for _ in range(side * side * 4):
            if (x, y) not in seen:
                seen.add((x, y))
                order.append((x, y))
            if len(order) == side * side:
                break
            x = (x + 1) % side
            y = (y + 2) % side
        for c in cells:
            if c not in seen:
                order.append(c)
        return order
    if mode in ("Spiral in", "Spiral out"):
        order = _spiral(side)
        return list(reversed(order)) if mode == "Spiral out" else order
    return cells  # Rows → (default) and Random


def _spiral(side: int) -> list[tuple[int, int]]:
    """Outside-in clockwise spiral of (x, y) for a side×side grid."""
    if side <= 0:
        return []
    visited = [[False] * side for _ in range(side)]
    order: list[tuple[int, int]] = []
    x = y = 0
    dx, dy = 1, 0  # start moving right
    for _ in range(side * side):
        order.append((x, y))
        visited[y][x] = True
        nx, ny = x + dx, y + dy
        if not (0 <= nx < side and 0 <= ny < side and not visited[ny][nx]):
            dx, dy = -dy, dx  # turn clockwise
            nx, ny = x + dx, y + dy
        x, y = nx, ny
    return order


class Cartesian(PluginBase):
    """René-style 2D sequencer voicing a held note."""

    SURFACE_KIND = "play"

    NAME = "Cartesian"
    DESCRIPTION = "2D grid sequencer — voices a held note, swept by two clocks"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
A note held on Play Ch is the root; the grid plays root + each cell's
semitone offset, so the whole figure transposes with the played note
(arp-like). Two clocks drive it: X steps through the cells along the
Path; Y advances the inversion lap, re-voicing the grid one inversion
further (the Inversion wheel sets how far, and the direction).

Harmony = Chordal makes the played note the tonic (Scale sets the chord
quality, transposing with the note); Harmony = Diatonic adds a Root
wheel so Root + Scale define a key and the played note is harmonised
in-key (third → iii-chord, fifth → V-chord, …).

Fill Voicing stamps the grid with a chord (Unison / 5th / Triad / 7th /
Scale), scale-aware via the Scale wheel. In Fill = Live the voicing,
scale, size and inversion act immediately (all CC-bindable) and re-stamp
the offsets while preserving your on/off + accent mask — so you keep the
rhythm and sweep only the harmony with one knob and one held note. In
Fill = Latch the grid is frozen: tap Apply once, then hand-edit cell
offsets; the Y-clock inversion sweep pauses.

Fill Ch records offsets: hold notes and each writes its interval
(relative to the first note) into the next cell along the Path. Touching
Fill Ch flips the surface to Latch so the recording isn't overwritten.

Path: Rows → / Cols ↓ / Diagonal / Knight / Spiral in / Spiral out /
Random changes how the X-clock sweeps the grid.

Routing example:
  [Keyboard]     → [Cartesian] → [Synth]
  [Master Clock] → [Cartesian]

CC automation: every play-surface knob is bindable. Long-press a control
to pick a Channel + CC (or MIDI-Learn one)."""

    params = [
        # Top wide row — the two performance knobs.
        Wheel("fill_voicing", "Fill Voicing",
              min=0, max=len(_VOICING_OPTIONS) - 1,
              labels=_VOICING_OPTIONS, default=2,
              wide=True, span=2, play_only=True, default_cc=70),
        Wheel("inversion", "Inversion", min=-4, max=4, default=0,
              wide=True, span=2, play_only=True, default_cc=71),

        # Harmony mode + the key.
        #   Chordal  — the played note is the tonic; Scale only sets the
        #              chord quality, which transposes with the note.
        #   Diatonic — Root + Scale define a key; the played note picks a
        #              degree and the voicing is harmonised in-key (Root
        #              wheel appears).
        Radio("harmony", "Harmony", ["Chordal", "Diatonic"],
              default="Chordal", play_only=True),
        Wheel("scale", "Scale",
              min=0, max=len(_SCALE_OPTIONS) - 1,
              labels=_SCALE_OPTIONS, default=0,
              wide=True, span=2, play_only=True, default_cc=87),
        Wheel("root", "Root", min=0, max=11, default=0,
              labels=_NOTE_NAMES, wide=True, span=2, play_only=True,
              default_cc=88, visible_when=("harmony", "Diatonic")),

        # Motion row — the two clocks + Path.
        Wheel("x_rate", "X Rate",
              min=0, max=len(_RATE_OPTIONS) - 1,
              labels=_RATE_OPTIONS, default=_DEFAULT_X_RATE,
              play_only=True, default_cc=74),
        Wheel("y_rate", "Y Rate",
              min=0, max=len(_RATE_OPTIONS) - 1,
              labels=_RATE_OPTIONS, default=_DEFAULT_Y_RATE,
              play_only=True, default_cc=75),
        Wheel("path", "Path",
              min=0, max=len(_PATH_OPTIONS) - 1,
              labels=_PATH_OPTIONS, default=0,
              wide=True, span=2, play_only=True, default_cc=79),

        # Shaper row.
        Wheel("grid_size", "Grid",
              min=0, max=len(_SIZES) - 1,
              labels=[f"{s}×{s}" for s in _SIZES], default=2,
              play_only=True, default_cc=72),
        Wheel("gate", "Gate %", min=10, max=100, default=80,
              play_only=True, default_cc=73),
        Knob("accent_vel", "Accent Vel.", min=0, max=127, default=30,
             play_only=True, default_cc=83),
        Radio("fill_mode", "Fill", ["Live", "Latch"], default="Live",
              play_only=True),
        Button("fill_apply", "Apply", trigger=True, color="blue",
               play_only=True, visible_when=("fill_mode", "Latch")),

        # The grid itself (no title — the 2D grid is self-evident, and
        # "Grid" already labels the size wheel above).
        CartesianGrid("grid", "", cols=_STORAGE, default_on=True,
                      size_param="grid_size", sizes=_SIZES,
                      playhead_param="playhead", play_only=True),

        # Pattern-slot strip — same bank machinery as Arp / Euclidean.
        PatternStrip("active_slot", "Patterns",
                     count=slot_bank.SLOT_COUNT, default=0,
                     slots_param="pattern_slots",
                     cmd_param="pattern_cmd",
                     play_only=True),

        Group("Setup", [
            Radio("sync_mode", "Sync",
                  ["free", "tempo", "transport"], default="transport"),
            # Play Ch (0 = Any) — notes here are the played root.
            ChannelSelect("play_channel", "Play Ch", default=0, allow_any=True),
            # Fill Ch (Off / 1..16) — notes here record cell offsets.
            Wheel("fill_channel", "Fill Ch",
                  min=0, max=16, default=0,
                  labels=["Off"] + [str(i) for i in range(1, 17)]),
            # Pattern-slot hardware trigger — Tracker-shaped.
            Wheel("pattern_ctrl_ch", "Ctrl Ch",
                  min=0, max=16, default=0,
                  labels=["Off"] + [str(i) for i in range(1, 17)]),
            Wheel("bpm", "BPM", min=40, max=300, default=120,
                  visible_when=("sync_mode", "free")),
            Group("Pattern Notes", [
                NoteSelect(f"pattern_note_{i}", f"P{i + 1}",
                           default=36 + i, config_only=True)
                for i in range(slot_bank.SLOT_COUNT)
            ], config_only=True,
                visible_when=("pattern_ctrl_ch", list(range(1, 17)))),
        ], config_only=True),
    ]

    cc_outputs = []

    inputs = [
        "Notes (Play Ch — the played root)",
        "Notes (Fill Ch — records cell offsets)",
        "CC for any bound play-surface knob (long-press to bind)",
        "Ctrl Ch notes (set Pattern slot 1..8)",
        "Clock",
        "Aftertouch",
        "Pitch Bend",
    ]
    outputs = [
        "Notes (grid-voiced)",
        "Aftertouch (pass-through)",
        "Pitch Bend (pass-through)",
    ]

    clock_divisions = list(_RATE_OPTIONS)

    # Every play_only param captured into a pattern slot. `active_slot`
    # is the bank selector and excluded; `playhead` is transient.
    _SLOT_PARAMS = [
        "fill_voicing", "inversion", "harmony", "scale", "root",
        "x_rate", "y_rate", "path",
        "grid_size", "gate", "accent_vel", "fill_mode", "grid",
    ]

    # ----- lifecycle ----------------------------------------------------------

    def on_start(self):
        self.transient_params = {"playhead", "fill_apply"}

        self._held: list[tuple[int, int, int]] = []  # (note, vel, channel)
        self._playing_notes: list[tuple[int, int]] = []
        self._step = 0          # index along the Path
        self._inv_lap = 0       # inversion lap counter (driven by Y clock)
        self._lock = threading.Lock()
        self._free_running = False
        self._free_thread: threading.Thread | None = None
        self._transport_playing = False
        self._sustain_active = False
        self._physically_pressed: dict[tuple[int, int], int] = {}

        # Fill-Ch recording state.
        self._fill_ref: int | None = None  # first note of the gesture
        self._fill_cursor = 0              # next Path index to write
        self._fill_held: set[tuple[int, int]] = set()

        slot_bank.init_slot_bank(self, self._SLOT_PARAMS)

        # Live mode: stamp the grid from the current voicing so a fresh
        # instance plays a chord immediately. persist=False — the value
        # is still serialised on Save, we just don't dirty on load.
        if self._mode() == "Live":
            self._apply_fill(self._inv_step(), persist=False)

    def on_stop(self):
        self._free_running = False
        self._silence_all()

    def panic(self):
        with self._lock:
            self._free_running = False
            self._held = []
            self._physically_pressed.clear()
            self._sustain_active = False
            self._fill_ref = None
            self._fill_held.clear()
            self._silence_all()

    # ----- helpers ------------------------------------------------------------

    def _mode(self) -> str:
        return "Latch" if self.get_param("fill_mode") == "Latch" else "Live"

    def _side(self) -> int:
        v = self.get_param("grid_size")
        try:
            return _SIZES[int(v) if v is not None else len(_SIZES) - 1]
        except (IndexError, TypeError, ValueError):
            return 4

    def _path_str(self) -> str:
        try:
            return _PATH_OPTIONS[int(self.get_param("path") or 0)]
        except (IndexError, TypeError, ValueError):
            return _PATH_OPTIONS[0]

    def _rate_str(self, param: str) -> str:
        try:
            return _RATE_OPTIONS[int(self.get_param(param) or 0)]
        except (IndexError, TypeError, ValueError):
            return _RATE_OPTIONS[_DEFAULT_X_RATE]

    def _scale_intervals(self) -> list[int]:
        try:
            name = _SCALE_OPTIONS[int(self.get_param("scale") or 0)]
        except (IndexError, TypeError, ValueError):
            name = "major"
        return SCALES.get(name, SCALES["major"])

    def _harmony(self) -> str:
        return "Diatonic" if self.get_param("harmony") == "Diatonic" else "Chordal"

    def _voicing_degrees(self) -> list[int]:
        """The Fill Voicing as scale-degree indices (0=root, 2=third,
        4=fifth, 6=seventh)."""
        try:
            return _VOICING_DEGREES[int(self.get_param("fill_voicing") or 0)]
        except (KeyError, TypeError, ValueError):
            return [0]

    def _voicing_intervals(self) -> list[int]:
        """Chordal voicing as a sorted list of in-octave semitone
        intervals relative to the played note (e.g. major triad →
        [0, 4, 7]). The Scale wheel sets the chord quality."""
        intervals = self._scale_intervals()
        semis = sorted({_scale_degree_semitone(intervals, d) % 12
                        for d in self._voicing_degrees()})
        return semis or [0]

    def _chord_tone(self, i: int, voicing: list[int]) -> int:
        """The i-th chord tone of `voicing`, climbing/descending in
        octaves outside the in-octave set. Works for negative i."""
        n = len(voicing)
        if n == 0:
            return 0
        return voicing[i % n] + 12 * (i // n)

    def _fill_offset(self, k: int, ref_note: int) -> int:
        """Semitone offset (relative to `ref_note`) for chord-tone index
        `k`. In Chordal the played note is the tonic and the voicing is a
        fixed-quality stack. In Diatonic, Root + Scale define a key, the
        ref note picks a degree, and the voicing is harmonised in-key —
        so the same grid gives a iii-chord when you play the third, etc.

        Both branches return a *relative* offset; playback adds it to the
        actually-played note. In Live we re-stamp on every root change so
        the offsets track the held note; in Latch the stamped offsets are
        frozen and simply transpose with whatever you play."""
        if self._harmony() != "Diatonic":
            return self._chord_tone(k, self._voicing_intervals())

        scale = self._scale_intervals()
        n = len(scale) or 1
        root = int(self.get_param("root") or 0) % 12
        degrees = self._voicing_degrees()
        ladder = len(degrees)

        rel = ref_note - root
        octave = rel // 12
        pc = rel % 12
        # The played note's scale degree in the key (nearest if off-key).
        deg0 = min(range(n), key=lambda i: abs(scale[i] - pc))
        # Stack the voicing's degrees on deg0, wrapping +n (one octave of
        # scale degrees) each time index k passes the chord size.
        deg = deg0 + degrees[k % ladder] + n * (k // ladder)
        abs_note = root + 12 * octave + _scale_degree_semitone(scale, deg)
        return abs_note - ref_note

    def _fill_ref_note(self) -> int:
        """The note the fill is computed relative to: the most-recently
        held note, or — when nothing is held — the key root near middle
        C so the grid shows the tonic chord."""
        if self._held:
            return self._held[-1][0]
        return 60 + (int(self.get_param("root") or 0) % 12)

    def _inv_step(self) -> int:
        """Chord-tone shift for the current inversion lap."""
        inv = int(self.get_param("inversion") or 0)
        if inv == 0:
            return 0
        sign = 1 if inv > 0 else -1
        return (self._inv_lap % (abs(inv) + 1)) * sign

    def _publish_playhead(self, idx: int) -> None:
        self.set_param("playhead", idx, persist=False)

    # ----- fill ---------------------------------------------------------------

    def _apply_fill(self, inv_step: int, persist: bool) -> None:
        """Write the voicing into the active cells' `offset` field,
        preserving on/off + accent. Inactive cells are left untouched."""
        side = self._side()
        ref = self._fill_ref_note()
        grid = list(self.get_param("grid") or [])
        while len(grid) < _STORAGE * _STORAGE:
            grid.append({"on": True, "offset": 0})
        for y in range(_STORAGE):
            for x in range(_STORAGE):
                idx = y * _STORAGE + x
                cell = dict(grid[idx]) if isinstance(grid[idx], dict) \
                    else {"on": True, "offset": 0}
                if x < side and y < side:
                    cell["offset"] = self._fill_offset(x + y + inv_step, ref)
                grid[idx] = cell
        self.set_param("grid", grid, persist=persist)

    def _live_restamp(self) -> None:
        if self._mode() == "Live":
            self._apply_fill(self._inv_step(), persist=False)

    # ----- input handlers -----------------------------------------------------

    def _channel_match(self, channel: int, param_name: str) -> bool:
        v = self.get_param(param_name)
        return v is None or v == 0 or int(v) - 1 == channel

    def _is_fill_channel(self, channel: int) -> bool:
        fc = int(self.get_param("fill_channel") or 0)
        return fc != 0 and fc - 1 == channel

    def on_note_on(self, channel, note, velocity):
        # Slot-trigger notes first — dedicated control channel.
        slot_idx = slot_bank.trigger_note_index(self, channel, note)
        if slot_idx is not None:
            if slot_idx != self.get_param("active_slot"):
                slot_bank.load_slot(self, self._SLOT_PARAMS, slot_idx)
            return

        # Fill Ch — record an offset into the next Path cell.
        if self._is_fill_channel(channel):
            self._record_fill(channel, note)
            return

        if not self._channel_match(channel, "play_channel"):
            return
        self._physically_pressed[(channel, note)] = velocity
        with self._lock:
            already = any(n == note and c == channel for n, _, c in self._held)
            if not already:
                self._held.append((note, velocity, channel))
            was_idle = len(self._held) == (0 if already else 1)
            if was_idle:
                self._step = 0
                self._inv_lap = 0
                if (self.get_param("sync_mode") or "tempo") == "free" \
                        and not self._free_running:
                    self._start_free_runner()
            # Re-stamp so the grid follows the root: always on the first
            # note of a phrase, and on every root change in Diatonic
            # (where the offsets depend on which degree you play).
            if was_idle or self._harmony() == "Diatonic":
                self._live_restamp()

    def on_note_off(self, channel, note):
        if slot_bank.trigger_note_index(self, channel, note) is not None:
            return
        if self._is_fill_channel(channel):
            self._fill_held.discard((channel, note))
            if not self._fill_held:
                self._fill_ref = None  # next gesture restarts the cursor
            return
        if not self._channel_match(channel, "play_channel"):
            return
        self._physically_pressed.pop((channel, note), None)
        with self._lock:
            if self._sustain_active:
                return
            self._held = [(n, v, c) for n, v, c in self._held
                          if not (n == note and c == channel)]
            if not self._held:
                self._free_running = False
                self._silence_all()
            elif self._harmony() == "Diatonic":
                # Root fell back to an earlier-held note — re-voice.
                self._live_restamp()

    def on_cc(self, channel, cc, value):
        if cc != 64:
            return
        if not self._channel_match(channel, "play_channel"):
            return
        new_active = value >= 64
        if self._sustain_active and not new_active:
            with self._lock:
                self._held = [(n, v, c) for n, v, c in self._held
                              if (c, n) in self._physically_pressed]
                if not self._held:
                    self._free_running = False
                    self._silence_all()
        self._sustain_active = new_active

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def _record_fill(self, channel, note) -> None:
        """Write `note`'s interval (relative to the first note of the
        gesture) into the next cell along the Path. Flips the surface to
        Latch so the recording isn't overwritten by the live fill."""
        self._fill_held.add((channel, note))
        side = self._side()
        path = _path_cells(side, self._path_str())
        if not path:
            return
        if self._fill_ref is None:
            self._fill_ref = note
            self._fill_cursor = 0
            if self._mode() != "Latch":
                self.set_param("fill_mode", "Latch")
        x, y = path[self._fill_cursor % len(path)]
        idx = y * _STORAGE + x
        grid = list(self.get_param("grid") or [])
        while len(grid) <= idx:
            grid.append({"on": True, "offset": 0})
        cell = dict(grid[idx]) if isinstance(grid[idx], dict) else {"on": True}
        cell["offset"] = max(-24, min(24, note - self._fill_ref))
        cell["on"] = True
        grid[idx] = cell
        self.set_param("grid", grid)  # a real edit → persist + slot record
        slot_bank.record_edit(self, self._SLOT_PARAMS, "grid", grid)
        self._fill_cursor += 1

    # ----- transport / clock --------------------------------------------------

    def on_transport_start(self):
        if (self.get_param("sync_mode") or "tempo") == "transport":
            self._step = 0
            self._inv_lap = 0
            self._note_off_current()
            self._transport_playing = True
            self._live_restamp()

    def on_transport_stop(self):
        if (self.get_param("sync_mode") or "tempo") == "transport":
            self._transport_playing = False
            self._silence_all()

    def on_tick(self, division):
        mode = self.get_param("sync_mode") or "tempo"
        if mode == "free":
            return
        if mode == "transport" and not self._transport_playing:
            self._transport_playing = True
            self._step = 0
            self._inv_lap = 0
        # A tick can match both rates on the same raw tick — fire both.
        if division == self._rate_str("x_rate"):
            self._advance_x()
        if division == self._rate_str("y_rate"):
            self._advance_y()

    # ----- param-change reactions --------------------------------------------

    def on_param_change(self, name, value):
        if name == "active_slot":
            slot_bank.load_slot(self, self._SLOT_PARAMS, int(value))
            return
        if name == "pattern_cmd":
            from raspimidihub.plugin_api import get_defaults
            slot_bank.handle_command(
                self, self._SLOT_PARAMS,
                get_defaults(type(self).params), value)
            if value is not None:
                self.set_param("pattern_cmd", None)
            return
        if name == "fill_apply":
            # Latch one-shot: stamp the current voicing, reset inversion.
            if value:
                self._inv_lap = 0
                self._apply_fill(0, persist=True)
                slot_bank.record_edit(self, self._SLOT_PARAMS, "grid",
                                      self.get_param("grid"))
                self.set_param("fill_apply", False)
            return

        slot_bank.record_edit(self, self._SLOT_PARAMS, name, value)

        if name == "inversion":
            self._inv_lap = 0
            self._live_restamp()
            return
        if name in ("fill_voicing", "scale", "grid_size", "harmony", "root"):
            self._live_restamp()
            return
        if name == "fill_mode":
            if value == "Live":
                self._inv_lap = 0
                self._apply_fill(0, persist=False)
            return
        if name == "sync_mode":
            self._free_running = False
            if value == "free" and self._held:
                self._start_free_runner()
            elif value == "transport":
                self._transport_playing = False
            return

    # ----- runner / advance ---------------------------------------------------

    def _start_free_runner(self):
        self._free_running = True

        def _run():
            now = time.monotonic()
            next_x = now
            next_y = now
            while self._free_running:
                now = time.monotonic()
                px = self._free_period("x_rate")
                py = self._free_period("y_rate")
                fired = False
                if now >= next_x:
                    self._advance_x()
                    next_x = now + px
                    fired = True
                if now >= next_y:
                    self._advance_y()
                    next_y = now + py
                    fired = True
                if not fired:
                    time.sleep(max(0.001, min(next_x, next_y) - now))

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self._free_thread = t

    def _free_period(self, param: str) -> float:
        bpm = self.get_param("bpm") or 120
        beats_per_sec = bpm / 60.0
        return _RATE_FREE_MULT.get(self._rate_str(param), 0.25) / beats_per_sec

    def _advance_y(self) -> None:
        """Y clock = inversion pulse. Re-voice the grid one inversion
        further (Live only — Latch keeps the frozen, hand-edited grid)."""
        inv = int(self.get_param("inversion") or 0)
        if inv == 0:
            return
        with self._lock:
            self._inv_lap += 1
        if self._mode() == "Live":
            self._apply_fill(self._inv_step(), persist=False)

    def _advance_x(self) -> None:
        """X clock = step pulse. Fire the next cell along the Path."""
        with self._lock:
            if not self._held:
                return
            side = self._side()
            path = _path_cells(side, self._path_str())
            if not path:
                return
            if self._path_str() == "Random":
                import random
                x, y = path[random.randrange(len(path))]
            else:
                if self._step >= len(path):
                    self._step = 0
                x, y = path[self._step]
                self._step = (self._step + 1) % len(path)
            self._fire_cell(x, y)

    def _fire_cell(self, x: int, y: int) -> None:
        idx = y * _STORAGE + x
        self._publish_playhead(idx)
        grid = self.get_param("grid") or []
        cell = grid[idx] if idx < len(grid) and isinstance(grid[idx], dict) else {}
        if not cell.get("on"):
            self._note_off_current()
            return
        root_note, root_vel, root_ch = self._held[-1]  # most recent = root
        offset = int(cell.get("offset", 0))
        note = root_note + offset
        if not (0 <= note <= 127):
            self._note_off_current()
            return
        accent = bool(cell.get("accent"))
        accent_add = int(self.get_param("accent_vel") or 0) if accent else 0
        vel = max(1, min(127, root_vel + accent_add))

        self._note_off_current()

        rate_period = self._rate_period_seconds("x_rate")
        if rate_period > 0:
            gate = (int(self.get_param("gate") or 80)) / 100.0
            off_at = time.monotonic() + max(0.005, rate_period * gate)
            self.send_note_on(root_ch, note, vel)
            self.send_note_off_at(off_at, root_ch, note, tag=_CART_TAG)
        else:
            self.send_note_on(root_ch, note, vel)
        self._playing_notes.append((root_ch, note))

    def _rate_period_seconds(self, param: str) -> float:
        mode = self.get_param("sync_mode") or "tempo"
        if mode == "free":
            return self._free_period(param)
        bus = getattr(self, "_clock_bus", None)
        period_ema = getattr(bus, "_tick_period_ema", None) if bus else None
        if period_ema is None:
            return 0.0
        return period_ema * _RATE_RAW_TICKS.get(self._rate_str(param), 6)

    # ----- note-off + cleanup -------------------------------------------------

    def _note_off_current(self) -> None:
        for ch, note in self._playing_notes:
            self.send_note_off(ch, note)
        self._playing_notes = []

    def _silence_all(self) -> None:
        self.cancel_scheduled(_CART_TAG)
        self._note_off_current()
