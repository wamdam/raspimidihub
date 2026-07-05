"""Velocity Equalizer — normalize note velocities to a fixed value or compressed range."""

from raspimidihub import midi_scale
from raspimidihub.plugin_api import Group, PluginBase, Radio, Wheel


class VelocityEqualizer(PluginBase):
    """Normalizes note velocities: fixed value or compressed range."""

    NAME = "Velocity Equalizer"
    DESCRIPTION = "Normalize velocities to fixed value or compressed range"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Normalizes note velocities to a fixed value or compresses them into a
narrower range. Use fixed mode for drum machines that need consistent
hits, or compress mode to tame an uneven player. Expand mode
stretches a narrow input range (set via Min/Max) to the full 0-127
output range, useful for controllers with limited dynamic range.
Example: Set mode=fixed, velocity=100 to make every note the same
volume -- ideal for triggering samples where dynamics are unwanted."""

    params = [
        Radio("mode", "Mode", ["fixed", "compress", "expand"], default="fixed"),
        Group("Fixed", [
            Wheel("fixed_vel", "Velocity", min=1, max=127, default=100,
                  visible_when=("mode", "fixed"), default_cc=74),
        ]),
        Group("Range", [
            Wheel("out_min", "Min", min=1, max=127, default=60,
                  visible_when=("mode", ["compress", "expand"]), default_cc=75),
            Wheel("out_max", "Max", min=1, max=127, default=120,
                  visible_when=("mode", ["compress", "expand"]), default_cc=76),
        ]),
    ]

    inputs = ["Notes", "All other events (pass-through)",
              "CC (long-press a Velocity / Min / Max wheel to bind)"]
    outputs = ["Notes (velocity adjusted)", "All other events (pass-through)"]

    # Float MIDI-unit velocity in (7-bit sources deliver exact ints):
    # hi-res keyboards keep their gradations through compress/expand.
    wants_hires_input = True

    def on_note_on(self, channel, note, velocity):
        mode = self.get_param("mode") or "fixed"
        if mode == "fixed":
            velocity = self.get_param("fixed_vel") or 100
        elif mode in ("compress", "expand"):
            lo = self.get_param("out_min") or 60
            hi = self.get_param("out_max") or 120
            if mode == "compress":
                out = lo + (velocity / 127) * (hi - lo)
                anchor = lo + round((velocity / 127) * (hi - lo))
            else:
                # Expand: stretch to full 1-127 from narrow input
                out = max(1.0, min(127.0,
                                   (velocity - lo) / max(1, hi - lo) * 127))
                anchor = round(out)
            # Float trajectory positioned in the legacy round() bucket:
            # MIDI 1.0 receivers stay byte-identical, 2.0 receivers get
            # the fine gradations.
            anchor = max(1, min(127, anchor))
            velocity = midi_scale.units_in_bucket(anchor,
                                                  max(1.0, min(127.0, out)))
        self.send_note_on(channel, note,
                          velocity if isinstance(velocity, float)
                          else max(1, min(127, velocity)))

    def on_note_off(self, channel, note):
        self.send_note_off(channel, note)

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)

    def on_program_change(self, channel, program):
        self.send_program_change(channel, program)
