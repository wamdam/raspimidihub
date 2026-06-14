"""Scale Remapper — quantize notes to a musical scale."""

from raspimidihub.plugin_api import PluginBase, Radio, Wheel
from raspimidihub.scales import SCALES, build_nearest_map


class ScaleRemapper(PluginBase):
    """Quantizes incoming notes to the nearest note in a selected scale."""

    NAME = "Scale Remapper"
    DESCRIPTION = "Quantize notes to a musical scale"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Quantizes every note to the nearest note in a chosen musical scale.
Play any key and only in-scale notes come out -- no wrong notes.
Root Note is 0-11 where 0=C, 1=C#, 2=D, 3=D#, 4=E, 5=F, 6=F#,
7=G, 8=G#, 9=A, 10=A#, 11=B.
Example: Set scale=pentatonic, root=0 (C). Now any key you press
snaps to C-D-E-G-A. Great for jamming, live performance, or making
a grid controller always sound musical."""

    params = [
        # Root before Scale so it reads "D minor", not "minor D".
        Wheel("root", "Root", min=0, max=11, default=0,
              labels=["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"],
              default_cc=74),
        Radio("scale", "Scale", list(SCALES.keys()), default="major"),
    ]

    inputs = ["Notes", "CC (long-press Root to bind)"]
    outputs = ["Notes (quantized to scale)"]

    def on_start(self):
        self._build_map()

    def on_param_change(self, name, value):
        self._build_map()

    def _build_map(self):
        """Build a 128-entry lookup table: input note -> nearest scale note."""
        scale_name = self.get_param("scale") or "major"
        root = self.get_param("root") or 0
        self._map = build_nearest_map(scale_name, root)

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
