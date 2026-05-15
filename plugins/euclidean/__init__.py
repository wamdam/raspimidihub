"""Euclidean — held-note pattern emitter built on Bjorklund distribution.

Lives on the Play tab next to the Arpeggiator and Tracker
(SURFACE_KIND = "play"). Three-layer pattern model:

  Layer 1 — Bjorklund distribution (Pulses / Steps / Rotate).
  Layer 2 — Window wave (Phase / Cycles / Open). A sine threshold
            masks which steps are allowed to fire. Open = 100 is
            transparent; Open = 0 closes the gate entirely.
  Layer 3 — Manual override grid (per-step state default /
            FORCE_ON / FORCE_ON+accent / FORCE_OFF, plus offset).

Pitch model: held notes, voiced per the Pattern wheel
(up / down / up-down / random / as-played / chord). chord fires
every held note simultaneously. Internal Scale + Root quantises
the output; Tune Spread randomly transposes (with Snap presets) before
the quantiser. Jitter humanises per-step timing; Fade In / Fade Out
ramp the velocity at the start and end of a phrase.

Time model: clock-consuming. Free / tempo / transport like the
Arp. Polyrhythm is two instances on the same clock with co-prime
pulse / step counts.
"""

import math
import random
import threading
import time

from raspimidihub.plugin_api import (
    Button,
    ChannelSelect,
    Display,
    Group,
    Knob,
    NoteSelect,
    PluginBase,
    Radio,
    StepEditor,
    Wheel,
)
from raspimidihub.scales import SCALES, build_nearest_map

# Raw 24-PPQN ticks per rate (mirrors the Arp's _ARP_RATE_RAW_TICKS so
# CC#74 on a hardware controller wired for the Arp drives this plugin's
# Rate identically).
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

# Tag for every scheduled note-off this plugin emits. Cancel-on-panic
# clears the whole pending burst in one call.
_EUC_TAG = 2  # disjoint from the Arp's _ARP_TAG = 1

_PATTERN_OPTIONS = [
    "up", "down", "up-down", "random", "as-played", "chord",
]

_RATE_OPTIONS = [
    "4/1", "4/1T", "2/1", "2/1T", "1/1", "1/1T",
    "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T",
    "1/16", "1/16T", "1/32",
]
_DEFAULT_RATE_IDX = _RATE_OPTIONS.index("1/16")

_SNAP_OPTIONS = ["free", "octaves", "5ths+oct."]

# `chromatic` last so the wheel reads major→…→chromatic. The dict in
# raspimidihub.scales lists it first as the identity pass-through.
_SCALE_OPTIONS = [
    "major", "minor", "dorian", "mixolydian", "pentatonic",
    "blues", "harmonic m", "whole tone", "chromatic",
]
# Build-time guard: a typo in _SCALE_OPTIONS would silently fall back
# to "major" via build_nearest_map. Catch it at import instead.
assert set(_SCALE_OPTIONS) == set(SCALES.keys()), (
    f"_SCALE_OPTIONS drifted from SCALES: {set(_SCALE_OPTIONS) ^ set(SCALES.keys())}")

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#",
               "G", "G#", "A", "A#", "B"]

# Cycles wheel is integer-indexed; index → number of wave periods that
# fit inside one pattern cycle.
_CYCLES_VALUES = [0.5, 1.0, 2.0, 3.0, 4.0]

# Per-step jump table for the Spread Snap presets. `free` falls
# through to a continuous ±12-semitone draw; the other two pick from a
# fixed set scaled by the spread amount.
_SNAP_INTERVALS = {
    "octaves": [-24, -12, 0, 12, 24],
    "5ths+oct.": [-24, -19, -12, -7, -5, 0, 5, 7, 12, 19, 24],
}


