"""midi_scale — spec vectors (M2-115-U) + exhaustive properties."""

import pytest

from raspimidihub import midi_scale as ms

PAIRS = [(7, 16), (7, 32), (14, 32), (16, 32), (14, 16)]


# --- Spec worked values (research annex 1 §3.1) ---

@pytest.mark.parametrize("val,expect", [
    (0, 0x0000), (32, 0x4000), (64, 0x8000), (70, 0x8C30),
    (96, 0xC104), (120, 0xF1C7), (127, 0xFFFF),
])
def test_spec_vectors_7_to_16(val, expect):
    assert ms.scale_up(val, 7, 16) == expect


def test_spec_vectors_7_to_32():
    assert ms.scale_up(70, 7, 32) == 0x8C30C30C
    assert ms.scale_up(127, 7, 32) == 0xFFFFFFFF


def test_kernel_verified_vector():
    # Observed live: ALSA seq up-converts 1.0 velocity 100 -> 0xC924
    assert ms.scale_up(100, 7, 16) == 0xC924


def test_one_bit_values():
    assert ms.scale_up(0, 1, 16) == 0
    assert ms.scale_up(1, 1, 16) == 0xFFFF


# --- Properties over full source domains ---

@pytest.mark.parametrize("src,dst", PAIRS)
def test_roundtrip_lossless(src, dst):
    for v in range(1 << min(src, 14)):
        assert ms.scale_down(ms.scale_up(v, src, dst), dst, src) == v


@pytest.mark.parametrize("src,dst", PAIRS)
def test_monotonic_and_anchors(src, dst):
    top_src, top_dst = (1 << src) - 1, (1 << dst) - 1
    center_src, center_dst = 1 << (src - 1), 1 << (dst - 1)
    assert ms.scale_up(0, src, dst) == 0
    assert ms.scale_up(center_src, src, dst) == center_dst
    assert ms.scale_up(top_src, src, dst) == top_dst
    if src <= 14:
        prev = -1
        for v in range(1 << src):
            cur = ms.scale_up(v, src, dst)
            assert cur > prev
            prev = cur


def test_equal_widths_identity():
    assert ms.scale_up(77, 7, 7) == 77
    assert ms.scale_down(77, 7, 7) == 77


# --- Zero-extension family ---

def test_zero_ext_up_is_shift():
    assert ms.scale_up_zero_ext(127, 7, 16) == 0xFE00  # NOT 0xFFFF
    assert ms.scale_up_zero_ext(64, 7, 16) == 0x8000


def test_zero_ext_down_rounds_half_up_and_clamps():
    assert ms.scale_down_rounding(0x8000, 16, 7) == 64
    assert ms.scale_down_rounding(0xFE00, 16, 7) == 127
    assert ms.scale_down_rounding(0xFFFF, 16, 7) == 127  # clamp
    # round-half-up: 0x01FF -> (511+256)>>9 = 1
    assert ms.scale_down_rounding(0x01FF, 16, 7) == 1


def test_zero_ext_roundtrip():
    for v in range(128):
        assert ms.scale_down_rounding(ms.scale_up_zero_ext(v, 7, 32), 32, 7) == v


def test_rpn_family_selector():
    assert ms.rpn_uses_zero_extension(0)      # pitch bend sensitivity
    assert ms.rpn_uses_zero_extension(31)
    assert not ms.rpn_uses_zero_extension(32)
    assert not ms.rpn_uses_zero_extension(127)


# --- Velocity helpers ---

def test_velocity_floor():
    assert ms.vel16_to_vel7(0x0001) == 1   # would truncate to 0
    assert ms.vel16_to_vel7(0x0000) == 1
    assert ms.vel16_to_vel7(0xFFFF) == 127
    for v in range(1, 128):
        assert ms.vel16_to_vel7(ms.vel7_to_vel16(v)) == v


# --- Pitch bend / ALSA sign convention ---

def test_bend_roundtrip_full_range():
    for v in range(-8192, 8192):
        assert ms.alsa_from_bend32(ms.bend32_from_alsa(v)) == v


def test_bend_anchors():
    assert ms.bend32_from_alsa(0) == ms.BEND32_CENTER
    assert ms.bend32_from_alsa(-8192) == 0
    assert ms.bend32_from_alsa(8191) == 0xFFFFFFFF


# --- Fractional MIDI units (D2) ---

@pytest.mark.parametrize("bits", [16, 32])
def test_units_anchor_points(bits):
    top = (1 << bits) - 1
    assert ms.to_midi_units(0, bits) == 0.0
    assert ms.to_midi_units(1 << (bits - 1), bits) == 64.0
    assert ms.to_midi_units(top, bits) == 127.0


@pytest.mark.parametrize("bits,tol", [(16, 5e-3), (32, 1e-6)])
def test_units_invert_scale_up(bits, tol):
    # 16-bit packets truncate the bit-repeat after ~1.5 blocks, so the
    # inversion is good to ~0.005 units; 32-bit is essentially exact.
    for v in range(128):
        units = ms.to_midi_units(ms.scale_up(v, 7, bits), bits)
        assert units == pytest.approx(float(v), abs=tol)


def test_units_roundtrip_and_clamp():
    for u in (0.0, 12.34, 63.999, 64.0, 64.001, 100.53, 127.0):
        back = ms.to_midi_units(ms.from_midi_units(u), 32)
        assert back == pytest.approx(u, abs=1e-6)
    assert ms.from_midi_units(-5) == 0
    assert ms.from_midi_units(200) == (1 << 32) - 1
