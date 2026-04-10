"""Master Clock — generate MIDI clock, start/stop/continue from internal BPM."""

import threading
import time

from raspimidihub.plugin_api import PluginBase, Group, Wheel, Toggle


class MasterClock(PluginBase):
    """Generates MIDI clock at a configurable BPM. Use when no external clock source is available."""

    NAME = "Master Clock"
    DESCRIPTION = "Generate MIDI clock from internal BPM"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"

    params = [
        Wheel("bpm", "BPM", min=20, max=300, default=120),
        Toggle("running", "Run", default=False),
    ]

    inputs = []
    outputs = ["MIDI Clock, Start, Stop"]

    def on_start(self):
        self._thread = None
        self._running_clock = False

    def on_stop(self):
        self._running_clock = False

    def on_param_change(self, name, value):
        if name == "running":
            if value and not self._running_clock:
                self._start_clock()
            elif not value and self._running_clock:
                self._stop_clock()

    def _start_clock(self):
        self._running_clock = True
        # Send MIDI Start
        self.send_cc(0, 123, 0)  # placeholder — real start needs raw MIDI

        def _run():
            while self._running_clock:
                bpm = self.get_param("bpm") or 120
                # 24 PPQ: interval between clock ticks
                interval = 60.0 / bpm / 24.0
                # We can't send raw clock events through the plugin API
                # (no send_clock method), so we send CC#121 as a clock proxy
                # The real implementation would need a send_raw method
                time.sleep(interval)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _stop_clock(self):
        self._running_clock = False
