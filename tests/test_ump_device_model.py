"""UMP device modelling — port presentation policy + config block."""

from raspimidihub.alsa_seq import MidiDevice, MidiPort, apply_ump_port_policy
from raspimidihub.config import DEFAULT_CONFIG


def _port(pid, group=0, endpoint=False):
    return MidiPort(port_id=pid, name=f"P{pid}", is_input=True, is_output=True,
                    ump_group=group, is_ump_endpoint=endpoint)


def test_policy_multi_block_hides_catchall():
    ports = [_port(0, endpoint=True), _port(1, group=1), _port(2, group=2)]
    kept = apply_ump_port_policy(ports, num_blocks=2)
    assert [p.port_id for p in kept] == [1, 2]


def test_policy_single_block_collapses_to_endpoint():
    ports = [_port(0, endpoint=True), _port(1, group=1)]
    kept = apply_ump_port_policy(ports, num_blocks=1)
    assert [p.port_id for p in kept] == [0]
    kept = apply_ump_port_policy(ports, num_blocks=0)
    assert [p.port_id for p in kept] == [0]


def test_policy_never_returns_empty():
    # Odd topologies (no endpoint port visible, or only the endpoint
    # port with many FBs) fall back to whatever exists.
    only_groups = [_port(1, group=1)]
    assert apply_ump_port_policy(only_groups, num_blocks=0) == only_groups
    only_ep = [_port(0, endpoint=True)]
    assert apply_ump_port_policy(only_ep, num_blocks=3) == only_ep


def test_device_defaults_non_ump():
    dev = MidiDevice(client_id=20, name="X")
    assert dev.is_ump is False and dev.midi2_protocol is False
    assert dev.function_blocks == [] and dev.endpoint_name == ""


def test_config_midi2_default_block():
    assert DEFAULT_CONFIG["midi2"] == {"force_midi1": [],
                                       "ci_enabled": True,
                                       "ci_disabled": []}
