"""FSD-09: float-valued sends — lattice_interp + plugin client path."""

from unittest.mock import MagicMock

from raspimidihub import midi_scale as ms
from raspimidihub import ump
from raspimidihub.alsa_seq import MidiEventType
from raspimidihub.plugin_host.alsa_client import PluginAlsaClient


def test_lattice_interp_truncation_property():
    # Every fractional unit value must truncate back to int(units) at
    # 7 bits — the projection legacy int() casts produced.
    u = 0.0
    prev = -1
    while u <= 127.0:
        v32 = ms.lattice_interp(u)
        assert (v32 >> 25) == int(u), u
        assert v32 >= prev  # monotonic
        prev = v32
        u = round(u + 0.13, 2)


def test_lattice_interp_anchors_and_clamp():
    assert ms.lattice_interp(0.0) == 0
    assert ms.lattice_interp(127.0) == 0xFFFFFFFF
    assert ms.lattice_interp(200.0) == 0xFFFFFFFF
    assert ms.lattice_interp(-5.0) == 0
    assert ms.lattice_interp(64.0) == 0x80000000
    # 16-bit variant (velocity)
    assert ms.lattice_interp(100.0, 7, 16) >> 9 == 100


def _client(midi_version):
    c = PluginAlsaClient.__new__(PluginAlsaClient)
    c._midi_version = midi_version
    c._rate_window = []
    c._client_id = 130
    c._out_port = 1
    c._handle = None  # mock lib ignores it
    c._alsa = __import__("raspimidihub.alsa_seq", fromlist=["x"])
    c._send_ump_words = MagicMock()
    return c


def test_float_cc_goes_out_as_ump_on_v2_client():
    c = _client(2)
    c.send_event(MidiEventType.CONTROLLER, channel=3, cc=74, value=64.5)
    words = c._send_ump_words.call_args[0][0]
    m = ump.decode(words)
    assert (m.kind, m.channel, m.index) == ("cc", 3, 74)
    assert m.value == ms.lattice_interp(64.5)
    assert (m.value >> 25) == 64  # 1.0 receivers see the legacy floor


def test_float_velocity_goes_out_as_ump_note_on():
    c = _client(2)
    c.send_event(MidiEventType.NOTEON, channel=0, note=60, velocity=100.5)
    m = ump.decode(c._send_ump_words.call_args[0][0])
    assert m.kind == "note_on" and m.note == 60
    assert (m.velocity >> 9) == 100


def test_int_values_keep_classic_path():
    c = _client(2)
    c.send_event(MidiEventType.CONTROLLER, channel=0, cc=1, value=100)
    c._send_ump_words.assert_not_called()


def test_legacy_client_floors_floats():
    c = _client(0)
    # mock lib swallows the output; just assert no crash and no UMP
    c.send_event(MidiEventType.CONTROLLER, channel=0, cc=1, value=99.9)
    c._send_ump_words.assert_not_called()
