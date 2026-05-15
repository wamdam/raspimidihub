"""UI Demo — visual showcase of every UI control type.

This plugin exists purely as a design/UX reference. It does NOT process MIDI:
wiring it in the matrix produces silence. The Display outputs are driven by
internal threads emitting low-rate (~20 Hz) data so the plugin -> SSE -> UI
update path can be observed live.
"""

import math
import random
import threading
import time

from raspimidihub.plugin_api import (
    Button,
    ChannelSelect,
    CurveEditor,
    Display,
    Fader,
    Group,
    Knob,
    LayoutCell,
    LayoutGrid,
    NoteSelect,
    PluginBase,
    Radio,
    StepEditor,
    Wheel,
    XYPad,
)


class UiDemo(PluginBase):
    """Showcases every existing UI control type side-by-side."""

    NAME = "UI Demo"
    DESCRIPTION = "Visual showcase of every UI control type"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
This plugin does nothing musically — wire it for the demo grid only.
It exists as a visual reference so every UI control can be seen
side-by-side, in proportion, and played with for design / UX
evaluation. Wiring it into the matrix produces silence: no notes,
no CC, no clock, no pass-through.

The two Display outputs (a scope and a meter) are fed by simple
internal logic at ~20 Hz so you can verify plugin -> SSE -> UI
updates are flowing."""

    params = [
        Group("Knobs", [
            Knob("knob_basic", "Cutoff", min=0, max=127, default=80),
            Knob("knob_freq", "Freq",
                 min=1, max=200, default=50,
                 display_factor=0.1, unit=" Hz"),
            Knob("knob_q", "Reso", min=0, max=127, default=20),
            Knob("knob_mode", "Mode",
                 min=0, max=3, default=1,
                 labels=["LP", "BP", "HP", "Notch"]),
        ]),
        Group("Wheels", [
            Wheel("wheel_basic", "Basic", min=0, max=127, default=64),
            Wheel("wheel_freq", "Freq",
                  min=1, max=200, default=50,
                  display_factor=0.1, unit=" Hz"),
            Wheel("wheel_labels", "Mode",
                  min=0, max=3, default=0,
                  labels=["Off", "Low", "Mid", "High"]),
            NoteSelect("note_pick", "Note", default=60),
            ChannelSelect("ch_pick", "Channel", default=1),
        ]),
        Group("Faders", [
            # Row 1: a row of 4 vertical faders side by side (mixer feel).
            Fader("fader_v1", "Kick",  min=0, max=127, default=96, vertical=True),
            Fader("fader_v2", "Snare", min=0, max=127, default=80, vertical=True),
            Fader("fader_v3", "Hat",   min=0, max=127, default=64, vertical=True),
            Fader("fader_v4", "Perc",  min=0, max=127, default=48, vertical=True),
            # Row 2: 1u horizontal + a 2u horizontal (showing span).
            Fader("fader_h1", "Horizontal", min=0, max=127, default=64),
            Fader("fader_h2", "Wide", min=0, max=127, default=80, span=2),
            Fader("fader_fmt", "Frequency",
                  min=1, max=200, default=20,
                  display_factor=0.1, display_format=" Hz"),
            # Row 3: full-row span (master fader feel).
            Fader("fader_master", "Master", min=0, max=127, default=100, span=4),
        ]),
        Group("Switches", [
            Button("button_green", "Green", color="green"),
            Button("button_yellow", "Yellow", color="yellow"),
            Button("button_red", "Red", color="red"),
            Button("button_blue", "Blue", color="blue"),
        ]),
        Group("Radio", [
            Radio("radio_short", "Shape",
                  ["sine", "triangle", "square", "saw"], default="sine"),
            Radio("radio_long", "Rate",
                  ["1/1", "1/2", "1/4", "1/8", "1/16", "1/32"], default="1/4"),
        ]),
        Group("Sequencer", [
            Wheel("step_count", "Steps", min=1, max=16, default=8),
            StepEditor("steps", "Pattern",
                       length_param="step_count",
                       default_length=8, default_on=True),
        ]),
        Group("Curve", [
            CurveEditor("curve", "Curve"),
        ]),
        Group("Displays", [
            Display("_scope", "Scope", display_name="scope_out"),
            Display("_meter", "Meter", display_name="meter_out"),
        ]),
        Group("Visibility", [
            Button("show_extra", "Reveal Extra", color="green"),
            Wheel("extra", "Extra Param",
                  min=0, max=127, default=42,
                  visible_when=("show_extra", True)),
        ]),
        # --- Grid-sizing experiments — feel out 5/6/7/8 cols at typical viewports ---
        Group("Grid 5-wide", [
            Knob(f"g5_k{i}", f"K{i+1}", min=0, max=127, default=64) for i in range(5)
        ], cols=5),
        Group("Grid 6-wide", [
            Knob(f"g6_k{i}", f"K{i+1}", min=0, max=127, default=64) for i in range(6)
        ], cols=6),
        Group("Grid 7-wide", [
            Knob(f"g7_k{i}", f"K{i+1}", min=0, max=127, default=64) for i in range(7)
        ], cols=7),
        Group("Grid 8-wide knobs", [
            Knob(f"g8_k{i}", f"K{i+1}", min=0, max=127, default=64) for i in range(8)
        ], cols=8),
        Group("Grid 8-wide faders", [
            Fader(f"g8_f{i}", f"F{i+1}",
                  min=0, max=127, default=64 + i * 4, vertical=True) for i in range(8)
        ], cols=8),
        Group("Grid 8-wide buttons", [
            Button(f"g8_t{i}", f"T{i+1}", color="green") for i in range(8)
        ], cols=8),
        # --- XYPad standalone (in a 2-col group so it doesn't stretch) ---
        Group("XY Pad", [
            XYPad("xy_demo", "XY", min=0, max=127, default_x=64, default_y=64),
            Knob("xy_demo_x_view", "X view", min=0, max=127, default=64),
        ], cols=2),
        # --- LayoutGrid demo: 6×4 grid mixing Knob / Fader / Button / XYPad ---
        # The XY pad spans 2×2 in the corner; surrounding cells are 1×1.
        Group("LayoutGrid demo", [
            LayoutGrid(
                "lg_demo", "Mixed",
                cols=6, rows=4,
                cells=[
                    # Top row: 4 knobs across cols 1-4; XY pad spans cols 5-6 rows 1-2.
                    LayoutCell(Knob("lg_k1", "K1", min=0, max=127, default=50), col=1, row=1),
                    LayoutCell(Knob("lg_k2", "K2", min=0, max=127, default=70), col=2, row=1),
                    LayoutCell(Knob("lg_k3", "K3", min=0, max=127, default=90), col=3, row=1),
                    LayoutCell(Knob("lg_k4", "K4", min=0, max=127, default=110), col=4, row=1),
                    LayoutCell(XYPad("lg_xy", "XY", default_x=64, default_y=64),
                               col=5, row=1, span_cols=2, span_rows=2),
                    # Row 2: 4 vertical faders below the knobs.
                    LayoutCell(Fader("lg_f1", "F1", min=0, max=127, default=80, vertical=True), col=1, row=2),
                    LayoutCell(Fader("lg_f2", "F2", min=0, max=127, default=64, vertical=True), col=2, row=2),
                    LayoutCell(Fader("lg_f3", "F3", min=0, max=127, default=48, vertical=True), col=3, row=2),
                    LayoutCell(Fader("lg_f4", "F4", min=0, max=127, default=96, vertical=True), col=4, row=2),
                    # Row 3: 6 mute buttons across the row.
                    LayoutCell(Button("lg_m1", "M1", color="green"), col=1, row=3),
                    LayoutCell(Button("lg_m2", "M2", color="green"), col=2, row=3),
                    LayoutCell(Button("lg_m3", "M3", color="green"), col=3, row=3),
                    LayoutCell(Button("lg_m4", "M4", color="green"), col=4, row=3),
                    LayoutCell(Button("lg_m5", "M5", color="green"), col=5, row=3),
                    LayoutCell(Button("lg_m6", "M6", color="green"), col=6, row=3),
                    # Row 4: a wide horizontal master fader spanning all 6 cols.
                    LayoutCell(Fader("lg_master", "Master", min=0, max=127, default=100), col=1, row=4, span_cols=6),
                ],
            ),
        ]),
    ]

    # No MIDI I/O — purely a UI demo
    cc_outputs: list[int] = []
    inputs: list[str] = []
    outputs: list[str] = []

    display_outputs = [
        {"name": "scope_out", "type": "scope", "label": "Sine",
         "min": 0, "max": 127, "duration": 2},
        {"name": "meter_out", "type": "meter", "label": "Random",
         "min": 0, "max": 127},
    ]

    # Cap emit rate at 20 Hz to avoid flooding SSE.
    _EMIT_HZ = 10

    def on_start(self):
        self._running = True
        self._phase = 0.0
        self._meter_value = 0
        # One thread per display so each emits at its own pace.
        self._scope_thread = threading.Thread(
            target=self._scope_loop, daemon=True)
        self._meter_thread = threading.Thread(
            target=self._meter_loop, daemon=True)
        self._scope_thread.start()
        self._meter_thread.start()

    def on_stop(self):
        self._running = False

    def panic(self):
        # Demo plugin holds no note state — nothing to release.
        pass

    # --- Event handlers: deliberately silent ---
    # No send_note_on / send_note_off / send_cc / send_clock anywhere.
    # Wiring this plugin produces no audible output by design.

    def on_note_on(self, channel, note, velocity):
        pass

    def on_note_off(self, channel, note):
        pass

    def on_cc(self, channel, cc, value):
        pass

    def on_pitchbend(self, channel, value):
        pass

    def on_aftertouch(self, channel, value):
        pass

    def on_program_change(self, channel, program):
        pass

    # --- Internal display drivers ---

    def _scope_loop(self):
        """Emit a slow sine into the scope at ~10 Hz."""
        interval = 1.0 / self._EMIT_HZ
        # ~0.25 Hz sine — one full sweep every 4 seconds.
        cycle_seconds = 4.0
        while self._running:
            self._phase += interval / cycle_seconds
            if self._phase >= 1.0:
                self._phase -= 1.0
            raw = math.sin(self._phase * 2 * math.pi)
            value = int(64 + raw * 60)
            value = max(0, min(127, value))
            self.set_display("scope_out", value)
            time.sleep(interval)

    def _meter_loop(self):
        """Emit a smoothly drifting value into the meter at ~5 Hz."""
        interval = 1.0 / 5  # half the scope rate — keeps SSE light
        while self._running:
            # Random walk, clamped to range — looks like a VU bouncing.
            self._meter_value += random.randint(-12, 12)
            self._meter_value = max(0, min(127, self._meter_value))
            self.set_display("meter_out", self._meter_value)
            time.sleep(interval)
