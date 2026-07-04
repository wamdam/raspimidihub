# FSD-05 — High-resolution MIDI monitor & SSE

**Step:** 2 · **Depends on:** FSD-02/03 · **Parallel with:** FSD-04

## Goal

The first client flip of decision D1: the engine's **monitor** path runs
at `midi_version=2` (on capable kernels), so the UI monitor shows what a
MIDI 2.0 controller actually sends — 16-bit velocity, 32-bit CC, atomic
RPN/NRPN — displayed in fractional 0–127 MIDI units (decision D2).
Read-only; no routing or plugin behaviour changes.

## Non-goals

Filters/mappings (FSD-07), plugin dispatch (FSD-08), observatory CC
cache semantics beyond value width, test-sender hi-res (stays 7-bit
until FSD-08 gives the UI fine-value widgets).

## Current state

- Monitor port: `midi_engine.py` `start()` L213–218 — receives copies of
  all traffic. The pump `run_event_loop()` L809 dispatches to
  `__main__.py` `on_midi_event` L174–252 which builds the SSE
  `midi-activity` payload (`channel/note/velocity/cc/value/dst_clients`,
  throttled 10/s/port). `_track_cc_to_destinations` L1303 caches 0–127
  CC values for `GET /api/observatory` (api.py L658).
- Frontend consumers of `midi-activity` (all parse 7-bit fields):
  `app.js` L303–305 (header midi-bar), `panels/devicedetail.js`
  `formatEvent()` L355, `panels/mappingform.js`, `components/ccselect.js`,
  `components/noteselect.js`, cc/cell binding learn popups.
- SSE registry: `web.py` `SSE_EVENTS` L52.

## Design

1. **Client strategy (decide at implementation, both acceptable):**
   (a) flip the whole engine client to `midi_version=2` — every event
   arrives up-converted, monitor decodes UMP, and events the engine
   *sends* (panic, test messages) are built as UMP; or (b) a separate
   monitor-only seq client at `midi_version=2`, leaving the main client
   legacy until FSD-07. Recommendation: **(b)** — smallest blast radius
   for a step whose promise is "read-only", one extra client is cheap,
   and hotplug/announce handling stays where it is. Revisit merging in
   FSD-07.
2. **Normalization at the boundary:** decoded UMP events are normalized
   once into the internal fractional-MIDI-unit form (FSD-06 scaling:
   32-bit → float 0–127 with full precision kept for display; note that
   *display* rounding is a frontend concern). 1.0 events pass through
   with integer values as today.
3. **SSE payload (additive, per D2):** `midi-activity` keeps existing
   integer fields byte-compatible and adds, when hi-res, `velocity_f`,
   `value_f` (fractional MIDI units, ≤ 4 decimals) and `proto: 2`.
   New message kinds that have no 1.0 equivalent get typed entries:
   RPN/NRPN (`kind: "rpn"/"nrpn"`, `bank`, `index`, `value_f`), per-note
   controller / per-note bend (`kind`, `note`, `index`, `value_f`) —
   monitor-only display; nothing else consumes them yet. Any new SSE
   event type must be registered in `SSE_EVENTS`; here we extend the
   existing `midi-activity` payload instead — update its registry
   description.
4. **Monitor rendering:** `formatEvent()` shows fractional values only
   when `proto: 2` (`vel=100.53`, `cc74=63.998`, `RPN 0.0=+2.00`), keeps
   exact current strings for 1.0 traffic. Other `midi-activity`
   consumers (ccselect/noteselect/learn) read the integer fields —
   verify they ignore unknown fields (they do today — additive is safe;
   confirm each).
5. **Observatory:** cache stores the fractional value; API returns both
   `value` (int, compat) and `value_f`. UI observatory view shows
   fractional when present.

## Config / API / manual impact

- No config. API: additive fields on `midi-activity` + observatory.
- Manual: `06-interacting-with-the-web-ui.md` (monitor shows fractional
  2.0 values), `E-appendix-rest-and-sse-api.md` — update the
  `midi-activity` SSE registry description in `web.py` (the appendix
  documents the mechanism; the registry line is the doc).

## Tests

- UMP→SSE payload unit tests with golden packets (velocity 0x8000 →
  64.0; CC 0x8C30C30C → 70.0…; RPN kinds).
- Throttling still applies per port regardless of protocol.
- Regression: 1.0 event payloads byte-identical to today
  (snapshot-style asserts in tests).

## UX verification (Step 2 gate, together with FSD-04)

1. Turn a knob on a 2.0 controller: monitor shows smoothly changing
   fractional CC values; velocity shows decimals; RPN messages appear
   as single readable rows (not 4 CC rows).
2. Same gestures from a 1.0 controller: output identical to before this
   step (compare against the 5A5D reference Pi).
3. Header midi-bar, learn popups, cc/note pickers all behave unchanged
   with both device generations.
4. Non-UMP kernel: everything identical to pre-step behaviour.
