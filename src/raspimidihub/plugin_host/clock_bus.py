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
    """Counts incoming MIDI clock ticks and fires on_tick() at musical divisions.

    Also exposes a bar counter for plugins that need to schedule on
    musical-bar boundaries (e.g. drop-button "fire after 1 bar"):
    `bar_position()` returns `(bar, tick_in_bar, ticks_per_bar)` so
    plugins can compute "ticks until next bar". Time signature is
    fixed at 4/4 (96 ticks/bar at 24 PPQN); a future Master Clock
    `time_signature` param can feed `_ticks_per_bar` if odd-time
    material is needed.
    """

    # 24 PPQN × 4 quarters = 96 ticks per bar in 4/4. Plugins read
    # this via bar_position() rather than hard-coding so a future
    # time_signature param can change it.
    TICKS_PER_BAR_DEFAULT = 96

    def __init__(self):
        self._tick_count = 0
        self._running = False  # transport running (Start received)
        # Many MIDI clock masters keep sending clock ticks even after a
        # Stop message — that's how Continue can resume from where Stop
        # left off. Without this flag, the auto-start logic in
        # on_clock_tick would flip _running back to True on the very
        # next tick, masking the Stop. Set on Stop, cleared on Start /
        # Continue. Only suppresses auto-start; it does NOT block tick
        # delivery to subscribers (plugins keep getting their division
        # callbacks regardless).
        self._stopped_explicitly = False
        self._subscribers: list[tuple[PluginInstance, set[str]]] = []
        self._lock = threading.Lock()
        self._ticks_per_bar = self.TICKS_PER_BAR_DEFAULT
        # Optional callback fired once per musical quarter (24 ticks at
        # 24 PPQN) AND on every transport change (start / continue /
        # stop). Used by __main__ to broadcast a clock-position SSE so
        # the Controller frontend can run its drop-button rings off
        # the live tick count and freeze them when the transport stops.
        # Signature: callback(tick_count: int, ticks_per_bar: int, running: bool).
        self._on_quarter_callback = None

    def subscribe(self, instance: PluginInstance, divisions: list[str]) -> None:
        with self._lock:
            self._subscribers.append((instance, set(divisions)))

    def unsubscribe(self, instance: PluginInstance) -> None:
        with self._lock:
            self._subscribers = [(i, d) for i, d in self._subscribers if i is not instance]

    def bar_position(self) -> tuple[int, int, int]:
        """Return `(bar, tick_in_bar, ticks_per_bar)` based on the
        running tick count.

        Bar 0 starts at tick 0 (the first tick after the most recent
        MIDI Start, or the very first tick if no Start was seen).
        `tick_in_bar` is in [0, ticks_per_bar). Reading is lock-free —
        the values may shift by a tick under concurrent on_clock_tick,
        which is fine for "ticks until next bar boundary" arithmetic
        (the caller rounds up to the boundary anyway)."""
        tc = self._tick_count
        tpb = self._ticks_per_bar
        bar = tc // tpb
        tick_in_bar = tc % tpb
        return (bar, tick_in_bar, tpb)

    def ticks_until_next_grid(self, every_n_bars: int = 1) -> int:
        """How many ticks until the next bar boundary that lies on the
        N-bar musical grid (quantised, NOT "from now").

            every_n_bars=1  → next bar boundary       (bars 0, 1, 2, 3, …)
            every_n_bars=4  → next 4-bar grid line    (bars 0, 4, 8, 12, …)
            every_n_bars=8  → next 8-bar grid line    (bars 0, 8, 16, …)

        The returned boundary is strictly in the future: pressing
        exactly on a grid line schedules to the NEXT one, never to
        the current tick. Used by Controller drop scheduling so
        "4 bars" reads as "wait for the next musical 4-bar downbeat",
        not "delay by 4 bars of wall time"."""
        n = max(1, every_n_bars)
        tc = self._tick_count
        tpb = self._ticks_per_bar
        current_bar = tc // tpb
        next_grid_bar = ((current_bar // n) + 1) * n
        return next_grid_bar * tpb - tc

    def on_clock_tick(self) -> None:
        """Called by the engine for each MIDI Clock message (24 PPQ).

        Queues tick divisions for plugin threads instead of calling
        on_tick directly — avoids blocking the asyncio event loop.
        """
        if not self._running and not self._stopped_explicitly:
            self._running = True
            self._tick_count = 0
            log.info("Clock bus: auto-started on first clock tick")
        self._tick_count += 1
        # Fire the quarter listener (broadcasts clock-position SSE) so
        # the frontend's drop-button rings can advance even when no
        # schedule is active. Cheap — one int compare + at most one
        # bound-method call per tick.
        if self._on_quarter_callback and self._tick_count % 24 == 0:
            self._fire_position_callback()
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
        self._stopped_explicitly = False
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
        self._fire_position_callback()

    def on_continue(self) -> None:
        """MIDI Continue received — resumes from current position without
        resetting the tick counter (unlike Start)."""
        self._running = True
        self._stopped_explicitly = False
        self._notify_transport("_continue")
        self._fire_position_callback()

    def on_stop(self) -> None:
        """MIDI Stop received. Setting _stopped_explicitly=True is what
        makes Stop sticky — many clock masters keep sending ticks after
        a Stop (so Continue can resume), and without this flag
        on_clock_tick's auto-start branch would silently flip _running
        back to True on the very next tick."""
        self._running = False
        self._stopped_explicitly = True
        self._notify_transport("_stop")
        # One final position event with running=False so the frontend
        # can freeze its always-running drop-button rings.
        self._fire_position_callback()

    def _fire_position_callback(self) -> None:
        """Fire the position listener (broadcasts clock-position SSE).
        Called from on_clock_tick on every quarter boundary AND from
        each transport-state change so the frontend always sees the
        latest (tick, running) tuple."""
        if not self._on_quarter_callback:
            return
        try:
            self._on_quarter_callback(
                self._tick_count, self._ticks_per_bar, self._running)
        except Exception:
            log.exception("on_quarter_callback failed")

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
