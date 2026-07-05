"""UMP monitor shim — byte-compat for 1.0 sources, hires for 2.0."""

from raspimidihub import midi_scale as ms
from raspimidihub import ump


def shim(words, hires):
    m = ump.decode(words)
    return ump.to_monitor_shim(m, 24, 0, 128, 1, hires=hires)


def test_upscaled_10_source_is_byte_identical():
    # A 1.0 note-on vel 100 arrives kernel-upscaled; the shim must
    # reproduce exactly what the legacy monitor path reported.
    ev = shim(ump.note_on(0, 2, 64, ms.vel7_to_vel16(100)), hires=False)
    assert ev.type == 6 and ev.hires is None
    assert (ev.data.note.channel, ev.data.note.note, ev.data.note.velocity) \
        == (2, 64, 100)
    assert ev.channel == 2
    assert (ev.source.client, ev.source.port, ev.dest.port) == (24, 0, 1)

    ev = shim(ump.cc(0, 5, 74, ms.scale_up(101, 7, 32)), hires=False)
    assert ev.type == 10 and ev.hires is None
    assert (ev.data.control.param, ev.data.control.value) == (74, 101)
    assert ev.channel == 5


def test_hires_source_carries_fractional_units():
    ev = shim(ump.cc(0, 0, 74, 0x8C30C30C), hires=True)
    assert ev.data.control.value == 70          # legacy int stays 7-bit
    assert abs(ev.hires["value_f"] - 70.0) < 0.01
    ev = shim(ump.note_on(0, 0, 60, 0xC924), hires=True)
    assert ev.data.note.velocity == 100
    assert abs(ev.hires["velocity_f"] - 100.0) < 0.01


def test_note_on_velocity_floor():
    # MIDI 2.0 vel-0 note-on is a legal note-on; the 7-bit field must
    # not read as 0 (which downstream treats as note-off)
    ev = shim(ump.note_on(0, 0, 60, 0x0001), hires=True)
    assert ev.type == 6 and ev.data.note.velocity == 1


def test_pitch_bend_signed_alsa_convention():
    ev = shim(ump.pitch_bend(0, 0, ump.BEND32_CENTER), hires=False)
    assert ev.type == 13 and ev.data.control.value == 0
    ev = shim(ump.pitch_bend(0, 0, 0), hires=False)
    assert ev.data.control.value == -8192


def test_rpn_nrpn_shims():
    ev = shim(ump.rpn(0, 3, 0, 6, ms.scale_up_zero_ext(1, 7, 32)), hires=True)
    assert ev.type == 16  # REGPARAM
    assert ev.hires["kind"] == "rpn" and ev.hires["bank"] == 0
    assert ev.hires["index"] == 6 and ev.channel == 3
    ev = shim(ump.rpn(0, 3, 2, 20, 5, assignable=True), hires=True)
    assert ev.type == 15 and ev.hires["kind"] == "nrpn"
    assert ev.data.control.param == (2 << 7) | 20


def test_per_note_pseudo_types():
    ev = shim(ump.per_note_controller(0, 1, 61, 74, 0x80000000), hires=True)
    assert ev.type == ump.T_PER_NOTE_CC and ev.data.note.note == 61
    assert ev.hires["index"] == 74 and abs(ev.hires["value_f"] - 64.0) < 0.01
    ev = shim(ump.per_note_bend(0, 1, 61, ump.BEND32_CENTER), hires=True)
    assert ev.type == ump.T_PER_NOTE_BEND
    ev = shim((0x41F13D02, 0, 0, 0), hires=True)  # per-note mgmt, D flag
    assert ev.type == ump.T_PER_NOTE_MGMT and ev.hires["flags"] == 2


def test_system_and_program():
    ev = shim(ump.system_packet(0, 0xF8), hires=False)
    assert ev.type == 36  # CLOCK
    ev = shim(ump.system_packet(0, 0xFA), hires=False)
    assert ev.type == 30  # START
    ev = shim(ump.program_change(0, 4, 12, bank=3), hires=True)
    assert ev.type == 11 and ev.data.control.value == 12
    assert ev.hires == {"bank": 3}


def test_ignored_kinds_return_none():
    # Stream messages are endpoint metadata, not monitor traffic
    m = ump.decode(ump.endpoint_discovery())
    assert ump.to_monitor_shim(m, 1, 0, 2, 0, hires=False) is None
