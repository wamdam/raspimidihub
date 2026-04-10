"""MIDI Delay — delays notes with optional feedback and velocity decay."""

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
Feedback % controls how many repeats (0 = one echo, 100 = maximum
repeats). Vel Decay % makes each repeat quieter by that amount, so
echoes fade out naturally.
Example: Set delay=250ms, feedback=50%, decay=20% to add rhythmic
echoes to a lead synth line. Plays the original note immediately,
then softer repeats that fade out."""

    params = [
        Group("Timing", [
            Toggle("sync", "Sync to Clock", default=False),
            Wheel("delay_ms", "Delay (ms)", min=10, max=2000, default=250,
                  visible_when=("sync", False)),
            Radio("rate", "Rate", ["1/4", "1/8", "1/16", "1/8T"], default="1/8",
                  visible_when=("sync", True)),
        ]),
        Group("Controls", [
            Fader("feedback", "Feedback %", min=0, max=100, default=50),
            Fader("vel_decay", "Vel Decay %", min=0, max=100, default=20),
        ]),
    ]

    cc_inputs = {74: "delay_ms", 75: "feedback"}

    inputs = ["Notes", "CC#74 (delay time)", "CC#75 (feedback)", "Clock"]
    outputs = ["Notes (original + delayed)"]

    clock_divisions = ["1/4", "1/8", "1/16", "1/4T", "1/8T", "1/16T"]

    def on_start(self):
        # Free mode: [(fire_time, channel, note, velocity, repeat)]
        self._pending = []
        # Sync mode: [(ticks_remaining, channel, note, velocity, repeat)]
        self._sync_queue = []
        # Note-offs: [(fire_time, channel, note)]
        self._note_offs = []
        self._lock = threading.Lock()
        self._running = True
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer_thread.start()

    def on_stop(self):
        self._running = False

    def on_note_on(self, channel, note, velocity):
        self.send_note_on(channel, note, velocity)
        self._schedule_echo(channel, note, velocity, 0)

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
        with self._lock:
            remaining = []
            for ticks, ch, note, vel, repeat in self._sync_queue:
                if ticks <= 1:
                    self.send_note_on(ch, note, vel)
                    # Schedule note-off via timer loop (no thread spawn)
                    self._note_offs.append((time.monotonic() + 0.05, ch, note))
                    self._schedule_echo(ch, note, vel, repeat)
                else:
                    remaining.append((ticks - 1, ch, note, vel, repeat))
            self._sync_queue = remaining

    def _schedule_echo(self, channel, note, velocity, repeat):
        feedback = (self.get_param("feedback") or 50) / 100.0
        max_repeats = max(0, min(10, int(feedback * 10)))
        if repeat >= max_repeats:
            return

        vel_decay = (self.get_param("vel_decay") or 20) / 100.0
        new_vel = int(velocity * (1 - vel_decay))
        if new_vel < 1:
            return

        if self.get_param("sync"):
            with self._lock:
                # Safety: cap sync queue to prevent runaway
                if len(self._sync_queue) < 50:
                    self._sync_queue.append((1, channel, note, new_vel, repeat + 1))
        else:
            delay_sec = (self.get_param("delay_ms") or 250) / 1000.0
            fire_time = time.monotonic() + delay_sec
            with self._lock:
                if len(self._pending) < 50:
                    self._pending.append((fire_time, channel, note, new_vel, repeat + 1))

    def _timer_loop(self):
        while self._running:
            now = time.monotonic()
            to_fire = []
            offs_to_send = []

            with self._lock:
                # Free-mode echoes
                remaining = []
                for item in self._pending:
                    if item[0] <= now:
                        to_fire.append(item)
                    else:
                        remaining.append(item)
                self._pending = remaining

                # Note-offs
                off_remaining = []
                for item in self._note_offs:
                    if item[0] <= now:
                        offs_to_send.append(item)
                    else:
                        off_remaining.append(item)
                self._note_offs = off_remaining

            for fire_time, channel, note, velocity, repeat in to_fire:
                self.send_note_on(channel, note, velocity)
                with self._lock:
                    self._note_offs.append((now + 0.05, channel, note))
                self._schedule_echo(channel, note, velocity, repeat)

            for _, channel, note in offs_to_send:
                self.send_note_off(channel, note)

            time.sleep(0.005)
