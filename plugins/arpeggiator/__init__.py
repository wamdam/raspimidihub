"""Arpeggiator — plays held notes through a step pattern with note offsets.

Note timing goes through the ALSA queue: each note-on is sent
immediately when the step fires, but its note-off is scheduled at
`note_on_time + gate_duration` via send_note_off_at, so the gate %
is honored with sub-ms accuracy regardless of Python jitter. Without
this, gate was effectively 100% (cut by the next step's note_off).

Surface: kind="play" — appears in the Play tab carousel next to the
Tracker. Pattern, Rate, Steps, Accent, Gate, Octaves and the step
grid render on the play surface; channel filters / Sync + BPM /
Pattern Ctrl Ch + Pattern Notes are config_only and live in the
device-detail panel. Pattern and Rate are wide integer-indexed
Wheels (storage is the index into _PATTERN_OPTIONS / _RATE_OPTIONS);
on_start migrates legacy string-stored configs.
"""

import random
import threading
import time

from raspimidihub import slot_bank
from raspimidihub.plugin_api import (
    ChannelSelect,
    Group,
    Knob,
    NoteSelect,
    PatternStrip,
    PluginBase,
    Radio,
    StepEditor,
    Wheel,
)

# Raw 24-PPQN ticks per arp rate. Used to convert clock-bus period →
# rate period for gate-duration computation.
_ARP_RATE_RAW_TICKS = {
    "4/1": 384, "2/1": 192, "1/1": 96, "1/2": 48,
    "1/4": 24, "1/8": 12, "1/16": 6, "1/32": 3,
    "4/1T": 256, "2/1T": 128, "1/1T": 64, "1/2T": 32,
    "1/4T": 16, "1/8T": 8, "1/16T": 4,
}

# Free-mode rate → quarter-note multiplier.
_ARP_RATE_FREE_MULT = {
    "4/1": 16, "2/1": 8, "1/1": 4, "1/2": 2,
    "1/4": 1, "1/8": 0.5, "1/16": 0.25, "1/32": 0.125,
    "4/1T": 32 / 3, "2/1T": 16 / 3, "1/1T": 8 / 3, "1/2T": 4 / 3,
    "1/4T": 2 / 3, "1/8T": 1 / 3, "1/16T": 1 / 6,
}

# Tag for all our scheduled note-offs. Cancel-on-panic clears the
# pending burst in one call.
_ARP_TAG = 1


