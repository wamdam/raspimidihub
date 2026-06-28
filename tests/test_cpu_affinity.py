"""CPU-affinity layout logic (cpu_affinity.py). The /sys read and the
actual sched_setaffinity calls are stubbed, so these exercise the pure
layout maths: loop core, plugin cores, housekeeping cores, and the
no-op-off-appliance guarantee."""

import raspimidihub.cpu_affinity as ca


def test_parse_cores():
    assert ca._parse_cores("3") == {3}
    assert ca._parse_cores("2,3") == {2, 3}
    assert ca._parse_cores("2-3") == {2, 3}
    assert ca._parse_cores("0,2-3\n") == {0, 2, 3}
    assert ca._parse_cores("") == set()
    assert ca._parse_cores("garbage") == set()


def test_layout_two_isolated_cores(monkeypatch):
    """The target layout: loop=3, plugins=2, housekeeping=0-1."""
    monkeypatch.setattr(ca, "_all_cpus", lambda: {0, 1, 2, 3})
    monkeypatch.setattr(ca, "isolated_cores", lambda: {2, 3})
    assert ca.loop_core() == 3
    assert ca.plugin_cpus() == {2}
    assert ca.housekeeping_cpus() == {0, 1}
    assert ca.housekeeping_taskset_arg() == "0,1"


def test_layout_one_isolated_core_interim(monkeypatch):
    """Before the cmdline/reboot (isolcpus=3): plugins fall back to the
    housekeeping cores rather than sharing the loop core."""
    monkeypatch.setattr(ca, "_all_cpus", lambda: {0, 1, 2, 3})
    monkeypatch.setattr(ca, "isolated_cores", lambda: {3})
    assert ca.loop_core() == 3
    assert ca.plugin_cpus() == {0, 1, 2}
    assert ca.housekeeping_cpus() == {0, 1, 2}


def test_layout_no_isolation_is_noop(monkeypatch):
    """Dev box / CI: nothing isolated → loop_core None and the move
    helpers never touch affinity."""
    monkeypatch.setattr(ca, "_all_cpus", lambda: {0, 1, 2, 3})
    monkeypatch.setattr(ca, "isolated_cores", lambda: set())
    assert ca.loop_core() is None
    called = []
    monkeypatch.setattr(ca, "_set_affinity", lambda c: called.append(c))
    ca.move_to_housekeeping()
    ca.move_to_plugin_cores()
    assert called == []


def test_move_helpers_target_correct_cores(monkeypatch):
    monkeypatch.setattr(ca, "_all_cpus", lambda: {0, 1, 2, 3})
    monkeypatch.setattr(ca, "isolated_cores", lambda: {2, 3})
    called = []
    monkeypatch.setattr(ca, "_set_affinity", lambda c: called.append(c))
    ca.move_to_housekeeping()
    ca.move_to_plugin_cores()
    assert called == [{0, 1}, {2}]
