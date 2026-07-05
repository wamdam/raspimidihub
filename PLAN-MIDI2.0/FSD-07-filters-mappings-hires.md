# FSD-07 — Filter/mapping engine at high resolution

**Step:** 3 · **Depends on:** FSD-03, FSD-06 · **Parallel with:** FSD-08
(coordinate on decision D1 client strategy)

## Status (2026-07-05): implemented (commit a7959c6)

- Main client flipped to midi_version=2 (not just the per-edge ports —
  they live on the main client); announce/hotplug/classic sends
  verified working on the v2 client (hotplug sim, test sender, panic).
- Golden equivalence implemented as *live pairwise tests* (legacy path
  vs UMP path over the full 7-bit domain, all 5 types + toggle
  sequences) instead of a committed fixture — the legacy code stays
  untouched as the reference. Mapped scalar outputs snap to legacy
  integer math for lattice inputs (§design), float MIDI units
  otherwise.
- Filter-group decision: **RPN/NRPN gate under "cc"**, per-note
  messages under a new **"midi2"** group (8th toggle, shipped);
  old all-allowing saved filters migrate to include it.
- Live-verified on A6DC end-to-end: LFO → filtered edge → Keystation;
  write-port tap shows 7-bit for a legacy reader and 32-bit for a
  UMP reader simultaneously.
- **Open:** fractional *entry* widgets in the mapping form (values
  render + persist; typing fractions rides with FSD-08's fine-value
  widgets). Perf guardrail: no regression observed at LFO rates;
  proper jitter measurement with the latency suite still owed before
  the Step 3 gate closes. Hi-res *source* verification needs 2.0
  hardware, as everywhere.

## Goal

Filtered/mapped edges stop being a resolution bottleneck: when both
endpoints of an edge are MIDI 2.0-capable, values traverse mappings at
full resolution. All 1.0 edges behave bit-identically to today. The
mapping editor accepts fractional values (decision D2) without changing
its layout or defaults.

## Non-goals

New mapping types (per-note controller mappings etc. — parked, README
open question 2). Group-aware channel masks beyond what's below. Plugin
edges (FSD-08).

## Current state

- `midi_filter.py`: `MappingType` L29 (5 types), `MidiMapping` L38
  (`cc_on_value=127`, ranges 0–127, `to_dict`/`from_dict` L69/96 land in
  config verbatim), `_scale_value` L122 (clamp 0–127 at L129),
  `MidiFilter` L241 (`channel_mask` 16-bit, `msg_types` from
  `ALL_MSG_TYPES` L24), `FilterEngine` L321: unfiltered edges = kernel
  subscriptions; filtered edges = per-edge userspace ports,
  `process_event()` L471, `_apply_mappings()` L528 (`velocity > 0`
  checks), `_forward_cc()` L518.
- Frontend: `panels/filterpanel.js` (16-ch grid), `panels/mappingform.js`
  (range wheels hardcoded 0–127, L187–246).
- Kernel behaviour to remember: with our per-edge clients at
  `midi_version=0`, the kernel *down-converts 2.0 traffic to 7-bit
  before we see it* — that is the bottleneck this FSD removes.

## Design

1. **Client flip (D1):** the FilterEngine's per-edge client(s) run at
   `midi_version=2` on capable kernels. All inbound events then arrive
   as MIDI 2.0-width (kernel up-converts 1.0 sources); outbound events
   are emitted as 2.0 and the kernel down-converts for 1.0 receivers.
   Consequence: `process_event`/`_apply_mappings` are rewritten against
   **one** internal width (32-bit ints at the edges, fractional MIDI
   units in mapping math via FSD-06), deleting the 7-bit clamps rather
   than duplicating paths. On non-UMP kernels the client stays legacy
   and a thin adapter feeds the same math with 7-bit-scaled values.
