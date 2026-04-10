"""Example pass-through plugin — forwards all MIDI from IN to OUT.

This is the minimal plugin template. It demonstrates the basic structure
that every plugin follows. Use it as a starting point for new plugins.
"""

from raspimidihub.plugin_api import PluginBase


class PassThrough(PluginBase):
    """Passes all MIDI events through unchanged."""

    NAME = "Pass-Through"
    DESCRIPTION = "Forwards all MIDI from IN to OUT unchanged"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"

    params = []

    inputs = ["All MIDI events"]
    outputs = ["All MIDI events (unchanged)"]

    def on_note_on(self, channel, note, velocity):
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
