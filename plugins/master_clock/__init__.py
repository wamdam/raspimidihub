"""Master Clock — generate MIDI clock with transport controls."""

import threading
import time

from raspimidihub.plugin_api import Button, PluginBase, Wheel


class MasterClock(PluginBase):
    """Generates MIDI clock at a configurable BPM with transport controls."""

    NAME = "Master Clock"
    DESCRIPTION = "Generate MIDI clock from internal BPM"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Generates continuous MIDI clock (24 PPQ) at a configurable BPM.
Clock starts immediately when the plugin is created.

Press Play to send MIDI Start (resets beat position for synced
devices) and keep sending clock. Press again to send MIDI Stop.
Clock ticks continue regardless of transport state.

Wire the Master Clock OUT to any device or plugin that needs clock."""

    params = [
        Wheel("bpm", "BPM", min=20, max=300, default=120),
        Button("play", "Play", default=False, color="green"),
    ]

    inputs = []
    outputs = ["MIDI Clock (24 PPQ), Start, Stop"]

    feeds_clock_bus = True  # pure generator — drives the global ClockBus

    # ALSA-queue scheduled tag for our pre-emitted clock burst. Used by
    # cancel_scheduled when tempo changes — the old burst is dropped
    # and a new one scheduled with the new period.
    _CLOCK_TAG = 1

    # Look-ahead window for the burst. We pre-schedule this many seconds
    # of clock ticks; the refill loop tops up before the queue runs dry.
    # 0.5 s = ~12 quarter-notes at 120 BPM, plenty of headroom against
    # any Python latency, small enough that a tempo change shows up
    # within ~half a second.
    _LOOKAHEAD_S = 0.5

    def on_start(self):
        self._running = True
        # next_emit_monotonic = when the next clock tick should land.
        # Updated as we schedule each tick; refill loop reads + advances.
        self._next_tick_monotonic: float | None = None
        self._thread = threading.Thread(target=self._refill_loop, daemon=True)
        self._thread.start()

    def on_stop(self):
        self._running = False
        self.cancel_scheduled(self._CLOCK_TAG)

    def on_param_change(self, name, value):
        if name == "play":
            if value:
                self.send_start()
            else:
                self.send_stop()
        elif name == "bpm":
            # Drop the rest of the pre-scheduled burst and re-anchor to
            # the current moment with the new period. The refill loop
            # picks up from there.
            self.cancel_scheduled(self._CLOCK_TAG)
            self._next_tick_monotonic = None

    def _refill_loop(self):
        """Schedule clock ticks `LOOKAHEAD_S` ahead of wall-clock time.
        Sleeps until the next refill window. The ALSA queue dispatches
        each tick at its exact target moment with sub-ms jitter — the
        Python sleep here only governs how often we top up the queue."""
        while self._running:
            bpm = self.get_param("bpm") or 120
            interval = 60.0 / bpm / 24.0
            now = time.monotonic()
            if self._next_tick_monotonic is None or self._next_tick_monotonic < now:
                # First entry, or we fell behind a wake-up — anchor at now.
                self._next_tick_monotonic = now + 0.001
            target = now + self._LOOKAHEAD_S
            scheduled = 0
            while self._next_tick_monotonic < target and self._running:
                self.send_clock_at(self._next_tick_monotonic, self._CLOCK_TAG)
                self._next_tick_monotonic += interval
                scheduled += 1
            # Sleep until ~half the lookahead has elapsed before refilling
            # again. Refill at ~2× the burst rate keeps the queue reliably
            # primed without waking up too often.
            if scheduled == 0:
                time.sleep(0.05)
            else:
                time.sleep(self._LOOKAHEAD_S * 0.5)
