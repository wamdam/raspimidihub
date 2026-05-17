"""Tests for the FilterEngine mapping pipeline.

These test _apply_mappings with captured output instead of real ALSA.
"""

from unittest.mock import MagicMock

from helpers import make_event

from raspimidihub.alsa_seq import MidiEventType
from raspimidihub.midi_filter import (
    FilteredConnection,
    FilterEngine,
    MappingType,
    MidiFilter,
    MidiMapping,
)


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


class TestNoteToNoteMapping:
    """Sampler use case: rewrite pad notes on one channel to C-3 on a per-voice channel.

    The mapping must preserve velocity (note dynamics) and emit both note-on
    and note-off so the receiver doesn't get a stuck note.
    """

    def test_note_on_rewrites_note_and_channel(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_NOTE,
            src_channel=0, src_note=36,
            dst_channel=2, dst_note=60,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.NOTEON, channel=0, note=36, velocity=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_ev) == 1
        out = fwd_ev[0]
        assert out.type == MidiEventType.NOTEON
        assert out.data.note.note == 60
        assert out.data.note.channel == 2
        assert out.data.note.velocity == 100  # preserved
        assert len(fwd_cc) == 0

    def test_note_off_rewrites_too(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_NOTE,
            src_channel=0, src_note=36,
            dst_channel=2, dst_note=60,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.NOTEOFF, channel=0, note=36, velocity=0,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_ev) == 1
        out = fwd_ev[0]
        assert out.type == MidiEventType.NOTEOFF
        assert out.data.note.note == 60
        assert out.data.note.channel == 2

    def test_unmatched_note_passes_through(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_NOTE,
            src_channel=0, src_note=36,
            dst_channel=2, dst_note=60,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.NOTEON, channel=0, note=37, velocity=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        # Mapping didn't fire; original note is forwarded unchanged.
        assert len(fwd_ev) == 1
        assert fwd_ev[0].data.note.note == 37
        assert fwd_ev[0].data.note.channel == 0

    def test_pass_through_forwards_both(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_NOTE,
            src_channel=0, src_note=36,
            dst_channel=2, dst_note=60,
            pass_through=True,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.NOTEON, channel=0, note=36, velocity=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        # Two events forwarded: the rewritten one + the original.
        assert len(fwd_ev) == 2
        notes = {(e.data.note.note, e.data.note.channel) for e in fwd_ev}
        assert notes == {(60, 2), (36, 0)}

    def test_fan_out_two_voices(self):
        """Sampler scenario: one pad triggers C-3 on two different voice channels."""
        mappings = [
            MidiMapping(type=MappingType.NOTE_TO_NOTE,
                        src_channel=0, src_note=36, dst_channel=1, dst_note=60),
            MidiMapping(type=MappingType.NOTE_TO_NOTE,
                        src_channel=0, src_note=36, dst_channel=2, dst_note=60),
        ]
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn(mappings)

        ev = make_event(
            MidiEventType.NOTEON, channel=0, note=36, velocity=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_ev) == 2
        assert {e.data.note.channel for e in fwd_ev} == {1, 2}
        assert all(e.data.note.note == 60 for e in fwd_ev)

    def test_dst_channel_none_keeps_source_channel(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_NOTE,
            src_channel=None, src_note=36,
            dst_channel=None, dst_note=60,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])

        ev = make_event(
            MidiEventType.NOTEON, channel=4, note=36, velocity=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_ev) == 1
        assert fwd_ev[0].data.note.note == 60
        assert fwd_ev[0].data.note.channel == 4  # source channel kept


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

        # One copy forwarded on the remapped channel; original consumed.
        assert len(fwd_ev) == 1
        assert fwd_ev[0].data.note.channel == 5

    def test_fan_out_two_channels(self):
        """Two channel maps on same src (bass + strings) -> two copies forwarded."""
        mappings = [
            MidiMapping(type=MappingType.CHANNEL_MAP, src_channel=None, dst_channel=0),
            MidiMapping(type=MappingType.CHANNEL_MAP, src_channel=None, dst_channel=5),
        ]
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn(mappings)

        ev = make_event(
            MidiEventType.NOTEON, channel=2, note=60, velocity=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_ev) == 2
        assert {e.data.note.channel for e in fwd_ev} == {0, 5}

    def test_fan_out_note_off(self):
        """Note-off also fans out to all mapped channels."""
        mappings = [
            MidiMapping(type=MappingType.CHANNEL_MAP, src_channel=None, dst_channel=0),
            MidiMapping(type=MappingType.CHANNEL_MAP, src_channel=None, dst_channel=5),
        ]
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn(mappings)

        ev = make_event(
            MidiEventType.NOTEOFF, channel=2, note=60, velocity=0,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_ev) == 2
        assert {e.data.note.channel for e in fwd_ev} == {0, 5}
        assert all(e.type == MidiEventType.NOTEOFF for e in fwd_ev)


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


class TestCcFanOut:
    """One controller knob (Ch1 CC1) controlling multiple destinations.

    Real-world scenario: a single mod wheel on a controller mapped to
    different CCs and channels across multiple synths via separate connections.
    """

    def test_one_knob_to_multiple_ccs_same_channel(self):
        """CC1 -> CC7 (volume) + CC74 (filter cutoff) on same channel."""
        mappings = [
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=7,
                        out_range_min=0, out_range_max=127, pass_through=True),
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=74,
                        out_range_min=0, out_range_max=127, pass_through=True),
        ]
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn(mappings)

        ev = make_event(
            MidiEventType.CONTROLLER, channel=0, cc=1, value=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_cc) == 2
        assert (0, 7, 100) in fwd_cc
        assert (0, 74, 100) in fwd_cc

    def test_one_knob_to_different_channels(self):
        """CC1 on ch0 -> CC1 on ch1 + CC1 on ch2 (broadcast to multiple synths)."""
        mappings = [
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=1,
                        dst_channel=1, pass_through=True),
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=1,
                        dst_channel=2, pass_through=True),
        ]
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn(mappings)

        ev = make_event(
            MidiEventType.CONTROLLER, channel=0, cc=1, value=80,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        assert len(fwd_cc) == 2
        assert (1, 1, 80) in fwd_cc  # ch1
        assert (2, 1, 80) in fwd_cc  # ch2

    def test_one_knob_with_different_ranges(self):
        """CC1 -> CC7 full range + CC74 inverted half range.

        Mod wheel controls volume (0-127) and filter cutoff inverted (127-64).
        """
        mappings = [
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=7,
                        out_range_min=0, out_range_max=127),
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=74,
                        out_range_min=127, out_range_max=64, pass_through=True),
        ]
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn(mappings)

        # Knob at 50%
        ev = make_event(
            MidiEventType.CONTROLLER, channel=0, cc=1, value=64,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        cc_by_num = {cc: val for _, cc, val in fwd_cc}
        assert cc_by_num[7] == 64          # linear: 64
        assert 90 <= cc_by_num[74] <= 100  # inverted: ~95

    def test_fan_out_across_connections(self):
        """One knob (CC1) routed to two separate connections (two synths).

        Connection 1: CC1 -> CC7 (volume)
        Connection 2: CC1 -> CC74 (filter cutoff), different range
        """
        mock_seq = MagicMock()
        mock_seq.client_id = 128
        engine = FilterEngine(mock_seq)

        # Connection to Synth A: CC1 -> CC7
        fc1 = FilteredConnection(
            src_client=1, src_port=0, dst_client=2, dst_port=0,
            filter=MidiFilter(),
            mappings=[MidiMapping(
                type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=7,
            )],
            _read_port=10, _write_port=11,
        )
        engine._filtered[fc1.conn_id] = fc1

        # Connection to Synth B: CC1 -> CC74, half range
        fc2 = FilteredConnection(
            src_client=1, src_port=0, dst_client=3, dst_port=0,
            filter=MidiFilter(),
            mappings=[MidiMapping(
                type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=74,
                out_range_min=0, out_range_max=63,
            )],
            _read_port=12, _write_port=13,
        )
        engine._filtered[fc2.conn_id] = fc2

        # Capture output
        forwarded = []
        engine._forward_cc = lambda fc_, ch, cc, val: forwarded.append(
            (fc_.dst_client, ch, cc, val)
        )
        engine._forward_event = lambda ev_, fc_: None

        # Send CC1=100 — needs to arrive on both read ports
        for read_port in (10, 12):
            ev = make_event(
                MidiEventType.CONTROLLER, channel=0, cc=1, value=100,
                src_client=1, src_port=0, dst_client=128, dst_port=read_port,
            )
            engine.process_event(ev)

        # Synth A gets CC7=100, Synth B gets CC74=50
        synth_a = [(cc, val) for dst, ch, cc, val in forwarded if dst == 2]
        synth_b = [(cc, val) for dst, ch, cc, val in forwarded if dst == 3]
        assert synth_a == [(7, 100)]
        assert synth_b == [(74, 50)]

    def test_large_mapping_table(self):
        """One CC1 knob controlling 8 different parameters across channels.

        Simulates a performance macro knob mapped to many destinations.
        """
        mappings = [
            # Same channel, different CCs
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=7,
                        pass_through=True),   # volume
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=74,
                        out_range_min=0, out_range_max=63, pass_through=True),  # filter
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=71,
                        out_range_min=127, out_range_max=0, pass_through=True),  # resonance inv
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=91,
                        out_range_min=0, out_range_max=40, pass_through=True),  # reverb
            # Different channels
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=1,
                        dst_channel=1, pass_through=True),
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=1,
                        dst_channel=2, pass_through=True),
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=1,
                        dst_channel=9, pass_through=True),
            MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=11,
                        dst_channel=3, out_range_min=64, out_range_max=127,
                        pass_through=True),  # expression, upper half only
        ]
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn(mappings)

        ev = make_event(
            MidiEventType.CONTROLLER, channel=0, cc=1, value=127,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)

        # All 8 mappings should fire
        assert len(fwd_cc) == 8

        # Check a few specific outputs
        cc_outputs = {(ch, cc): val for ch, cc, val in fwd_cc}
        assert cc_outputs[(0, 7)] == 127    # volume full
        assert cc_outputs[(0, 74)] == 63    # filter half range
        assert cc_outputs[(0, 71)] == 0     # resonance inverted
        assert cc_outputs[(0, 91)] == 40    # reverb max
        assert cc_outputs[(1, 1)] == 127    # ch2 mod wheel
        assert cc_outputs[(2, 1)] == 127    # ch3 mod wheel
        assert cc_outputs[(9, 1)] == 127    # ch10 mod wheel
        assert cc_outputs[(3, 11)] == 127   # expression upper half


