"""Arpeggiator — plays held notes through a step pattern with note offsets."""

import random
import threading
import time

from raspimidihub.plugin_api import (
    PluginBase, Group, Radio, Wheel, Toggle, Fader, StepEditor,
)


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
Gate % = note length (100=legato, 10=staccato)."""

    params = [
        Group("Pattern", [
            Radio("pattern", "Pattern", ["up", "down", "up-down", "random", "as-played"],
                  default="up"),
            Radio("rate", "Rate",
                  ["4/1", "4/1T", "2/1", "2/1T", "1/1", "1/1T",
                   "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T",
                   "1/16", "1/16T", "1/32"],
                  default="1/8"),
        ]),
        Group("Steps", [
            Wheel("step_count", "Steps", min=1, max=32, default=8),
            Wheel("accent_vel", "Accent Vel.", min=0, max=127, default=30),
            StepEditor("steps", "Pattern", length_param="step_count",
                       default_length=8, default_on=True),
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

    inputs = ["Notes", "CC#74 (rate)", "CC#75 (gate)", "Clock", "Aftertouch", "Pitch Bend"]
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
        self._note_off_current()

    def panic(self):
        with self._lock:
            self._free_running = False
            self._held_notes = []
            self._sorted_notes = []
            self._note_off_current()

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
            self._note_off_current()

    def on_note_on(self, channel, note, velocity):
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
        with self._lock:
            self._held_notes = [(n, v, c) for n, v, c in self._held_notes if n != note]
            self._sorted_notes = sorted(self._held_notes, key=lambda x: x[0])
            if not self._held_notes:
                self._free_running = False
                self._note_off_current()

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
            gate_pct = (self.get_param("gate") or 80) / 100.0
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
            self._playing_note = None
