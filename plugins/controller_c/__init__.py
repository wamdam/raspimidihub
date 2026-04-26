"""Controller C — 6-wide FX (THROWAWAY visual mock).

Layout: 6 knobs / 6 vertical faders / 6 buttons — middle-ground density.
No MIDI I/O — for layout review only. Delete after Phase 4 design call.
"""

from raspimidihub.plugin_api import (
    Button,
    Fader,
    Group,
    Knob,
    PluginBase,
)


class ControllerC(PluginBase):
    """6-wide FX layout (knobs / faders / buttons)."""

    NAME = "Controller C — FX 6"
    DESCRIPTION = "6-wide FX layout: knobs, faders, buttons (visual mock)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "0.1"
    HELP = """\
Visual mock of a fixed-template Controller plugin. Three rows of
6 cells — a middle-ground density between the 4-wide and 8-wide
templates. No MIDI is emitted — this is a Phase-4 layout-review
plugin only and will be removed."""

    params = [
        Group("FX Macros", [
            Knob(f"fx{i}", f"FX{i+1}", min=0, max=127, default=64) for i in range(6)
        ], cols=6),
        Group("Sends", [
            Fader(f"s{i}", f"S{i+1}", min=0, max=127,
                  default=64 + (i * 5) % 40, vertical=True) for i in range(6)
        ], cols=6),
        Group("Bypass", [
            Button(f"b{i}", f"B{i+1}", color="green") for i in range(6)
        ], cols=6),
    ]

    cc_inputs: dict[int, str] = {}
    cc_outputs: list[int] = []
    inputs: list[str] = []
    outputs: list[str] = []

    def on_start(self): pass
    def on_stop(self): pass
    def panic(self): pass
    def on_note_on(self, channel, note, velocity): pass
    def on_note_off(self, channel, note): pass
    def on_cc(self, channel, cc, value): pass
    def on_pitchbend(self, channel, value): pass
    def on_aftertouch(self, channel, value): pass
    def on_program_change(self, channel, program): pass
