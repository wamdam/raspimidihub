"""ClockBus — distributes MIDI clock ticks to subscribed plugin instances.

Plugins declare which musical divisions they care about (`clock_divisions`)
and the bus fires `on_tick(division)` at the corresponding subdivision of
incoming 24-PPQ MIDI clock. Transport (Start / Continue / Stop) is also
fanned out via the same per-instance tick queue.
"""

import logging
import os
import threading

from .instance import PluginInstance

log = logging.getLogger(__name__)

# Division name → ticks per division at 24 PPQ (1 PPQ = 1/24 of a quarter).
DIVISION_TICKS = {
    "tick": 1,    # raw 24 PPQ — every incoming MIDI Clock
    "4/1": 384,   # 4 bars
    "2/1": 192,   # 2 bars
    "1/1": 96,    # 1 bar / whole note
    "1/2": 48,
    "1/4": 24,
    "1/8": 12,
    "1/16": 6,
    "1/32": 3,
    "4/1T": 256,  # 3 in the space of 2 × 4-bar
    "2/1T": 128,
    "1/1T": 64,
    "1/2T": 32,
    "1/4T": 16,
    "1/8T": 8,
    "1/16T": 4,
}


class ClockBus:
    """Counts incoming MIDI clock ticks and fires on_tick() at musical divisions."""

    def __init__(self):
        self._tick_count = 0
        self._running = False  # transport running (Start received)
        self._subscribers: list[tuple[PluginInstance, set[str]]] = []
        self._lock = threading.Lock()

    def subscribe(self, instance: PluginInstance, divisions: list[str]) -> None:
        with self._lock:
            self._subscribers.append((instance, set(divisions)))

    def unsubscribe(self, instance: PluginInstance) -> None:
        with self._lock:
            self._subscribers = [(i, d) for i, d in self._subscribers if i is not instance]

    def on_clock_tick(self) -> None:
        """Called by the engine for each MIDI Clock message (24 PPQ).

        Queues tick divisions for plugin threads instead of calling
        on_tick directly — avoids blocking the asyncio event loop.
        """
        if not self._running:
            self._running = True
            self._tick_count = 0
            log.info("Clock bus: auto-started on first clock tick")
        self._tick_count += 1
        with self._lock:
            for instance, divisions in self._subscribers:
                if not instance.running:
                    continue
                for div in divisions:
                    ticks = DIVISION_TICKS.get(div, 0)
                    if ticks and self._tick_count % ticks == 0:
                        # Queue for the plugin thread via its tick queue
                        q = getattr(instance, '_tick_queue', None)
                        if q is not None:
                            try:
                                q.put_nowait(div)
                                # Wake the plugin thread's select() immediately
                                pipe = getattr(instance, '_tick_pipe', None)
                                if pipe:
                                    try:
                                        os.write(pipe[1], b'\x01')
                                    except OSError:
                                        pass
                            except Exception:
                                pass

    def on_start(self) -> None:
        """MIDI Start received. Per MIDI spec, the first clock tick
        after Start is beat 1. We reset tick_count to 0 so that the
        first on_clock_tick increments to 1, and divisions fire cleanly."""
        self._tick_count = 0
        self._running = True
        # Flush stale ticks from plugin queues before sending transport
        with self._lock:
            for instance, _ in self._subscribers:
                q = getattr(instance, '_tick_queue', None)
                if q:
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except Exception:
                            break
        self._notify_transport("_start")

    def on_continue(self) -> None:
        """MIDI Continue received — resumes from current position without
        resetting the tick counter (unlike Start)."""
        self._running = True
        self._notify_transport("_continue")

    def on_stop(self) -> None:
        """MIDI Stop received."""
        self._running = False
        self._notify_transport("_stop")

    def _notify_transport(self, event: str) -> None:
        """Queue a transport event to all subscribed plugin threads."""
        with self._lock:
            for instance, _ in self._subscribers:
                if not instance.running:
                    continue
                q = getattr(instance, '_tick_queue', None)
                if q is not None:
                    try:
                        q.put_nowait(event)
                        pipe = getattr(instance, '_tick_pipe', None)
                        if pipe:
                            try:
                                os.write(pipe[1], b'\x01')
                            except OSError:
                                pass
                    except Exception:
                        pass