2. **Mapping semantics in fractional MIDI units:**
   - `MidiMapping` value fields become floats internally
     (`cc_on_value: float = 127.0` etc.). `from_dict` accepts int or
     float → **no config migration**; `to_dict` writes ints when the
     value is integral (keeps configs diff-friendly and 1.0-user-clean).
   - `_scale_value` maths in float, clamp to 0.0–127.0; conversion to
     wire width happens once at emit (FSD-06 `from_midi_units` →
     32-bit, or 7-bit on the legacy path).
   - `velocity > 0` note-on checks: in 2.0, vel-0 note-on is legal —
     but the kernel's 1.0→2.0 up-conversion already turns 1.0 vel-0
     note-ons into Note Offs, so `_apply_mappings` must key on the
     event *type*, not `velocity > 0`. Audit every velocity comparison.
   - `note_to_cc` with `cc_value_source="velocity"`: forwards the
     fractional velocity.
3. **New 2.0-only message handling in filtered edges:** RPN/NRPN atomic
   messages, per-note controllers, per-note bend, 32-bit
   pressure/bend **pass through** filtered edges unmodified (subject to
   the filter's msg-type groups: map RPN/NRPN into the existing `cc`
   filter group, per-note controllers into `aftertouch`?? — **decide
   during implementation and document in the manual**; recommendation:
   a new `MSG_FILTER_GROUPS` entry `midi2` is honest and keeps old
   groups' meanings stable, but check UI grid space in
   `filterpanel.js`). Mappings apply only to plain CC/note messages as
   today.
4. **Groups vs channel mask:** a UMP group port carries 16 channels —
   the existing `channel_mask` semantics hold per-port unchanged. The
   endpoint catch-all port (group-spanning) is hidden by FSD-03's
   presentation policy, so no 256-channel mask UI is needed. Assert
   this invariant in code (drop/log events whose group ≠ the port's
   group).
5. **Mapping editor (`mappingform.js`):** wheels gain fractional
   awareness only for display (step stays 1; typing `64.5` allowed).
   Defaults unchanged (127/0). No layout change.
6. **Perf guardrail:** filtered edges are the hot path on the isolated
   core. The rewrite must not add per-event allocations beyond today's;
   measure with the existing latency plugin / perf_stats before+after
   on A6DC (1.0 traffic) and confirm no regression.

## Config / API / manual impact

- Config: mapping value fields accept floats (accepting-int unchanged).
  Documented in `05-configuration…` + `10-filters-and-mappings.md` +
  `C-appendix-midi-mapping-reference.md` (fractional values, 2.0
  pass-through behaviour, the chosen filter-group answer).
- API: mappings endpoints (api.py L1266–1329) pass floats through —
  validation bounds update.

## Tests

- Rewrite-safety net **first**: capture current `_apply_mappings`
  behaviour as golden tests over the full 7-bit domain per mapping type
  (inputs 0–127 × the 5 types × edge configs) against the *old* code,
  then require identical results from the new code on the legacy path.
- New: hi-res pass-through, fractional scaling, vel-0/type-keying,
  RPN/NRPN filter-group behaviour, group invariant.
- `test_midi_filter.py`, `test_filter_pipeline.py`,
  `test_mapping_validation.py` extended, not replaced.

## UX verification (Step 3 gate)

1. 2.0 controller → filtered edge (channel filter active) → 2.0 synth:
   monitor at the destination shows fractional values preserved.
2. cc_to_cc mapping (range 0–127 → 20–100) between 2.0 endpoints:
   stepless sweep in the target range; same mapping with 1.0 devices
   behaves exactly as before this step.
3. note_to_cc velocity-source mapping from a 2.0 keyboard: CC follows
   16-bit velocity smoothly.
4. Regression sweep of all 5 mapping types with 1.0 hardware against
   the 5A5D reference Pi; latency measurement unchanged.
5. Mapping form: entering 64.5 works; existing mappings display as
   integers; save/load round-trips.
