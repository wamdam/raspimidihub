"""Hold — latches pressed notes until a release-note or a new note is played."""

from raspimidihub.plugin_api import (
    Button,
    Group,
    NoteSelect,
    PluginBase,
)


class Hold(PluginBase):
    """Sustains played notes without needing a pedal.

    Two modes:
      - Chord-latch (default, Toggle notes off): while any key is held,
        further presses build a chord; once every key is released the chord
        stays sounding. The release note (and any new note after a full
        release) silences the held chord.
      - Toggle notes (button on): each note latches independently. The first
        press of a note plays it and holds it; the next press of the same
        note releases it. Physical note-offs are ignored. The release note,
        if enabled, silences every latched note at once.
    """

    NAME = "Hold"
    DESCRIPTION = "Latch notes until released or a new note is played"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.1"
    HELP = """\
Turns any keyboard into a sustained-chord (or per-key latch) instrument
without a pedal.

Two modes, chosen with the Toggle notes button:

Chord-latch (Toggle notes OFF — the default):
  While you still have any key physically pressed, new notes add to the
  held chord. As soon as you lift all fingers, the chord stays sounding
  until you either:
    - press the configured Release Note (silent — just releases), or
    - press any other note, which releases the previous chord and starts
      a new one with that note as the first in the new chord.

Toggle notes (button ON):
  Each note latches independently. Press a note to play and hold it;
  press the same note again to release it. The keyboard's own note-off
  events are ignored — what's playing is decided entirely by which notes
  you've toggled on. The Release Note (if enabled) still works as an
  "all off" trigger that releases every latched note at once.

Tip: pick a Release Note at the very top or bottom of the keyboard so
you don't hit it by accident. Disable the release note with the toggle
if you only want the "play a new note to replace" / "press again to
release" behaviour."""

    params = [
        Button("toggle_notes", "Toggle notes", default=False, color="green"),
        Group("Release Note", [
            Button("use_release_note", "Enabled", default=True, color="green"),
            NoteSelect("release_note", "Note", default=108,  # C8
                       visible_when=("use_release_note", True)),
        ]),
    ]

    inputs = ["Notes", "CC / Pitchbend / Aftertouch (pass-through)"]
    outputs = ["Notes (held)", "CC / Pitchbend / Aftertouch (pass-through)"]

    def on_start(self):
        self._physical: set[tuple[int, int]] = set()  # chord-latch: keys currently pressed
        self._held: list[tuple[int, int]] = []       # chord-latch: notes currently sounding
        self._locked = False                          # chord-latch: all physical keys released
        self._toggled: set[tuple[int, int]] = set()  # toggle-mode: notes currently latched on

    def _is_release_note(self, note: int) -> bool:
        return bool(self.get_param("use_release_note")) and note == self.get_param("release_note")

    def _release_all(self):
        # Releases both pools — in practice only one is populated at a time
        # (per mode), but switching modes or panicking should clear either.
        for ch, n in list(self._held):
            self.send_note_off(ch, n)
        for ch, n in list(self._toggled):
            self.send_note_off(ch, n)
        self._held = []
        self._toggled = set()
        self._locked = False

    def on_note_on(self, channel, note, velocity):
        if self.get_param("toggle_notes"):
            # Velocity-0 note-on is running-status note-off — ignored in
            # toggle mode; latched notes only flip on a real press.
            if velocity == 0:
                return
            if self._is_release_note(note):
                self._release_all()
                return  # swallow
            key = (channel, note)
            if key in self._toggled:
                self._toggled.discard(key)
                self.send_note_off(channel, note)
            else:
                self._toggled.add(key)
                self.send_note_on(channel, note, velocity)
            return

        # Chord-latch mode (unchanged) ---------------------------------
        if velocity == 0:
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
        if self.get_param("toggle_notes"):
            # Physical note-off doesn't unlatch — the next press of the same
            # note is what releases it. Nothing to track.
            return

        # Chord-latch mode (unchanged) ---------------------------------
        # Always clear physical state, even for the release-note key — if the
        # user pressed a key as a "normal" note and then Learn changed the
        # release-note to that same note, the paired note-off would otherwise
        # leave (channel, note) wedged in _physical forever and the plugin
        # would never reach LOCKED again.
        self._physical.discard((channel, note))
        if not self._physical and self._held:
            self._locked = True

    def on_param_change(self, name, value):
        if name == "toggle_notes":
            # Switching modes: release every sounding note. Without this the
            # previous mode's bookkeeping (chord-latch's _held or toggle's
            # _toggled) would never get cleared by the new mode's logic and
            # we'd ship the user a stuck-note bug.
            self._release_all()
            self._physical.clear()

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
