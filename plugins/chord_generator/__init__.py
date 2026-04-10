"""Chord Generator — input note triggers a full chord."""

from raspimidihub.plugin_api import (
    PluginBase, Group, Radio, Wheel, ChannelSelect,
)

# Intervals in semitones from root
CHORD_INTERVALS = {
    "major":  [0, 4, 7],
    "minor":  [0, 3, 7],
    "7th":    [0, 4, 7, 10],
    "maj7":   [0, 4, 7, 11],
    "min7":   [0, 3, 7, 10],
    "sus2":   [0, 2, 7],
    "sus4":   [0, 5, 7],
    "dim":    [0, 3, 6],
    "aug":    [0, 4, 8],
    "power":  [0, 7],
    "octave": [0, 12],
}


class ChordGenerator(PluginBase):
    """Turns single notes into chords."""

    NAME = "Chord Generator"
    DESCRIPTION = "Input note triggers a full chord"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"

    params = [
        Group("Chord", [
            Radio("chord", "Type",
                  list(CHORD_INTERVALS.keys()), default="major"),
            Radio("inversion", "Inversion", ["root", "1st", "2nd"], default="root"),
        ]),
        Group("Output", [
            Wheel("vel_scale", "Added Note Vel %", min=10, max=100, default=90),
        ]),
    ]

    inputs = ["Notes"]
    outputs = ["Notes (chord)"]

    def on_start(self):
        self._active = {}  # root_note -> [notes_playing]

    def on_note_on(self, channel, note, velocity):
        chord_type = self.get_param("chord") or "major"
        inversion = self.get_param("inversion") or "root"
        vel_scale = (self.get_param("vel_scale") or 90) / 100.0

        intervals = list(CHORD_INTERVALS.get(chord_type, [0, 4, 7]))

        # Apply inversion
        if inversion == "1st" and len(intervals) >= 2:
            intervals[0] += 12
            intervals.sort()
        elif inversion == "2nd" and len(intervals) >= 3:
            intervals[0] += 12
            intervals[1] += 12
            intervals.sort()

        notes_playing = []
        for i, semi in enumerate(intervals):
            n = note + semi
            if 0 <= n <= 127:
                vel = velocity if i == 0 else max(1, int(velocity * vel_scale))
                self.send_note_on(channel, n, vel)
                notes_playing.append((channel, n))

        self._active[note] = notes_playing

    def on_note_off(self, channel, note):
        notes = self._active.pop(note, [])
        for ch, n in notes:
            self.send_note_off(ch, n)

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)
