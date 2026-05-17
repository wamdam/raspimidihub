"""MIDI Delay — delays notes via ALSA-queue scheduling.

Each incoming note pre-schedules its echoes (note_on + note_off pairs)
at the right monotonic moments. The ALSA kernel queue dispatches them
with sub-ms jitter regardless of Python latency or load.
"""

import time

from raspimidihub.plugin_api import (
    Button,
    Fader,
    Group,
    PluginBase,
    Radio,
    Wheel,
)

_DELAY_RATES = [
    "4/1", "4/1T", "2/1", "2/1T", "1/1", "1/1T",
    "1/2", "1/2T", "1/4", "1/4T", "1/8", "1/8T",
    "1/16", "1/16T",
]

# Raw ticks at 24 PPQN per delay rate. Used in sync mode to compute the
# monotonic moment of each echo via ClockBus.tick_to_monotonic.
_RATE_RAW_TICKS = {
    "4/1": 96 * 4, "4/1T": 64 * 4,
    "2/1": 96 * 2, "2/1T": 64 * 2,
    "1/1": 96, "1/1T": 64,
    "1/2": 48, "1/2T": 32,
    "1/4": 24, "1/4T": 16,
    "1/8": 12, "1/8T": 8,
    "1/16": 6, "1/16T": 4,
}

# Echo note duration. Long enough for the destination synth to register
# the note, short enough that adjacent echoes don't bleed.
_ECHO_NOTE_DURATION_S = 0.05

# All scheduled echoes share this tag so panic / transport-stop can
# clear the entire pending burst with one cancel call.
_DELAY_TAG = 1


class MidiDelay(PluginBase):
    """Delays MIDI notes with configurable time, feedback, and velocity decay."""

    NAME = "MIDI Delay"
    DESCRIPTION = "Delay notes with feedback and velocity decay"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Repeats notes after a delay, like a tape echo for MIDI.
Repeats sets the exact number of echoes (0-10). Vel Decay %
makes each repeat quieter by that amount so echoes fade out.
In sync mode, echoes land exactly on beat divisions. In free mode,
echoes are timed in milliseconds.
Example: Set delay=250ms, repeats=3, decay=20% for three rhythmic
echoes that fade out on a lead synth line."""

    params = [
        Group("Timing", [
            Button("sync", "Sync to Clock", color="green"),
            Fader("delay_ms", "Delay (ms)", min=10, max=2000, default=250,
                  visible_when=("sync", False), span=3, default_cc=74),
            Radio("rate", "Rate", _DELAY_RATES, default="1/8",
                  visible_when=("sync", True), span=3),
        ]),
        Group("Controls", [
            Wheel("repeats", "Repeats", min=0, max=10, default=3, default_cc=75),
            Fader("vel_decay", "Vel Decay %", min=0, max=100, default=20, span=3, default_cc=76),
        ]),
    ]

    inputs = ["Notes", "CC (long-press any value control to bind)", "Clock"]
    outputs = ["Notes (original + delayed)"]

    clock_divisions = _DELAY_RATES

    def on_start(self):
        # All scheduled echoes are tagged with _DELAY_TAG, so panic /
        # transport-stop clears the in-flight burst by cancelling that
        # tag instead of tracking individual events.
        pass

    def on_stop(self):
        self.cancel_scheduled(_DELAY_TAG)

    def on_transport_start(self):
        self.cancel_scheduled(_DELAY_TAG)

    def on_transport_stop(self):
        self.cancel_scheduled(_DELAY_TAG)

    def panic(self):
        self.cancel_scheduled(_DELAY_TAG)

    def on_note_on(self, channel, note, velocity):
        self.send_note_on(channel, note, velocity)
        self._place_echoes(channel, note, velocity)

    def on_note_off(self, channel, note):
        self.send_note_off(channel, note)

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def _place_echoes(self, channel, note, velocity):
        """Pre-schedule each echo's note_on + note_off via the ALSA
        queue. ALSA dispatches at the exact target moment with sub-ms
        jitter; no Python timer involved."""
        max_repeats = self.get_param("repeats")
        if max_repeats is None:
            max_repeats = 3
        max_repeats = max(0, min(10, max_repeats))
        # Explicit None check — `... or 20` would treat a legitimate 0 ("no
        # decay, every echo at full velocity") as falsy and snap to 20%.
        vel_decay_pct = self.get_param("vel_decay")
        if vel_decay_pct is None:
            vel_decay_pct = 20
        vel_decay = vel_decay_pct / 100.0

        if self.get_param("sync"):
            # Sync mode: each echo lands on the next musical-rate tick
            # boundary. tick_to_monotonic maps a future raw tick to its
            # wall-clock moment via the ClockBus's running EMA estimate.
            bus = getattr(self, "_clock_bus", None)
            if bus is None:
                return
            tick_to_monotonic = getattr(bus, "tick_to_monotonic", None)
            if not callable(tick_to_monotonic):
                return
            rate = self.get_param("rate") or "1/8"
            rate_ticks = _RATE_RAW_TICKS.get(rate, 12)
            now_tick = bus._tick_count
            vel = velocity
            for i in range(1, max_repeats + 1):
                vel = int(vel * (1 - vel_decay))
                if vel < 1:
                    break
                target_tick = now_tick + i * rate_ticks
                t_on = tick_to_monotonic(target_tick)
                if t_on is None:
                    return
                self.send_note_on_at(t_on, channel, note, vel, tag=_DELAY_TAG)
                self.send_note_off_at(
                    t_on + _ECHO_NOTE_DURATION_S, channel, note, tag=_DELAY_TAG)
        else:
            # Free mode: time-based, doesn't need clock-bus.
            delay_sec = (self.get_param("delay_ms") or 250) / 1000.0
            now = time.monotonic()
            vel = velocity
            for i in range(1, max_repeats + 1):
                vel = int(vel * (1 - vel_decay))
                if vel < 1:
                    break
                t_on = now + delay_sec * i
                self.send_note_on_at(t_on, channel, note, vel, tag=_DELAY_TAG)
                self.send_note_off_at(
                    t_on + _ECHO_NOTE_DURATION_S, channel, note, tag=_DELAY_TAG)
