"""FSD-07 golden equivalence: the UMP mapping path must produce
byte-identical results to the legacy path for all 7-bit-lattice
inputs (what 1.0 devices deliver after kernel up-conversion), plus
hi-res behaviours the legacy path can't express."""

from unittest.mock import MagicMock

from helpers import make_event

from raspimidihub import midi_scale as ms
from raspimidihub import ump
from raspimidihub.alsa_seq import MidiEventType
from raspimidihub.midi_filter import (
    ALL_MSG_TYPES,
    FilteredConnection,
    FilterEngine,
    MappingType,
    MidiFilter,
    MidiMapping,
)


def _mk(mappings=None, channel_mask=0xFFFF, msg_types=None):
    """Twin capture harness: legacy + UMP forwards recorded separately."""
    mock_seq = MagicMock()
    mock_seq.client_id = 128
    engine = FilterEngine(mock_seq)
    fc = FilteredConnection(
        src_client=1, src_port=0, dst_client=2, dst_port=0,
        filter=MidiFilter(channel_mask=channel_mask,
                          msg_types=set(msg_types) if msg_types else ALL_MSG_TYPES.copy()),
        mappings=mappings or [], _read_port=10, _write_port=11)
    engine._filtered[fc.conn_id] = fc

    legacy_cc, legacy_ev, ump_out = [], [], []
    engine._forward_cc = lambda fc_, ch, cc, val: legacy_cc.append((ch, cc, val))
    engine._forward_event = lambda ev_, fc_: legacy_ev.append(
        (ev_.type, ev_.data.note.channel, ev_.data.note.note,
         ev_.data.note.velocity))
    engine._forward_ump = lambda words, fc_: ump_out.append(tuple(words))
    return engine, fc, legacy_cc, legacy_ev, ump_out


class _UmpEv:
    """Duck-typed snd_seq_ump_event for process_ump."""

    def __init__(self, words, src=(1, 0), dest=(128, 10)):
        self.ump_words = tuple(words)
        self.source = MagicMock(client=src[0], port=src[1])
        self.dest = MagicMock(client=dest[0], port=dest[1])
        self.is_ump = True


def _ump_cc_outputs_as_7bit(ump_out):
    """Decode captured UMP CC packets to (ch, cc, value7) like a 1.0
    receiver would see them after kernel down-conversion."""
    out = []
    for words in ump_out:
        m = ump.decode(words)
        assert m is not None and m.kind == "cc"
        out.append((m.channel, m.index, ms.scale_down(m.value, 32, 7)))
    return out


# --- Golden equivalence over the full 7-bit domain -------------------

def test_cc_to_cc_full_domain_equivalence():
    configs = [
        dict(in_range_min=0, in_range_max=127, out_range_min=0, out_range_max=127),
        dict(in_range_min=0, in_range_max=127, out_range_min=20, out_range_max=100),
        dict(in_range_min=30, in_range_max=90, out_range_min=127, out_range_max=0),
        dict(in_range_min=64, in_range_max=64, out_range_min=5, out_range_max=99),
    ]
    for cfg in configs:
        mp = [MidiMapping(type=MappingType.CC_TO_CC, src_cc=1, dst_cc_num=7, **cfg)]
        eng_l, fc_l, cc_l, _, _ = _mk([MidiMapping.from_dict(m.to_dict()) for m in mp])
        eng_u, fc_u, _, _, out_u = _mk([MidiMapping.from_dict(m.to_dict()) for m in mp])
        for v in range(128):
            eng_l._apply_mappings(
                make_event(MidiEventType.CONTROLLER, channel=3, cc=1, value=v), fc_l)
            m = ump.decode(ump.cc(0, 3, 1, ms.scale_up(v, 7, 32)))
            eng_u._apply_mappings_ump(m, ump.cc(0, 3, 1, ms.scale_up(v, 7, 32)), fc_u)
        assert _ump_cc_outputs_as_7bit(out_u) == cc_l, cfg


def test_note_to_cc_full_domain_equivalence():
    for src in (dict(cc_value_source="velocity"),
                dict(cc_on_value=127, cc_off_value=0),
                dict(cc_on_value=99, cc_off_value=12)):
        mp = dict(type=MappingType.NOTE_TO_CC, src_note=60, dst_cc=20, **src)
        eng_l, fc_l, cc_l, _, _ = _mk([MidiMapping(**mp)])
        eng_u, fc_u, _, _, out_u = _mk([MidiMapping(**mp)])
        for v in range(1, 128):
            eng_l._apply_mappings(
                make_event(MidiEventType.NOTEON, channel=0, note=60, velocity=v), fc_l)
            eng_l._apply_mappings(
                make_event(MidiEventType.NOTEOFF, channel=0, note=60, velocity=0), fc_l)
            w = ump.note_on(0, 0, 60, ms.vel7_to_vel16(v))
            eng_u._apply_mappings_ump(ump.decode(w), w, fc_u)
            w = ump.note_off(0, 0, 60)
            eng_u._apply_mappings_ump(ump.decode(w), w, fc_u)
        assert _ump_cc_outputs_as_7bit(out_u) == cc_l, src


