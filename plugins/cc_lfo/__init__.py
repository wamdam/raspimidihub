"""CC LFO — generate CC waveforms (sine, triangle, square, saw, S&H)."""

import math
import random

from raspimidihub.plugin_api import (
    PluginBase, Group, Radio, Wheel, Fader, Toggle, ChannelSelect,
)


class CcLfo(PluginBase):
    """Generates a CC LFO waveform on a configurable CC number and channel."""

    NAME = "CC LFO"
    DESCRIPTION = "Generate CC waveforms (sine, triangle, square, saw, S&H)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"

    params = [
        Group("Waveform", [
            Radio("wave", "Wave", ["sine", "triangle", "square", "saw", "s&h"], default="sine"),
        ]),
        Group("Timing", [
            Toggle("sync", "Sync to Clock", default=False),
            Radio("rate", "Rate", ["1/1", "1/2", "1/4", "1/8", "1/16"], default="1/4",
                  visible_when=("sync", True)),
            Wheel("freq_hz", "Freq (Hz x10)", min=1, max=100, default=5,
                  visible_when=("sync", False)),
        ]),
        Group("Output", [
            Wheel("cc_num", "CC #", min=0, max=127, default=1),
            ChannelSelect("out_ch", "Channel", default=1),
            Fader("depth", "Depth", min=0, max=127, default=127),
            Fader("center", "Center", min=0, max=127, default=64),
        ]),
    ]

    cc_inputs = {74: "freq_hz", 75: "depth"}
    cc_outputs = [1]

    inputs = ["CC#74 (frequency)", "CC#75 (depth)", "Clock"]
    outputs = ["CC (configurable #)"]

    clock_divisions = ["1/1", "1/2", "1/4", "1/8", "1/16"]

    def on_start(self):
        self._phase = 0.0
        self._tick_count = 0
        self._last_value = -1
        self._sh_value = 64
        self._free_running = True
        self._free_thread = None
        self._start_free_runner()

    def on_stop(self):
        self._free_running = False

    def on_param_change(self, name, value):
        if name == "sync":
            if value:
                self._free_running = False
            else:
                self._start_free_runner()

    def _start_free_runner(self):
        """Run LFO in free mode using a thread-based timer."""
        import threading

        self._free_running = True

        def _run():
            while self._free_running and self.get_param("sync") is False:
                freq_x10 = self.get_param("freq_hz") or 5
                freq = freq_x10 / 10.0
                interval = 1.0 / max(freq * 32, 1)  # 32 steps per cycle
                self._phase += 1.0 / 32.0
                if self._phase >= 1.0:
                    self._phase -= 1.0
                self._emit_lfo()
                import time
                time.sleep(interval)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def on_tick(self, division):
        if not self.get_param("sync"):
            return
        rate = self.get_param("rate") or "1/4"
        if division != rate:
            return
        self._tick_count += 1
        self._phase = (self._tick_count % 32) / 32.0
        self._emit_lfo()

    def _emit_lfo(self):
        wave = self.get_param("wave") or "sine"
        depth = self.get_param("depth") or 127
        center = self.get_param("center") or 64
        cc_num = self.get_param("cc_num")
        if cc_num is None:
            cc_num = 1
        out_ch = (self.get_param("out_ch") or 1) - 1
        phase = self._phase

        # Generate waveform value (-1 to 1)
        if wave == "sine":
            raw = math.sin(phase * 2 * math.pi)
        elif wave == "triangle":
            raw = 1 - 4 * abs(phase - 0.5)
        elif wave == "square":
            raw = 1.0 if phase < 0.5 else -1.0
        elif wave == "saw":
            raw = 2 * phase - 1
        elif wave == "s&h":
            if phase < 0.03:  # new random at start of each cycle
                self._sh_value = random.randint(0, 127)
            value = max(0, min(127, self._sh_value))
            if value != self._last_value:
                self._last_value = value
                self.send_cc(out_ch, cc_num, value)
            return
        else:
            raw = 0

        # Scale to MIDI range
        half_depth = depth / 2.0
        value = int(center + raw * half_depth)
        value = max(0, min(127, value))

        if value != self._last_value:
            self._last_value = value
            self.send_cc(out_ch, cc_num, value)
