"""Shared scheduled-clock generator for plugins that emit their own
24-PPQ MIDI clock at a UI-controlled BPM.

Pre-schedules ticks `LOOKAHEAD_S` ahead of wall-clock time through the
plugin's `send_clock_at()` — the ALSA queue dispatches each tick at its
exact target moment with sub-millisecond jitter, so the Python thread's
job is only to keep the queue topped up. Used by Master Clock and the
Tracker (clock-master mode); any future plugin emitting clock at a
UI-controlled BPM can lean on this.

Usage:

    self._clock_gen = ScheduledClockGenerator(
        self, bpm_getter=lambda: self.get_param("bpm"), tag=1,
    )
    self._clock_gen.start()   # spins up the daemon thread
    self._clock_gen.reanchor()  # call on BPM change to apply now
    self._clock_gen.stop()    # cancel pending burst + join cleanly
"""

from __future__ import annotations

import threading
import time
from typing import Callable


class ScheduledClockGenerator:
    """Daemon-threaded helper that pre-schedules 24-PPQ clock ticks
    via the host plugin's `send_clock_at()`.

    Reads BPM through a getter callback so the plugin keeps owning
    the parameter; out-of-range / non-numeric values clamp to the
    sensible range, with 120 as the fallback default.
    """

    # Look-ahead window for the burst. 0.5 s = ~12 quarter-notes at
    # 120 BPM — plenty of headroom against Python latency, small
    # enough that a tempo change shows up within ~half a second.
    LOOKAHEAD_S = 0.5

    # Clamp range. 20..300 BPM covers the union of MasterClock
    # (20..300) and Tracker (40..300); plugins narrow further in
    # their UI by setting their Wheel's min/max.
    BPM_MIN = 20
    BPM_MAX = 300

    def __init__(
        self,
        plugin,
        bpm_getter: Callable[[], int | float | None],
        tag: int = 1,
    ) -> None:
        self._plugin = plugin
        self._bpm_getter = bpm_getter
        self._tag = tag
        self._running = False
        self._next_tick: float | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._next_tick = None
        self._thread = threading.Thread(target=self._refill_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            self._plugin.cancel_scheduled(self._tag)
        except Exception:
            pass
        self._next_tick = None

    def reanchor(self) -> None:
        """Drop the rest of the pre-scheduled burst and reset the
        anchor. Call when BPM changes mid-burst so the new tempo
        applies immediately rather than after the look-ahead window."""
        try:
            self._plugin.cancel_scheduled(self._tag)
        except Exception:
            pass
        self._next_tick = None

    def _refill_loop(self) -> None:
        while self._running:
            bpm = self._bpm_getter()
            try:
                bpm = max(self.BPM_MIN, min(self.BPM_MAX, int(bpm or 120)))
            except (TypeError, ValueError):
                bpm = 120
            interval = 60.0 / bpm / 24.0
            now = time.monotonic()
            if self._next_tick is None or self._next_tick < now:
                # First entry, or we fell behind a wake-up — anchor at now.
                self._next_tick = now + 0.001
            target = now + self.LOOKAHEAD_S
            scheduled = 0
            while self._running and self._next_tick < target:
                try:
                    self._plugin.send_clock_at(self._next_tick, self._tag)
                except Exception:
                    pass
                self._next_tick += interval
                scheduled += 1
            # Refill at ~2× the burst rate keeps the queue reliably
            # primed without waking up too often. An empty burst
            # (BPM unread, anchor reset) sleeps shorter so a tempo
            # change applies promptly.
            time.sleep(0.05 if scheduled == 0 else self.LOOKAHEAD_S * 0.5)
