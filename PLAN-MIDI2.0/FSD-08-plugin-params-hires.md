# FSD-08 — Plugin param binding & UI controls at high resolution

**Step:** 4 · **Depends on:** FSD-03, FSD-06 (FSD-07 recommended first
for the D1 pattern) · **Parallel with:** FSD-10

## Status (2026-07-05): implemented

- Plugin clients run at midi_version=2 on capable systems; inbound UMP
  is shimmed via ump.to_monitor_shim (SKIP_EVENT sentinel keeps the
  drain loop honest), so plugins keep the 0-127 API (D3) and dispatch
  code is unchanged except the CC-binding walk.
- _cc_to_param: lattice inputs use the legacy integer math verbatim
  (unit-tested over the full domain); off-lattice inputs map in float.
  New `fine`/`decimals` flags on Param (schema-exported); fine params
  round to their declared decimals, shipped on CC LFO Depth + Center.
- Fader UI steps/displays at fine precision; renderparam passes the
  flags. Learn already works via the FSD-05 monitor shims.
- Live on A6DC: fake_midi2_synth CC75 → cc_lfo depth tracks
  fractionally (126.9 → 114.8 → 79.9), zero errors; 1.0 path
  byte-identical by golden tests.
- **Deferred:** wheel per-integer-tick threshold for very large ranges
  (fine params keep 0-127 ranges, so not yet needed); knob/wheel fine
  display (fader was the shipped candidate); plugin-param SSE floats
  work via the untouched pass-through payloads.

## Goal

CC automation of plugin parameters uses the controller's full
resolution: a 2.0 endless encoder bound to a filter-cutoff param sweeps
it smoothly instead of in 1/128 steps. Web UI value widgets stay usable
for fine-grained params. Plugin API remains 0–127-compatible (D3).

## Non-goals

Plugins *emitting* hi-res (FSD-09). New param types. Tracker pattern
format (README open question 3).

## Current state

- `plugin_host/host.py`: `_dispatch_event()` L507 → CC-binding walk
  L524–540 matches CONTROLLER events against instance `cc_map`;
  `_cc_to_param()` L567: `value = pmin + (cc_value / 127) * (pmax -
  pmin)` (or Radio index). This one function is where resolution dies.
- `plugin_host/alsa_client.py`: per-instance client `PluginAlsaClient`
  L28 — currently legacy; its inbound side feeds `_dispatch_event`.
- `plugin_api.py`: `Wheel`/`Knob`/`Fader` default `min=0,max=127`
  (L74–141) with `default_cc` seeds; `PluginBase` L701.
- Learn flow: api.py `_cc_learn_observe` L410, routes L2398/2430/2442,
  `PUT …/cc-map/…` L2709.
- Frontend: `components/renderparam.js` (range from manifest),
  `ui/plugin-params.js` (rAF-coalesced PATCH), `wheel.js` **one tick per
  integer value** L225, `ccbinding.js` wheel 0–127 L296,
  `cellbinding.js` L314, `curveeditor.js` 128-point hardcode.

## Design

1. **Client flip:** plugin-host inbound handling runs `midi_version=2`
   on capable kernels (same D1 pattern as FSD-07; whether it's one
   client per instance as today or the shared host client depends on
   FSD-07's outcome — keep the per-instance client model, just
   versioned).
2. **`_cc_to_param` at full resolution:** incoming CC arrives 32-bit →
   normalize 0.0–1.0 (FSD-06) → `value = pmin + t * (pmax - pmin)`.
   Params whose declared range is integral keep snapping to ints
   (today's behaviour); **new opt-in param flag `fine=True`** on
   Wheel/Knob/Fader lets a plugin declare float-valued params that take
   the full resolution (stored as floats in `params` config — additive,
   no migration). Radio/NoteSelect/Button semantics unchanged (they
   quantize anyway).
3. **Bidirectional sync:** where controller feedback exists (cc_map
   echo, controller templates), emitting back uses the source's width —
   handled in FSD-09; this FSD only receives.
4. **Learn flow:** `_cc_learn_observe` must recognize 2.0 CC events
   (post-FSD-05 monitor normalization) — learn captures `{ch, cc}`
   exactly as today; no schema change.
5. **Web UI widgets:**
   - `wheel.js`: tick rendering switches to a fixed tick count above a
     range threshold (e.g. >128 span or non-integer step) — fixes the
     per-integer-tick blowup (L225) generically, needed for `fine`
     params.
   - `renderparam.js`/`plugin-params.js`: float-valued params render
     with sensible precision (from a `decimals` hint on the param,
     default 2 for `fine`); PATCH carries floats.
   - `ccbinding.js`/`cellbinding.js`: unchanged (CC numbers are still
     0–127 in 2.0). `curveeditor.js`: unchanged this step (curves stay
     128-point 7-bit editors; applying a curve to hi-res input
     interpolates between points — implemented where curves are
     evaluated, e.g. velocity plugins in FSD-09).
6. **SSE:** `plugin-param` events carry floats for `fine` params
   (additive; registry description updated in `web.py`).

## Config / API / manual impact

- Config: `params` values may be floats for `fine` params (older builds
  loading such a config would truncate — call this out in CHANGELOG;
  acceptable, config `version` key exists for gating if needed).
- API: plugin instance PATCH accepts floats for `fine` params.
- Manual: `11-plugins.md` "CC Automation" (hi-res behaviour, `fine`),
  `08-ui-controls.md` (fractional display, wheel ticks),
  `A-appendix-plugin-reference.md` (param tables gain `fine` column
  where used — only when FSD-09 actually flips plugins to use it).

## Tests

- `test_cc_binding.py` extended: 32-bit CC → param value precision;
  integral params still snap; Radio indexing; learn with 2.0 events.
- Golden regression: 7-bit CC in → identical param values as today for
  every existing plugin manifest.
- Frontend: wheel tick-count logic is pure — extract and unit-test if
  practical, else cover via screenshot scene.

## UX verification (Step 4 gate)

1. Bind a 2.0 controller knob to a `fine` param (ship one candidate:
   e.g. cc_lfo rate) → sweep is visibly smooth in the UI and audibly
   smooth downstream; the same binding from a 1.0 controller steps in
   128 increments as expected.
2. All existing bindings (1.0 controllers, `default_cc` templates)
   behave identically to before.
3. Learn flow works from both 1.0 and 2.0 controllers.
4. Wheel/knob widgets on fine params: usable drag resolution, readable
   value display, no tick-render slowdown.
