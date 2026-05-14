"""Pitch CC — turn played notes into a pitch CC + the trigger note.

Built for samplers like the Korg Volca Sample whose pitch is controlled by
a CC rather than the MIDI note number. Every semitone above the configured
base note adds 1 to the base CC value; every semitone below subtracts 1.
The CC is emitted *before* the Note On so the receiving synth latches the
new pitch in time for the trigger.
"""

from raspimidihub.plugin_api import NoteSelect, PluginBase, Wheel


class PitchCC(PluginBase):
    NAME = "Pitch CC"
    DESCRIPTION = "Pitch-by-note via CC (Volca Sample style)"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Turns a keyboard into a chromatic player for synths/samplers whose pitch
is controlled by a Control Change rather than by note number — the Korg
Volca Sample being the canonical example (CC 49 = sample playback rate).

For every Note On, the plugin first emits a CC change whose value is
Base CC Value + (played_note - Base Note), clamped to 0..127. Then it
forwards the Note On itself. The Note Off is forwarded without a CC.

The CC always goes out first; reversing the order would play the very
first note at whatever pitch the synth happened to be parked at.

Example: Volca Sample on channel 10, sample tuned to play at center
rate when CC 49 = 64. Set Base Note = C-3 (60), Out CC# = 49,
Base CC Value = 64. Now play any note: C-3 plays the sample at the
center rate; D-3 plays 2 semitones up; B-2 plays 1 semitone down; and
so on. Notes that would push the CC outside 0..127 still trigger,
just clamped to the floor/ceiling."""

    params = [
        NoteSelect("base_note", "Base Note", default=60),       # Middle C
        Wheel("out_cc", "Out CC#", min=0, max=127, default=49),  # Volca Sample pitch
        Wheel("base_cc_value", "Base Val", min=0, max=127, default=64),
    ]

    inputs = ["Notes", "CC / Pitchbend / Aftertouch (pass-through)"]
    outputs = [
        "CC (pitch, emitted before each Note On)",
        "Notes (forwarded unchanged)",
        "Other events (pass-through)",
    ]

    def on_note_on(self, channel, note, velocity):
        if velocity == 0:
            # Running-status note-off — forward as a note-off, no CC.
            self.send_note_off(channel, note)
            return
        base_note = int(self.get_param("base_note") or 60)
        out_cc = int(self.get_param("out_cc") or 0)
        base_val = int(self.get_param("base_cc_value") or 0)
        cc_val = max(0, min(127, base_val + (note - base_note)))
        # Order is load-bearing: emit pitch CC FIRST so the synth latches
        # the new value before the Note On triggers the sample.
        self.send_cc(channel, out_cc, cc_val)
        self.send_note_on(channel, note, velocity)

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
