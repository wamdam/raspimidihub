"""Controller A — 8-wide Mixer (THROWAWAY visual mock).

Layout: 8 knobs / 8 vertical faders / 8 mute buttons, three rows wide.
No MIDI I/O — for layout review only. Delete after Phase 4 design call.
"""

from raspimidihub.plugin_api import (
    Button,
    Fader,
    Group,
    Knob,
    PluginBase,
)


class ControllerA(PluginBase):
    """8-wide mixer-strip layout (knobs / faders / mutes)."""

    NAME = "Controller A — Mixer 8"
    DESCRIPTION = "8-wide mixer-style layout: knobs, faders, mutes (visual mock)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "0.1"
    HELP = """\
Visual mock of a fixed-template Controller plugin. Three rows of
8 cells: a row of knobs, a row of vertical faders, a row of
mutes. No MIDI is emitted — this is a Phase-4 layout-review
plugin only and will be removed."""

    params = [
        Group("Send / Pan", [
            Knob(f"k{i}", f"K{i+1}", min=0, max=127, default=64) for i in range(8)
        ], cols=8),
        Group("Volume", [
            Fader(f"f{i}", f"F{i+1}", min=0, max=127,
                  default=80 + (i % 3) * 8, vertical=True) for i in range(8)
        ], cols=8),
        Group("Mute", [
            Button(f"m{i}", f"M{i+1}", color="green") for i in range(8)
        ], cols=8),
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
