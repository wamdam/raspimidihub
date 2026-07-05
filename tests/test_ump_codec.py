"""UMP codec (raspimidihub.ump) — golden packets + round-trips.

Golden words are hand-assembled from M2-104-UM v1.1.2 field layouts;
the on-Pi interop check against aseqdump -u 2 is the final authority.
"""

import pytest

from raspimidihub import ump

# --- packet sizing ---

@pytest.mark.parametrize("mt,words", [
    (0x0, 1), (0x1, 1), (0x2, 1), (0x3, 2), (0x4, 2), (0x5, 4),
    (0x6, 1), (0x7, 1), (0x8, 2), (0x9, 2), (0xA, 2), (0xB, 3),
    (0xC, 3), (0xD, 4), (0xE, 4), (0xF, 4),
])
def test_packet_words(mt, words):
    assert ump.packet_words(mt << 28) == words


# --- MIDI 2.0 channel voice golden packets ---

def test_note_on_golden():
    words = ump.note_on(0, 0, 60, 0xFFFF)
    assert words == (0x40903C00, 0xFFFF0000)
    m = ump.decode(words)
    assert (m.kind, m.group, m.channel, m.note, m.velocity) == \
        ("note_on", 0, 0, 60, 0xFFFF)
    assert m.attr_type == 0 and m.attr_data == 0


def test_note_on_with_attribute():
    # Attribute type 3 = Pitch 7.9
    words = ump.note_on(1, 2, 64, 0x8000, attr_type=3, attr_data=0x4123)
    m = ump.decode(words)
    assert (m.group, m.channel, m.attr_type, m.attr_data) == (1, 2, 3, 0x4123)
    assert m.velocity == 0x8000


def test_note_off_default_velocity():
    # Spec: 1.0 vel-0 note-ons translate to Note Off w/ velocity 0x8000
    m = ump.decode(ump.note_off(0, 0, 60))
    assert m.kind == "note_off" and m.velocity == 0x8000


def test_cc_golden():
    words = ump.cc(2, 1, 74, 0x8C30C30C)
    assert words == (0x42B14A00, 0x8C30C30C)
    m = ump.decode(words)
    assert (m.kind, m.group, m.channel, m.index, m.value) == \
        ("cc", 2, 1, 74, 0x8C30C30C)


def test_rpn_golden():
    # RPN bank 0 index 0 = pitch bend sensitivity
    words = ump.rpn(0, 0, 0, 0, 0x02000000)
    assert words == (0x40200000, 0x02000000)
    m = ump.decode(words)
    assert (m.kind, m.bank, m.index, m.value) == ("rpn", 0, 0, 0x02000000)


def test_nrpn_and_relative():
    m = ump.decode(ump.rpn(0, 3, 5, 17, 42, assignable=True))
    assert (m.kind, m.channel, m.bank, m.index, m.value) == ("nrpn", 3, 5, 17, 42)
    m = ump.decode(ump.rpn(0, 0, 1, 2, 0xFFFFFFFF, relative=True))
    assert m.kind == "rel_rpn" and m.value == 0xFFFFFFFF  # -1 two's complement
    m = ump.decode(ump.rpn(0, 0, 1, 2, 3, assignable=True, relative=True))
    assert m.kind == "rel_nrpn"


def test_pitch_bend_center():
    words = ump.pitch_bend(0, 0, ump.BEND32_CENTER)
    assert words == (0x40E00000, 0x80000000)
    m = ump.decode(words)
    assert m.kind == "pitch_bend" and m.value == ump.BEND32_CENTER


def test_per_note_bend_and_controllers():
    m = ump.decode(ump.per_note_bend(0, 4, 61, 0x90000000))
    assert (m.kind, m.note, m.value) == ("per_note_bend", 61, 0x90000000)
    m = ump.decode(ump.per_note_controller(0, 4, 61, 74, 7))
    assert (m.kind, m.note, m.index, m.value) == ("per_note_rcc", 61, 74, 7)
    m = ump.decode(ump.per_note_controller(0, 4, 61, 200, 7, assignable=True))
    assert m.kind == "per_note_acc" and m.index == 200  # 8-bit index


def test_program_change_with_and_without_bank():
    words = ump.program_change(0, 5, 10, bank=258)  # bank MSB 2, LSB 2
    assert words == (0x40C50001, 0x0A000202)
    m = ump.decode(words)
    assert (m.kind, m.channel, m.program, m.bank_valid, m.bank) == \
        ("program", 5, 10, True, 258)
    m = ump.decode(ump.program_change(0, 5, 10))
    assert m.bank_valid is False


def test_poly_and_channel_pressure():
    m = ump.decode(ump.poly_pressure(0, 0, 60, 0x12345678))
    assert (m.kind, m.note, m.value) == ("poly_pressure", 60, 0x12345678)
    m = ump.decode(ump.chan_pressure(0, 9, 0xCAFEBABE))
    assert (m.kind, m.channel, m.value) == ("chan_pressure", 9, 0xCAFEBABE)


