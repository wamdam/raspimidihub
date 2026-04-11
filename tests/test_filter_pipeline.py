"""Tests for the FilterEngine mapping pipeline.

These test _apply_mappings with captured output instead of real ALSA.
"""

from unittest.mock import MagicMock

from raspimidihub.alsa_seq import MidiEventType, SndSeqEvent
from raspimidihub.midi_filter import (
    FilterEngine, FilteredConnection, MappingType, MidiFilter, MidiMapping,
)

from helpers import make_event


def _make_engine_and_conn(mappings=None, channel_mask=0xFFFF):
    """Create a FilterEngine with a mock AlsaSeq and a FilteredConnection."""
    mock_seq = MagicMock()
    mock_seq.client_id = 128
    engine = FilterEngine(mock_seq)

    fc = FilteredConnection(
        src_client=1, src_port=0,
        dst_client=2, dst_port=0,
        filter=MidiFilter(channel_mask=channel_mask),
        mappings=mappings or [],
        _read_port=10,
        _write_port=11,
    )
    engine._filtered[fc.conn_id] = fc

    # Capture forwarded events
    forwarded_cc = []
    forwarded_events = []

    original_forward_cc = engine._forward_cc
    original_forward_event = engine._forward_event

    def capture_cc(fc_, ch, cc, val):
        forwarded_cc.append((ch, cc, val))

    def capture_event(ev_, fc_):
        forwarded_events.append(ev_)

    engine._forward_cc = capture_cc
    engine._forward_event = capture_event

    return engine, fc, forwarded_cc, forwarded_events


class TestCcToCcMapping:
    def test_basic_remap(self):
        """CC1 0-127 -> CC7 0-63, value 100 -> 50."""
        mapping = MidiMapping(
            type=MappingType.CC_TO_CC,
            src_cc=1, dst_cc_num=7,
            in_range_min=0, in_range_max=127,
            out_range_min=0, out_range_max=63,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.CONTROLLER, channel=0, cc=1, value=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_cc) == 1
        assert fwd_cc[0] == (0, 7, 50)
        assert len(fwd_ev) == 0  # consumed

    def test_pass_through(self):
        """With pass_through=True, original event is also forwarded."""
        mapping = MidiMapping(
            type=MappingType.CC_TO_CC,
            src_cc=1, dst_cc_num=7,
            out_range_max=63,
            pass_through=True,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.CONTROLLER, channel=0, cc=1, value=64,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_cc) == 1  # mapped CC
        assert len(fwd_ev) == 1  # original also forwarded

    def test_unmatched_cc_passes(self):
        """CC2 is not matched by a mapping on CC1, so it passes through."""
        mapping = MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=7)
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.CONTROLLER, channel=0, cc=2, value=50,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_cc) == 0
        assert len(fwd_ev) == 1  # passed through unmodified


class TestNoteToCcMapping:
    def test_note_on_sends_cc(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_CC,
            src_note=60, dst_cc=64,
            cc_on_value=127, cc_off_value=0,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.NOTEON, channel=0, note=60, velocity=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert fwd_cc == [(0, 64, 127)]
        assert len(fwd_ev) == 0  # consumed

    def test_note_off_sends_cc_off(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_CC,
            src_note=60, dst_cc=64,
            cc_on_value=127, cc_off_value=0,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.NOTEOFF, channel=0, note=60, velocity=0,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert fwd_cc == [(0, 64, 0)]

    def test_unmatched_note_passes(self):
        mapping = MidiMapping(type=MappingType.NOTE_TO_CC, src_note=60, dst_cc=64)
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.NOTEON, channel=0, note=61, velocity=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_cc) == 0
        assert len(fwd_ev) == 1  # not consumed


class TestNoteToCcToggle:
    def test_toggle_on_off(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_CC_TOGGLE,
            src_note=36, dst_cc=80,
            cc_on_value=127, cc_off_value=0,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        # First note-on: toggle to ON
        ev = make_event(
            MidiEventType.NOTEON, channel=0, note=36, velocity=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)
        assert fwd_cc == [(0, 80, 127)]

        fwd_cc.clear()

        # Second note-on: toggle to OFF
        engine.process_event(ev)
        assert fwd_cc == [(0, 80, 0)]


class TestChannelMap:
    def test_remap_channel(self):
        mapping = MidiMapping(
            type=MappingType.CHANNEL_MAP,
            src_channel=0, dst_channel=5,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.NOTEON, channel=0, note=60, velocity=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        # Channel map modifies in-place and does NOT consume
        assert len(fwd_ev) == 1
        assert ev.data.note.channel == 5


class TestChannelMismatch:
    def test_src_channel_mismatch_skips(self):
        """Mapping with src_channel=2, event on ch0 -> mapping not applied."""
        mapping = MidiMapping(
            type=MappingType.CC_TO_CC,
            src_channel=2, src_cc=1, dst_cc_num=7,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.CONTROLLER, channel=0, cc=1, value=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_cc) == 0  # mapping didn't fire
        assert len(fwd_ev) == 1  # original passed through


class TestFilterBlocksBeforeMapping:
    def test_channel_filter_blocks(self):
        """Filter blocks channel 0, mapping never applies."""
        mapping = MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=7)
        # Only allow channel 1 (bit 1)
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping], channel_mask=0x0002)

        ev = make_event(
            MidiEventType.CONTROLLER, channel=0, cc=1, value=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_cc) == 0
        assert len(fwd_ev) == 0  # blocked by filter


class TestMultipleMappings:
    def test_two_mappings_both_fire(self):
        m1 = MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=7, pass_through=True)
        m2 = MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=11, pass_through=True)
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([m1, m2])

        ev = make_event(
            MidiEventType.CONTROLLER, channel=0, cc=1, value=64,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        # Both mappings produce output
        assert len(fwd_cc) == 2
        cc_nums = {cc for _, cc, _ in fwd_cc}
        assert cc_nums == {7, 11}
