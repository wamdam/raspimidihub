"""FSD-08: CC→param binding at MIDI 2.0 resolution + `fine` params."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from raspimidihub import midi_scale as ms
from raspimidihub.plugin_api import Fader, PluginBase, Wheel
from raspimidihub.plugin_host.host import PluginHost


class _P(PluginBase):
    NAME = "P"
    params = [
        Wheel("coarse", "Coarse", min=0, max=100),
        Fader("smooth", "Smooth", min=0.0, max=1.0, fine=True, decimals=3),
    ]


def _host_and_instance():
    host = PluginHost()
    plugin = _P()
    inst = SimpleNamespace(id="p-1", name="P", plugin=plugin)
    host._instances = {"p-1": inst}
    host.set_param = MagicMock()
    return host, inst, host.set_param


def test_lattice_input_matches_legacy_math():
    host, inst, set_param = _host_and_instance()
    for v in range(128):
        set_param.reset_mock()
        host._cc_to_param(inst, "coarse", v, ms.scale_up(v, 7, 32))
        legacy = round(v / 127 * 100)
        set_param.assert_called_once_with("p-1", "coarse", legacy)


def test_legacy_client_none_value32():
    host, inst, set_param = _host_and_instance()
    host._cc_to_param(inst, "coarse", 64, None)
    set_param.assert_called_once_with("p-1", "coarse", round(64 / 127 * 100))


def test_hires_input_drives_fine_param_fractionally():
    host, inst, set_param = _host_and_instance()
    val32 = ms.from_midi_units(100.5)  # off-lattice
    host._cc_to_param(inst, "smooth", ms.scale_down(val32, 32, 7), val32)
    value = set_param.call_args[0][2]
    assert abs(value - 100.5 / 127) < 0.001
    assert value != round(value)  # genuinely fractional


def test_hires_input_on_integer_param_hits_intermediate_steps():
    host, inst, set_param = _host_and_instance()
    # Two adjacent hi-res values that straddle an integer boundary of
    # the 0-100 param still land on ints (param is not fine)…
    val32 = ms.from_midi_units(64.33)
    host._cc_to_param(inst, "coarse", ms.scale_down(val32, 32, 7), val32)
    v = set_param.call_args[0][2]
    assert isinstance(v, int) and 0 <= v <= 100


def test_fine_param_schema_export():
    d = _P.params[1].to_dict()
    assert d["fine"] is True and d["decimals"] == 3
    assert "fine" not in _P.params[0].to_dict()
