"""Note Splitter — split keyboard at a note, route to two channels."""

from raspimidihub.plugin_api import (
    PluginBase, Group, NoteSelect, ChannelSelect, Toggle,
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

Example: Set split point to C4, lower to channel 1 (bass), upper to
channel 2 (piano). Left hand plays bass, right hand plays piano."""

    params = [
        NoteSelect("split_point", "Split Point", default=60),
        Group("Lower Zone", [
            ChannelSelect("lower_ch", "Channel", default=1),
        ]),
        Group("Upper Zone", [
            ChannelSelect("upper_ch", "Channel", default=2),
        ]),
        Toggle("overlap", "Split note to both", default=False),
    ]

    cc_inputs = {74: "split_point"}

    inputs = ["Notes", "CC#74 (split point)"]
    outputs = ["Notes (lower → ch A, upper → ch B)"]

    def on_note_on(self, channel, note, velocity):
        split = self.get_param("split_point") or 60
        lower_ch = (self.get_param("lower_ch") or 1) - 1
        upper_ch = (self.get_param("upper_ch") or 2) - 1
        overlap = self.get_param("overlap")

        if note < split:
            self.send_note_on(lower_ch, note, velocity)
        elif note > split:
            self.send_note_on(upper_ch, note, velocity)
        else:
            # At split point
            if overlap:
                self.send_note_on(lower_ch, note, velocity)
                self.send_note_on(upper_ch, note, velocity)
            else:
                self.send_note_on(upper_ch, note, velocity)

    def on_note_off(self, channel, note):
        split = self.get_param("split_point") or 60
        lower_ch = (self.get_param("lower_ch") or 1) - 1
        upper_ch = (self.get_param("upper_ch") or 2) - 1
        overlap = self.get_param("overlap")

        if note < split:
            self.send_note_off(lower_ch, note)
        elif note > split:
            self.send_note_off(upper_ch, note)
        else:
            if overlap:
                self.send_note_off(lower_ch, note)
                self.send_note_off(upper_ch, note)
            else:
                self.send_note_off(upper_ch, note)

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)
