"""Master Clock — generate MIDI clock with transport controls."""

from raspimidihub.clock_gen import ScheduledClockGenerator
from raspimidihub.plugin_api import Button, PluginBase, Wheel


class MasterClock(PluginBase):
    """Generates MIDI clock at a configurable BPM with transport controls."""

    NAME = "Master Clock"
    DESCRIPTION = "Generate MIDI clock from internal BPM"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.1"
    HELP = """\
Generates continuous MIDI clock (24 PPQ) at a configurable BPM.
Clock starts immediately when the plugin is created.

Press Play to send MIDI Start (resets beat position for synced
devices) and keep sending clock. Press again to send MIDI Stop.
Clock ticks continue regardless of transport state.

Wire the Master Clock OUT to any device or plugin that needs clock."""

    params = [
        Wheel("bpm", "BPM", min=20, max=300, default=120, default_cc=74),
        Button("play", "Play", default=False, color="green"),
    ]

    inputs = ["CC (long-press BPM to bind)"]
    outputs = ["MIDI Clock (24 PPQ), Start, Stop"]

    feeds_clock_bus = True  # pure generator — drives the global ClockBus

    # ALSA-queue scheduled tag for our pre-emitted clock burst.
    _CLOCK_TAG = 1

    def on_start(self):
        self._clock_gen = ScheduledClockGenerator(
            self, bpm_getter=lambda: self.get_param("bpm"),
            tag=self._CLOCK_TAG,
        )
        self._clock_gen.start()

    def on_stop(self):
        self._clock_gen.stop()

    def on_param_change(self, name, value):
        if name == "play":
            if value:
                self.send_start()
            else:
                self.send_stop()
        elif name == "bpm":
            self._clock_gen.reanchor()
