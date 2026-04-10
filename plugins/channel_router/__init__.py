"""Channel Router — remap MIDI channels."""

from raspimidihub.plugin_api import (
    PluginBase, Group, ChannelSelect, Radio,
)


class ChannelRouter(PluginBase):
    """Routes all input to a fixed output channel, or remaps channels."""

    NAME = "Channel Router"
    DESCRIPTION = "Route all MIDI to a specific channel"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"

    params = [
        Radio("mode", "Mode", ["fixed", "remap"], default="fixed"),
        Group("Fixed Output", [
            ChannelSelect("out_ch", "Output Channel", default=1),
        ]),
    ]

    inputs = ["All MIDI events"]
    outputs = ["All MIDI events (channel remapped)"]

    def _out_channel(self, in_channel):
        mode = self.get_param("mode") or "fixed"
        if mode == "fixed":
            return (self.get_param("out_ch") or 1) - 1
        return in_channel

    def on_note_on(self, channel, note, velocity):
        self.send_note_on(self._out_channel(channel), note, velocity)

    def on_note_off(self, channel, note):
        self.send_note_off(self._out_channel(channel), note)

    def on_cc(self, channel, cc, value):
        self.send_cc(self._out_channel(channel), cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(self._out_channel(channel), value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(self._out_channel(channel), value)

    def on_program_change(self, channel, program):
        self.send_program_change(self._out_channel(channel), program)
