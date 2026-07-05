"""MIDI-CI codec (midi_ci) — build/parse round-trips + robustness."""

import json

from raspimidihub import midi_ci as ci


def test_muid_range_and_encoding():
    for _ in range(20):
        m = ci.new_muid()
        assert 0 <= m < 0x0FFFFF00
    assert ci._read_u28(ci._u28(0x0ABCDEF)) == 0x0ABCDEF
    assert ci._u28(ci.BROADCAST_MUID) == b"\x7f\x7f\x7f\x7f"
    assert all(b <= 0x7F for b in ci._u28(0x0FFFFFFE))


def test_discovery_roundtrip():
    frame = ci.build_discovery_inquiry(0x123456)
    assert frame[0] == 0xF0 and frame[-1] == 0xF7
    assert all(b <= 0x7F for b in frame[1:-1])  # 7-bit clean
    m = ci.parse(frame)
    assert m.sub2 == ci.MSG_DISCOVERY
    assert m.src_muid == 0x123456 and m.dst_muid == ci.BROADCAST_MUID
    assert m.max_sysex == 4096


def test_discovery_reply_roundtrip():
    frame = ci.build_discovery_reply(
        0x0A0B0C, 0x123456, manufacturer=(0x7D, 0x01, 0x02),
        family=0x0001, model=0x0002, version=b"\x01\x00\x00\x00",
        categories=ci.CAT_PROPERTY_EXCHANGE | ci.CAT_PROFILES, max_sysex=512)
    m = ci.parse(frame)
    assert m.sub2 == ci.MSG_DISCOVERY_REPLY
    assert m.manufacturer == (0x7D, 0x01, 0x02)
    assert (m.family, m.model) == (1, 2)
    assert m.device_version == (1, 0, 0, 0)
    assert m.categories & ci.CAT_PROPERTY_EXCHANGE
    assert m.categories & ci.CAT_PROFILES
    assert not m.categories & ci.CAT_PROCESS_INQUIRY
    assert m.max_sysex == 512


def test_pe_get_and_reply_roundtrip():
    frame = ci.build_pe_get(1, 2, 5, "DeviceInfo")
    m = ci.parse(frame)
    assert m.sub2 == ci.MSG_PE_GET and m.request_id == 5
    assert m.header == {"resource": "DeviceInfo"}
    assert (m.num_chunks, m.chunk_num) == (1, 1)

    body = json.dumps({"model": "X", "serialNumber": "1"}).encode()
    frame = ci.build_pe_get_reply(2, 1, 5, body)
    m = ci.parse(frame)
    assert m.sub2 == ci.MSG_PE_GET_REPLY and m.request_id == 5
    assert m.header == {"status": 200}
    assert json.loads(m.data) == {"model": "X", "serialNumber": "1"}
    assert all(b <= 0x7F for b in frame[1:-1])


def test_parse_accepts_unframed_and_rejects_garbage():
    frame = ci.build_discovery_inquiry(7)
    assert ci.parse(frame[1:-1]).sub2 == ci.MSG_DISCOVERY  # no F0/F7
    assert ci.parse(b"") is None
    assert ci.parse(b"\xF0\x43\x10\x00\xF7") is None       # non-universal
    assert ci.parse(b"\xF0\x7E\x7F\x0D\x70\xF7") is None   # truncated
    assert ci.parse(bytes(range(0, 0x70))) is None


def test_sysex_accumulator_reassembles_split_frames():
    frame = ci.build_discovery_inquiry(42)
    acc = ci.SysexAccumulator()
    out = []
    for i in range(0, len(frame), 5):  # arbitrary ALSA chunking
        out.extend(acc.feed(frame[i:i + 5]))
    assert out == [frame]
    # garbage before F0 is dropped; two frames back to back both land
    out = acc.feed(b"\x01\x02" + frame + frame)
    assert out == [frame, frame]
