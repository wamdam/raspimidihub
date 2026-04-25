"""Clock Divider — emit one MIDI Clock for every N received."""

from raspimidihub.plugin_api import PluginBase, Wheel


class ClockDivider(PluginBase):
    """Slows MIDI clock down by an integer divisor without changing tempo upstream."""

    NAME = "Clock Divider"
    DESCRIPTION = "Emit one MIDI Clock for every N received"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Divides the incoming MIDI clock by an integer factor. With Divide
by = 2, the slave receives one clock tick for every two from the
master — effectively half-speed. Range 2..32.

Start, Continue, and Stop are forwarded unchanged. The internal
counter resets on Start and Continue so the first emitted tick
lines up with the downbeat.

All non-clock events (notes, CC, pitch bend, aftertouch, program
change) pass through unchanged, so the divider can sit in any
chain without breaking it.

Wire: Master clock → Divider IN, Divider OUT → slave instrument."""

    params = [
        Wheel("divide_by", "Divide by", min=2, max=32, default=2),
    ]

    inputs = ["MIDI Clock", "Start / Continue / Stop", "All other events (pass-through)"]
    outputs = ["MIDI Clock (÷N)", "Start / Continue / Stop", "All other events (pass-through)"]

    clock_divisions = ["tick"]

    def on_start(self):
        self._n = 0

    def on_tick(self, division):
        if division != "tick":
            return
        self._n += 1
        if self._n >= (self.get_param("divide_by") or 2):
            self._n = 0
            self.send_clock()

    def on_transport_start(self):
        self._n = 0
        self.send_start()

    def on_transport_continue(self):
        self._n = 0
        self.send_continue()

    def on_transport_stop(self):
        self.send_stop()

    def on_note_on(self, channel, note, velocity):
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
