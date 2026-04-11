"""Tests for MIDI filter and mapping logic."""

from raspimidihub.alsa_seq import MidiEventType
from raspimidihub.midi_filter import (
    ALL_CHANNELS, ALL_MSG_TYPES, MappingType, MidiFilter, MidiMapping,
)

from helpers import make_event


# ---------------------------------------------------------------------------
# MidiMapping._scale_value
# ---------------------------------------------------------------------------

class TestScaleValue:
    def _make(self, in_min=0, in_max=127, out_min=0, out_max=127):
        return MidiMapping(
            type=MappingType.CC_TO_CC,
            in_range_min=in_min, in_range_max=in_max,
            out_range_min=out_min, out_range_max=out_max,
        )

    def test_identity(self):
        m = self._make()
        assert m._scale_value(64) == 64
        assert m._scale_value(0) == 0
        assert m._scale_value(127) == 127

    def test_scale_down(self):
        """CC1 0-127 -> CC7 0-63, value 100 should map to 50."""
        m = self._make(out_max=63)
        assert m._scale_value(100) == round(100 / 127 * 63)  # 50

    def test_scale_up(self):
        m = self._make(in_max=63, out_max=127)
        assert m._scale_value(32) == round(32 / 63 * 127)  # 65

    def test_inverted_range(self):
        """out_range 127-0 inverts the value."""
        m = self._make(out_min=127, out_max=0)
        assert m._scale_value(0) == 127
        assert m._scale_value(127) == 0

    def test_zero_input_span(self):
        m = self._make(in_min=64, in_max=64, out_min=50, out_max=100)
        assert m._scale_value(64) == 50  # returns out_range_min

    def test_clamp_to_127(self):
        m = self._make(out_min=0, out_max=200)
        assert m._scale_value(127) == 127  # clamped

    def test_clamp_to_0(self):
        m = self._make(out_min=-50, out_max=127)
        assert m._scale_value(0) == 0  # clamped (max(0, ...))

    def test_mid_range_offset(self):
        m = self._make(in_min=0, in_max=127, out_min=64, out_max=127)
        assert m._scale_value(0) == 64
        assert m._scale_value(127) == 127


# ---------------------------------------------------------------------------
# MidiFilter.allows_event
# ---------------------------------------------------------------------------

class TestMidiFilter:
    def test_all_pass(self):
        f = MidiFilter()
        ev = make_event(MidiEventType.NOTEON, channel=0)
        assert f.allows_event(ev)

    def test_channel_mask_blocks(self):
        """Only channel 0 (bit 0) allowed."""
        f = MidiFilter(channel_mask=0x0001)
        ev_ch0 = make_event(MidiEventType.NOTEON, channel=0)
        ev_ch1 = make_event(MidiEventType.NOTEON, channel=1)
        assert f.allows_event(ev_ch0)
        assert not f.allows_event(ev_ch1)

    def test_channel_mask_specific(self):
        """Only channel 9 (bit 9) allowed."""
        f = MidiFilter(channel_mask=(1 << 9))
        ev = make_event(MidiEventType.NOTEON, channel=9)
        assert f.allows_event(ev)
        ev2 = make_event(MidiEventType.NOTEON, channel=0)
        assert not f.allows_event(ev2)

    def test_msg_type_blocks_notes(self):
        f = MidiFilter(msg_types={"cc", "pc", "pitchbend", "aftertouch", "sysex", "clock"})
        ev = make_event(MidiEventType.NOTEON, channel=0)
        assert not f.allows_event(ev)

    def test_msg_type_allows_cc(self):
        f = MidiFilter(msg_types={"cc"})
        ev = make_event(MidiEventType.CONTROLLER, channel=0, cc=1, value=64)
        assert f.allows_event(ev)

    def test_msg_type_blocks_cc(self):
        f = MidiFilter(msg_types={"note"})
        ev = make_event(MidiEventType.CONTROLLER, channel=0, cc=1, value=64)
        assert not f.allows_event(ev)

    def test_clock_filtering(self):
        f = MidiFilter(msg_types={"note", "cc"})  # no clock
        ev = make_event(MidiEventType.CLOCK, channel=0)
        assert not f.allows_event(ev)

    def test_clock_allowed(self):
        f = MidiFilter(msg_types={"clock"})
        ev = make_event(MidiEventType.CLOCK)
        assert f.allows_event(ev)

    def test_unknown_type_passes(self):
        f = MidiFilter(msg_types=set())  # block everything known
        ev = make_event(255, channel=0)  # unknown type
        assert f.allows_event(ev)

    def test_is_passthrough_true(self):
        f = MidiFilter()
        assert f.is_passthrough

    def test_is_passthrough_false_channel(self):
        f = MidiFilter(channel_mask=0x0001)
        assert not f.is_passthrough

    def test_is_passthrough_false_types(self):
        f = MidiFilter(msg_types={"note"})
        assert not f.is_passthrough


# ---------------------------------------------------------------------------
# MidiMapping serialization round-trip
# ---------------------------------------------------------------------------

class TestMappingSerialization:
    def test_note_to_cc_roundtrip(self):
        m = MidiMapping(
            type=MappingType.NOTE_TO_CC,
            src_channel=0, src_note=60, dst_cc=64,
            cc_on_value=127, cc_off_value=0, pass_through=True,
        )
        d = m.to_dict()
        m2 = MidiMapping.from_dict(d)
        assert m2.type == MappingType.NOTE_TO_CC
        assert m2.src_note == 60
        assert m2.dst_cc == 64
        assert m2.cc_on_value == 127
        assert m2.pass_through is True

    def test_cc_to_cc_roundtrip(self):
        m = MidiMapping(
            type=MappingType.CC_TO_CC,
            src_cc=1, dst_cc_num=7,
            in_range_min=0, in_range_max=127,
            out_range_min=0, out_range_max=63,
        )
        d = m.to_dict()
        m2 = MidiMapping.from_dict(d)
        assert m2.src_cc == 1
        assert m2.dst_cc_num == 7
        assert m2.out_range_max == 63

    def test_channel_map_roundtrip(self):
        m = MidiMapping(type=MappingType.CHANNEL_MAP, src_channel=0, dst_channel=5)
        d = m.to_dict()
        m2 = MidiMapping.from_dict(d)
        assert m2.dst_channel == 5

    def test_toggle_roundtrip(self):
        m = MidiMapping(
            type=MappingType.NOTE_TO_CC_TOGGLE,
            src_note=36, dst_cc=80, cc_on_value=127, cc_off_value=0,
        )
        d = m.to_dict()
        m2 = MidiMapping.from_dict(d)
        assert m2.type == MappingType.NOTE_TO_CC_TOGGLE
        assert m2.src_note == 36


# ---------------------------------------------------------------------------
# MidiFilter serialization round-trip
# ---------------------------------------------------------------------------

class TestFilterSerialization:
    def test_roundtrip(self):
        f = MidiFilter(channel_mask=0x00FF, msg_types={"note", "cc"})
        d = f.to_dict()
        f2 = MidiFilter.from_dict(d)
        assert f2.channel_mask == 0x00FF
        assert f2.msg_types == {"note", "cc"}

    def test_defaults(self):
        f = MidiFilter.from_dict({})
        assert f.channel_mask == ALL_CHANNELS
        assert f.msg_types == ALL_MSG_TYPES
