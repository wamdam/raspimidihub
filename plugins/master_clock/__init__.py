"""Master Clock — generate MIDI clock with transport controls."""

import threading
import time

from raspimidihub.plugin_api import PluginBase, Wheel, Button


class MasterClock(PluginBase):
    """Generates MIDI clock at a configurable BPM with transport controls."""

    NAME = "Master Clock"
    DESCRIPTION = "Generate MIDI clock from internal BPM"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Generates continuous MIDI clock (24 PPQ) at a configurable BPM.
Clock starts immediately when the plugin is created.

Press Play to send MIDI Start (resets beat position for synced
devices) and keep sending clock. Press again to send MIDI Stop.
Clock ticks continue regardless of transport state.

Wire the Master Clock OUT to any device or plugin that needs clock."""

    params = [
        Wheel("bpm", "BPM", min=20, max=300, default=120),
        Button("play", "Play", default=False, color="green"),
    ]

    inputs = []
    outputs = ["MIDI Clock (24 PPQ), Start, Stop"]

    def on_start(self):
        self._running = True
        self._thread = threading.Thread(target=self._clock_loop, daemon=True)
        self._thread.start()

    def on_stop(self):
        self._running = False

    def on_param_change(self, name, value):
        if name == "play":
            if value:
                self.send_start()
            else:
                self.send_stop()

    def _clock_loop(self):
        while self._running:
            bpm = self.get_param("bpm") or 120
            interval = 60.0 / bpm / 24.0
            self.send_clock()
            time.sleep(interval)