def _window_mask(steps: int, phase: int, cycles_idx: int,
                 open_pct: int) -> list[bool]:
    """Return a per-step boolean list of length `steps` where a True
    means "the sine window allows this step to fire".

    The window is a sine wave whose peak sits at step `phase`. The
    `cycles_idx` selects how many wave periods fit in one pattern
    cycle (0.5 / 1 / 2 / 3 / 4). `open_pct` 0..100 controls how much
    of the wave sits above the open threshold:
      - open_pct = 100 → threshold = -1 → every step passes (caller
        skips this path; included for completeness)
      - open_pct =  50 → threshold =  0 → the top half passes (a
        classic 50%-duty window)
      - open_pct =   0 → threshold = +1 → nothing passes (a fully
        closed gate; useful only as the manual-only mode)
    """
    if steps <= 0:
        return []
    try:
        cycles = _CYCLES_VALUES[cycles_idx]
    except (IndexError, TypeError):
        cycles = 1.0
    threshold = 1.0 - 2.0 * (max(0, min(100, open_pct)) / 100.0)
    period_steps = steps / cycles if cycles > 0 else float(steps)
    out: list[bool] = []
    for i in range(steps):
        angle = 2.0 * math.pi * ((i - phase) / period_steps)
        value = math.cos(angle)  # cos so the peak sits at idx == phase
        out.append(value >= threshold)
    return out


def euclidean_pattern(pulses: int, steps: int) -> list[bool]:
    """Classical Bjorklund distribution: a length-`steps` boolean
    list with `pulses` ones spaced as evenly as possible. The first
    cell is always True when pulses > 0 — callers apply Rotate
    separately."""
    if steps <= 0:
        return []
    if pulses <= 0:
        return [False] * steps
    if pulses >= steps:
        return [True] * steps

    groups: list[list[int]] = [[1] for _ in range(pulses)]
    remainders: list[list[int]] = [[0] for _ in range(steps - pulses)]
    while len(remainders) > 1:
        n = min(len(groups), len(remainders))
        new_groups = [groups[i] + remainders[i] for i in range(n)]
        new_remainders: list[list[int]] = []
        if len(groups) > n:
            new_remainders = groups[n:]
        elif len(remainders) > n:
            new_remainders = remainders[n:]
        groups = new_groups
        remainders = new_remainders
        if not remainders:
            break
    flat: list[int] = []
    for g in groups:
        flat.extend(g)
    for r in remainders:
        flat.extend(r)
    return [bool(x) for x in flat]


class Euclidean(PluginBase):
    """Bjorklund-driven held-note pattern emitter."""

    SURFACE_KIND = "play"

    NAME = "Euclidean"
    DESCRIPTION = "Held notes voiced through a Bjorklund-distributed step pattern"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Holds incoming notes and plays them as an evenly-distributed pattern
over the configured Steps. Pulses controls density, Rotate offsets
the phase. Per-step Manual overrides on the Step Grid force individual
steps on or off independent of the algorithm (tap-cycle: default →
force-on → force-on + accent → force-off → default).

Pattern picks how held notes are voiced per step: up / down /
up-down / random / as-played / chord. chord fires every held note
simultaneously each step.

Pitch is quantised to the internal Scale + Root. Set Scale =
chromatic for an identity pass-through.

Tune Spread randomly transposes each step (Snap = free / octaves /
5ths+oct.). Jitter humanises the per-step timing.

Fade In / Fade Out ramp velocity at the start of a phrase (from
silence) and at the end (after every key is released).

Routing example:
  [Keyboard]    → [Euclidean] → [Synth]
  [Master Clock] → [Euclidean]

