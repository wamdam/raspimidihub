"""Note Transpose — shift all notes up or down by semitones."""

from raspimidihub.plugin_api import PluginBase, Wheel


class NoteTranspose(PluginBase):
    """Transposes all incoming notes by a configurable number of semitones."""

    NAME = "Note Transpose"
    DESCRIPTION = "Shift all notes up or down by semitones"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Shifts all incoming notes up or down by a fixed number of semitones.
All other MIDI messages pass through unchanged.

Example: Set semitones=12 to transpose a keyboard up one octave, or
set semitones=-7 to drop everything by a fifth."""

    params = [
        Wheel("semitones", "Semitones", min=-48, max=48, default=0),
    ]

    cc_inputs = {74: "semitones"}

    inputs = ["Notes", "CC#74 (transpose)", "All other events (pass-through)"]
    outputs = ["Notes (transposed)", "All other events (pass-through)"]

    def on_note_on(self, channel, note, velocity):
        n = note + (self.get_param("semitones") or 0)
        if 0 <= n <= 127:
            self.send_note_on(channel, n, velocity)

    def on_note_off(self, channel, note):
        n = note + (self.get_param("semitones") or 0)
        if 0 <= n <= 127:
            self.send_note_off(channel, n)

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)

    def on_program_change(self, channel, program):
        self.send_program_change(channel, program)
