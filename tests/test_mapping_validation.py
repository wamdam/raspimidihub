"""Parametrized matrix for the mapping add/duplicate/pointless rules.

Rules (as agreed):
  - REJECT an exact duplicate — every behavior-affecting field matches an
    existing mapping of the same type.
  - REJECT a pointless single mapping (no audible effect on its own):
      * CC→CC with same src+dst channel, same src+dst CC, identity scaling.
      * Channel-map with src_channel == dst_channel.
  - ALLOW everything else. In particular: fan-out to different dst channel,
    fan-out to different dst CC, and same-to-same with non-identity scaling
    are all legitimate.
"""

import pytest

from raspimidihub.midi_filter import (
    MappingType, MidiMapping, validate_new_mapping,
)


# ---------------------------------------------------------------------------
# Factories — keep tests short and readable.
# ---------------------------------------------------------------------------

def cc(src_ch=0, src_cc=1, dst_ch=0, dst_cc=10,
       in_min=0, in_max=127, out_min=0, out_max=127,
       pass_through=False):
    return MidiMapping(
        type=MappingType.CC_TO_CC,
        src_channel=src_ch, src_cc=src_cc,
        dst_channel=dst_ch, dst_cc_num=dst_cc,
        in_range_min=in_min, in_range_max=in_max,
        out_range_min=out_min, out_range_max=out_max,
        pass_through=pass_through,
    )


def note(src_ch=0, src_note=60, dst_ch=0, dst_cc=10,
         cc_on=127, cc_off=0, pass_through=False,
         toggle=False):
    return MidiMapping(
        type=MappingType.NOTE_TO_CC_TOGGLE if toggle else MappingType.NOTE_TO_CC,
        src_channel=src_ch, src_note=src_note,
        dst_channel=dst_ch, dst_cc=dst_cc,
        cc_on_value=cc_on, cc_off_value=cc_off,
        pass_through=pass_through,
    )


def chmap(src_ch=0, dst_ch=5):
    return MidiMapping(
        type=MappingType.CHANNEL_MAP,
        src_channel=src_ch, dst_channel=dst_ch,
    )


# ---------------------------------------------------------------------------
# CC→CC matrix
# ---------------------------------------------------------------------------

class TestCcToCcMatrix:
    """Existing: src_ch=8, src_cc=1, dst_ch=0, dst_cc=10 (identity scaling)."""

    EXISTING = cc(src_ch=8, src_cc=1, dst_ch=0, dst_cc=10)

    @pytest.mark.parametrize("new,expect_error", [
        # Exact duplicate → REJECT
        pytest.param(cc(8, 1, 0, 10), True, id="exact-duplicate"),
        # Same src+dst, different scaling → ALLOW (value-shape variant)
        pytest.param(cc(8, 1, 0, 10, out_max=63), False, id="same-src-dst-different-out-range"),
        pytest.param(cc(8, 1, 0, 10, in_min=10, in_max=117), False, id="same-src-dst-different-in-range"),
        # Different dst_cc → ALLOW (fan-out to 2nd CC same ch)
        pytest.param(cc(8, 1, 0, 11), False, id="fan-out-different-dst-cc"),
        # Different dst_ch → ALLOW (fan-out to same CC, different ch — user's case)
        pytest.param(cc(8, 1, 2, 10), False, id="fan-out-different-dst-ch"),
        # Totally different dst → ALLOW
        pytest.param(cc(8, 1, 2, 11), False, id="fan-out-different-dst-ch-and-cc"),
        # Different src_cc → ALLOW
        pytest.param(cc(8, 2, 0, 10), False, id="different-src-cc"),
        # Different src_ch → ALLOW
        pytest.param(cc(9, 1, 0, 10), False, id="different-src-ch"),
        # Different pass_through → ALLOW
        pytest.param(cc(8, 1, 0, 10, pass_through=True), False, id="different-pass-through"),
    ])
    def test_matrix(self, new, expect_error):
        err = validate_new_mapping([self.EXISTING], new)
        if expect_error:
            assert err, f"expected rejection, got None"
        else:
            assert err is None, f"expected allow, got: {err!r}"


