"""Monitor/Logger — logs all incoming MIDI for debugging."""

from raspimidihub.plugin_api import PluginBase

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(n):
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 2}"


class Monitor(PluginBase):
    """Logs all incoming MIDI events for debugging."""

    NAME = "Monitor"
    DESCRIPTION = "View all incoming MIDI events in the config panel"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Displays all incoming MIDI events in a scrolling log. Does not modify
or forward any data -- purely a debugging and inspection tool.

Example: Plug in a controller and open Monitor to verify which channel,
CC numbers, and note values it actually sends. Invaluable when setting
up a new device or diagnosing why a connection is not working."""

    params = []

    inputs = ["All MIDI events"]
    outputs = []

    def on_start(self):
        self._log = []  # list of event strings, newest first
        self._max_log = 50

    def _add_log(self, msg):
        self._log.insert(0, msg)
        if len(self._log) > self._max_log:
            self._log.pop()
        # Notify UI via param change callback
        if self._notify_param_change:
            self._notify_param_change(None, "_log", self._log)

    def on_note_on(self, channel, note, velocity):
        self._add_log(f"Note On  ch{channel+1:2d} {note_name(note):4s} vel={velocity}")

    def on_note_off(self, channel, note):
        self._add_log(f"Note Off ch{channel+1:2d} {note_name(note):4s}")

    def on_cc(self, channel, cc, value):
        self._add_log(f"CC       ch{channel+1:2d} #{cc:3d} val={value}")

    def on_pitchbend(self, channel, value):
        self._add_log(f"PitchB   ch{channel+1:2d} val={value}")

    def on_aftertouch(self, channel, value):
        self._add_log(f"ATouch   ch{channel+1:2d} val={value}")

    def on_program_change(self, channel, program):
        self._add_log(f"PgmChg   ch{channel+1:2d} #{program}")
