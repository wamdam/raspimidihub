"""Velocity Curve — remap note velocity through a drawable curve."""

from raspimidihub import midi_scale
from raspimidihub.plugin_api import CurveEditor, PluginBase


class VelocityCurve(PluginBase):
    """Remaps note velocity using a custom curve."""

    NAME = "Velocity Curve"
    DESCRIPTION = "Remap velocity response with a drawable curve"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Remaps note velocity through a drawable curve. Shape the dynamic
response of any keyboard to match your playing style or target synth.

Example: Draw a steep curve at the low end to make a stiff keyboard
feel more responsive to soft playing, or flatten the top to prevent
accidental loud notes on a sensitive controller."""

    params = [
        CurveEditor("curve", "Velocity Curve"),
    ]

    inputs = ["Notes", "All other events (pass-through)"]
    outputs = ["Notes (velocity remapped)", "All other events (pass-through)"]

    # Float MIDI-unit velocity in (7-bit sources deliver exact ints),
    # so hi-res keyboards keep their fine gradations through the curve.
    wants_hires_input = True

    def on_note_on(self, channel, note, velocity):
        curve = self.get_param("curve")
        if curve and 0 <= velocity <= 127:
            # Evaluate the 128-point curve with linear interpolation
            # between points for fractional velocity; integer velocity
            # hits curve[v] exactly (legacy behaviour). Emit positioned
            # in the legacy result's bucket: MIDI 1.0 receivers stay
            # byte-identical, 2.0 receivers keep the fine trajectory.
            i = int(velocity)
            frac = velocity - i
            lo = curve[i]
            hi = curve[min(i + 1, 127)]
            out = max(1.0, min(127.0, lo + frac * (hi - lo)))
            anchor = max(1, min(127, curve[i] if frac == 0
                                else int(round(out))))
            velocity = midi_scale.units_in_bucket(anchor, out)
        self.send_note_on(channel, note, velocity)

    def on_note_off(self, channel, note):
        self.send_note_off(channel, note)

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)

    def on_program_change(self, channel, program):
        self.send_program_change(channel, program)
