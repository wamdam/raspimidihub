"""Latency — adds a fixed delay (ms) to every MIDI event via the ALSA queue.

Compensates for synths whose own MIDI-in processing lands the sound a
few milliseconds after the message arrives. Route a tight source (the
Arpeggiator, the Tracker, a controller) through Latency before that
synth so the audio lines up with the synth's internal sequencer.

Clock and transport (Start/Stop/Continue) pass through immediately —
delaying clock would shift the downstream synth's own sequencer and
defeat the point of compensation."""

import time

from raspimidihub.plugin_api import Fader, PluginBase

# All scheduled events share this tag so panic / on_stop can clear
# the entire pending burst with one cancel call.
_TAG = 1


class Latency(PluginBase):
    """Delays MIDI events by a fixed millisecond offset."""

    NAME = "Latency"
    DESCRIPTION = "Add a fixed millisecond delay to all MIDI events"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Adds a fixed delay (in milliseconds) to every MIDI event before
forwarding it. Clock and transport messages pass through immediately.

Use it to compensate for synths that respond to MIDI with a small
built-in latency. Example: route the Arpeggiator into a Digitone via
Latency; tune delay_ms until the Digitone's audio lines up with its
own internal sequencer.

The ALSA kernel queue dispatches the delayed events with sub-ms jitter
regardless of Python load."""

    params = [
        Fader("delay_ms", "Delay (ms)", min=1, max=100, default=10,
              span=4, default_cc=74),
    ]

    inputs = ["All events (notes, CC, pitchbend, aftertouch, program change)",
              "Clock + transport (pass-through, not delayed)",
              "CC (long-press Delay (ms) to bind)"]
    outputs = ["All events (delayed by delay_ms)",
               "Clock + transport (immediate)"]

    def on_start(self):
        # Per-note delay snapshot. note_off reuses the delay value
        # captured at note_on so a live fader move mid-note can't
        # reorder the pair and strand the note.
        self._note_delay: dict[tuple[int, int], float] = {}

    def on_stop(self):
        self.cancel_scheduled(_TAG)
        self._note_delay.clear()

    def panic(self):
        self.cancel_scheduled(_TAG)
        self._note_delay.clear()

    def _delay_s(self) -> float:
        d = self.get_param("delay_ms")
        if d is None:
            d = 10
        return d / 1000.0

    def on_note_on(self, channel, note, velocity):
        d = self._delay_s()
        self._note_delay[(channel, note)] = d
        self.send_note_on_at(time.monotonic() + d, channel, note, velocity, tag=_TAG)

    def on_note_off(self, channel, note):
        d = self._note_delay.pop((channel, note), self._delay_s())
        self.send_note_off_at(time.monotonic() + d, channel, note, tag=_TAG)

    def on_cc(self, channel, cc, value):
        self.send_cc_at(time.monotonic() + self._delay_s(),
                        channel, cc, value, tag=_TAG)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend_at(time.monotonic() + self._delay_s(),
                               channel, value, tag=_TAG)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch_at(time.monotonic() + self._delay_s(),
                                channel, value, tag=_TAG)

    def on_program_change(self, channel, program):
        self.send_program_change_at(time.monotonic() + self._delay_s(),
                                    channel, program, tag=_TAG)

    def on_clock(self):
        self.send_clock()

    def on_clock_start(self):
        self.send_start()

    def on_clock_stop(self):
        self.send_stop()

    def on_clock_continue(self):
        self.send_continue()