class TestCcToCcPointless:
    """Standalone pointless checks (no existing mappings)."""

    def test_same_ch_same_cc_identity_scaling_rejected(self):
        err = validate_new_mapping([], cc(src_ch=8, src_cc=5, dst_ch=8, dst_cc=5))
        assert err and "no effect" in err.lower()

    def test_same_ch_same_cc_different_out_range_allowed(self):
        err = validate_new_mapping([],
            cc(src_ch=8, src_cc=5, dst_ch=8, dst_cc=5, out_min=40, out_max=100))
        assert err is None, err

    def test_same_ch_same_cc_different_in_range_allowed(self):
        err = validate_new_mapping([],
            cc(src_ch=8, src_cc=5, dst_ch=8, dst_cc=5, in_min=10, in_max=117))
        assert err is None, err

    def test_dst_channel_none_falls_back_to_src_channel(self):
        """dst_channel=None + dst_cc=src_cc + identity curve == no-op."""
        m = MidiMapping(
            type=MappingType.CC_TO_CC,
            src_channel=8, src_cc=5,
            dst_channel=None, dst_cc_num=None,
        )
        err = validate_new_mapping([], m)
        assert err and "no effect" in err.lower()


# ---------------------------------------------------------------------------
# Note→CC matrix (both NOTE_TO_CC and NOTE_TO_CC_TOGGLE)
# ---------------------------------------------------------------------------

class TestNoteToCcMatrix:
    """Existing: src_ch=0, src_note=60, dst_ch=0, dst_cc=74."""

    EXISTING = note(src_ch=0, src_note=60, dst_ch=0, dst_cc=74)

    @pytest.mark.parametrize("new,expect_error", [
        pytest.param(note(0, 60, 0, 74), True, id="exact-duplicate"),
        pytest.param(note(0, 60, 0, 75), False, id="fan-out-different-dst-cc"),
        pytest.param(note(0, 60, 1, 74), False, id="fan-out-different-dst-ch"),
        pytest.param(note(0, 60, 1, 75), False, id="fan-out-different-dst-ch-and-cc"),
        pytest.param(note(0, 61, 0, 74), False, id="different-src-note"),
        pytest.param(note(1, 60, 0, 74), False, id="different-src-ch"),
        pytest.param(note(0, 60, 0, 74, cc_on=64), False, id="different-on-value"),
        pytest.param(note(0, 60, 0, 74, cc_off=32), False, id="different-off-value"),
        pytest.param(note(0, 60, 0, 74, pass_through=True), False, id="different-pass-through"),
    ])
    def test_matrix(self, new, expect_error):
        err = validate_new_mapping([self.EXISTING], new)
        if expect_error:
            assert err
        else:
            assert err is None, err

    def test_note_to_cc_and_toggle_are_not_duplicates(self):
        """Same (note, dst) but one toggle, one plain — different types, allowed."""
        existing = note(0, 60, 0, 74, toggle=False)
        new = note(0, 60, 0, 74, toggle=True)
        assert validate_new_mapping([existing], new) is None


# ---------------------------------------------------------------------------
# Channel-map matrix
# ---------------------------------------------------------------------------

class TestChannelMapMatrix:
    """Existing: src_ch=2, dst_ch=0."""

    EXISTING = chmap(src_ch=2, dst_ch=0)

    @pytest.mark.parametrize("new,expect_error", [
        pytest.param(chmap(2, 0), True, id="exact-duplicate"),
        pytest.param(chmap(2, 5), False, id="fan-out-to-different-dst-ch"),
        pytest.param(chmap(3, 0), False, id="different-src-ch"),
        pytest.param(chmap(3, 5), False, id="different-src-and-dst"),
    ])
    def test_matrix(self, new, expect_error):
        err = validate_new_mapping([self.EXISTING], new)
        if expect_error:
            assert err
        else:
            assert err is None, err

    def test_src_equals_dst_pointless(self):
        err = validate_new_mapping([], chmap(src_ch=5, dst_ch=5))
        assert err and "no effect" in err.lower()


# ---------------------------------------------------------------------------
# The exact regression the user hit
# ---------------------------------------------------------------------------

def test_regression_same_src_same_dst_cc_different_dst_channel():
    """
    User: existing ch9,cc1 -> ch1,cc10. Adding ch9,cc1 -> ch2,cc10 got rejected
    as duplicate. Must be allowed (fan-out across dst channels).
    """
    existing = cc(src_ch=8, src_cc=1, dst_ch=0, dst_cc=10)  # ch9,cc1 -> ch1,cc10 (0-indexed)
    new      = cc(src_ch=8, src_cc=1, dst_ch=1, dst_cc=10)  # ch9,cc1 -> ch2,cc10
    err = validate_new_mapping([existing], new)
    assert err is None, err


# ---------------------------------------------------------------------------
# Cross-type isolation
# ---------------------------------------------------------------------------

def test_different_types_never_duplicate():
    """A Note→CC and a CC→CC on superficially similar numbers don't collide."""
    existing = note(src_ch=0, src_note=60, dst_ch=0, dst_cc=74)
    new = cc(src_ch=0, src_cc=60, dst_ch=0, dst_cc=74)
    assert validate_new_mapping([existing], new) is None
    assert validate_new_mapping([new], existing) is None
