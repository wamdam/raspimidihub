# Latency / jitter perf harness

A developer/diagnostic harness that reads the hub's timing distributions
(`GET /api/stats`) and measures MIDI timing stability. Stdlib-only.

```
make perf TARGET=http://10.1.1.2                       # operations sweep (default)
make perf TARGET=http://10.1.1.2 PERF_ARGS="--mode passive --duration 3600"
make perf TARGET=http://10.1.1.2 PERF_ARGS="--mode both --out runs/box"
```

## What it measures

Hub-stats-only. Jitter and drift are measured against the Pi's stable
`CLOCK_MONOTONIC`, which is honest for *relative* timing. Absolute
input→wire latency needs external MIDI capture and is out of scope.

Metrics (via `/api/stats`, distributions with p50/p95/p99/p999/max):

- `loop_lag` — asyncio loop scheduling lag (the loop's responsiveness).
- `clock_tick_jitter` — per-tick deviation from the running tempo, on the
  clock bus.
- `plugin_note_jitter`, `net_midi_rx` — (further instrumentation; populated
  as those hooks land).

Plus a context snapshot (per-core CPU, temp) so spikes correlate with load.

## Modes

- **`ops`** (default) — operations-disturbance sweep. With a MIDI scene
  playing, it performs each disruptive operation one at a time
  (add plugin, add cable, change filter, save, load, remove plugin),
  resets stats, runs the op, lets it settle, and reads the jitter/lag it
  injected. Attributes each spike to its operation. **This is the
  latency-regression detector — run it after a change and watch for any
  operation's impact growing.**
- **`passive`** — start a scene, sample distributions over `--duration`
  seconds (multi-hour soak supported), report percentiles/histograms.
- **`both`** — ops sweep then passive.

`--out PREFIX` writes JSON reports (`PREFIX-ops.json`, `PREFIX-passive.json`).

## ⚠️ Never run `ops` against a live performance rig

The `ops` sweep **creates/deletes plugins and Saves/Loads config** on the
target. Use a dedicated test hub. `passive` also builds a temporary scene
(pass `--no-scene` to measure an existing setup read-only-ish).
