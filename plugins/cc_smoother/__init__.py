"""CC Smoother — smooths incoming CC values to remove jitter."""

import threading
import time

from raspimidihub.plugin_api import (
    PluginBase, Group, Wheel, Fader, Display,
)


class CcSmoother(PluginBase):
    """Smooths CC values to remove jitter from noisy controllers."""

    NAME = "CC Smoother"
    DESCRIPTION = "Smooth incoming CC values to remove jitter"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Smooths incoming CC values to remove jitter from noisy knobs and faders.
Applies a low-pass filter so jumpy values glide to their target.

Example: A cheap MIDI controller sends CC#7 (volume) values that jitter
between 95-100. The smoother outputs a steady stream instead of audible
zipper noise. Essential for older or budget controllers."""

    params = [
        Group("Settings", [
            Wheel("cc_in", "Input CC #", min=0, max=127, default=1),
            Wheel("cc_out", "Output CC #", min=0, max=127, default=1),
            Fader("smoothing", "Smoothing", min=1, max=50, default=10),
            Display("_in_scope", "Input", display_name="input"),
            Display("_out_scope", "Output", display_name="output"),
        ]),
    ]

    display_outputs = [
        {"name": "input", "type": "scope", "label": "Input", "min": 0, "max": 127, "duration": 2},
        {"name": "output", "type": "scope", "label": "Output", "min": 0, "max": 127, "duration": 2},
    ]

    inputs = ["CC (configurable #)"]
    outputs = ["CC (smoothed)"]

    def on_start(self):
        self._current = {}  # channel -> current smoothed value (float)
        self._target = {}   # channel -> target value
        self._running = True
        self._thread = threading.Thread(target=self._smooth_loop, daemon=True)
        self._thread.start()

    def on_stop(self):
        self._running = False

    def on_cc(self, channel, cc, value):
        cc_in = self.get_param("cc_in")
        if cc_in is None:
            cc_in = 1
        if cc != cc_in:
            # Pass through non-target CCs
            self.send_cc(channel, cc, value)
            return
        self._target[channel] = value
        self.set_display("input", value)
        if channel not in self._current:
            self._current[channel] = float(value)

    def on_note_on(self, channel, note, velocity):
        self.send_note_on(channel, note, velocity)

    def on_note_off(self, channel, note):
        self.send_note_off(channel, note)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def _smooth_loop(self):
        while self._running:
            smoothing = (self.get_param("smoothing") or 10) / 100.0
            alpha = max(0.02, min(1.0, 1.0 - smoothing))
            cc_out = self.get_param("cc_out")
            if cc_out is None:
                cc_out = 1

            for channel in list(self._target.keys()):
                target = self._target[channel]
                current = self._current.get(channel, float(target))
                new_val = current + alpha * (target - current)
                self._current[channel] = new_val

                rounded = int(round(new_val))
                rounded = max(0, min(127, rounded))
                self.send_cc(channel, cc_out, rounded)
                self.set_display("output", rounded)

            time.sleep(0.01)  # 100 Hz update rate
