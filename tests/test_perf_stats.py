"""perf_stats accumulator: histogram percentiles + reset."""

import raspimidihub.perf_stats as ps


def test_percentiles_and_summary():
    m = ps.Metric("t")
    for v in range(1, 101):          # 1..100 ms uniform
        m.record(float(v))
    snap = m.snapshot()
    assert snap["count"] == 100
    assert snap["min"] == 1.0
    assert snap["max"] == 100.0
    assert 45 <= snap["p50"] <= 55          # ~median
    assert snap["p99"] >= 90                 # tail near the top
    assert snap["p95"] <= snap["p99"] <= snap["max"]


def test_reset_clears():
    m = ps.Metric("t")
    m.record(5.0)
    m.reset()
    assert m.snapshot() == {"name": "t", "unit": "ms", "count": 0}


def test_registry_record_and_snapshot_all():
    ps.reset_all()
    ps.record("metricA", 2.0)
    ps.record("metricA", 4.0)
    snap = ps.snapshot_all()
    assert snap["metricA"]["count"] == 2
    assert snap["metricA"]["mean"] == 3.0
    ps.reset_all()
    assert ps.snapshot_all()["metricA"]["count"] == 0
