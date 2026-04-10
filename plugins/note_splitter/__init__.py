"""Note Splitter — split keyboard at a note, route to two channels."""

from raspimidihub.plugin_api import (
    PluginBase, Group, NoteSelect, ChannelSelect, Toggle, Wheel,
)


class NoteSplitter(PluginBase):
    """Splits keyboard at a configurable note into two output channels."""

    NAME = "Note Splitter"
    DESCRIPTION = "Split keyboard at a note into two channels"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Splits a keyboard at a chosen note, sending lower notes to one MIDI
channel and upper notes to another. Lets you play two sounds from
a single keyboard.

Each zone has its own channel and transpose (+-48 semitones).
Example: Split at C4, lower ch1 transpose -12 (bass octave down),
upper ch2 transpose 0 (piano). Left hand plays bass, right plays piano."""

    params = [
        NoteSelect("split_point", "Split Point", default=60),
        Group("Lower Zone", [
            ChannelSelect("lower_ch", "Channel", default=1),
            Wheel("lower_transpose", "Transpose", min=-48, max=48, default=0),
        ]),
        Group("Upper Zone", [
            ChannelSelect("upper_ch", "Channel", default=2),
            Wheel("upper_transpose", "Transpose", min=-48, max=48, default=0),
        ]),
    ]

    cc_inputs = {74: "split_point"}

    inputs = ["Notes", "CC#74 (split point)"]
    outputs = ["Notes (lower → ch A, upper → ch B)"]

    def _route(self, note):
        """Returns list of (channel, transposed_note) for this note."""
        split = self.get_param("split_point") or 60
        lower_ch = (self.get_param("lower_ch") or 1) - 1
        upper_ch = (self.get_param("upper_ch") or 2) - 1
        lower_t = self.get_param("lower_transpose") or 0
        upper_t = self.get_param("upper_transpose") or 0

        result = []
        if note < split:
            n = note + lower_t
            if 0 <= n <= 127:
                result.append((lower_ch, n))
        else:
            n = note + upper_t
            if 0 <= n <= 127:
                result.append((upper_ch, n))
        return result

    def on_note_on(self, channel, note, velocity):
        for ch, n in self._route(note):
            self.send_note_on(ch, n, velocity)

    def on_note_off(self, channel, note):
        for ch, n in self._route(note):
            self.send_note_off(ch, n)

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)
