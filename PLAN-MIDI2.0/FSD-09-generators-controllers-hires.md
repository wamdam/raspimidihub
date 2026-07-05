# FSD-09 — Hi-res generation: plugins & controller templates

**Step:** 5 · **Depends on:** FSD-08 · **Parallel with:** FSD-10

## Status (2026-07-05): implemented (core), several adoptions deferred

- Send API: PluginAlsaClient.send_event accepts float MIDI units for
  CC value / note-on velocity — emitted as UMP at full width on v2
  clients via midi_scale.lattice_interp (floor-compatible: 1.0
  receivers see exactly the legacy int() projection, unit-tested as a
  truncation property over the whole units range); floats floor on
  legacy clients. Scheduled sends (send_event_at) stay int-only.
- cc_lfo emits float (dedup quantized to 0.01): live dual-tap on A6DC
  shows identical 7-bit ints on a legacy reader and off-lattice 32-bit
  on a UMP reader.
- **Deferred adoptions completed 2026-07-05:**
  `midi_scale.units_in_bucket(anchor, value)` positions a float
  trajectory inside a legacy-computed integer's truncation bucket —
  byte-compat by construction for ANY legacy rounding scheme. The
  shim's value_f/velocity_f snap 7-bit-lattice values to exact
  integers, and `PluginBase.wants_hires_input` (opt-in, D3) delivers
  float MIDI units to on_note_on / on_cc. Adopted: cc_smoother
  (stepless glide, legacy round() projection preserved),
  velocity_curve (curve interpolation between points),
  velocity_equalizer (compress/expand in float), pitch_cc
  (lossless pass-through). Live-verified: smoother glide off-lattice
  on a UMP tap, clean legacy ints on a 1.0 tap. Still 7-bit by
  design: controller templates (hardware-mirror byte-stability),
  sequencer pattern data.

## Goal

The hub's own MIDI *sources* can emit high resolution: CC-generating
plugins (LFO, smoother), velocity-transforming plugins, and the
software controller templates produce 32-bit CC / 16-bit velocity
toward 2.0-capable destinations. 1.0 destinations receive identical
output to today (kernel down-converts).

## Non-goals

Tracker pattern format (velocity stays 0–127 in patterns; README open
question 3). New plugins (e.g. an RPN sender) — candidates for later.
Per-note controller generation.

## Current state

- Send path: `plugin_host/host.py` `_start_instance()` L225–330 injects
  `_send_cc(ch, cc, value)` etc. over `PluginAlsaClient.send_event(_at)`
  (`alsa_client.py` L118/152) — all 7-bit ints today; rate limiter
  (1000 ev/s "DIN limit") at L118; CC coalescing `send_event_coalesced`
  (`alsa_seq.py` L673).
- Generators (annex 3 §4): `cc_lfo` (amplitude math 0–127, 10 hits),
  `cc_smoother` (5), `velocity_curve`/`velocity_equalizer` (curve math
  pure 7-bit), `arpeggiator`/`euclidean`/`chord_generator`/`tracker`
  (note velocity), `pitch_cc` (passes bend through).
- Controller templates: `controller_base.py` `_cell_value_to_cc()` L243
  (clamp 0–127), `_store_cc_into_cell` L253, xypad emit L281, `on_cc`
  sync L296, drop-scheduling `send_cc_at` L684; four `controller_*`
  plugins on top. (Per the LaunchControl-mirroring memory: hardware
  twins are 7-bit — templates must keep byte-identical behaviour when
  mirrored to 1.0 hardware.)

## Design

1. **Send API grows float variants, old signatures unchanged (D3):**
   `_send_cc(ch, cc, value)` accepts int 0–127 (exact today's semantics)
   or float (fractional MIDI units → 32-bit via FSD-06 when the client
   is UMP; rounded to 7-bit otherwise). Same for `_send_note_on`
   velocity. Zero changes required in plugins that don't care.
2. **Per-plugin adoption, smallest first:**
   - `cc_lfo`: compute the waveform in float (0.0–127.0 amplitude),
     emit floats. Biggest audible win (stepless slow sweeps).
   - `cc_smoother`: interpolate in float between received values
     (which arrive hi-res post-FSD-07/08 when the source is 2.0).
   - `velocity_curve`/`velocity_equalizer`: evaluate the 128-point
     curve with interpolation between points for hi-res input velocity;
     emit float velocity.
   - `pitch_cc`: bend↔CC conversions via FSD-06 helpers (and fix the
     signed-bend handling while there if still open).
   - Sequencer plugins (`tracker`, `arpeggiator`, `euclidean`,
     `chord_generator`): pattern-stored velocities stay 0–127; they
     emit ints — no change this step beyond confirming nothing breaks.
3. **Controller templates:** cell values remain 0–127 ints in cells and
   config (mirroring rule above), but `on_cc` *receiving* from a 2.0
   twin must round consistently, and xypad/fader emits may use floats
   internally for smoother drop-scheduling ramps. Explicitly verify a
   LaunchControl-XL-style 7-bit mirror round-trips without value drift
   (round-half consistency both directions).
4. **Rate limiting & coalescing:** hi-res sources produce *more distinct
   values*, not necessarily more events — but LFO/smoother step counts
   will rise. Keep the 1000 ev/s limiter; verify coalescing
   (`send_event_coalesced`) treats a hi-res CC stream correctly
   (coalesce key = (ch, cc), value replaced — width-agnostic; confirm).
5. **`cc_outputs` metadata:** unchanged (CC numbers, not widths).

## Config / API / manual impact

- Config: none (patterns/cells stay int).
- Manual: `11-plugins.md` + `A-appendix-plugin-reference.md` rows for
  each adopted plugin ("emits high resolution to MIDI 2.0
  destinations"), `12-controllers.md`/`B-appendix…` note on template
  mirroring behaviour, `13-play-surfaces.md` only if any surface
  behaviour visibly changes (should not).

## Tests

- Per-plugin `test_plugin.py` extensions: float emission values, curve
  interpolation vectors, int-path regression (7-bit in → identical
  bytes out as today).
- Controller mirror round-trip test (7-bit twin sync stability).
- Coalescing/rate-limit behaviour under a fast float LFO.

## UX verification (Step 5 gate)

1. Slow cc_lfo (e.g. 30 s sine) into a 2.0 synth's filter: audibly
   stepless; monitor shows fractional ramp. Same patch into a 1.0
   synth: identical to pre-step behaviour.
2. velocity_curve between a 2.0 keyboard and 2.0 synth: fine velocity
   gradations survive the curve.
3. Launch Control XL mirror workflow (per the standing user pattern):
   move hardware fader → software twin → hardware LED/state remains
   in perfect sync, no oscillation or off-by-one drift.
4. Full play-surface regression (tracker/arp/euclidean) on 1.0 gear.
