"""Hold — latches pressed notes until a release-note or a new note is played."""

from raspimidihub.plugin_api import (
    PluginBase, Group, NoteSelect, Toggle,
)


class Hold(PluginBase):
    """Sustains played notes without needing a pedal.

    Press any number of notes to build a chord. While at least one key is still
    physically down, further presses add to the chord. Once every key is
    released, the chord stays sounding. Pressing the configured release-note
    (which is never forwarded) silences the chord. Pressing any other note
    silences the previous chord and starts a fresh one.
    """

    NAME = "Hold"
    DESCRIPTION = "Latch notes until released or a new note is played"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Turns any keyboard into a sustained-chord instrument without a pedal.

While you still have any key physically pressed, new notes add to the
held chord. As soon as you lift all fingers, the chord stays sounding
until you either:
  - press the configured Release Note (silent — just releases), or
  - press any other note, which releases the previous chord and starts
    a new one with that note as the first in the new chord.

Tip: pick a Release Note at the very top or bottom of the keyboard so
you don't hit it by accident. Disable the release note with the toggle
if you only want the "play a new note to replace" behaviour."""

    params = [
        Group("Release Note", [
            Toggle("use_release_note", "Enabled", default=True),
            NoteSelect("release_note", "Note", default=108,  # C8
                       visible_when=("use_release_note", True)),
        ]),
    ]

    inputs = ["Notes", "CC / Pitchbend / Aftertouch (pass-through)"]
    outputs = ["Notes (held)", "CC / Pitchbend / Aftertouch (pass-through)"]

    def on_start(self):
        self._physical: set[tuple[int, int]] = set()  # (channel, note) currently pressed
        self._held: list[tuple[int, int]] = []       # (channel, note) currently sounding
        self._locked = False                          # True once all physical keys released

    def _is_release_note(self, note: int) -> bool:
        return bool(self.get_param("use_release_note")) and note == self.get_param("release_note")

    def _release_all(self):
        for ch, n in self._held:
            self.send_note_off(ch, n)
        self._held = []
        self._locked = False

    def on_note_on(self, channel, note, velocity):
        if velocity == 0:
            # Running-status note-off
            self.on_note_off(channel, note)
            return

        if self._is_release_note(note):
            self._release_all()
            return  # swallow — the release note itself is never forwarded

        if self._locked:
            self._release_all()

        self._physical.add((channel, note))
        self._held.append((channel, note))
        self.send_note_on(channel, note, velocity)

    def on_note_off(self, channel, note):
        # Always clear physical state, even for the release-note key — if the
        # user pressed a key as a "normal" note and then Learn changed the
        # release-note to that same note, the paired note-off would otherwise
        # leave (channel, note) wedged in _physical forever and the plugin
        # would never reach LOCKED again.
        self._physical.discard((channel, note))
        if not self._physical and self._held:
            self._locked = True

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)

    def on_program_change(self, channel, program):
        self.send_program_change(channel, program)

    def on_transport_stop(self):
        self._release_all()
        self._physical.clear()

    def panic(self):
        self._release_all()
        self._physical.clear()

    def on_stop(self):
        # Plugin shutdown — clean up any sounding notes.
        self._release_all()
        self._physical.clear()