class TestNoteToNoteWildcard:
    """src_note=None matches any incoming note — fold a whole keyboard
    onto a single pitch."""

    def test_any_note_maps_to_dst(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_NOTE,
            src_note=None, dst_note=60,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])
        for incoming in (36, 60, 90, 127):
            fwd_ev.clear()
            ev = make_event(
                MidiEventType.NOTEON, channel=0, note=incoming, velocity=100,
                src_client=1, src_port=0, dst_client=128, dst_port=10,
            )
            engine.process_event(ev)
            assert len(fwd_ev) == 1, f"input {incoming} not forwarded"
            assert fwd_ev[0].data.note.note == 60, \
                f"input {incoming} → {fwd_ev[0].data.note.note}, expected 60"

    def test_wildcard_still_respects_src_channel(self):
        """src_note wildcard does not also wildcard the channel — Src Ch
        filtering still applies."""
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_NOTE,
            src_channel=0, src_note=None, dst_note=60,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])
        ev = make_event(
            MidiEventType.NOTEON, channel=5, note=42, velocity=100,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)
        # Ch5 doesn't match src_channel=0, so the mapping is inert and
        # the original event is forwarded untouched.
        assert len(fwd_ev) == 1
        assert fwd_ev[0].data.note.note == 42

    def test_note_off_also_folds(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_NOTE,
            src_note=None, dst_note=60,
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])
        ev = make_event(
            MidiEventType.NOTEOFF, channel=0, note=42, velocity=0,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)
        assert len(fwd_ev) == 1
        assert fwd_ev[0].data.note.note == 60


