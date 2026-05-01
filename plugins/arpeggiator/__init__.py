"""Arpeggiator — plays held notes through a step pattern with note offsets.

Note timing goes through the ALSA queue: each note-on is sent
immediately when the step fires, but its note-off is scheduled at
`note_on_time + gate_duration` via send_note_off_at, so the gate %
is honored with sub-ms accuracy regardless of Python jitter. Without
this, gate was effectively 100% (cut by the next step's note_off).
"""

import random
import threading
import time

from raspimidihub.plugin_api import (
    Button,
    Group,
    Knob,
    NoteSelect,
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

    NAME = "Arpeggiator"
    DESCRIPTION = "Plays held notes as a pattern with step sequencer"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Combines arpeggiator patterns with a step sequencer. Hold notes and
the arp cycles through them in the selected pattern (up/down/etc).
Each step can be on/off and has a note offset (semitones from the
current arp note). Only active steps play — inactive steps are rests.

Default: all steps on, zero offset = classic arpeggiator.
Set offsets to create melodic variations on each step.
Set some steps off to create rhythmic gaps.

Sync: Free=internal BPM, Tempo=external clock, Transport=clock+Start/Stop.
Gate % = note length (100=legato, 10=staccato).

Trigger Note: when on, MIDI notes from `Base` upward set the rate
live. Base = first rate (4/1), Base+1 semitone = 4/1T, +2 = 2/1, …
covering all 15 rates. Trigger notes are consumed — they don't get
arpeggiated. Pick a Base outside your playing range (default C1).
Use MIDI Learn on the Base wheel to capture from a controller."""

    # Single source of truth for the rate Radio's options AND the
    # rate-trigger note→rate mapping. Index N in this list is the rate
    # selected when (note - rate_base) == N.
    _RATE_OPTIONS = [
        "4/1", "4/1T", "2/1", "2/1T", "1/1", "1/1T",
        "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T",
        "1/16", "1/16T", "1/32",
    ]

    params = [
        Group("Pattern", [
            Radio("pattern", "Pattern", ["up", "down", "up-down", "random", "as-played"],
                  default="up"),
            # Live-rate trigger: when enabled, a MIDI note in the
            # [rate_base, rate_base + len(_RATE_OPTIONS)) range sets
            # the Rate radio without being arpeggiated. Hit MIDI Learn
            # on the Base wheel and play the lowest rate-trigger key
            # to capture; the next 14 semitones cover the remaining
            # rates in the order they appear in the radio below.
            Button("rate_trigger", "Trigger Note", default=False, color="green"),
            NoteSelect("rate_base", "Base", default=24,  # C1 — well below
                       visible_when=("rate_trigger", True)),  # most playing ranges
            Radio("rate", "Rate", _RATE_OPTIONS, default="1/8"),
        ]),
        Group("Steps", [
            Wheel("step_count", "Steps", min=1, max=32, default=8),
            Knob("accent_vel", "Accent Vel.", min=0, max=127, default=30),
            StepEditor("steps", "Pattern", length_param="step_count",
                       default_length=8, default_on=True, span=4),
        ]),
        Group("Controls", [
            Wheel("gate", "Gate %", min=10, max=100, default=80),
            Wheel("octaves", "Octaves", min=1, max=4, default=1),
            Radio("sync_mode", "Sync", ["free", "tempo", "transport"], default="transport"),
            Wheel("bpm", "BPM", min=40, max=300, default=120, visible_when=("sync_mode", "free")),
        ]),
    ]

    cc_inputs = {74: "rate", 75: "gate"}
    cc_outputs = []

    inputs = ["Notes", "CC#74 (rate)", "CC#75 (gate)",
              "Notes in [Base, Base+15) when Trigger Note is on (sets Rate)",
              "Clock", "Aftertouch", "Pitch Bend"]
    outputs = ["Notes (arpeggiated)", "Aftertouch (pass-through)", "Pitch Bend (pass-through)"]

    clock_divisions = [
        "4/1", "4/1T", "2/1", "2/1T", "1/1", "1/1T",
        "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T",
        "1/16", "1/16T", "1/32",
    ]

    def on_start(self):
        self._held_notes = []
        self._sorted_notes = []
        self._arp_step = 0       # position in the arp note sequence
        self._seq_step = 0       # position in the step editor
        self._direction = 1
        self._playing_note = None
        self._lock = threading.Lock()
        self._free_thread = None
        self._free_running = False
        self._transport_playing = False

    def on_stop(self):
        self._free_running = False
        self._silence_all()

    def panic(self):
        with self._lock:
            self._free_running = False
            self._held_notes = []
            self._sorted_notes = []
            self._silence_all()

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

    def _rate_trigger_index(self, note: int) -> int | None:
        """Return rate-table index N if `note` is the Nth semitone of
        the rate-trigger range, else None. The trigger feature is
        opt-in via the Pattern group's "Trigger Note" toggle; when
        off, this always returns None and notes flow into the arp
        normally."""
        if not self.get_param("rate_trigger"):
            return None
        base = self.get_param("rate_base")
        if base is None:
            return None
        idx = note - int(base)
        if 0 <= idx < len(self._RATE_OPTIONS):
            return idx
        return None

    def on_note_on(self, channel, note, velocity):
        # Rate trigger notes are consumed: they set the Rate radio and
        # do NOT join the held-notes set, so the trigger range can't
        # be accidentally arpeggiated. set_param broadcasts the change
        # to the UI via SSE so the user sees the radio flip live.
        idx = self._rate_trigger_index(note)
        if idx is not None:
            self.set_param("rate", self._RATE_OPTIONS[idx])
            return
        with self._lock:
            self._held_notes.append((note, velocity, channel))
            self._sorted_notes = sorted(self._held_notes, key=lambda x: x[0])
            if len(self._held_notes) == 1:
                self._arp_step = 0
                self._seq_step = 0
                self._direction = 1
                mode = self.get_param("sync_mode") or "tempo"
                if mode == "free":
                    self._start_free_runner()

    def on_note_off(self, channel, note):
        # Symmetric: trigger-range note-offs are also consumed, so the
        # held-notes list never sees them at all.
        if self._rate_trigger_index(note) is not None:
            return
        with self._lock:
            self._held_notes = [(n, v, c) for n, v, c in self._held_notes if n != note]
            self._sorted_notes = sorted(self._held_notes, key=lambda x: x[0])
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

        rate = self.get_param("rate") or "1/8"
        if division != rate:
            return
        self._advance()

    def on_param_change(self, name, value):
        if name == "sync_mode":
            if value == "free":
                self._free_running = False
                if self._held_notes:
                    self._start_free_runner()
            else:
                self._free_running = False
                if value == "transport":
                    self._transport_playing = False

    def _start_free_runner(self):
        self._free_running = True
        def _run():
            while self._free_running:
                bpm = self.get_param("bpm") or 120
                rate = self.get_param("rate") or "1/8"
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
            if not self._sorted_notes:
                return

            pattern = self.get_param("pattern") or "up"
            octaves = self.get_param("octaves") or 1
            gate = (self.get_param("gate") or 80) / 100.0
            steps = self.get_param("steps") or []
            step_count = self.get_param("step_count") or 8

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
                self._playing_note = (ch, note)

            # Advance arp position
            if pattern == "up-down":
                self._arp_step += self._direction
            elif pattern != "random":
                self._arp_step += 1

    def _note_off_current(self):
        if self._playing_note:
            ch, note = self._playing_note
            self.send_note_off(ch, note)

    def _silence_all(self):
        """Cancel every pending scheduled note-off and immediately
        silence the currently-sounding note. Used by panic / transport-
        stop / no-keys-held — we need notes to stop NOW, not at their
        gate boundary."""
        self.cancel_scheduled(_ARP_TAG)
        self._note_off_current()
        self._playing_note = None

    def _rate_period_seconds(self) -> float:
        """Seconds per arp step at the current rate + sync mode. Used
        for gate timing. Returns 0 if neither the master clock nor a
        free-mode BPM is available."""
        rate = self.get_param("rate") or "1/8"
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
