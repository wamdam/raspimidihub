"""Phase 1 backend coverage for the user-bindable MIDI CC feature.

Exercises:
  - default_cc on Wheel / Knob / Fader / Radio / NoteSelect / Button
    seeds PluginBase.cc_map with {ch: None, cc: <default_cc>}.
  - serialize_instances writes cc_map only when it differs from the
    seed (and preserves cleared bindings).
  - restore_instances overlays the saved cc_map on top of the seed.
  - The dispatch loop fires every param whose binding matches and
    honours per-binding channel filters.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from raspimidihub.alsa_seq import MidiEventType
from raspimidihub.plugin_api import (
    BINDABLE_PARAM_TYPES,
    Button,
    Fader,
    Knob,
    NoteSelect,
    PluginBase,
    Radio,
    Wheel,
    get_default_cc_map,
)
from raspimidihub.plugin_host.host import PluginHost, _diff_cc_map


class _SeedPlugin(PluginBase):
    NAME = "Seed"
    params = [
        Wheel("rate", "Rate", default_cc=74),
        Knob("gate", "Gate", default_cc=75),
        Fader("depth", "Depth", default_cc=76),
        Radio("mode", "Mode", options=["a", "b"], default="a", default_cc=77),
        NoteSelect("split", "Split", default_cc=78),
        Button("trigger", "Trigger", default_cc=64),
        Wheel("undeclared", "Undeclared"),
    ]


def test_default_cc_seeds_cc_map():
    seed = get_default_cc_map(_SeedPlugin.params)
    assert seed == {
        "rate":    {"ch": None, "cc": 74},
        "gate":    {"ch": None, "cc": 75},
        "depth":   {"ch": None, "cc": 76},
        "mode":    {"ch": None, "cc": 77},
        "split":   {"ch": None, "cc": 78},
        "trigger": {"ch": None, "cc": 64},
    }
    assert "undeclared" not in seed


def test_pluginbase_init_seeds_cc_map():
    p = _SeedPlugin()
    assert p.cc_map["rate"] == {"ch": None, "cc": 74}
    assert p.cc_map["trigger"] == {"ch": None, "cc": 64}
    assert "undeclared" not in p.cc_map


def test_bindable_param_types_covers_every_default_cc_aware_class():
    # Every type that declares a default_cc field should be in the
    # BINDABLE_PARAM_TYPES tuple — otherwise the seeder silently drops
    # the binding and the param never accepts CC even though the
    # dataclass exposes the field.
    classes_with_default_cc = []
    for cls in (Wheel, Knob, Fader, Radio, NoteSelect, Button):
        fields = getattr(cls, "__dataclass_fields__", {})
        if "default_cc" in fields:
            classes_with_default_cc.append(cls)
    for cls in classes_with_default_cc:
        assert cls in BINDABLE_PARAM_TYPES, (
            f"{cls.__name__} declares default_cc but is not in "
            f"BINDABLE_PARAM_TYPES — its CC bindings would be ignored.")


def test_diff_cc_map_returns_only_changes():
    seed = {"rate": {"ch": None, "cc": 74}, "gate": {"ch": None, "cc": 75}}
    # Unchanged → no diff
    assert _diff_cc_map(dict(seed), seed) == {}
    # User rebinds rate to ch 1 cc 80
    live = {"rate": {"ch": 0, "cc": 80}, "gate": {"ch": None, "cc": 75}}
    assert _diff_cc_map(live, seed) == {"rate": {"ch": 0, "cc": 80}}


def test_diff_cc_map_persists_cleared_binding():
    # The cleared state (cc=None) must survive serialization so a
    # restart doesn't re-seed the default. _diff_cc_map sees None != 74
    # and emits the entry.
    seed = {"rate": {"ch": None, "cc": 74}}
    live = {"rate": {"ch": None, "cc": None}}
    diff = _diff_cc_map(live, seed)
    assert diff == {"rate": {"ch": None, "cc": None}}


def _host_with_seed_plugin():
    """Build a PluginHost with _SeedPlugin manually registered. The
    real discover_plugins() walks the plugins/ dir; tests don't need
    that — they just need a host that can serialise / restore /
    dispatch against our toy class."""
    host = PluginHost()
    host._plugin_types["_seed"] = _SeedPlugin
    return host


def test_serialize_clean_instance_omits_cc_map():
    host = _host_with_seed_plugin()
    plugin = _SeedPlugin()
    plugin._param_values = {p.name: getattr(p, "default", 0) for p in _SeedPlugin.params}
    inst = SimpleNamespace(
        id="seed-1",
        plugin_type="_seed",
        name="Seed 1",
        plugin=plugin,
    )
    host._instances["seed-1"] = inst
    snapshot = host.serialize_instances()
    assert len(snapshot) == 1
    assert "cc_map" not in snapshot[0]


def test_serialize_with_user_binding_carries_diff_only():
    host = _host_with_seed_plugin()
    plugin = _SeedPlugin()
    plugin._param_values = {p.name: getattr(p, "default", 0) for p in _SeedPlugin.params}
    plugin.cc_map["rate"] = {"ch": 0, "cc": 80}
    inst = SimpleNamespace(id="seed-1", plugin_type="_seed", name="Seed 1", plugin=plugin)
    host._instances["seed-1"] = inst
    snap = host.serialize_instances()[0]
    assert snap["cc_map"] == {"rate": {"ch": 0, "cc": 80}}


def test_round_trip_restores_user_binding_and_cleared_entries():
    host = _host_with_seed_plugin()
    plugin = _SeedPlugin()
    plugin._param_values = {p.name: getattr(p, "default", 0) for p in _SeedPlugin.params}
    plugin.cc_map["rate"] = {"ch": 0, "cc": 80}
    plugin.cc_map["gate"] = {"ch": None, "cc": None}  # cleared
    inst = SimpleNamespace(id="seed-1", plugin_type="_seed", name="Seed 1", plugin=plugin)
    host._instances["seed-1"] = inst
    snap = host.serialize_instances()

    # New host: restore via the same path the engine uses
    host2 = _host_with_seed_plugin()
    host2.create_instance = MagicMock(side_effect=lambda _t, _n: _make_fake_instance(host2))
    host2._restore_instances(snap)
    inst2 = next(iter(host2._instances.values()))
    assert inst2.plugin.cc_map["rate"] == {"ch": 0, "cc": 80}
    assert inst2.plugin.cc_map["gate"] == {"ch": None, "cc": None}
    # Untouched defaults survive
    assert inst2.plugin.cc_map["depth"] == {"ch": None, "cc": 76}


def _make_fake_instance(host: PluginHost):
    """Pretend the host created an instance — bypass ALSA + threading."""
    plugin = _SeedPlugin()
    plugin._param_values = {p.name: getattr(p, "default", 0) for p in _SeedPlugin.params}
    inst = SimpleNamespace(id=f"seed-{len(host._instances)+1}",
                            plugin_type="_seed", name="Seed", plugin=plugin)
    host._instances[inst.id] = inst
    return inst


def _build_cc_event(channel: int, cc: int, value: int) -> SimpleNamespace:
    """Minimal stand-in for an ALSA SndSeqEvent that _dispatch_event reads."""
    return SimpleNamespace(
        type=MidiEventType.CONTROLLER,
        data=SimpleNamespace(
            control=SimpleNamespace(channel=channel, param=cc, value=value),
            note=SimpleNamespace(channel=channel, note=0, velocity=0),
        ),
    )


class _CapturePlugin(PluginBase):
    NAME = "Capture"
    params = [
        Wheel("rate", "Rate", default_cc=74),
        Knob("gate", "Gate", default_cc=75),
    ]

    def __init__(self):
        super().__init__()
        self.on_cc_calls: list[tuple] = []

    def on_cc(self, channel, cc, value):
        self.on_cc_calls.append((channel, cc, value))


def _instance_for(plugin) -> SimpleNamespace:
    return SimpleNamespace(id="cap-1", plugin_type="_cap", name="Capture",
                           plugin=plugin, crashed=False, running=True,
                           crash_error=None)


def test_dispatch_routes_cc_to_bound_param():
    host = PluginHost()
    plugin = _CapturePlugin()
    inst = _instance_for(plugin)
    host._cc_to_param = MagicMock()

    host._dispatch_event(inst, _build_cc_event(0, 74, 100), MidiEventType)

    host._cc_to_param.assert_called_once_with(inst, "rate", 100, None)
    assert plugin.on_cc_calls == []  # matched binding short-circuits on_cc


def test_dispatch_falls_through_to_on_cc_when_no_binding_matches():
    host = PluginHost()
    plugin = _CapturePlugin()
    inst = _instance_for(plugin)
    host._cc_to_param = MagicMock()

    host._dispatch_event(inst, _build_cc_event(0, 99, 100), MidiEventType)

    host._cc_to_param.assert_not_called()
    assert plugin.on_cc_calls == [(0, 99, 100)]


def test_dispatch_fires_every_param_on_a_shared_cc():
    host = PluginHost()
    plugin = _CapturePlugin()
    # User binds gate to the same CC 74 — collisions are allowed.
    plugin.cc_map["gate"] = {"ch": None, "cc": 74}
    inst = _instance_for(plugin)
    host._cc_to_param = MagicMock()

    host._dispatch_event(inst, _build_cc_event(0, 74, 100), MidiEventType)

    call_params = [c.args[1] for c in host._cc_to_param.call_args_list]
    assert sorted(call_params) == ["gate", "rate"]


def test_dispatch_honours_channel_filter():
    host = PluginHost()
    plugin = _CapturePlugin()
    # Restrict the gate binding to channel 0 (wire MIDI ch 1).
    plugin.cc_map["gate"] = {"ch": 0, "cc": 75}
    inst = _instance_for(plugin)
    host._cc_to_param = MagicMock()

    # CC 75 on channel 1 → does NOT match gate (ch=0), falls through.
    host._dispatch_event(inst, _build_cc_event(1, 75, 100), MidiEventType)
    host._cc_to_param.assert_not_called()
    assert plugin.on_cc_calls == [(1, 75, 100)]

    # CC 75 on channel 0 → matches.
    host._cc_to_param.reset_mock()
    plugin.on_cc_calls.clear()
    host._dispatch_event(inst, _build_cc_event(0, 75, 100), MidiEventType)
    host._cc_to_param.assert_called_once_with(inst, "gate", 100, None)
    assert plugin.on_cc_calls == []


def test_dispatch_skips_cleared_bindings():
    host = PluginHost()
    plugin = _CapturePlugin()
    plugin.cc_map["rate"] = {"ch": None, "cc": None}  # cleared
    inst = _instance_for(plugin)
    host._cc_to_param = MagicMock()

    host._dispatch_event(inst, _build_cc_event(0, 74, 100), MidiEventType)

    host._cc_to_param.assert_not_called()
    # Falls through to on_cc since no binding matched
    assert plugin.on_cc_calls == [(0, 74, 100)]