class TestNoteToCcVelocityValue:
    """cc_value_source='velocity' sends the note-on velocity as the CC
    value; cc_off_value still applies on release."""

    def test_velocity_used_on_note_on(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_CC,
            src_note=60, dst_cc=11,
            cc_on_value=99,  # should be ignored when source=velocity
            cc_off_value=0,
            cc_value_source="velocity",
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])
        for vel in (1, 64, 100, 127):
            fwd_cc.clear()
            ev = make_event(
                MidiEventType.NOTEON, channel=0, note=60, velocity=vel,
                src_client=1, src_port=0, dst_client=128, dst_port=10,
            )
            engine.process_event(ev)
            assert fwd_cc == [(0, 11, vel)], f"velocity {vel} → {fwd_cc}"

    def test_note_off_uses_off_value(self):
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_CC,
            src_note=60, dst_cc=11,
            cc_off_value=7,
            cc_value_source="velocity",
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])
        ev = make_event(
            MidiEventType.NOTEOFF, channel=0, note=60, velocity=0,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)
        assert fwd_cc == [(0, 11, 7)]

    def test_any_note_plus_velocity(self):
        """Wildcard src_note + velocity source = any-keypress velocity → CC."""
        mapping = MidiMapping(
            type=MappingType.NOTE_TO_CC,
            src_note=None, dst_cc=11,
            cc_value_source="velocity",
        )
        engine, fc, fwd_cc, fwd_ev = _make_engine_and_conn([mapping])
        ev = make_event(
            MidiEventType.NOTEON, channel=0, note=42, velocity=88,
            src_client=1, src_port=0, dst_client=128, dst_port=10,
        )
        engine.process_event(ev)
        assert fwd_cc == [(0, 11, 88)]
