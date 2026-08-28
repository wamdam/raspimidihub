"""Config restore must not clobber slot-bank plugins' live params.

Regressions for the Arpeggiator / Euclidean save-Load bug: the
serialized params dict carries `active_slot` BEFORE `pattern_slots`
(the bank list is only appended by `slot_bank.init_slot_bank` in
`on_start`, after the declared defaults). The old restore loop
applied saved params one by one in dict order, so
`active_slot=N` fired `on_param_change` → `slot_bank.load_slot(N)`
against the still factory-default bank and wrote every snapshotted
live param (root / scale / steps / pulses / steps_grid / ...) back
to defaults on every boot and Load — while the saved bank itself
landed correctly right after, with nothing left to re-sync.

The fix (`PluginHost._restore_instances`) applies saved params in
two passes — all values first, then `on_param_change` — and suppresses
`slot_bank.record_edit` for the duration so the replay cannot stamp
restored values onto the wrong slot.
"""

import json
from types import SimpleNamespace

from arpeggiator import Arpeggiator
from euclidean import Euclidean

from raspimidihub.plugin_api import get_defaults
from raspimidihub.plugin_host.host import PluginHost


def _make_fake_instance(host, plugin_type, name):
    """Stand-in for create_instance: same _param_values seeding and
    on_start (→ init_slot_bank) as the real path, without ALSA or the
    plugin thread. Running on_start BEFORE the restore applies the
    saved params is the worst case — the bank is seeded from factory
    defaults and then must be replaced by the saved bank."""
    cls = host._plugin_types[plugin_type]
    plugin = cls()
    plugin._param_values = get_defaults(cls.params)
    plugin.on_start()
    inst = SimpleNamespace(id=f"{plugin_type}-1", plugin_type=plugin_type,
                           name=name, plugin=plugin)
    host._instances[inst.id] = inst
    return inst


def _build_host():
    host = PluginHost()
    host._plugin_types["euclidean"] = Euclidean
    host._plugin_types["arpeggiator"] = Arpeggiator
    host.create_instance = (
        lambda t, n: _make_fake_instance(host, t, n or "1"))
    return host


def _edit(p, name, value):
    """Mimic PluginHost.set_param on the live plugin: value write +
    on_param_change (where the slot bank records the edit)."""
    p.set_param(name, value)
    p.on_param_change(name, value)


def _round_trip(host):
    """serialize_instances → JSON (order preserved) → fresh host."""
    snap = json.loads(json.dumps(host.serialize_instances()))
    host2 = _build_host()
    host2.restore_instances(snap)
    return host2, snap


def test_serialized_order_has_active_slot_before_pattern_slots():
    """The test's premise: a real running instance serialises
    `active_slot` ahead of `pattern_slots` (bank key appended in
    on_start). If that ever changes, re-check this file."""
    host = _build_host()
    host.create_instance("euclidean", "Euclidean 1")
    order = list(host.serialize_instances()[0]["params"].keys())
    assert order.index("active_slot") < order.index("pattern_slots"), (
        "pattern_slots now precedes active_slot in the serialized "
        "params — the restore-ordering regression this file guards "
        "against may no longer be reachable; update the test.")


def test_euclidean_nonzero_active_slot_survives_restore():
    """The user-reported case: D minor / 9 steps / 5 pulses on slot 3.
    A restore must bring the live surface back to the user's values,
    and must NOT stamp them onto slot 0 (which holds a different
    pattern)."""
    host = _build_host()
    host.create_instance("euclidean", "Euclidean 1")
    p = next(iter(host._instances.values())).plugin

    # Work on slot 0 first (give it its own distinct contents).
    _edit(p, "root", 9)          # A# major on slot 0
    _edit(p, "steps", 12)
    # Then switch to slot 3 and build the user's set there.
    _edit(p, "active_slot", 3)
    _edit(p, "root", 2)          # D
    _edit(p, "scale", 1)         # minor
    _edit(p, "steps", 9)
    _edit(p, "pulses", 5)
    assert (p.get_param("root"), p.get_param("scale"),
            p.get_param("steps"), p.get_param("pulses")) == (2, 1, 9, 5)
    slot0 = p.get_param("pattern_slots")[0]
    assert (slot0["root"], slot0["steps"]) == (9, 12)

    host2, _ = _round_trip(host)
    p2 = next(iter(host2._instances.values())).plugin

    # Live state restored to the user's set, not the factory defaults
    # (C major / 16 steps / 4 pulses).
    assert (p2.get_param("root"), p2.get_param("scale"),
            p2.get_param("steps"), p2.get_param("pulses")) == (2, 1, 9, 5), (
        f"live params clobbered on restore: "
        f"root={p2.get_param('root')} scale={p2.get_param('scale')} "
        f"steps={p2.get_param('steps')} pulses={p2.get_param('pulses')}")
    assert p2.get_param("active_slot") == 3
    # Slot 0 keeps its own contents — the replay must not stamp the
    # restored live values onto it.
    s0 = p2.get_param("pattern_slots")[0]
    assert (s0["root"], s0["steps"]) == (9, 12), (
        f"slot 0 corrupted by restore replay: {s0['root']}/{s0['steps']}")
    # Slot 3 carries the user's set.
    s3 = p2.get_param("pattern_slots")[3]
    assert (s3["root"], s3["scale"], s3["steps"], s3["pulses"]) == (2, 1, 9, 5)


def test_euclidean_active_slot_zero_survives_restore():
    """The path that already worked (edits record into the active slot
    0 during the replay): guard it against regressions of the
    two-pass restore."""
    host = _build_host()
    host.create_instance("euclidean", "Euclidean 1")
    p = next(iter(host._instances.values())).plugin
    _edit(p, "root", 2)
    _edit(p, "scale", 1)
    _edit(p, "steps", 9)
    assert p.get_param("active_slot") == 0

    host2, _ = _round_trip(host)
    p2 = next(iter(host2._instances.values())).plugin
    assert (p2.get_param("root"), p2.get_param("scale"),
            p2.get_param("steps"), p2.get_param("pulses")) == (2, 1, 9, 4)
    assert p2.get_param("active_slot") == 0


def test_arpeggiator_nonzero_active_slot_survives_restore():
    """Same machinery, second consumer: the Arpeggiator's bank."""
    host = _build_host()
    host.create_instance("arpeggiator", "Arp 1")
    p = next(iter(host._instances.values())).plugin

    _edit(p, "accent_vel", 90)     # distinct slot-0 content
    _edit(p, "active_slot", 5)
    _edit(p, "step_count", 12)
    _edit(p, "pattern", 2)        # "up-down"
    assert (p.get_param("step_count"), p.get_param("pattern")) == (12, 2)

    host2, _ = _round_trip(host)
    p2 = next(iter(host2._instances.values())).plugin
    # Not the factory defaults (8 steps / pattern 0).
    assert (p2.get_param("step_count"), p2.get_param("pattern")) == (12, 2), (
        f"live params clobbered on restore: "
        f"step_count={p2.get_param('step_count')} "
        f"pattern={p2.get_param('pattern')}")
    assert p2.get_param("active_slot") == 5
    s0 = p2.get_param("pattern_slots")[0]
    assert s0["accent_vel"] == 90, "slot 0 corrupted by restore replay"