CC automation: CC 74 = Rate, CC 75 = Gate (Arp-consistent).
Block CC 70..88 (skipping CC 84 / Portamento Control) covers every
play-surface knob; see Appendix A for the full table."""

    params = [
        # Top wide row — chosen on stage.
        Wheel("pattern", "Pattern",
              min=0, max=len(_PATTERN_OPTIONS) - 1,
              labels=_PATTERN_OPTIONS, default=0,
              wide=True, span=2, play_only=True),
        Wheel("rate", "Rate",
              min=0, max=len(_RATE_OPTIONS) - 1,
              labels=_RATE_OPTIONS, default=_DEFAULT_RATE_IDX,
              wide=True, span=2, play_only=True),

        # Layer 1 — Euclidean distribution.
        Wheel("pulses", "Pulses", min=0, max=32, default=4, play_only=True),
        Wheel("steps",  "Steps",  min=1, max=32, default=16, play_only=True),
        Wheel("rotate", "Rotate", min=-16, max=16, default=0, play_only=True),
        Wheel("octaves", "Octaves", min=1, max=4, default=1, play_only=True),

        # Layer 2 — Window wave (sine threshold mask).
        Wheel("phase",  "Phase",  min=0, max=31, default=0, play_only=True),
        Wheel("cycles", "Cycles",
              min=0, max=4, labels=["0.5", "1", "2", "3", "4"],
              default=1, play_only=True),
        Knob("open",    "Open",   min=0, max=100, default=100, play_only=True),
        Wheel("gate",   "Gate %", min=10, max=100, default=80, play_only=True),
        Knob("accent_vel", "Accent Vel.", min=0, max=127, default=30, play_only=True),

        # Envelope row.
        Wheel("fade_in",  "Fade In",  min=0, max=16, default=0, play_only=True),
        Wheel("fade_out", "Fade Out", min=0, max=16, default=0, play_only=True),

        # Humanisation row.
        Knob("jitter",      "Jitter %",    min=0, max=100, default=0, play_only=True),
        Knob("tune_spread", "Tune Spread", min=0, max=100, default=0, play_only=True),
        Wheel("spread_snap", "Snap",
              min=0, max=len(_SNAP_OPTIONS) - 1,
              labels=_SNAP_OPTIONS, default=1, play_only=True),

        # Pitch quantiser (reuses Scale Remapper's catalogue).
        Wheel("scale", "Scale",
              min=0, max=len(_SCALE_OPTIONS) - 1,
              labels=_SCALE_OPTIONS, default=0, play_only=True),
        Wheel("root", "Root", min=0, max=11, default=0,
              labels=_NOTE_NAMES, play_only=True),

        # Layer 3 — override grid + per-step semitone offset.
        StepEditor("steps_grid", "Step Pattern",
                   length_param="steps", default_length=16,
                   default_on=False,
                   span=4, play_only=True,
                   override_mode=True,
                   algo_underlay_param="step_algo_on"),

        # Velocity-envelope strip below the grid (Fade In / Fade Out
        # indicator). Read-only meter.
        Display("_envelope", "Envelope", display_name="envelope"),

        Group("Setup", [
            ChannelSelect("arp_channel", "Arp Ch", default=0, allow_any=True),
            ChannelSelect("control_channel", "Ctrl Ch", default=0, allow_any=True),
            Button("pattern_trigger", "Pattern Trigger", default=False, color="green"),
            NoteSelect("pattern_base", "Base", default=36,
                       visible_when=("pattern_trigger", True)),
            Radio("sync_mode", "Sync",
                  ["free", "tempo", "transport"], default="transport"),
            Wheel("bpm", "BPM", min=40, max=300, default=120,
                  visible_when=("sync_mode", "free")),
            Button("retrig", "Retrig", default=True, color="green"),
        ], config_only=True),
    ]

    # Full block CC 70..88 (skipping CC 84 = Portamento Control). The
    # gate is exact: a CC number outside this dict is dropped before
    # it can touch a param. Discrete-enum params (Pattern / Snap /
    # Scale / Root) are integer-indexed Wheels — the host's
    # _cc_to_param scales 0..127 to the param's min..max so a single
    # 0..127 CC steps through every option.
    cc_inputs = {
        70: "pattern",
        71: "octaves",
        72: "pulses",
        73: "steps",
        74: "rate",        # ← Arp-consistent
        75: "gate",        # ← Arp-consistent
        76: "open",
        77: "phase",
        78: "cycles",
        79: "rotate",
        80: "fade_in",
        81: "fade_out",
        82: "jitter",
        83: "accent_vel",
        85: "tune_spread",
        86: "spread_snap",
        87: "scale",
        88: "root",
    }
    cc_outputs = []

    inputs = [
        "Notes",
        "CC#64 (sustain pedal — temporarily holds the input chord)",
        "CC#70..83, CC#85..88 (parameter automation; see HELP)",
        "Notes in [Base, Base+6) when Pattern Trigger is on (sets Pattern)",
        "Clock",
        "Aftertouch",
        "Pitch Bend",
    ]
    outputs = [
        "Notes (Bjorklund-voiced)",
        "Aftertouch (pass-through)",
        "Pitch Bend (pass-through)",
    ]

    clock_divisions = list(_RATE_OPTIONS)

    display_outputs = [
        {"name": "envelope", "type": "meter", "label": "Envelope",
         "min": 0, "max": 127},
    ]

    # ----- lifecycle ----------------------------------------------------------

    def on_start(self):
        self._held_notes: list[tuple[int, int, int]] = []  # (note, vel, channel)
        self._sorted_notes: list[tuple[int, int, int]] = []
        self._pitch_step = 0       # index into the per-tick pitch list
        self._seq_step = 0         # index into the step-grid cycle
        self._direction = 1        # +1/-1 for up-down
        self._playing_notes: list[tuple[int, int]] = []
        self._lock = threading.Lock()
        self._free_thread: threading.Thread | None = None
        self._free_running = False
        self._transport_playing = False
        self._physically_pressed: dict[tuple[int, int], int] = {}
        self._sustain_active = False

        # Fade envelope. `_fade_value` is the current 0..1 multiplier
        # applied to every emitted velocity. `_fade_dir` is the per-
        # firing-step delta: +ramp_in / 0 / -ramp_out. `_fadeout_notes`
        # is a snapshot of the last held chord that keeps the pattern
        # voicing the same notes through a fade-out after every key
        # has been released.
        self._fade_value = 0.0
        self._fade_dir = 0.0
        self._fadeout_notes: list[tuple[int, int, int]] = []

        # Cache of the current Bjorklund × window-wave result.
        # Recomputed lazily when any input to the algorithm changes
        # (pulses / steps / rotate from Layer 1; phase / cycles / open
        # from Layer 2). A CC tweak does not rebuild every tick.
        self._algo_pattern: list[bool] = []
        self._algo_key: tuple = ()

        # Cached nearest-in-scale lookup table; rebuilt when (scale,
        # root) changes.
        self._scale_map: list[int] = list(range(128))
        self._scale_key: tuple[str, int] = ("", -1)

        self._refresh_algo_pattern()
        self._refresh_scale_map()
        self._publish_algo_underlay()
        self.set_display("envelope", 0)

    def on_stop(self):
        self._free_running = False
        self._silence_all()

    def panic(self):
        with self._lock:
            self._free_running = False
            self._held_notes = []
            self._sorted_notes = []
            self._physically_pressed.clear()
            self._sustain_active = False
            self._fade_value = 0.0
            self._fade_dir = 0.0
            self._fadeout_notes = []
            self._silence_all()
        self.set_display("envelope", 0)

    # ----- input handlers -----------------------------------------------------

    def _channel_match(self, channel: int, param_name: str) -> bool:
        v = self.get_param(param_name)
        return v is None or v == 0 or int(v) - 1 == channel

    def _pattern_trigger_index(self, channel: int, note: int) -> int | None:
        """Return pattern-table index N if `note` on `channel` is the
        Nth semitone of the pattern-trigger range AND control_channel
        allows the source channel, else None. Returns None when the
        Setup-group "Pattern Trigger" toggle is off, so trigger notes
        flow into the held-notes buffer normally."""
        if not self.get_param("pattern_trigger"):
            return None
        if not self._channel_match(channel, "control_channel"):
            return None
        base = self.get_param("pattern_base")
        if base is None:
            return None
        idx = note - int(base)
        if 0 <= idx < len(_PATTERN_OPTIONS):
            return idx
        return None

    def on_note_on(self, channel, note, velocity):
        # Pattern-trigger notes are consumed: they set the Pattern
        # wheel and do not join the held-notes buffer.
        idx = self._pattern_trigger_index(channel, note)
        if idx is not None:
            self.set_param("pattern", idx)
            return
        if not self._channel_match(channel, "arp_channel"):
            return
        self._physically_pressed[(channel, note)] = velocity
        with self._lock:
            already = any(n == note and c == channel
                          for n, _, c in self._held_notes)
            if not already:
                self._held_notes.append((note, velocity, channel))
                self._sorted_notes = sorted(self._held_notes, key=lambda x: x[0])
            was_idle = (
                len(self._held_notes) == (0 if already else 1)
                and not self._fadeout_notes
            )
            # New keypress cancels a running fade-out: snap envelope
            # back to full and forget the fade-out snapshot.
            if self._fade_dir < 0 or self._fadeout_notes:
                self._fade_value = 1.0
                self._fade_dir = 0.0
                self._fadeout_notes = []
            if was_idle:
                # First note of a fresh phrase. Honour Retrig + Fade In.
                if self.get_param("retrig"):
                    self._pitch_step = 0
                    self._seq_step = 0
                    self._direction = 1
                self._begin_fade_in()
                mode = self.get_param("sync_mode") or "tempo"
                if mode == "free" and not self._free_running:
                    self._start_free_runner()

    def on_note_off(self, channel, note):
        if self._pattern_trigger_index(channel, note) is not None:
            return
        if not self._channel_match(channel, "arp_channel"):
            return
        self._physically_pressed.pop((channel, note), None)
        with self._lock:
            if self._sustain_active:
                return  # pedal holds the note; cleared on pedal lift
            self._held_notes = [(n, v, c) for n, v, c in self._held_notes
                                if not (n == note and c == channel)]
            self._sorted_notes = sorted(self._held_notes, key=lambda x: x[0])
            if not self._held_notes:
                self._begin_fade_out_or_stop()

    def on_cc(self, channel, cc, value):
        if cc != 64:
            return
        if not self._channel_match(channel, "arp_channel"):
            return
        new_active = value >= 64
        if self._sustain_active and not new_active:
            with self._lock:
                self._held_notes = [
                    (n, v, c) for n, v, c in self._held_notes
                    if (c, n) in self._physically_pressed
                ]
                self._sorted_notes = sorted(self._held_notes, key=lambda x: x[0])
                if not self._held_notes:
                    self._begin_fade_out_or_stop()
        self._sustain_active = new_active

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    # ----- transport / clock --------------------------------------------------

    def on_transport_start(self):
        if (self.get_param("sync_mode") or "tempo") == "transport":
            self._pitch_step = 0
            self._seq_step = 0
            self._direction = 1
            self._note_off_current()
            self._transport_playing = True

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
            self._pitch_step = 0
            self._seq_step = 0
            self._direction = 1
        if division != self._rate_str():
            return
        self._advance()

    # ----- param-change reactions --------------------------------------------

    def on_param_change(self, name, value):
        if name in ("pulses", "steps", "rotate", "phase", "cycles", "open"):
            with self._lock:
                self._refresh_algo_pattern()
            self._publish_algo_underlay()
            return
        if name in ("scale", "root"):
            with self._lock:
                self._refresh_scale_map()
            return
        if name == "sync_mode":
            if value == "free":
                self._free_running = False
                if self._has_input():
                    self._start_free_runner()
            else:
                self._free_running = False
                if value == "transport":
                    self._transport_playing = False
            return

    # ----- algorithm + scale cache -------------------------------------------

    def _refresh_algo_pattern(self) -> None:
        pulses = max(0, int(self.get_param("pulses") or 0))
        steps = max(1, int(self.get_param("steps") or 16))
        rotate = int(self.get_param("rotate") or 0)
        phase = int(self.get_param("phase") or 0)
        cycles_idx = int(self.get_param("cycles") or 1)
        open_pct = int(self.get_param("open") or 100)
        key = (pulses, steps, rotate, phase, cycles_idx, open_pct)
        if key == self._algo_key and len(self._algo_pattern) == steps:
            return

        # Layer 1: Bjorklund + Rotate.
        base = euclidean_pattern(min(pulses, steps), steps)
        r = rotate % steps if steps else 0
        rotated = base[-r:] + base[:-r] if r else base

        # Layer 2: Window wave (sine threshold). Open=100 is the
        # transparent / no-op case; skip the math entirely.
        if open_pct >= 100:
            window = [True] * steps
        else:
            window = _window_mask(steps, phase, cycles_idx, open_pct)

        # Combined: a step is in the algorithm preview iff both layers
        # agree. Manual overrides on top of this are evaluated per
        # tick in `_advance`.
        self._algo_pattern = [r and w for r, w in zip(rotated, window)]
        self._algo_key = key

    def _publish_algo_underlay(self) -> None:
        """Push the per-step boolean ('does the algorithm want this
        step on?') to a sibling param so the StepEditor renders the
        algorithm's preview as an underlay tint on default-state
        cells."""
        self.set_param("step_algo_on", list(self._algo_pattern))

    def _refresh_scale_map(self) -> None:
        scale_idx = int(self.get_param("scale") or 0)
        root = int(self.get_param("root") or 0)
        try:
            name = _SCALE_OPTIONS[scale_idx]
        except IndexError:
            name = "major"
        key = (name, root)
        if key == self._scale_key:
            return
        self._scale_map = build_nearest_map(name, root)
        self._scale_key = key

    # ----- runner / advance ---------------------------------------------------

    def _has_input(self) -> bool:
        return bool(self._held_notes or self._fadeout_notes)

    def _pattern_str(self) -> str:
        idx = self.get_param("pattern")
        if idx is None:
            return "up"
        try:
            return _PATTERN_OPTIONS[int(idx)]
        except (ValueError, IndexError, TypeError):
            return "up"

    def _rate_str(self) -> str:
        idx = self.get_param("rate")
        if idx is None:
            return _RATE_OPTIONS[_DEFAULT_RATE_IDX]
        try:
            return _RATE_OPTIONS[int(idx)]
        except (ValueError, IndexError, TypeError):
            return _RATE_OPTIONS[_DEFAULT_RATE_IDX]

    def _start_free_runner(self):
        self._free_running = True

        def _run():
            while self._free_running:
                bpm = self.get_param("bpm") or 120
                rate = self._rate_str()
                beats_per_sec = bpm / 60.0
                interval = _RATE_FREE_MULT.get(rate, 0.5) / beats_per_sec
                self._advance()
                time.sleep(interval)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self._free_thread = t

    def _advance(self) -> None:
        with self._lock:
            self._refresh_algo_pattern()  # cheap (cached)

            steps_total = max(1, len(self._algo_pattern))
            grid = self.get_param("steps_grid") or []
            seq_idx = self._seq_step % steps_total
            self._seq_step += 1

            cell = grid[seq_idx] if seq_idx < len(grid) else {}
            state = cell.get("state", "default") if isinstance(cell, dict) else "default"
            algo_on = self._algo_pattern[seq_idx] if seq_idx < len(self._algo_pattern) else False

            if state == "off":
                fire = False
                accent = False
            elif state in ("on", "accent"):
                fire = True
                accent = state == "accent"
            else:  # "default"
                fire = algo_on
                accent = False

            self._note_off_current()

            if not fire:
                # The step is a rest; the envelope holds its current
                # value (fade counters tick only on actual firings).
                return

            note_source = self._held_notes or self._fadeout_notes
            if not note_source:
                # No held notes and no fade-out tail — nothing to play.
                return

            voiced = self._build_voicing(note_source)
            if not voiced:
                return

            self._apply_envelope_step()  # bump fade after we know we'd fire
            vel_mul = self._fade_value

            offset = int(cell.get("offset", 0)) if isinstance(cell, dict) else 0
            accent_add = (int(self.get_param("accent_vel") or 0) if accent else 0)

            jitter_off = self._jitter_offset_seconds()
            base_time = time.monotonic() + jitter_off if jitter_off > 0 else None
            on_time = base_time if base_time is not None else None
            rate_period = self._rate_period_seconds()
            note_off_at = None
            if rate_period > 0:
                gate = (int(self.get_param("gate") or 80)) / 100.0
                note_off_at = (on_time or time.monotonic()) \
                    + max(0.005, rate_period * gate)

            spread = int(self.get_param("tune_spread") or 0)
            snap = self._snap_str()

            for raw_note, raw_vel, ch in voiced:
                shifted = raw_note + self._spread_offset(spread, snap) + offset
                quantised = self._scale_lookup(shifted)
                if not (0 <= quantised <= 127):
                    continue
                vel = max(1, min(127, int(round((raw_vel + accent_add) * vel_mul))))
                if on_time is not None:
                    self.send_note_on_at(on_time, ch, quantised, vel, tag=_EUC_TAG)
                else:
                    self.send_note_on(ch, quantised, vel)
                if note_off_at is not None:
                    self.send_note_off_at(note_off_at, ch, quantised, tag=_EUC_TAG)
                self._playing_notes.append((ch, quantised))

            # If we just finished the fade-out tail, silence the rest
            # of the runner.
            if self._fade_dir < 0 and self._fade_value <= 0.0:
                self._fade_dir = 0.0
                self._fade_value = 0.0
                self._fadeout_notes = []
                self._held_notes = []
                self._sorted_notes = []
                self._free_running = False

            self.set_display("envelope", int(self._fade_value * 127))

    # ----- voicing / scale / spread ------------------------------------------

    def _build_voicing(self, source: list[tuple[int, int, int]]
                       ) -> list[tuple[int, int, int]]:
        """Return the (note, vel, channel) tuples that fire on this
        step. The Pattern wheel selects either a single voice from the
        held buffer (up / down / up-down / random / as-played) or the
        full chord (chord)."""
        pattern = self._pattern_str()
        octaves = max(1, int(self.get_param("octaves") or 1))

        # The "as-played" pattern uses press order; everything else
        # uses sorted-by-pitch order. chord plays every voice and is
        # by convention sorted (predictable layout in MIDI Monitor).
        if pattern == "as-played":
            base = list(source)
        else:
            base = sorted(source, key=lambda x: x[0])

        # Apply Octaves: extend the base list with each octave shift.
        extended: list[tuple[int, int, int]] = []
        for oct_idx in range(octaves):
            for n, v, c in base:
                extended.append((n + oct_idx * 12, v, c))

        if not extended:
            return []
        if pattern == "chord":
            return extended

        seq = list(extended)
        if pattern == "down":
            seq.reverse()

        if pattern == "random":
            return [seq[random.randrange(len(seq))]]
        if pattern == "up-down":
            if len(seq) <= 1:
                return [seq[0]]
            if self._pitch_step >= len(seq):
                self._direction = -1
                self._pitch_step = len(seq) - 2
            elif self._pitch_step < 0:
                self._direction = 1
                self._pitch_step = 1
            idx = self._pitch_step
            chosen = [seq[idx]]
            self._pitch_step += self._direction
            return chosen
        # up / down / as-played
        idx = self._pitch_step % len(seq)
        chosen = [seq[idx]]
        self._pitch_step += 1
        return chosen

    def _scale_lookup(self, note: int) -> int:
        """Snap `note` to the nearest in-scale degree. Out-of-range
        values clamp to the table bounds before lookup so a wild
        Tune Spread + Offset combination doesn't crash."""
        if not (0 <= note <= 127):
            note = max(0, min(127, note))
        return self._scale_map[note]

    def _snap_str(self) -> str:
        idx = int(self.get_param("spread_snap") or 0)
        try:
            return _SNAP_OPTIONS[idx]
        except IndexError:
            return "free"

    def _spread_offset(self, amount: int, snap: str) -> int:
        """Return a per-step random semitone offset. `amount` 0..100 is
        both the probability of a non-zero offset AND the magnitude
        scale: 0 = always 0, 100 = always picks from the full table."""
        if amount <= 0:
            return 0
        if random.randrange(100) >= amount:
            return 0
        if snap == "free":
            scale = max(1, round(12 * amount / 100))
            return random.randint(-scale, scale)
        table = _SNAP_INTERVALS.get(snap, [0])
        return random.choice(table)

    # ----- envelope / fade ---------------------------------------------------

    def _begin_fade_in(self) -> None:
        n = int(self.get_param("fade_in") or 0)
        if n <= 0:
            self._fade_value = 1.0
            self._fade_dir = 0.0
        else:
            self._fade_value = 0.0
            self._fade_dir = 1.0 / n

    def _begin_fade_out_or_stop(self) -> None:
        """Called when the last key is released (and sustain is up).
        With Fade Out > 0, snapshot the last chord into `_fadeout_notes`
        and start the ramp; the pattern keeps voicing those notes for
        N more firing steps. With Fade Out = 0, silence immediately."""
        n = int(self.get_param("fade_out") or 0)
        if n <= 0 or self._fade_value <= 0.0:
            self._free_running = False
            self._fade_value = 0.0
            self._fade_dir = 0.0
            self._fadeout_notes = []
            self._silence_all()
            self.set_display("envelope", 0)
            return
        # Capture the source the next _advance should keep voicing.
        # `_sorted_notes` is empty here (we just cleared `_held_notes`),
        # so re-snapshot from `_physically_pressed` — same channels and
        # default velocity for any key still in `_physically_pressed`
        # via sustain. If that's also empty, capture whatever was
        # _last_ playing (`_playing_notes` has the (ch, note) pairs).
        snapshot: list[tuple[int, int, int]] = []
        for (ch, n_), vel in self._physically_pressed.items():
            snapshot.append((n_, vel, ch))
        if not snapshot and self._playing_notes:
            # _playing_notes only has (ch, note); use velocity 100 as a
            # reasonable default so the fade-out tail has audible body.
            for ch, n_ in self._playing_notes:
                snapshot.append((n_, 100, ch))
        self._fadeout_notes = snapshot
        self._fade_dir = -1.0 / n

    def _apply_envelope_step(self) -> None:
        """Move the fade value by one firing-step's worth. Called from
        `_advance` when a step is actually about to fire (rests don't
        consume envelope steps — fade time follows musical pacing of
        the pattern, not real-time)."""
        if self._fade_dir == 0.0:
            return
        self._fade_value = max(0.0, min(1.0, self._fade_value + self._fade_dir))
        if self._fade_dir > 0 and self._fade_value >= 1.0:
            self._fade_dir = 0.0  # reached sustain plateau
        # Fade-out termination is handled by `_advance` after emit.

    # ----- timing helpers ----------------------------------------------------

    def _jitter_offset_seconds(self) -> float:
        amount = int(self.get_param("jitter") or 0)
        if amount <= 0:
            return 0.0
        period = self._rate_period_seconds()
        if period <= 0:
            return 0.0
        # One-sided forward jitter: a step lands at most period/2 *
        # amount/100 seconds after its nominal tick. Plan describes a
        # ±period/2 symmetric jitter, but scheduling earlier than
        # "now" isn't possible without lookahead from the clock bus;
        # this captures the audible humanisation either way.
        spread = period * 0.5 * amount / 100.0
        return random.uniform(0.0, spread)

    def _rate_period_seconds(self) -> float:
        rate = self._rate_str()
        mode = self.get_param("sync_mode") or "tempo"
        if mode == "free":
            bpm = self.get_param("bpm") or 120
            beats_per_sec = bpm / 60.0
            return _RATE_FREE_MULT.get(rate, 0.5) / beats_per_sec
        bus = getattr(self, "_clock_bus", None)
        period_ema = getattr(bus, "_tick_period_ema", None) if bus else None
        if period_ema is None:
            return 0.0
        return period_ema * _RATE_RAW_TICKS.get(rate, 12)

    # ----- note-off + cleanup -------------------------------------------------

    def _note_off_current(self) -> None:
        for ch, note in self._playing_notes:
            self.send_note_off(ch, note)
        self._playing_notes = []

    def _silence_all(self) -> None:
        self.cancel_scheduled(_EUC_TAG)
        self._note_off_current()
