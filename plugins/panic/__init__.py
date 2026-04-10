"""Panic Button — sends All Notes Off + All Sound Off on all channels."""

from raspimidihub.plugin_api import (
    PluginBase, Toggle, Wheel,
)

# CC numbers for panic messages
ALL_SOUND_OFF = 120
ALL_NOTES_OFF = 123


class Panic(PluginBase):
    """Sends All Notes Off and All Sound Off on all 16 channels."""

    NAME = "Panic Button"
    DESCRIPTION = "Send All Notes Off + All Sound Off on all channels"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Sends All Notes Off and All Sound Off on all 16 MIDI channels. Kills
stuck notes instantly. Can be triggered from the UI or via a CC.

Example: A stuck note is droning on your synth. Hit the Panic toggle
or send CC#64 value 127 from a foot switch to silence everything.
Keep this wired to your output as a safety net."""

    params = [
        Toggle("trigger", "Panic!", default=False),
        Wheel("trigger_cc", "Trigger CC #", min=0, max=127, default=64),
    ]

    cc_inputs = {64: "trigger"}

    inputs = ["CC#64 (trigger)"]
    outputs = ["All Notes Off + All Sound Off on all channels"]

    def on_param_change(self, name, value):
        if name == "trigger" and value:
            self._send_panic()
            # Reset toggle
            self._param_values["trigger"] = False

    def on_cc(self, channel, cc, value):
        trigger_cc = self.get_param("trigger_cc")
        if trigger_cc is not None and cc == trigger_cc and value >= 64:
            self._send_panic()

    def _send_panic(self):
        for ch in range(16):
            self.send_cc(ch, ALL_SOUND_OFF, 0)
            self.send_cc(ch, ALL_NOTES_OFF, 0)