# --- MIDI 1.0 in UMP + system ---

def test_midi1_packet_golden():
    (w0,) = ump.midi1_packet(0, 0x90, 60, 100)
    assert w0 == 0x20903C64
    m = ump.decode((w0,))
    assert (m.kind, m.status, m.data1, m.data2) == ("midi1", 0x90, 60, 100)
    assert m.channel == 0


def test_system_packet():
    (w0,) = ump.system_packet(0, 0xF8)  # clock
    m = ump.decode((w0,))
    assert m.kind == "system" and m.status == 0xF8


# --- SysEx7 ---

def test_sysex7_complete_golden():
    packets = ump.sysex7_encode(0, bytes([0x7E, 0x7F, 0x09]))
    assert packets == [(0x30037E7F, 0x09000000)]
    asm = ump.Sysex7Assembler()
    m = asm.feed(packets[0])
    assert m.kind == "sysex7" and m.payload == bytes([0x7E, 0x7F, 0x09])


@pytest.mark.parametrize("length", [0, 1, 5, 6, 7, 12, 13, 100])
def test_sysex7_roundtrip(length):
    payload = bytes(range(length % 128)) [:length] or bytes(length)
    payload = bytes((i * 7) % 128 for i in range(length))
    asm = ump.Sysex7Assembler()
    out = None
    for pkt in ump.sysex7_encode(3, payload):
        out = asm.feed(pkt)
    assert out is not None and out.payload == payload and out.group == 3


def test_sysex7_interleaved_groups():
    a = ump.sysex7_encode(1, bytes(range(10)))
    b = ump.sysex7_encode(2, bytes(range(64, 74)))
    asm = ump.Sysex7Assembler()
    results = []
    for pkt in (a[0], b[0], a[1], b[1]):
        m = asm.feed(pkt)
        if m:
            results.append((m.group, m.payload))
    assert results == [(1, bytes(range(10))), (2, bytes(range(64, 74)))]


def test_sysex7_orphan_continuation_dropped():
    packets = ump.sysex7_encode(0, bytes(range(10)))
    asm = ump.Sysex7Assembler()
    assert asm.feed(packets[1]) is None  # end without start


# --- Stream messages ---

def test_endpoint_info_notification():
    # status 0x01, UMP 1.1, 3 FBs, static, MIDI1+MIDI2 capable
    words = (0xF0010101, (1 << 31) | (3 << 24) | 0x3, 0, 0)
    m = ump.decode(words)
    assert m.kind == "stream" and m.status == ump.STREAM_EP_INFO
    assert m.index == 3          # function blocks
    assert m.bank_valid is True  # static
    assert m.value == 0x3        # protocol caps
    assert (m.data1, m.data2) == (1, 1)  # UMP version


def test_function_block_info_notification():
    # FB #2, active, first group 4, 2 groups
    w0 = (0xF << 28) | (ump.STREAM_FB_INFO << 16) | (1 << 15) | (2 << 8) | 0x03
    w1 = (4 << 24) | (2 << 16) | (0x11 << 8) | 0
    m = ump.decode((w0, w1, 0, 0))
    assert m.status == ump.STREAM_FB_INFO
    assert m.index == 2 and m.bank_valid is True
    assert m.note == 4 and m.velocity == 2   # first group / num groups
    assert m.data1 == 0x11                   # MIDI-CI version


def test_endpoint_name_text():
    name = b"TestSynth"
    raw = bytes(2) + name + bytes(16 - 2 - len(name))
    words = tuple(int.from_bytes(raw[i:i + 4], "big") for i in range(0, 16, 4))
    words = (words[0] | (0xF << 28) | (ump.STREAM_EP_NAME << 16),) + words[1:]
    m = ump.decode(words)
    assert m.status == ump.STREAM_EP_NAME and m.payload == name


def test_discovery_requests_encode():
    words = ump.endpoint_discovery()
    assert (words[0] >> 28) == 0xF and ((words[0] >> 16) & 0x3FF) == 0x00
    assert words[1] == 0x1F
    words = ump.function_block_discovery()
    assert ((words[0] >> 16) & 0x3FF) == 0x10 and ((words[0] >> 8) & 0xFF) == 0xFF


# --- ignored packet classes ---

@pytest.mark.parametrize("w0", [
    0x00000000,           # utility NOOP
    0x00200000 | 0x1234,  # utility JR timestamp (D5: strip)
    0x50000000,           # SysEx8/MDS
    0xD0000000,           # Flex Data
    0x60000000,           # reserved MT
])
def test_ignored_packets_return_none(w0):
    n = ump.packet_words(w0)
    assert ump.decode((w0,) + (0,) * (n - 1)) is None
