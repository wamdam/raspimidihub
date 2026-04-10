"""MIDI Sync Offset — delay or advance note output relative to clock beats."""

import threading
import collections

from raspimidihub.plugin_api import PluginBase, Group, Wheel, Radio, Toggle


class SyncOffset(PluginBase):
    """Delays or advances notes relative to MIDI clock beats. Useful for tight sync or swing."""

    NAME = "Sync Offset"
    DESCRIPTION = "Offset note timing relative to clock beats"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Shifts note timing forward by milliseconds relative to the beat, or
quantizes notes to a grid. Fixes timing drift between devices or adds
deliberate push/pull feel.

Example: A drum machine triggers 10ms late due to USB latency. Set
offset=-10 to compensate (negative = send earlier). Or enable quantize
to snap sloppy playing to the nearest 1/8 note grid."""

    params = [
        Group("Timing", [
            Wheel("offset_ms", "Offset (ms)", min=-50, max=50, default=0),
            Toggle("quantize", "Quantize to Beat", default=False),
            Radio("grid", "Grid", ["1/4", "1/8", "1/16"], default="1/8",
                  visible_when=("quantize", True)),
        ]),
    ]

    clock_divisions = ["1/4", "1/8", "1/16"]

    inputs = ["Notes", "Clock"]
    outputs = ["Notes (time-shifted)"]

    def on_start(self):
        self._pending = collections.deque()  # (fire_time, type, channel, note, velocity)
        self._lock = threading.Lock()
        self._running = True
        self._timer = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer.start()
        self._last_beat_time = 0

    def on_stop(self):
        self._running = False

    def on_tick(self, division):
        grid = self.get_param("grid") or "1/8"
        if division == grid:
            import time
            self._last_beat_time = time.monotonic()
            # Flush any quantized notes waiting for this beat
            if self.get_param("quantize"):
                with self._lock:
                    while self._pending and self._pending[0][0] <= 0:
                        _, typ, ch, note, vel = self._pending.popleft()
                        if typ == "on":
                            self.send_note_on(ch, note, vel)
                        else:
                            self.send_note_off(ch, note)

    def on_note_on(self, channel, note, velocity):
        import time
        offset_ms = self.get_param("offset_ms") or 0

        if self.get_param("quantize"):
            # Queue note, fire on next beat
            with self._lock:
                self._pending.append((0, "on", channel, note, velocity))
        elif offset_ms == 0:
            self.send_note_on(channel, note, velocity)
        elif offset_ms > 0:
            # Delay: queue for later
            fire_time = time.monotonic() + offset_ms / 1000.0
            with self._lock:
                self._pending.append((fire_time, "on", channel, note, velocity))
        else:
            # Negative offset: send immediately (can't go back in time)
            self.send_note_on(channel, note, velocity)

    def on_note_off(self, channel, note):
        import time
        offset_ms = self.get_param("offset_ms") or 0

        if self.get_param("quantize"):
            with self._lock:
                self._pending.append((0, "off", channel, note, 0))
        elif offset_ms > 0:
            fire_time = time.monotonic() + offset_ms / 1000.0
            with self._lock:
                self._pending.append((fire_time, "off", channel, note, 0))
        else:
            self.send_note_off(channel, note)

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)

    def _timer_loop(self):
        import time
        while self._running:
            now = time.monotonic()
            with self._lock:
                while self._pending and self._pending[0][0] > 0 and self._pending[0][0] <= now:
                    _, typ, ch, note, vel = self._pending.popleft()
                    if typ == "on":
                        self.send_note_on(ch, note, vel)
                    else:
                        self.send_note_off(ch, note)
            time.sleep(0.001)  # 1ms resolution
