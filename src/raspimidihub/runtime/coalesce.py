"""Trailing-edge coalescer for rate-limited last-value-wins streams.

Producers (plugin threads, ALSA reader, etc.) submit (key, value) updates
at any rate. A periodic consumer flushes the queue — the latest value per
key is delivered to the emit callback; older intermediate values are
dropped. This caps the downstream event rate while still guaranteeing the
freshest value reaches the consumer within one flush interval of input
ceasing — which the naive "throttle" pattern does NOT (a fader stopping
between two throttle windows leaves the UI on a stale value forever).

Use cases in this codebase:
- plugin param updates: a sweeping hardware fader fanned out to multiple
  Controller plugins listening on the same CC range used to push 1000+
  SSE events/s. Coalesced at 20 Hz per (instance, name) → ~80 events/s
  with the trailing value still landing.
- plugin display outputs (meter, scope) — same shape, plugin-driven.
- midi-activity broadcasts per source port — also same shape.

Threading model: producers write under a lock; flush() drains under the
same lock. The emit callback is invoked OUTSIDE the lock so it can do
slow I/O (SSE fan-out, etc.) without blocking producers.
"""

from __future__ import annotations

import threading
from collections.abc import Hashable
from typing import Any, Callable


class TrailingCoalescer:
    """Last-value-wins coalescer + dedup.

    Producer side (any thread):
      coalescer.submit(key, value)        # queue, latest value wins
      coalescer.emit_now(key, value, em)  # bypass queue (state transitions)

    Consumer side (typically driven by an asyncio task at fixed cadence):
      coalescer.flush(emit_callback)      # drain + dispatch

    Dedup: a value identical to the last emitted value for the same key
    is dropped — applies on both submit/flush and emit_now paths.
    """

    __slots__ = ("_pending", "_sent", "_lock")

    def __init__(self) -> None:
        self._pending: dict[Hashable, Any] = {}
        self._sent: dict[Hashable, Any] = {}
        self._lock = threading.Lock()

    def submit(self, key: Hashable, value: Any) -> None:
        """Queue the latest value for key. Older queued values for the
        same key are overwritten — the most recent submit always wins."""
        with self._lock:
            self._pending[key] = value

    def flush(self, emit: Callable[[Hashable, Any], None]) -> None:
        """Drain pending updates. For each key whose queued value
        differs from its last-emitted value, emit(key, value) is
        called. Identical values are deduped; older queued values
        are dropped (only the freshest survives). Emit is invoked
        outside the lock."""
        with self._lock:
            if not self._pending:
                return
            snapshot = self._pending
            self._pending = {}
            new_sent = {}
            to_emit = []
            for key, value in snapshot.items():
                if self._sent.get(key) == value:
                    continue
                new_sent[key] = value
                to_emit.append((key, value))
            self._sent.update(new_sent)
        for key, value in to_emit:
            emit(key, value)

    def emit_now(
        self,
        key: Hashable,
        value: Any,
        emit: Callable[[Hashable, Any], None],
    ) -> None:
        """Bypass the queue and emit synchronously; stamp _sent so
        future submits with the same value get deduped, and clear
        any pending queued value for the same key. Use this for
        state-machine transitions (DropButtonRow drops.action cycling
        through fire / capture / idle, trigger button press→release)
        where every change must reach the UI."""
        with self._lock:
            if self._sent.get(key) == value:
                return
            self._sent[key] = value
            self._pending.pop(key, None)
        emit(key, value)

    def forget(self, key: Hashable) -> None:
        """Drop tracking for a key that no longer exists — used on
        plugin instance teardown so stale dedup state doesn't leak."""
        with self._lock:
            self._pending.pop(key, None)
            self._sent.pop(key, None)
