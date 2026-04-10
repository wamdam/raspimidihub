"""Scale Remapper — quantize notes to a musical scale."""

from raspimidihub.plugin_api import PluginBase, Group, Radio, Wheel

SCALES = {
    "chromatic": [0,1,2,3,4,5,6,7,8,9,10,11],
    "major":     [0,2,4,5,7,9,11],
    "minor":     [0,2,3,5,7,8,10],
    "dorian":    [0,2,3,5,7,9,10],
    "mixolydian":[0,2,4,5,7,9,10],
    "pentatonic":[0,2,4,7,9],
    "blues":     [0,3,5,6,7,10],
    "harmonic m":[0,2,3,5,7,8,11],
    "whole tone": [0,2,4,6,8,10],
}


class ScaleRemapper(PluginBase):
    """Quantizes incoming notes to the nearest note in a selected scale."""

    NAME = "Scale Remapper"
    DESCRIPTION = "Quantize notes to a musical scale"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Quantizes every note to the nearest note in a chosen musical scale.
Play any key and only in-scale notes come out -- no wrong notes.

Example: Set scale=pentatonic, root=C. Now any key you press snaps
to C-D-E-G-A. Great for jamming, live performance, or making a
grid controller always sound musical."""

    params = [
        Radio("scale", "Scale", list(SCALES.keys()), default="major"),
        Wheel("root", "Root Note", min=0, max=11, default=0),
    ]

    inputs = ["Notes"]
    outputs = ["Notes (quantized to scale)"]

    def on_start(self):
        self._build_map()

    def on_param_change(self, name, value):
        self._build_map()

    def _build_map(self):
        """Build a 128-entry lookup table: input note -> nearest scale note."""
        scale_name = self.get_param("scale") or "major"
        root = self.get_param("root") or 0
        intervals = SCALES.get(scale_name, SCALES["major"])
        # Build set of all valid MIDI notes in this scale
        valid = set()
        for octave in range(-1, 12):
            for interval in intervals:
                n = root + octave * 12 + interval
                if 0 <= n <= 127:
                    valid.add(n)
        # For each note 0-127, find the closest valid note
        self._map = [0] * 128
        for n in range(128):
            if n in valid:
                self._map[n] = n
            else:
                # Search outward
                for d in range(1, 128):
                    if n - d >= 0 and n - d in valid:
                        self._map[n] = n - d
                        break
                    if n + d <= 127 and n + d in valid:
                        self._map[n] = n + d
                        break

    def on_note_on(self, channel, note, velocity):
        self.send_note_on(channel, self._map[note], velocity)

    def on_note_off(self, channel, note):
        self.send_note_off(channel, self._map[note])

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)
