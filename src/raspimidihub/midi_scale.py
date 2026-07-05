"""MIDI value-resolution scaling (M2-115-U v1.0.2 + M2-104 App. D).

Two spec-mandated conversion families:

- **Min-center-max** (`scale_up` / `scale_down`): the default for
  velocity, pressure, pitch bend, CC and NRPN data. min→min, max→max,
  center→center, and `scale_down(scale_up(x)) == x` for every x.
  Upscaling fills the low bits with an expanded bit-repeat of the
  source's lower bits so values ramp smoothly to all-ones at max;
  downscaling is plain truncation.
- **Zero-extension** (`scale_up_zero_ext` / `scale_down_rounding`):
  for Registered Controller (RPN) data with index 0-31 — fixed-point
  unit values (pitch bend sensitivity, tuning, MPE config) where
  min-center-max would inject noise (spec's ⅓-cent example).

Plus the hub's user-facing value scale (decision D2): fractional
"MIDI units" 0.0–127.0 with center 64.0, piecewise-linear so that
every min-center-max-upscaled integer maps back to (approximately)
itself, and the ALSA pitch-bend convention helpers (ALSA classic
events carry SIGNED bend −8192..+8191; wire/UMP forms are unsigned).

Kernel-verified vector: the ALSA sequencer up-converts 7-bit velocity
100 → 0xC924 (observed live on the A6DC Pi), matching `scale_up(100,
7, 16)` exactly.

Pure functions, no I/O — everything here is unit-tested exhaustively.
"""


def scale_up(val: int, src_bits: int, dst_bits: int) -> int:
    """Min-center-max upscale (M2-115-U §3). Requires dst >= src."""
    if dst_bits == src_bits:
        return val
    if src_bits == 1:  # spec special case: 0 -> 0, 1 -> all-ones
        return (1 << dst_bits) - 1 if val else 0
    scale = dst_bits - src_bits
    center = 1 << (src_bits - 1)
    shifted = val << scale
    if val <= center:
        return shifted
    repeat_bits = src_bits - 1
    repeat = val & ((1 << repeat_bits) - 1)
    if scale > repeat_bits:
        repeat <<= scale - repeat_bits
    else:
        repeat >>= repeat_bits - scale
    while repeat:
        shifted |= repeat
        repeat >>= repeat_bits
    return shifted


def scale_down(val: int, src_bits: int, dst_bits: int) -> int:
    """Min-center-max downscale: truncation (round-trip stable)."""
    if dst_bits >= src_bits:
        return scale_up(val, src_bits, dst_bits)
    return val >> (src_bits - dst_bits)


def scale_up_zero_ext(val: int, src_bits: int, dst_bits: int) -> int:
    """Zero-extension upscale: plain left shift (RPN index 0-31)."""
    return val << (dst_bits - src_bits)


def scale_down_rounding(val: int, src_bits: int, dst_bits: int) -> int:
    """Zero-extension downscale: round-half-up, clamped."""
    scale = src_bits - dst_bits
    if scale <= 0:
        return scale_up_zero_ext(val, src_bits, dst_bits)
    shifted = (val + (1 << (scale - 1))) >> scale
    max_val = (1 << dst_bits) - 1
    return max_val if shifted > max_val else shifted


def rpn_uses_zero_extension(index: int) -> bool:
    """True for Registered Controller data that must use the
    zero-extension family: the classic unit-valued RPNs live at index
    (LSB) 0-31; indexes 32-127 (and all NRPNs) use min-center-max."""
    return index < 32


# --- Velocity (spec App. D edge cases as named helpers) ---

def vel7_to_vel16(vel: int) -> int:
    """1.0 → 2.0 note-on velocity. Callers must map 1.0 vel-0
    note-ons to a MIDI 2.0 Note OFF *before* scaling — that rule is
    message-level, not value-level."""
    return scale_up(vel, 7, 16)


def vel16_to_vel7(vel16: int) -> int:
    """2.0 → 1.0 note-on velocity: a result of 0 must become 1 (a
    vel-0 note-on would mean note-off to a 1.0 receiver)."""
    return max(1, scale_down(vel16, 16, 7))


# --- Pitch bend (ALSA classic events are SIGNED −8192..+8191) ---

BEND14_CENTER = 0x2000
BEND32_CENTER = 0x8000_0000


def bend32_from_alsa(value: int) -> int:
    """ALSA signed bend (−8192..+8191) → 32-bit unsigned UMP bend."""
    return scale_up(value + BEND14_CENTER, 14, 32)


def alsa_from_bend32(value32: int) -> int:
    """32-bit unsigned UMP bend → ALSA signed bend."""
    return scale_down(value32, 32, 14) - BEND14_CENTER


# --- Fractional MIDI units (decision D2): 0.0 .. 127.0, center 64.0 ---
#
# Piecewise-linear with the same three anchors as min-center-max
# (min/center/max), so an upscaled integer reads back as itself:
# to_midi_units(scale_up(v, 7, bits), bits) ≈ float(v).

def to_midi_units(val: int, bits: int = 32) -> float:
    center = 1 << (bits - 1)
    if val <= center:
        return val * 64.0 / center
    top = (1 << bits) - 1
    return 64.0 + (val - center) * 63.0 / (top - center)


def lattice_interp(units: float, src_bits: int = 7, dst_bits: int = 32) -> int:
    """Float MIDI units → dst-width value that truncates back to
    int(units) at src_bits width.

    For hub-side generators (CC LFO etc.) whose legacy code cast with
    int(): MIDI 1.0 receivers keep seeing exactly the old truncated
    values, while 2.0 receivers get the fractional part interpolated
    within the lattice bucket. Monotonic; clamped to the valid range.
    """
    top = (1 << src_bits) - 1
    units = min(float(top), max(0.0, units))
    b = int(units)
    if b >= top:
        return (1 << dst_bits) - 1
    lo = scale_up(b, src_bits, dst_bits)
    # Interpolate only up to the truncation-bucket end — above the
    # center the next lattice point sits past the bucket boundary and
    # crossing it would truncate to b+1.
    end = (b + 1) << (dst_bits - src_bits)
    return lo + int((units - b) * (end - lo))


def from_midi_units(units: float, bits: int = 32) -> int:
    units = min(127.0, max(0.0, units))
    center = 1 << (bits - 1)
    if units <= 64.0:
        return round(units * center / 64.0)
    top = (1 << bits) - 1
    return center + round((units - 64.0) * (top - center) / 63.0)
