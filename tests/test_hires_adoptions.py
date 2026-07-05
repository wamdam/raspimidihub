"""FSD-09 deferred adoptions: units_in_bucket, lattice snap in shims,
wants_hires_input dispatch, and byte-compat of the adopted plugins."""

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

from raspimidihub import midi_scale as ms
from raspimidihub import ump
from raspimidihub.alsa_seq import MidiEventType
from raspimidihub.plugin_host.host import PluginHost

cc_smoother = importlib.import_module("plugins.cc_smoother").CcSmoother
velocity_curve = importlib.import_module("plugins.velocity_curve").VelocityCurve
velocity_eq = importlib.import_module(
    "plugins.velocity_equalizer").VelocityEqualizer


# --- units_in_bucket ---------------------------------------------------

def test_units_in_bucket_projects_to_anchor():
    # Whatever the trajectory value, the floor projection (what a 1.0
    # receiver sees after lattice_interp + kernel truncation) is the
    # anchor.
    for anchor in (0, 1, 63, 64, 100, 126, 127):
        for v in (anchor - 0.49, anchor - 0.01, float(anchor),
                  anchor + 0.3, anchor + 0.49):
            u = ms.units_in_bucket(anchor, v)
            assert int(u) == anchor, (anchor, v, u)
            assert (ms.lattice_interp(u) >> 25) == anchor


def test_units_in_bucket_monotonic_within_bucket():
    prev = -1.0
    for i in range(50):
        u = ms.units_in_bucket(64, 63.51 + i * 0.019)
        assert u >= prev
        prev = u


# --- lattice snap in the shim -------------------------------------------

def test_shim_snaps_lattice_values_to_exact_ints():
    w = ump.cc(0, 0, 74, ms.scale_up(70, 7, 32))  # kernel-upscaled "70"
    ev = ump.to_monitor_shim(ump.decode(w), 1, 0, 2, 0, hires=True)
    assert ev.hires["value_f"] == 70.0            # not 69.999
    w = ump.note_on(0, 0, 60, ms.scale_up(100, 7, 16))
    ev = ump.to_monitor_shim(ump.decode(w), 1, 0, 2, 0, hires=True)
    assert ev.hires["velocity_f"] == 100.0
    # genuinely off-lattice values stay fractional
    w = ump.cc(0, 0, 74, ms.from_midi_units(70.5))
    ev = ump.to_monitor_shim(ump.decode(w), 1, 0, 2, 0, hires=True)
    assert ev.hires["value_f"] != 70.0 and abs(ev.hires["value_f"] - 70.5) < 0.01


# --- wants_hires_input dispatch ------------------------------------------

def _dispatch(plugin, ev):
    host = PluginHost()
    inst = SimpleNamespace(id="x", name="x", plugin=plugin)
    host._cc_to_param = MagicMock()
    host._dispatch_event(inst, ev, MidiEventType)
    return host


def _note_shim(vel16, hires=True):
    w = ump.note_on(0, 0, 60, vel16)
    return ump.to_monitor_shim(ump.decode(w), 1, 0, 2, 0, hires=hires)


class _HiresCapture(cc_smoother.__bases__[0]):  # PluginBase
    NAME = "HC"
    params = []
    wants_hires_input = True

    def __init__(self):
        super().__init__()
        self.notes, self.ccs = [], []

    def on_note_on(self, ch, note, vel):
        self.notes.append(vel)

    def on_cc(self, ch, cc, value):
        self.ccs.append(value)


def test_opted_in_plugin_receives_float_units():
    p = _HiresCapture()
    _dispatch(p, _note_shim(ms.from_midi_units(100.5, 16)))
    assert p.notes and isinstance(p.notes[0], float)
    assert abs(p.notes[0] - 100.5) < 0.01
    w = ump.cc(0, 0, 74, ms.from_midi_units(64.25))
    _dispatch(p, ump.to_monitor_shim(ump.decode(w), 1, 0, 2, 0, hires=True))
    assert p.ccs and abs(p.ccs[0] - 64.25) < 0.01


def test_opted_in_plugin_gets_exact_ints_from_7bit_sources():
    p = _HiresCapture()
    _dispatch(p, _note_shim(ms.scale_up(100, 7, 16)))
    assert p.notes[0] == 100.0


def test_non_opted_plugin_keeps_ints():
    class _Plain(_HiresCapture):
        wants_hires_input = False
    p = _Plain()
    vel16 = ms.from_midi_units(100.5, 16)
    _dispatch(p, _note_shim(vel16))
    assert isinstance(p.notes[0], int)
    assert p.notes[0] == ms.scale_down(vel16, 16, 7)  # plain 7-bit int


# --- adopted plugins: byte-compat for integer inputs ----------------------

def _sent(plugin):
    out = []
    plugin._send_note_on = lambda ch, n, v: out.append(v)
    plugin._send_cc = lambda ch, cc, v: out.append(v)
    return out


def test_velocity_curve_integer_inputs_byte_identical():
    p = velocity_curve()
    curve = [max(0, min(127, 127 - v)) for v in range(128)]  # inverse
    p._param_values["curve"] = curve
    out = _sent(p)
    for v in range(128):
        out.clear()
        p.on_note_on(0, 60, v)
        legacy = max(1, min(127, curve[v]))
        assert int(out[0]) == legacy, v  # floor projection == legacy


def test_velocity_curve_fractional_velocity_interpolates():
    p = velocity_curve()
    p._param_values["curve"] = list(range(128))  # identity
    out = _sent(p)
    p.on_note_on(0, 60, 100.5)
    # identity curve → out trajectory ≈ 100.5, projected into round's
    # bucket (100.5 rounds to 100 by banker's or 101 half-up — the
    # anchor comes from int(round(out)))
    assert abs(out[0] - (int(round(100.5)) - 0.5 + 100.5 - int(100.5))) < 1.0


def test_velocity_equalizer_integer_inputs_byte_identical():
    p = velocity_eq()
    out = _sent(p)
    for mode in ("compress", "expand"):
        p._param_values.update({"mode": mode, "out_min": 60, "out_max": 120})
        for v in range(128):
            out.clear()
            p.on_note_on(0, 60, v)
            if mode == "compress":
                legacy = 60 + round((v / 127) * 60)
            else:
                legacy = round(max(1, min(127, (v - 60) / 60 * 127)))
            legacy = max(1, min(127, legacy))
            assert int(out[0]) == legacy, (mode, v)


def test_cc_smoother_projection_matches_legacy_round():
    # The smoother emits units_in_bucket(round(new_val), new_val): for
    # any float trajectory the 1.0 projection equals the legacy
    # int(round(...)) output.
    x = 90.0
    for _ in range(40):
        x = x + 0.31 * (100 - x)
        legacy = max(0, min(127, int(round(x))))
        v = ms.units_in_bucket(legacy, x)
        assert int(v) == legacy
        assert (ms.lattice_interp(v) >> 25) == legacy
