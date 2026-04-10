"""Velocity Curve — remap note velocity through a drawable curve."""

from raspimidihub.plugin_api import PluginBase, CurveEditor


class VelocityCurve(PluginBase):
    """Remaps note velocity using a custom curve."""

    NAME = "Velocity Curve"
    DESCRIPTION = "Remap velocity response with a drawable curve"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"

    params = [
        CurveEditor("curve", "Velocity Curve"),
    ]

    inputs = ["Notes", "All other events (pass-through)"]
    outputs = ["Notes (velocity remapped)", "All other events (pass-through)"]

    def on_note_on(self, channel, note, velocity):
        curve = self.get_param("curve")
        if curve and 0 <= velocity <= 127:
            velocity = max(1, min(127, curve[velocity]))
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
