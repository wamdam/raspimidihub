"""MIDI Delay — delays notes using a clock-synced circular buffer."""

import threading
import time

from raspimidihub.plugin_api import (
    PluginBase, Group, Wheel, Fader, Toggle, Radio,
)


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
            Toggle("sync", "Sync to Clock", default=False),
            Wheel("delay_ms", "Delay (ms)", min=10, max=2000, default=250,
                  visible_when=("sync", False)),
            Radio("rate", "Rate", ["1/4", "1/8", "1/16", "1/8T"], default="1/8",
                  visible_when=("sync", True)),
        ]),
        Group("Controls", [
            Wheel("repeats", "Repeats", min=0, max=10, default=3),
            Fader("vel_decay", "Vel Decay %", min=0, max=100, default=20),
        ]),
    ]

    cc_inputs = {74: "delay_ms", 75: "repeats"}

    inputs = ["Notes", "CC#74 (delay time)", "CC#75 (repeats)", "Clock"]
    outputs = ["Notes (original + delayed)"]

    clock_divisions = ["1/4", "1/8", "1/16", "1/4T", "1/8T", "1/16T"]

    def on_start(self):
        # Sync mode: circular buffer of 32 tick slots
        # Each slot: dict of (channel, note) -> velocity
        self._buf_size = 32
        self._buffer = [dict() for _ in range(self._buf_size)]
        self._buf_pos = 0  # current write position (advances on each tick)

        # Free mode: timed pending list
        self._pending = []  # [(fire_time, channel, note, velocity)]
        self._note_offs = []  # [(fire_time, channel, note)]
        self._lock = threading.Lock()
        self._running = True
        self._timer = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer.start()

    def on_stop(self):
        self._running = False

    def on_transport_start(self):
        """Clear delay buffers on MIDI Start."""
        with self._lock:
            self._buffer = [dict() for _ in range(self._buf_size)]
            self._buf_pos = 0
            self._pending.clear()
            self._note_offs.clear()

    def on_transport_stop(self):
        """Clear pending echoes on MIDI Stop."""
        with self._lock:
            self._pending.clear()
            self._note_offs.clear()

    def on_note_on(self, channel, note, velocity):
        # Pass through immediately
        self.send_note_on(channel, note, velocity)
        # Place echoes into future
        self._place_echoes(channel, note, velocity)

    def on_note_off(self, channel, note):
        self.send_note_off(channel, note)

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_tick(self, division):
        if not self.get_param("sync"):
            return
        rate = self.get_param("rate") or "1/8"
        if division != rate:
            return
        # Advance buffer position and play notes in current slot
        self._buf_pos = (self._buf_pos + 1) % self._buf_size
        slot = self._buffer[self._buf_pos]
        if slot:
            for (ch, note), vel in slot.items():
                self.send_note_on(ch, note, vel)
                # Schedule note-off
                with self._lock:
                    self._note_offs.append((time.monotonic() + 0.05, ch, note))
            slot.clear()

    def _place_echoes(self, channel, note, velocity):
        """Place echo notes into future buffer slots or pending list."""
        max_repeats = self.get_param("repeats")
        if max_repeats is None:
            max_repeats = 3
        max_repeats = max(0, min(10, max_repeats))
        vel_decay = (self.get_param("vel_decay") or 20) / 100.0

        if self.get_param("sync"):
            # Place into circular buffer at future tick positions
            vel = velocity
            for i in range(1, max_repeats + 1):
                vel = int(vel * (1 - vel_decay))
                if vel < 1:
                    break
                slot_idx = (self._buf_pos + i) % self._buf_size
                key = (channel, note)
                slot = self._buffer[slot_idx]
                if key in slot:
                    # Note already in this slot — add velocities (cap at 127)
                    slot[key] = min(127, slot[key] + vel)
                else:
                    slot[key] = vel
        else:
            # Free mode: place into timed pending list
            delay_sec = (self.get_param("delay_ms") or 250) / 1000.0
            vel = velocity
            for i in range(1, max_repeats + 1):
                vel = int(vel * (1 - vel_decay))
                if vel < 1:
                    break
                fire_time = time.monotonic() + delay_sec * i
                with self._lock:
                    self._pending.append((fire_time, channel, note, vel))

    def _timer_loop(self):
        while self._running:
            now = time.monotonic()
            to_fire = []
            offs = []

            with self._lock:
                # Free mode echoes
                remaining = []
                for item in self._pending:
                    if item[0] <= now:
                        to_fire.append(item)
                    else:
                        remaining.append(item)
                self._pending = remaining

                # Note-offs (both modes)
                off_remaining = []
                for item in self._note_offs:
                    if item[0] <= now:
                        offs.append(item)
                    else:
                        off_remaining.append(item)
                self._note_offs = off_remaining

            for _, channel, note, velocity in to_fire:
                self.send_note_on(channel, note, velocity)
                with self._lock:
                    self._note_offs.append((now + 0.05, channel, note))

            for _, channel, note in offs:
                self.send_note_off(channel, note)

            time.sleep(0.005)
