# FSD-06 — Bit-scaling library (`midi_scale.py`)

**Step:** 3 (needed from Step 2 onward; **start any time — zero
dependencies, ideal first parallel work package**)

## Goal

One small, exhaustively tested pure-Python module implementing the
spec-mandated value conversions (M2-115-U v1.0.2 + M2-104 Appendix D).
Every other FSD imports these; nobody re-implements scaling inline.

## Non-goals

No I/O, no ALSA, no event objects — pure integer/float math. Message-
*level* translation (RPN state machines etc.) lives with the codecs that
need it, not here.

## Current state

Nothing exists; `_scale_value` in `midi_filter.py` L122 does linear
0–127 range mapping (different job — stays). The exact algorithms with
worked values are in research annex 1 §3 — port the pseudocode verbatim.

## API (proposal)

```python
# midi_scale.py — all pure functions
def scale_up(val: int, src_bits: int, dst_bits: int) -> int
    # min-center-max with expanded bit-repeat (M2-115-U §3.1)
def scale_down(val: int, src_bits: int, dst_bits: int) -> int
    # truncation (round-trip stable with scale_up)
def scale_up_zero_ext(val: int, src_bits: int, dst_bits: int) -> int
    # plain left shift (RPN LSB 0–31 fields)
def scale_down_rounding(val: int, src_bits: int, dst_bits: int) -> int
    # round-half-up + clamp (RPN LSB 0–31 fields)

# fractional MIDI units (decision D2): the UI/config currency
def to_midi_units(val32: int) -> float      # 0.0 … 127.0, center 64.0
def from_midi_units(units: float) -> int    # inverse, clamped
# 14-bit variants for pitch bend (signed ALSA convention!)
def bend_to_units(...) / units_to_bend(...)
```

Selection rule helpers (`is_zero_extension_rpn(bank, index)`), and the
velocity edge cases as named helpers so call sites can't get them wrong:
`vel16_to_vel7(v)` (0 → 1 floor) and `vel7_to_vel16(v)`.

## Critical correctness notes (from the spec)

- min-center-max: `scale_down(scale_up(x)) == x` must hold for all x and
  all bit-width pairs — property-test it.
- Worked values to pin as test vectors (7→16): 0→0x0000, 32→0x4000,
  64→0x8000, 70→0x8C30, 96→0xC104, 120→0xF1C7, 127→0xFFFF; (7→32):
  70→0x8C30C30C, 127→0xFFFFFFFF; 1-bit: 0→0, 1→max.
- Zero-extension: 7-bit 127 → 16-bit **0xFE00** (not 0xFFFF) — mixing
  the two methods on RPN 0–31 injects audible detune (spec's ⅓-cent
  example).
- Velocity: 2.0→1.0 result 0 must become 1; 1.0 note-on vel 0 is a
  *message-level* rule (becomes 2.0 Note Off) — belongs to the codec,
  but document it here so nobody hunts for it.
- Pitch bend: ALSA classic events carry **signed −8192..+8191**; the
  wire/UMP forms are unsigned with center 0x2000/0x80000000. The
  existing `midi_codec.py` L139–142 ignores this (pre-existing bug
  candidate, annex 3 §2) — fixing that is in scope for whichever FSD
  first touches the codec (FSD-11), but the correct helpers live here.

## Tests

`tests/test_midi_scale.py`: all spec vectors above; round-trip property
tests across bit-width pairs (7↔16, 7↔32, 14↔32, 16↔32); monotonicity;
center preservation; clamping; velocity floor; zero-ext vs
min-center-max divergence cases. Fast, no fixtures — aim for exhaustive
7-bit domains (128 values × pairs is trivial).

## UX verification

None directly (pure library) — correctness is the test suite. Its UX
lands via FSD-05/07/08.
