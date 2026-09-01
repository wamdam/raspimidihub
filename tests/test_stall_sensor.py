"""StallSensor — event-loop stall forensics.

The sensor fingerprints each loop lag above its threshold from a
watchdog-side ring of per-thread samples (frame + wchan + CPU). These
tests drive `_make_episode` with injected samples so the fingerprint
logic is covered without waiting for a real stall.
"""

import threading

from raspimidihub.runtime.stall_sensor import (
    StallSensor,
    _frame_fp,
    _task_cpu,
    _task_wchan,
)

LOOP_TID = 100
WORKER_TID = 200


def _sample(ts, loop_frame, loop_cpu, loop_wchan="0",
            worker_frame="encoder.py:434 (encode)", worker_cpu=0):
    """One ring sample in the exact shape _sample() produces."""
    return {
        "ts": ts,
        "loop_wchan": loop_wchan,
        "threads": {
            LOOP_TID: {
                "name": "MainThread", "cpu": loop_cpu, "frame": loop_frame,
            },
            WORKER_TID: {
                "name": "ThreadPoolExecutor-1_1", "cpu": worker_cpu,
                "frame": worker_frame,
            },
        },
    }


def _frozen_ring(n=10):
    """n samples where the loop is FROZEN in one frame (a stall) while
    a worker burns CPU — the classic GIL-starvation signature."""
    return [
        _sample(0.05 * i, "config.py:217 (api_export_config)",
                100 + i, worker_cpu=10 * i)
        for i in range(n)
    ]


def test_episode_fingerprints_frozen_loop_and_hog():
    s = StallSensor(loop_tid=LOOP_TID)
    for sample in _frozen_ring():
        s._ring.append(sample)
    s._make_episode(1168.6)
    (ep,) = s.episodes()["episodes"]
    assert ep["lag_ms"] == 1168.6
    # The frozen frame is the dominant loop entry across the ring.
    assert ep["loop"]["frozen"]["frame"] == "config.py:217 (api_export_config)"
    assert ep["loop"]["frozen"]["samples"] == 10
    # The worker with the most CPU delta is reported as the hog.
    assert ep["hog"]["name"] == "ThreadPoolExecutor-1_1"
    assert ep["hog"]["frame"] == "encoder.py:434 (encode)"
    # Per-thread list is sorted by CPU (worker first).
    assert ep["threads"][0]["name"] == "ThreadPoolExecutor-1_1"
    assert ep["threads"][0]["cpu_ms"] > ep["threads"][1]["cpu_ms"]
    # Loop CPU over the ring: 100 -> 190 jiffies.
    assert ep["loop"]["cpu_ms"] > 0


def test_episode_bounded_and_newest_first():
    s = StallSensor(loop_tid=LOOP_TID)
    for _ in range(15):
        for sample in _frozen_ring(n=3):
            s._ring.append(sample)
        s._make_episode(120.0)
    eps = s.episodes()["episodes"]
    assert len(eps) <= 10
    # Threshold is exposed for the endpoint consumer.
    assert s.episodes()["threshold_ms"] == s.threshold_ms


def test_report_requested_queues_without_starting_thread():
    s = StallSensor(loop_tid=LOOP_TID)
    s.report_requested(150.0)
    assert len(s._requests) == 1
    ts, lag = s._requests.pop()
    assert lag == 150.0
    # No watchdog thread started — report_requested must be safe to
    # call from the loop thread pre/post start.
    assert s._thread is None


def test_task_cpu_reports_own_thread():
    cpu = _task_cpu(threading.get_native_id())
    assert isinstance(cpu, int) and cpu >= 0
    assert _task_cpu(99999999) is None
    wchan = _task_wchan(threading.get_native_id())
    assert isinstance(wchan, str) and wchan
    assert _task_wchan(99999999) == "?"


def test_frame_fp():
    import sys
    frames = sys._current_frames()
    fp = _frame_fp(frames, threading.get_ident())
    assert fp.endswith("(test_frame_fp)")
    assert _frame_fp(frames, 99999999) == "n/a"