class Arpeggiator(PluginBase):
    """Plays held notes back as a rhythmic pattern through a step sequencer."""

    SURFACE_KIND = "play"

    NAME = "Arpeggiator"
    DESCRIPTION = "Plays held notes as a pattern with step sequencer"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.2"
    HELP = """\
Combines arpeggiator patterns with a step sequencer. Hold notes and
the arp cycles through them in the selected pattern (up/down/etc).
Each step can be on/off and has a note offset (semitones from the
current arp note). Only active steps play — inactive steps are rests.

Pattern modes: up / down / up-down / random / as-played / programmed
/ chord. `chord` fires every held note simultaneously each step
(same offset / accent / gate apply to the whole burst).

Default: all steps on, zero offset = classic arpeggiator.
Set offsets to create melodic variations on each step.
Set some steps off to create rhythmic gaps.

Sync: Free=internal BPM, Tempo=external clock, Transport=clock+Start/Stop.
Gate % = note length (100=legato, 10=staccato).

Arp Ch / Ctrl Ch: channel filters on the input. Default Any =
accept any channel. Set Arp Ch = 1 + Ctrl Ch = 16 to wire a
separate keyboard / footswitch on ch16 that only switches
patterns, never plays.

Pattern Ctrl Ch + Pattern Notes (P1..P8): reserve a MIDI channel
for pattern-slot switching and MIDI-Learn one trigger note per
slot. Notes on that channel are consumed — they switch the
active slot without arpeggiating."""

    # Single source of truth for the pattern Wheel's tick labels AND
    # the runtime conditional logic (`as-played`, `programmed`, …).
    # Stored value is the integer index into this list; _pattern_str()
    # converts back to the label string for comparisons.
    # `chord` is appended at the end on purpose: legacy configs that
    # stored the pattern as an int index (post-3.1.6) still resolve to
    # their original label because nothing earlier in the list shifted.
    _PATTERN_OPTIONS = [
        "up", "down", "up-down", "random", "as-played", "programmed",
        "chord",
    ]

    # Tick labels for the rate Wheel. The param stores the integer
    # index, `_rate_str()` returns the label.
    _RATE_OPTIONS = [
        "4/1", "4/1T", "2/1", "2/1T", "1/1", "1/1T",
        "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T",
        "1/16", "1/16T", "1/32",
    ]
    _DEFAULT_RATE_IDX = _RATE_OPTIONS.index("1/8")  # 10

    # Every play_only param that should be captured into a pattern
    # slot. Switching slot N replaces each of these from
    # `pattern_slots[N]`; edits to any of them auto-write back into
    # the active slot. `active_slot` itself is excluded — it's the
    # bank selector, not part of the snapshot.
    _SLOT_PARAMS = [
        "pattern", "rate", "step_count", "accent_vel",
        "gate", "octaves", "steps",
    ]

    params = [
        # Play-surface controls. Pattern + Rate are wide wheels in the
        # top row (span=2 each → 4-col grid filled). The four shapers
        # auto-pack into the next row as inline wheels/knob. The Step
        # Editor below spans the full row. All marked play_only so the
        # device-detail panel doesn't duplicate them — power users
        # still see them on the Play tab, the config card stays
        # focused on the wiring choices.
        Wheel("pattern", "Pattern",
              min=0, max=len(_PATTERN_OPTIONS) - 1,
              labels=_PATTERN_OPTIONS, default=0,
              wide=True, span=2, play_only=True),
        Wheel("rate", "Rate",
              min=0, max=len(_RATE_OPTIONS) - 1,
              labels=_RATE_OPTIONS, default=_DEFAULT_RATE_IDX,
              wide=True, span=2, play_only=True),
        Wheel("step_count", "Steps", min=1, max=32, default=8, play_only=True),
        Knob("accent_vel", "Accent Vel.", min=0, max=127, default=30, play_only=True),
        Wheel("gate", "Gate %", min=10, max=100, default=80, play_only=True),
        Wheel("octaves", "Octaves", min=1, max=4, default=1, play_only=True),
        StepEditor("steps", "Step Pattern", length_param="step_count",
                   default_length=8, default_on=True, span=4,
                   slot_notes_param="step_slot_notes", play_only=True),
        # Pattern-slot strip — bottom-of-play-surface bank selector.
        # Switching slots is immediate and held notes / sustain
        # persist across the switch; the snapshot scope is the
        # `_SLOT_PARAMS` set above.
        PatternStrip("active_slot", "Patterns",
                     count=slot_bank.SLOT_COUNT, default=0,
                     slots_param="pattern_slots",
                     cmd_param="pattern_cmd",
                     play_only=True),
        # Config-only setup. Channel filters, rate-trigger plumbing
        # and the sync-mode + BPM live here — touched on initial
        # wiring, never during a set.
        Group("Setup", [
            # Channel filters. 0 = Any (default); 1-16 restricts which
            # incoming notes count as arpeggiate input vs rate-trigger
            # input. Useful when one keyboard plays melodies on ch1
            # and a footswitch / aux key sends rate-trigger notes on
            # ch16 — set arp_channel=1, control_channel=16 and the
            # same note range no longer has to be split between the
            # two functions.
            ChannelSelect("arp_channel", "Arp Ch", default=0, allow_any=True),
            ChannelSelect("control_channel", "Ctrl Ch", default=0, allow_any=True),
            Radio("sync_mode", "Sync",
                  ["free", "tempo", "transport"], default="transport"),
            Wheel("bpm", "BPM", min=40, max=300, default=120,
                  visible_when=("sync_mode", "free")),
            # Pattern-slot hardware trigger — mirrors the Tracker's
            # plumbing. 0 = Off; 1..16 reserves that channel for
            # slot selection (every note on the channel is
            # consumed). Each pattern_note_N is the learnable note
            # that picks slot N.
            Wheel("pattern_ctrl_ch", "Pattern Ctrl Ch",
                  min=0, max=16, default=0,
                  labels=["Off"] + [str(i) for i in range(1, 17)]),
            Group("Pattern Notes", [
                NoteSelect(f"pattern_note_{i}", f"P{i + 1}",
                           default=36 + i, config_only=True)
                for i in range(slot_bank.SLOT_COUNT)
            ], config_only=True,
                visible_when=("pattern_ctrl_ch", list(range(1, 17)))),
        ], config_only=True),
    ]

    # Block CC#70..83 — mirrors the Euclidean's shared-param
    # mapping so a hardware controller wired for one plugin drives
    # the matching knobs on the other.
    cc_inputs = {
        70: "pattern",
        71: "octaves",
        73: "step_count",
        74: "rate",
        75: "gate",
        83: "accent_vel",
    }
    cc_outputs = []

    inputs = ["Notes", "CC#64 (sustain pedal — temporarily holds arping notes)",
              "CC#70 (pattern)", "CC#71 (octaves)", "CC#73 (steps)",
              "CC#74 (rate)", "CC#75 (gate)", "CC#83 (accent vel.)",
              "Pattern Ctrl Ch notes (set Pattern slot 1..8)",
              "Clock", "Aftertouch", "Pitch Bend"]
    outputs = ["Notes (arpeggiated)", "Aftertouch (pass-through)", "Pitch Bend (pass-through)"]

    clock_divisions = [
        "4/1", "4/1T", "2/1", "2/1T", "1/1", "1/1T",
        "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T",
        "1/16", "1/16T", "1/32",
    ]

    def on_start(self):
        # Migrate legacy string-stored pattern / rate to integer index.
        # Old configs saved before the Wheel switch carry strings;
        # _PATTERN_OPTIONS / _RATE_OPTIONS define the canonical order.
        # Any value already an int (or missing) flows through unchanged.
        legacy_pattern = self._param_values.get("pattern")
        if isinstance(legacy_pattern, str):
            try:
                self._param_values["pattern"] = self._PATTERN_OPTIONS.index(legacy_pattern)
            except ValueError:
                self._param_values["pattern"] = 0  # "up"
        legacy_rate = self._param_values.get("rate")
        if isinstance(legacy_rate, str):
            try:
                self._param_values["rate"] = self._RATE_OPTIONS.index(legacy_rate)
            except ValueError:
                self._param_values["rate"] = self._DEFAULT_RATE_IDX

        self._held_notes = []
        self._sorted_notes = []
        self._arp_step = 0       # position in the arp note sequence
        self._seq_step = 0       # position in the step editor
        self._direction = 1
        # Notes currently sounding from the last fired step. List form
        # so chord mode can keep multiple alive and `_note_off_current`
        # silences the whole burst on the next step. Single-note
        # patterns simply keep one entry.
        self._playing_notes: list[tuple[int, int]] = []
        self._lock = threading.Lock()
        self._free_thread = None
        self._free_running = False
        self._transport_playing = False
        # Sustain pedal (CC 64) state. `_physically_pressed` tracks
        # what the user is actually holding right now — used on pedal
        # release to drop notes that are only "alive" via sustain.
        self._physically_pressed: dict = {}  # (channel, note) -> velocity
        self._sustain_active = False
        # Programmed-pattern state. Each slot is None or
        # (note, velocity, channel). The pattern's step_count is
        # authoritative for length; _ensure_slots() resizes lazily.
        # `_next_slot_to_play` is the slot the next _advance fires;
        # `_write_slot` is where the next keypress lands. They diverge
        # between ticks so a flurry of fingers fans into consecutive
        # slots; a tick re-syncs them.
        self._step_slots: list = []
        self._next_slot_to_play = 0
        self._write_slot = 0

        # Pattern bank — 8 snapshots of the play-surface params. On a
        # fresh instance every slot is a clone of the defaults so
        # switching slot N always lands on a real (if undifferentiated)
        # pattern; existing saved configs keep whatever they stored.
        slot_bank.init_slot_bank(self, self._SLOT_PARAMS)

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
            self._step_slots = []
            self._next_slot_to_play = 0
            self._write_slot = 0
            self._silence_all()
        self._publish_slot_notes()

    def _publish_slot_notes(self) -> None:
        """Push the per-slot MIDI note numbers (or None) to a sibling
        param so the StepEditor frontend can render note names under
        each square. Called whenever `_step_slots` is mutated."""
        notes = [s[0] if s is not None else None for s in self._step_slots]
        # set_param broadcasts via SSE plus persists in _param_values.
        self.set_param("step_slot_notes", notes)

    def _ensure_slots(self) -> None:
        """Grow / shrink `_step_slots` to match the current step_count.
        Growing pads with None; shrinking truncates (caller is the
        step_count param-change handler — user-driven shrink is rare
        and discarding the tail is the obvious behaviour)."""
        sc = max(1, int(self.get_param("step_count") or 8))
        size_changed = False
        if len(self._step_slots) < sc:
            self._step_slots.extend([None] * (sc - len(self._step_slots)))
            size_changed = True
        elif len(self._step_slots) > sc:
            self._step_slots = self._step_slots[:sc]
            size_changed = True
        if self._next_slot_to_play >= sc:
            self._next_slot_to_play = 0
        if self._write_slot >= sc:
            self._write_slot = self._next_slot_to_play
        if size_changed:
            self._publish_slot_notes()

    def _next_enabled_slot(self, start: int, total: int) -> int:
        """Index of the next enabled step ≥ start (mod total). Steps
        toggled off in the StepEditor are skipped — assigning a note
        to a muted step would silently never play. Falls back to
        start % total if every step is disabled."""
        steps = self.get_param("steps") or []
        for offset in range(total):
            idx = (start + offset) % total
            step = steps[idx] if idx < len(steps) else {"on": True}
            if step.get("on", True):
                return idx
        return start % total

    def _pattern_str(self) -> str:
        """Return the string label for the currently-selected pattern.
        Stored value is an int index into _PATTERN_OPTIONS; this is
        the helper that callers use when they need to compare against
        a literal ("programmed", "as-played", …)."""
        idx = self.get_param("pattern")
        if idx is None:
            return "up"
        try:
            return self._PATTERN_OPTIONS[int(idx)]
        except (ValueError, IndexError, TypeError):
            return "up"

    def _rate_str(self) -> str:
        """Return the string label for the currently-selected rate.
        See _pattern_str() — same idea, index into _RATE_OPTIONS."""
        idx = self.get_param("rate")
        if idx is None:
            return "1/8"
        try:
            return self._RATE_OPTIONS[int(idx)]
        except (ValueError, IndexError, TypeError):
            return "1/8"

    def _has_input(self) -> bool:
        """True if the arp has anything to play. Pattern-aware so the
        free runner doesn't spin forever after the user releases the
        last key (held-pattern modes) or clears every slot
        (programmed)."""
        if self._pattern_str() == "programmed":
            return any(s is not None for s in self._step_slots)
        return bool(self._held_notes)

    def _seek_to_new_note(self, new_note: int) -> None:
        """Set _arp_step so the next _advance plays new_note. Pattern-
        aware. Called after a non-programmed `_held_notes.append`. The
        existing modular index logic in _advance then maps the seeded
        _arp_step to whichever index in the eventual `notes` list
        produces new_note."""
        pattern = self._pattern_str()
        if pattern in ("random", "chord"):
            return  # no single "next" note to seek toward
        if pattern == "as-played":
            # held_notes order is press order; new note was just appended.
            self._arp_step = max(0, len(self._held_notes) - 1)
            return
        sorted_idx = next(
            (i for i, (n, _, _) in enumerate(self._sorted_notes) if n == new_note),
            None)
        if sorted_idx is None:
            return
        octaves = max(1, int(self.get_param("octaves") or 1))
        sorted_len = max(1, len(self._sorted_notes))
        if pattern == "down":
            # _advance reverses the (sorted * octaves) list, so
            # sorted[k] of the FIRST octave block ends up at index
            # `octaves*sorted_len - 1 - k` in the reversed list.
            self._arp_step = (octaves * sorted_len - 1) - sorted_idx
        else:  # "up", "up-down"
            self._arp_step = sorted_idx

    def on_transport_start(self):
        mode = self.get_param("sync_mode") or "tempo"
        if mode == "transport":
            self._arp_step = 0
            self._seq_step = 0
            self._direction = 1
            self._note_off_current()
            self._transport_playing = True

    def on_transport_stop(self):
        mode = self.get_param("sync_mode") or "tempo"
        if mode == "transport":
            self._transport_playing = False
            self._silence_all()

    def _channel_match(self, channel: int, param_name: str) -> bool:
        """True if `channel` (0-based) passes the named filter param.
        Filter value 0 = Any (no filter); 1-16 = filter to that
        user-channel which is `value - 1` internally. Missing param
        or None defaults to Any."""
        v = self.get_param(param_name)
        return v is None or v == 0 or int(v) - 1 == channel

    def on_note_on(self, channel, note, velocity):
        # Slot-trigger notes are checked first — they live on a
        # dedicated control channel and switch the pattern bank.
        # Trigger notes are consumed (the held-notes buffer never
        # sees them) so the Pattern Ctrl Ch is fully reserved.
        slot_idx = slot_bank.trigger_note_index(self, channel, note)
        if slot_idx is not None:
            if slot_idx != self.get_param("active_slot"):
                slot_bank.load_slot(self, self._SLOT_PARAMS, slot_idx)
            return
        # Arp channel filter: notes on a non-matching channel pass
        # through without joining the held-notes set, so they don't
        # arpeggiate. The output is unchanged — this only governs
        # what counts as "input that should be arped".
        if not self._channel_match(channel, "arp_channel"):
            return
        # Track the physical state regardless of pattern, so the
        # sustain pedal (CC 64) release path can drop unheld notes.
        self._physically_pressed[(channel, note)] = velocity
        pattern = self._pattern_str()
        with self._lock:
            if pattern == "programmed":
                self._ensure_slots()
                sc = len(self._step_slots)
                if sc == 0:
                    return
                had_any = any(s is not None for s in self._step_slots)
                wr = self._next_enabled_slot(self._write_slot, sc)
                self._step_slots[wr] = (note, velocity, channel)
                self._publish_slot_notes()
                # Advance write head — multiple presses between ticks
                # fan into consecutive slots (3b: chord spread).
                self._write_slot = self._next_enabled_slot(wr + 1, sc)
                if not had_any:
                    # First populated slot kicks off playback.
                    self._next_slot_to_play = wr
                    self._seq_step = 0
                    mode = self.get_param("sync_mode") or "tempo"
                    if mode == "free" and not self._free_running:
                        self._start_free_runner()
                return
            # Non-programmed patterns: dedupe re-presses (sustain-
            # then-repress would otherwise stack two entries) and
            # seek the next-fire index to the new note.
            already = any(n == note and c == channel
                          for n, _, c in self._held_notes)
            if not already:
                self._held_notes.append((note, velocity, channel))
                self._sorted_notes = sorted(self._held_notes,
                                             key=lambda x: x[0])
            if len(self._held_notes) == 1:
                self._arp_step = 0
                self._seq_step = 0
                self._direction = 1
                mode = self.get_param("sync_mode") or "tempo"
                if mode == "free":
                    self._start_free_runner()
            elif not already:
                # Feature 2: new note plays on the very next tick;
                # pattern continues from there.
                self._seek_to_new_note(note)

    def on_note_off(self, channel, note):
        # Symmetric to on_note_on: slot-trigger and non-matching-
        # arp-channel note-offs are also consumed, so the held-notes
        # list never sees them at all.
        if slot_bank.trigger_note_index(self, channel, note) is not None:
            return
        if not self._channel_match(channel, "arp_channel"):
            return
        self._physically_pressed.pop((channel, note), None)
        pattern = self._pattern_str()
        cleared_programmed = False
        with self._lock:
            if pattern == "programmed":
                # Slots persist while ANY input is alive — at least
                # one key still held or sustain pedal still down. Once
                # everything is released, the programmed sequence
                # ends and the slots clear (otherwise the arp would
                # loop forever after first programming, which is
                # surprising). Re-press a key to start a new phrase.
                #
                # The gate is "no surviving slot still references a
                # pressed key", not "_physically_pressed is empty":
                # any path that adds (channel, note) without a paired
                # note-off (rate-trigger toggled mid-press, channel
                # filter changed mid-press, bridge dropping an event)
                # leaks an entry into _physically_pressed that the
                # user can't see. Trusting raw emptiness pins the
                # gate forever; checking against slot keys keeps the
                # arp silenceable even after a leak.
                slots_have_held_key = any(
                    s is not None and (s[2], s[0]) in self._physically_pressed
                    for s in self._step_slots
                )
                if not slots_have_held_key and not self._sustain_active:
                    self._step_slots = [None] * len(self._step_slots)
                    self._free_running = False
                    self._silence_all()
                    cleared_programmed = True
            elif self._sustain_active:
                # Sustain pedal holds the note across release. It only
                # leaves _held_notes when the pedal lifts AND the key
                # isn't physically held again by then.
                pass
            else:
                self._held_notes = [(n, v, c) for n, v, c in self._held_notes
                                    if not (n == note and c == channel)]
                self._sorted_notes = sorted(self._held_notes,
                                             key=lambda x: x[0])
                if not self._held_notes:
                    self._free_running = False
                    self._silence_all()
        if cleared_programmed:
            self._publish_slot_notes()

    def on_cc(self, channel, cc, value):
        """CC 64 (sustain pedal): pressing temporarily turns the arp
        into a Hold — keys you release stay arping, new keys stack.
        Releasing the pedal drops every note that isn't physically
        held right now. CC is consumed (not passed through), and the
        same `arp_channel` filter that gates note input applies."""
        if cc != 64:
            return
        if not self._channel_match(channel, "arp_channel"):
            return
        new_active = value >= 64
        if self._sustain_active and not new_active:
            self._on_sustain_release()
        self._sustain_active = new_active

    def _on_sustain_release(self) -> None:
        """Drop notes whose source key is no longer physically held."""
        pattern = self._pattern_str()
        with self._lock:
            if pattern == "programmed":
                changed = False
                for i, slot in enumerate(self._step_slots):
                    if slot is None:
                        continue
                    n, _, c = slot
                    if (c, n) not in self._physically_pressed:
                        self._step_slots[i] = None
                        changed = True
                if changed:
                    self._publish_slot_notes()
            else:
                self._held_notes = [
                    (n, v, c) for n, v, c in self._held_notes
                    if (c, n) in self._physically_pressed
                ]
                self._sorted_notes = sorted(self._held_notes,
                                             key=lambda x: x[0])
                if not self._held_notes:
                    self._free_running = False
                    self._silence_all()

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_tick(self, division):
        mode = self.get_param("sync_mode") or "tempo"
        if mode == "free":
            return
        if mode == "transport" and not self._transport_playing:
            self._transport_playing = True
            self._arp_step = 0
            self._seq_step = 0
            self._direction = 1

        rate = self._rate_str()
        if division != rate:
            return
        self._advance()

    def on_param_change(self, name, value):
        # Pattern bank: a user-driven `active_slot` change loads the
        # snapshot from the slot bank (and broadcasts every loaded
        # param via set_param, so the surface knobs animate to their
        # new values). The load path itself sets `_loading_slot`, so
        # the record_edit call below is a no-op while it's running.
        if name == "active_slot":
            slot_bank.load_slot(self, self._SLOT_PARAMS, int(value))
            return
        # Long-press menu on the pattern strip dispatches a
        # {slot, mode: "clone"|"clear"} payload through this sibling
        # param. After dispatch we clear the trigger so a repeat of
        # the same command (long-press same slot, same item) still
        # fires.
        if name == "pattern_cmd":
            from raspimidihub.plugin_api import get_defaults
            slot_bank.handle_command(
                self, self._SLOT_PARAMS,
                get_defaults(type(self).params), value)
            if value is not None:
                self.set_param("pattern_cmd", None)
            return
        # Any edit to a snapshotted play_only param writes back into
        # the active slot. Guarded against feedback loops by
        # `_loading_slot`.
        slot_bank.record_edit(self, self._SLOT_PARAMS, name, value)
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
        if name == "step_count":
            with self._lock:
                self._ensure_slots()
            return
        if name == "pattern":
            # Value here is the int index (post-migration). Look up the
            # label so the "programmed → seed slots" branch keeps its
            # semantic check by name rather than position.
            try:
                label = self._PATTERN_OPTIONS[int(value)]
            except (ValueError, IndexError, TypeError):
                label = "up"
            with self._lock:
                if label == "programmed":
                    self._ensure_slots()
                    self._next_slot_to_play = 0
                    self._write_slot = 0
            return

    def _start_free_runner(self):
        self._free_running = True
        def _run():
            while self._free_running:
                bpm = self.get_param("bpm") or 120
                rate = self._rate_str()
                beats_per_sec = bpm / 60.0
                rate_map = {
                    "4/1": 16, "2/1": 8, "1/1": 4, "1/2": 2,
                    "1/4": 1, "1/8": 0.5, "1/16": 0.25, "1/32": 0.125,
                    "4/1T": 32/3, "2/1T": 16/3, "1/1T": 8/3, "1/2T": 4/3,
                    "1/4T": 2/3, "1/8T": 1/3, "1/16T": 1/6,
                }
                interval = rate_map.get(rate, 0.5) / beats_per_sec
                self._advance()
                time.sleep(interval)
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _advance(self):
        with self._lock:
            pattern = self._pattern_str()
            octaves = self.get_param("octaves") or 1
            gate = (self.get_param("gate") or 80) / 100.0
            steps = self.get_param("steps") or []
            step_count = self.get_param("step_count") or 8

            if pattern == "programmed":
                self._advance_programmed(octaves, gate, steps, step_count)
                return

            if not self._sorted_notes:
                return

            # Build arp note sequence
            if pattern == "as-played":
                base_notes = list(self._held_notes)
            else:
                base_notes = list(self._sorted_notes)

            notes = []
            for oct in range(octaves):
                for note, vel, ch in base_notes:
                    notes.append((note + oct * 12, vel, ch))

            if not notes:
                return

            if pattern == "down":
                notes.reverse()

            # Get current step from step editor
            active_steps = steps[:step_count] if steps else []
            if not active_steps:
                # No steps defined — default all on, zero offset
                active_steps = [{"on": True, "offset": 0}] * step_count

            # Current step
            seq_idx = self._seq_step % len(active_steps)
            step = active_steps[seq_idx]

            # Always advance seq step
            self._seq_step += 1

            # Note off previous
            self._note_off_current()

            # Only play if step is active
            if not step.get("on", True):
                return

            # Chord mode: every held note (× octaves) fires at once on
            # this step, with the same per-step offset / accent / gate.
            # The `_arp_step` counter is not advanced — chord has no
            # "next" pitch to pick.
            if pattern == "chord":
                offset = step.get("offset", 0)
                accent_add = (self.get_param("accent_vel") or 0
                              if step.get("accent") else 0)
                rate_period = self._rate_period_seconds()
                note_off_at = (time.monotonic()
                               + max(0.005, rate_period * gate)
                               if rate_period > 0 else None)
                for note, vel, ch in notes:
                    out_note = note + offset
                    if not (0 <= out_note <= 127):
                        continue
                    out_vel = min(127, vel + accent_add) if accent_add else vel
                    self.send_note_on(ch, out_note, out_vel)
                    if note_off_at is not None:
                        self.send_note_off_at(note_off_at, ch, out_note,
                                              tag=_ARP_TAG)
                    self._playing_notes.append((ch, out_note))
                return

            # Get the arp note
            if pattern == "random":
                arp_idx = random.randint(0, len(notes) - 1)
            elif pattern == "up-down":
                if len(notes) <= 1:
                    arp_idx = 0
                else:
                    if self._arp_step >= len(notes):
                        self._direction = -1
                        self._arp_step = len(notes) - 2
                    elif self._arp_step < 0:
                        self._direction = 1
                        self._arp_step = 1
                    arp_idx = self._arp_step
            else:
                arp_idx = self._arp_step % len(notes)

            note, vel, ch = notes[arp_idx]

            # Apply step offset and accent
            offset = step.get("offset", 0)
            note = note + offset
            if step.get("accent"):
                accent_add = self.get_param("accent_vel") or 0
                vel = min(127, vel + accent_add)

            if 0 <= note <= 127:
                self.send_note_on(ch, note, vel)
                # Schedule the note-off at `gate` of the rate period —
                # gives accurate staccato/legato regardless of when the
                # next step fires. ALSA queue takes care of the timing
                # with sub-ms jitter; cancel_scheduled(_ARP_TAG) clears
                # the pending off if we silence the whole arp early.
                rate_period = self._rate_period_seconds()
                if rate_period > 0:
                    note_off_at = time.monotonic() + max(0.005, rate_period * gate)
                    self.send_note_off_at(note_off_at, ch, note, tag=_ARP_TAG)
                self._playing_notes.append((ch, note))

            # Advance arp position
            if pattern == "up-down":
                self._arp_step += self._direction
            elif pattern != "random":
                self._arp_step += 1

    def _advance_programmed(self, octaves: int, gate: float,
                              steps: list, step_count: int) -> None:
        """One tick of programmed pattern. The lock is already held by
        _advance. Cycle length = step_count × octaves: each octave
        block plays the same slot sequence at +12 semitones above the
        previous. `_seq_step` walks the total cycle; `_next_slot_to_play`
        is the slot index within one octave block (a redundant view kept
        for symmetry with how presses choose `_write_slot`)."""
        self._ensure_slots()
        sc = max(1, step_count)
        oct_count = max(1, int(octaves))
        total = sc * oct_count
        seq_idx = self._seq_step % total
        slot_idx = seq_idx % sc
        octave_idx = seq_idx // sc

        # Resolve the active step row (on/off, offset, accent).
        active_steps = steps[:sc] if steps else []
        if not active_steps:
            active_steps = [{"on": True, "offset": 0}] * sc
        step_row = active_steps[slot_idx] if slot_idx < len(active_steps) \
            else {"on": True, "offset": 0}

        # Advance the playback head BEFORE early-returns so a silent
        # / empty step still moves the cycle forward.
        self._seq_step += 1
        self._next_slot_to_play = (slot_idx + 1) % sc
        # Re-sync the write head to playhead each tick: presses
        # between ticks fan into consecutive slots; first press in a
        # new tick lands on the next-fire slot.
        self._write_slot = self._next_slot_to_play

        # Note-off the previous note before deciding what fires now.
        self._note_off_current()

        if not step_row.get("on", True):
            return
        slot = self._step_slots[slot_idx]
        if slot is None:
            return

        note, vel, ch = slot
        offset = step_row.get("offset", 0)
        note_out = note + octave_idx * 12 + offset
        if step_row.get("accent"):
            accent_add = self.get_param("accent_vel") or 0
            vel = min(127, vel + accent_add)

        if 0 <= note_out <= 127:
            self.send_note_on(ch, note_out, vel)
            rate_period = self._rate_period_seconds()
            if rate_period > 0:
                note_off_at = time.monotonic() + max(0.005, rate_period * gate)
                self.send_note_off_at(note_off_at, ch, note_out, tag=_ARP_TAG)
            self._playing_notes.append((ch, note_out))

    def _note_off_current(self):
        for ch, note in self._playing_notes:
            self.send_note_off(ch, note)
        self._playing_notes = []

    def _silence_all(self):
        """Cancel every pending scheduled note-off and immediately
        silence the currently-sounding notes. Used by panic / transport-
        stop / no-keys-held — we need notes to stop NOW, not at their
        gate boundary."""
        self.cancel_scheduled(_ARP_TAG)
        self._note_off_current()

    def _rate_period_seconds(self) -> float:
        """Seconds per arp step at the current rate + sync mode. Used
        for gate timing. Returns 0 if neither the master clock nor a
        free-mode BPM is available."""
        rate = self._rate_str()
        mode = self.get_param("sync_mode") or "tempo"
        if mode == "free":
            bpm = self.get_param("bpm") or 120
            beats_per_sec = bpm / 60.0
            return _ARP_RATE_FREE_MULT.get(rate, 0.5) / beats_per_sec
        # tempo / transport modes — read the running clock-bus estimate.
        bus = getattr(self, "_clock_bus", None)
        period_ema = getattr(bus, "_tick_period_ema", None) if bus else None
        if period_ema is None:
            return 0.0
        return period_ema * _ARP_RATE_RAW_TICKS.get(rate, 12)
