"""CC LFO — generate CC waveforms (sine, triangle, square, saw, S&H)."""

import math
import random
import threading
import time

from raspimidihub.plugin_api import (
    PluginBase, Group, Radio, Wheel, Fader, Toggle, ChannelSelect, Display,
)


class CcLfo(PluginBase):
    """Generates a CC LFO waveform on a configurable CC number and channel."""

    NAME = "CC LFO"
    DESCRIPTION = "Generate CC waveforms (sine, triangle, square, saw, S&H)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Generates an automatic CC waveform (sine, triangle, square, saw, or
sample-and-hold) on any CC number. Runs free or synced to MIDI clock.

Example: Set wave=sine, CC#1 (mod wheel), 0.5 Hz to add a slow vibrato
to a synth pad without touching a physical controller."""

    params = [
        Group("Waveform", [
            Radio("wave", "Wave", ["sine", "triangle", "square", "saw", "s&h"], default="sine"),
        ]),
        Group("Timing", [
            Toggle("sync", "Sync to Clock", default=False),
            Radio("rate", "Rate", ["1/1", "1/2", "1/4", "1/8", "1/16"], default="1/4",
                  visible_when=("sync", True)),
            Fader("freq", "Frequency", min=1, max=200, default=5,
                  display_factor=0.1, display_format=" Hz",
                  visible_when=("sync", False)),
        ]),
        Group("Output", [
            Wheel("cc_num", "CC #", min=0, max=127, default=1),
            ChannelSelect("out_ch", "Channel", default=1),
            Display("_scope", "Scope", display_name="level"),
            Fader("depth", "Depth", min=0, max=127, default=127),
            Fader("center", "Center", min=0, max=127, default=64),
        ]),
    ]

    cc_inputs = {74: "freq", 75: "depth"}
    cc_outputs = [1]

    inputs = ["CC#74 (frequency)", "CC#75 (depth)", "Clock"]
    outputs = ["CC (configurable #)"]

    display_outputs = [
        {"name": "level", "type": "scope", "label": "Output", "min": 0, "max": 127, "duration": 2},
    ]

    # Subscribe to all divisions — we use the finest (1/16) for smooth synced LFO
    clock_divisions = ["1/16"]

    # Ticks per cycle for each synced rate (at 1/16 resolution):
    # 1/1 = 16 sixteenths, 1/2 = 8, 1/4 = 4, 1/8 = 2, 1/16 = 1
    _RATE_TICKS = {"1/1": 16, "1/2": 8, "1/4": 4, "1/8": 2, "1/16": 1}

    def on_start(self):
        self._phase = 0.0
        self._last_value = -1
        self._sh_value = 64
        self._free_running = False
        self._thread = None
        if not self.get_param("sync"):
            self._start_free_runner()

    def on_stop(self):
        self._free_running = False

    def on_param_change(self, name, value):
        if name == "sync":
            if value:
                self._free_running = False
                self._phase = 0.0
            else:
                self._start_free_runner()

    def _start_free_runner(self):
        if self._free_running:
            return
        self._free_running = True

        def _run():
            while self._free_running:
                freq_raw = self.get_param("freq") or 5
                freq = freq_raw * 0.1  # convert to Hz
                steps = 64  # resolution per cycle
                interval = 1.0 / max(freq * steps, 1)
                self._phase += 1.0 / steps
                if self._phase >= 1.0:
                    self._phase -= 1.0
                self._emit_lfo()
                time.sleep(interval)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def on_tick(self, division):
        if not self.get_param("sync"):
            return
        # Each 1/16 tick advances the phase by 1/ticks_per_cycle
        rate = self.get_param("rate") or "1/4"
        ticks = self._RATE_TICKS.get(rate, 4)
        self._phase += 1.0 / ticks
        if self._phase >= 1.0:
            self._phase -= 1.0
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

        if wave == "sine":
            raw = math.sin(phase * 2 * math.pi)
        elif wave == "triangle":
            raw = 1 - 4 * abs(phase - 0.5)
        elif wave == "square":
            raw = 1.0 if phase < 0.5 else -1.0
        elif wave == "saw":
            raw = 2 * phase - 1
        elif wave == "s&h":
            if phase < 0.05:
                self._sh_value = random.randint(0, 127)
            value = max(0, min(127, self._sh_value))
            if value != self._last_value:
                self._last_value = value
                self.send_cc(out_ch, cc_num, value)
            return
        else:
            raw = 0

        half_depth = depth / 2.0
        value = int(center + raw * half_depth)
        value = max(0, min(127, value))

        if value != self._last_value:
            self._last_value = value
            self.send_cc(out_ch, cc_num, value)
            self.set_display("level", value)
