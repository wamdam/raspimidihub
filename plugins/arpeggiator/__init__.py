"""Arpeggiator — plays held notes as a pattern synced to clock or free BPM."""

import random
import threading
import time

from raspimidihub.plugin_api import (
    PluginBase, Group, Radio, Wheel, Toggle, Fader, Display, Param,
)


class Arpeggiator(PluginBase):
    """Plays held notes back as a rhythmic pattern."""

    NAME = "Arpeggiator"
    DESCRIPTION = "Plays held notes as a pattern (up, down, up-down, random)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Turns held notes into a rhythmic pattern, cycling through them in order.

Sync modes:
  Free = internal BPM, ignores external clock
  Tempo = syncs speed to external clock but runs continuously
  Transport = syncs to clock AND resets on Start/Stop

Gate % = how long each note sounds (100=legato, 10=staccato).
As-played pattern cycles notes in the order you pressed them.

Example: Hold a C minor chord and the arpeggiator plays C-Eb-G
in tempo. Set Transport mode for tight sync with a drum machine."""

    params = [
        Group("Pattern", [
            Radio("pattern", "Pattern", ["up", "down", "up-down", "random", "as-played"],
                  default="up"),
            Radio("rate", "Rate", ["1/4", "1/8", "1/16", "1/32", "1/8T"], default="1/8"),
        ]),
        Group("Controls", [
            Wheel("gate", "Gate %", min=10, max=100, default=80),
            Wheel("octaves", "Octaves", min=1, max=4, default=1),
            Radio("sync_mode", "Sync", ["free", "tempo", "transport"], default="tempo"),
            Wheel("bpm", "BPM", min=40, max=300, default=120, visible_when=("sync_mode", "free")),
            Display("_beat", "Beat", display_name="beat"),
        ]),
    ]

    display_outputs = [
        {"name": "beat", "type": "meter", "label": "Beat", "min": 0, "max": 3},
    ]

    cc_inputs = {74: "rate", 75: "gate"}
    cc_outputs = []

    inputs = ["Notes", "CC#74 (rate)", "CC#75 (gate)", "Clock", "Aftertouch", "Pitch Bend"]
    outputs = ["Notes (arpeggiated)", "Aftertouch (pass-through)", "Pitch Bend (pass-through)"]

    clock_divisions = ["1/4", "1/8", "1/16", "1/32", "1/4T", "1/8T", "1/16T"]

    def on_start(self):
        self._held_notes = []
        self._sorted_notes = []
        self._step = 0
        self._direction = 1
        self._playing_note = None
        self._lock = threading.Lock()
        self._free_thread = None
        self._free_running = False
        self._transport_playing = False  # transport mode: waiting for Start
        self._beat_count = 0

    def on_stop(self):
        self._free_running = False
        self._note_off_current()

    def on_transport_start(self):
        """MIDI Start received — reset if in transport mode."""
        mode = self.get_param("sync_mode") or "tempo"
        if mode == "transport":
            self._step = 0
            self._direction = 1
            self._note_off_current()
            self._transport_playing = True
            self._beat_count = 0
            self.set_display("beat", 0)

    def on_transport_stop(self):
        """MIDI Stop received — stop if in transport mode."""
        mode = self.get_param("sync_mode") or "tempo"
        if mode == "transport":
            self._transport_playing = False
            self._note_off_current()

    def on_note_on(self, channel, note, velocity):
        with self._lock:
            self._held_notes.append((note, velocity, channel))
            self._sorted_notes = sorted(self._held_notes, key=lambda x: x[0])
            if len(self._held_notes) == 1:
                self._step = 0
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

        # Transport mode: auto-start on first tick if no Start was received
        # (sequencer might already be playing when plugin is created)
        if mode == "transport" and not self._transport_playing:
            self._transport_playing = True
            self._step = 0
            self._direction = 1
            self._beat_count = 0

        rate = self.get_param("rate") or "1/8"
        if division != rate:
            # Track beats for indicator (count 1/4 ticks)
            if division == "1/4":
                self._beat_count = (self._beat_count + 1) % 4
                self.set_display("beat", self._beat_count)
            return

        self._advance_step()

    def on_param_change(self, name, value):
        if name == "sync_mode":
            if value == "free":
                self._free_running = False  # stop old free runner
                if self._held_notes:
                    self._start_free_runner()
            else:
                self._free_running = False
                if value == "transport":
                    self._transport_playing = False  # wait for Start

    def _start_free_runner(self):
        self._free_running = True

        def _run():
            while self._free_running:
                bpm = self.get_param("bpm") or 120
                rate = self.get_param("rate") or "1/8"
                beats_per_sec = bpm / 60.0
                rate_map = {
                    "1/4": 1, "1/8": 0.5, "1/16": 0.25, "1/32": 0.125,
                    "1/8T": 1/3,
                }
                interval = rate_map.get(rate, 0.5) / beats_per_sec
                self._advance_step()
                time.sleep(interval)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _advance_step(self):
        with self._lock:
            if not self._sorted_notes:
                return

            pattern = self.get_param("pattern") or "up"
            octaves = self.get_param("octaves") or 1
            gate_pct = (self.get_param("gate") or 80) / 100.0

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
            elif pattern == "random":
                idx = random.randint(0, len(notes) - 1)
                note, vel, ch = notes[idx]
                self._play_note(ch, note, vel, gate_pct)
                return
            elif pattern == "up-down":
                if len(notes) <= 1:
                    pass
                else:
                    if self._step >= len(notes):
                        self._direction = -1
                        self._step = len(notes) - 2
                    elif self._step < 0:
                        self._direction = 1
                        self._step = 1

            idx = self._step % len(notes)
            note, vel, ch = notes[idx]

            self._play_note(ch, note, vel, gate_pct)

            if pattern == "up-down":
                self._step += self._direction
            else:
                self._step += 1

    def _play_note(self, channel, note, velocity, gate_pct):
        self._note_off_current()
        if note < 0 or note > 127:
            return
        self.send_note_on(channel, note, velocity)
        self._playing_note = (channel, note)

    def _note_off_current(self):
        if self._playing_note:
            ch, note = self._playing_note
            self.send_note_off(ch, note)
            self._playing_note = None