def test_toggle_sequence_equivalence():
    mp = dict(type=MappingType.NOTE_TO_CC_TOGGLE, src_note=60, dst_cc=20,
              cc_on_value=127, cc_off_value=0)
    eng_l, fc_l, cc_l, _, _ = _mk([MidiMapping(**mp)])
    eng_u, fc_u, _, _, out_u = _mk([MidiMapping(**mp)])
    for _ in range(5):
        eng_l._apply_mappings(
            make_event(MidiEventType.NOTEON, note=60, velocity=100), fc_l)
        eng_l._apply_mappings(
            make_event(MidiEventType.NOTEOFF, note=60, velocity=0), fc_l)
        w = ump.note_on(0, 0, 60, ms.vel7_to_vel16(100))
        eng_u._apply_mappings_ump(ump.decode(w), w, fc_u)
        w = ump.note_off(0, 0, 60)
        eng_u._apply_mappings_ump(ump.decode(w), w, fc_u)
    assert _ump_cc_outputs_as_7bit(out_u) == cc_l


def test_note_to_note_and_channel_map_rewrites():
    mp = [MidiMapping(type=MappingType.NOTE_TO_NOTE, src_note=60,
                      dst_note=72, dst_channel=5)]
    eng_u, fc_u, _, _, out_u = _mk(mp)
    w = ump.note_on(0, 2, 60, 0xC924)
    assert eng_u._apply_mappings_ump(ump.decode(w), w, fc_u) is True
    m = ump.decode(out_u[0])
    assert (m.kind, m.channel, m.note, m.velocity) == ("note_on", 5, 72, 0xC924)

    mp = [MidiMapping(type=MappingType.CHANNEL_MAP, dst_channel=9)]
    eng_u, fc_u, _, _, out_u = _mk(mp)
    w = ump.pitch_bend(0, 1, 0x90000000)
    assert eng_u._apply_mappings_ump(ump.decode(w), w, fc_u) is True
    m = ump.decode(out_u[0])
    assert (m.kind, m.channel, m.value) == ("pitch_bend", 9, 0x90000000)


# --- Hi-res behaviours (no legacy equivalent) -------------------------

def test_cc_to_cc_hires_input_scales_fractionally():
    mp = [MidiMapping(type=MappingType.CC_TO_CC, src_cc=1,
                      out_range_min=0, out_range_max=63.5)]
    eng, fc, _, _, out = _mk(mp)
    val32 = ms.from_midi_units(100.5)  # off-lattice: genuine hi-res
    w = ump.cc(0, 0, 1, val32)
    eng._apply_mappings_ump(ump.decode(w), w, fc)
    got = ms.to_midi_units(ump.decode(out[0]).value, 32)
    assert abs(got - 100.5 / 127 * 63.5) < 0.01


def test_fractional_fixed_cc_values():
    mp = [MidiMapping(type=MappingType.NOTE_TO_CC, src_note=60, dst_cc=20,
                      cc_on_value=64.25, cc_off_value=0)]
    eng, fc, _, _, out = _mk(mp)
    w = ump.note_on(0, 0, 60, 0xFFFF)
    eng._apply_mappings_ump(ump.decode(w), w, fc)
    assert abs(ms.to_midi_units(ump.decode(out[0]).value, 32) - 64.25) < 0.001


# --- process_ump wiring: classification, gating, pass-through ---------

def test_process_ump_pass_through_and_gates():
    eng, fc, _, _, out = _mk(channel_mask=1 << 3)  # only channel 4
    w = ump.cc(0, 3, 74, 0x12345678)
    assert eng.process_ump(_UmpEv(w)) is True
    assert out == [w]                       # forwarded verbatim
    assert eng.process_ump(_UmpEv(ump.cc(0, 5, 74, 1))) is False  # wrong ch

    # msg-type gate: "cc" unticked blocks CC and RPN alike
    eng, fc, _, _, out = _mk(msg_types=ALL_MSG_TYPES - {"cc"})
    assert eng.process_ump(_UmpEv(ump.cc(0, 3, 74, 1))) is False
    assert eng.process_ump(_UmpEv(ump.rpn(0, 3, 0, 0, 1))) is False
    # per-note gates under "midi2", not "cc"
    assert eng.process_ump(_UmpEv(ump.per_note_bend(0, 3, 60, 5))) is True

    # utility / stream never forward (D5)
    eng, fc, _, _, out = _mk()
    assert eng.process_ump(_UmpEv((0x00200000, 0, 0, 0))) is False
    assert eng.process_ump(_UmpEv(ump.endpoint_discovery())) is False


def test_per_note_messages_pass_through_unmodified():
    eng, fc, _, _, out = _mk([MidiMapping(type=MappingType.CC_TO_CC, src_cc=1)])
    w = ump.per_note_controller(0, 0, 60, 74, 0xCAFEBABE)
    assert eng.process_ump(_UmpEv(w)) is True
    assert out == [w]  # mappings don't touch per-note messages


def test_filter_migration_old_full_set_gains_midi2():
    f = MidiFilter.from_dict({"channel_mask": 0xFFFF,
                              "msg_types": ["note", "cc", "pc", "pitchbend",
                                            "aftertouch", "sysex", "clock"]})
    assert f.msg_types == ALL_MSG_TYPES and f.is_passthrough
    # deliberate deselection stays as saved (midi2 arrives unticked)
    f = MidiFilter.from_dict({"msg_types": ["note", "cc"]})
    assert f.msg_types == {"note", "cc"}


def test_mapping_float_serialization_roundtrip():
    m = MidiMapping(type=MappingType.CC_TO_CC, src_cc=1,
                    out_range_min=0, out_range_max=63.5)
    d = m.to_dict()
    assert d["out_range_max"] == 63.5 and d["out_range_min"] == 0
    assert isinstance(d["out_range_min"], int)  # whole numbers stay ints
    m2 = MidiMapping.from_dict(d)
    assert m2.out_range_max == 63.5
