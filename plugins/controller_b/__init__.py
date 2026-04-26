"""Controller B — 4-wide Performance (THROWAWAY visual mock).

Layout: 4×4 grid of knobs (16 macros) + 4 scene buttons.
No MIDI I/O — for layout review only. Delete after Phase 4 design call.
"""

from raspimidihub.plugin_api import (
    Button,
    Group,
    Knob,
    PluginBase,
)


class ControllerB(PluginBase):
    """4-wide performance layout (16 macro knobs + 4 scene buttons)."""

    NAME = "Controller B — Performance 16"
    DESCRIPTION = "4-wide performance layout: 16 macros + 4 scenes (visual mock)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "0.1"
    HELP = """\
Visual mock of a fixed-template Controller plugin. 4 rows of 4
knobs (16 macros total) plus a row of 4 scene-launch buttons.
Densest knob area possible at the existing 4-col grid. No MIDI
is emitted — this is a Phase-4 layout-review plugin only and
will be removed."""

    params = [
        Group("", [
            Knob(f"m{i}", f"M{i+1}", min=0, max=127, default=64) for i in range(16)
        ]),
        Group("Scenes", [
            Button("scene_a", "A", color="green"),
            Button("scene_b", "B", color="yellow"),
            Button("scene_c", "C", color="blue"),
            Button("scene_d", "D", color="red"),
        ]),
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
