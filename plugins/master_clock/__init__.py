"""Master Clock — generate MIDI clock with transport controls."""

import threading
import time

from raspimidihub.plugin_api import PluginBase, Group, Wheel, Toggle, Display


class MasterClock(PluginBase):
    """Generates MIDI clock at a configurable BPM with transport controls."""

    NAME = "Master Clock"
    DESCRIPTION = "Generate MIDI clock from internal BPM"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Generates MIDI clock (24 PPQ) at a configurable BPM with Start, Stop,
and Pause transport controls. Use when no external clock source (DAW,
drum machine) is available but plugins or devices need tempo sync.

Wire the Master Clock OUT to any device or plugin that needs clock.
Start sends MIDI Start + clock ticks. Stop sends MIDI Stop. Pause
stops ticks but doesn't send MIDI Stop (transport stays at position)."""

    params = [
        Wheel("bpm", "BPM", min=20, max=300, default=120),
        Toggle("start", "Start", default=False),
        Toggle("pause", "Pause", default=False, visible_when=("start", True)),
    ]

    display_outputs = [
        {"name": "beat", "type": "meter", "label": "Beat", "min": 0, "max": 3},
    ]

    inputs = []
    outputs = ["MIDI Clock (24 PPQ), Start, Stop"]

    def on_start(self):
        self._running = False
        self._paused = False
        self._thread = None
        self._tick_count = 0

    def on_stop(self):
        self._running = False

    def on_param_change(self, name, value):
        if name == "start":
            if value:
                self._start_clock()
            else:
                self._stop_clock()
        elif name == "pause":
            self._paused = value

    def _start_clock(self):
        if self._running:
            return
        self._running = True
        self._paused = False
        self._tick_count = 0
        self.send_start()

        def _run():
            while self._running:
                if self._paused:
                    time.sleep(0.01)
                    continue
                bpm = self.get_param("bpm") or 120
                interval = 60.0 / bpm / 24.0  # 24 PPQ
                self.send_clock()
                self._tick_count += 1
                # Beat indicator: 24 ticks per beat, cycle 0-3
                beat = (self._tick_count // 24) % 4
                if self._tick_count % 24 == 0:
                    self.set_display("beat", beat)
                time.sleep(interval)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _stop_clock(self):
        self._running = False
        self.send_stop()
        self._tick_count = 0
        self.set_display("beat", 0)
        self._param_values["pause"] = False
