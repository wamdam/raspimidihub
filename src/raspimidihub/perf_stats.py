"""Performance statistics accumulators for the latency/jitter test suite.

Records timing samples (milliseconds) into per-metric histograms so the
perf harness can read distributions — p50/p95/p99/p999, min/max, mean,
stddev — not just a windowed max. Jitter and drift are measured against
the Pi's stable CLOCK_MONOTONIC (time.monotonic), so they are honest
even though the hub measures itself: they are *relative* timings, not
absolute wire latency (which would need external capture).

Hot-path safety is the whole point — instrumentation must not itself add
jitter. ``record()`` is one bucket lookup + a handful of integer/float
updates into preallocated arrays; no allocation, no locks. Under the GIL
the individual updates are atomic enough for statistics (a rare
interleave can miscount by one — irrelevant). Percentiles are computed
only at read time (``snapshot``), off the hot path.
"""

import contextlib
import math
import time

# Bucket upper edges in milliseconds. Fine in the sub-ms..few-ms range
# (where MIDI jitter lives), coarser above. A final implicit overflow
# bucket catches anything beyond the last edge.
_EDGES_MS = (
    0.01, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.75,
    1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0,
    20.0, 30.0, 50.0, 75.0, 100.0, 200.0, 500.0, 1000.0,
)


class Metric:
    """One named distribution of millisecond samples."""

    __slots__ = ("name", "unit", "_buckets", "count", "min", "max", "_sum", "_sumsq")

    def __init__(self, name: str, unit: str = "ms"):
        self.name = name
        self.unit = unit
        self._buckets = [0] * (len(_EDGES_MS) + 1)  # +1 overflow
        self.count = 0
        self.min = math.inf
        self.max = -math.inf
        self._sum = 0.0
        self._sumsq = 0.0

    def record(self, value_ms: float) -> None:
        """Add one sample. Hot path: bucket scan + scalar updates only."""
        # Linear scan is fine for ~25 edges and avoids bisect import cost.
        b = len(_EDGES_MS)
        for i, edge in enumerate(_EDGES_MS):
            if value_ms <= edge:
                b = i
                break
        self._buckets[b] += 1
        self.count += 1
        self._sum += value_ms
        self._sumsq += value_ms * value_ms
        if value_ms < self.min:
            self.min = value_ms
        if value_ms > self.max:
            self.max = value_ms

    def reset(self) -> None:
        for i in range(len(self._buckets)):
            self._buckets[i] = 0
        self.count = 0
        self.min = math.inf
        self.max = -math.inf
        self._sum = 0.0
        self._sumsq = 0.0

    def _percentile(self, frac: float) -> float:
        """Interpolated percentile from the cumulative bucket counts."""
        if self.count == 0:
            return 0.0
        target = frac * self.count
        cum = 0
        for i, c in enumerate(self._buckets):
            cum += c
            if cum >= target:
                lo = _EDGES_MS[i - 1] if i > 0 else 0.0
                hi = _EDGES_MS[i] if i < len(_EDGES_MS) else self.max
                # Linear interpolation within the bucket, capped at the
                # real max (the top bucket's edge can exceed it).
                prev_cum = cum - c
                frac_in = (target - prev_cum) / c if c else 0.0
                return round(min(lo + (hi - lo) * frac_in, self.max), 4)
        return round(self.max, 4)

    def snapshot(self) -> dict:
        n = self.count
        if n == 0:
            return {"name": self.name, "unit": self.unit, "count": 0}
        mean = self._sum / n
        var = max(0.0, self._sumsq / n - mean * mean)
        return {
            "name": self.name,
            "unit": self.unit,
            "count": n,
            "min": round(self.min, 4),
            "max": round(self.max, 4),
            "mean": round(mean, 4),
            "stddev": round(math.sqrt(var), 4),
            "p50": self._percentile(0.50),
            "p95": self._percentile(0.95),
            "p99": self._percentile(0.99),
            "p999": self._percentile(0.999),
            "buckets": list(self._buckets),
        }


# --- Global registry -----------------------------------------------------
# Metrics are created lazily on first record() so instrumentation sites
# stay one-liners. A plain dict; creation races are harmless (worst case a
# metric is created twice and one set of early samples is dropped).
_METRICS: dict[str, Metric] = {}


def record(name: str, value_ms: float) -> None:
    m = _METRICS.get(name)
    if m is None:
        m = _METRICS[name] = Metric(name)
    m.record(value_ms)


def reset_all() -> None:
    for m in _METRICS.values():
        m.reset()


def snapshot_all() -> dict:
    return {name: m.snapshot() for name, m in _METRICS.items()}


# Bucket edges, exposed so the harness can label histogram columns.
def bucket_edges_ms() -> list[float]:
    return list(_EDGES_MS)


def monotonic_ms() -> float:
    """Shared millisecond timebase for all instrumentation sites."""
    return time.monotonic() * 1000.0


@contextlib.contextmanager
def time_op(name: str):
    """Record the wall time spent in the block as metric ``name`` (ms).

    Used to time the *synchronous* part of an operation handler (add
    cable, change filter, …) — i.e. how long it blocks the asyncio loop.
    Because real operations self-measure this way, a hardware cable-add
    in normal use records its true cost, which a synthetic plugin-only
    connection in the harness cannot reproduce."""
    t0 = time.monotonic()
    try:
        yield
    finally:
        record(name, (time.monotonic() - t0) * 1000.0)
