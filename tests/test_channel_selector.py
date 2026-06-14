"""Tests for the Channel Selector plugin."""

import importlib.util
import os
import sys

from raspimidihub.plugin_api import PluginBase

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODULE_NAME = "raspimidihub_plugin_channel_selector"


def _load_channel_selector():
    init_file = os.path.join(_ROOT, "plugins", "channel_selector", "__init__.py")
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME, init_file,
        submodule_search_locations=[os.path.dirname(init_file)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    for name in dir(module):
        obj = getattr(module, name)
        if (isinstance(obj, type) and issubclass(obj, PluginBase)
                and obj is not PluginBase and obj.__module__ == module.__name__):
            return obj
    raise AssertionError("ChannelSelector class not found")


ChannelSelector = _load_channel_selector()


def _make():
    """Instance with default param values + capture hooks wired."""
    p = ChannelSelector()
    p._param_values = {pp.name: getattr(pp, "default", 0)
                       for pp in _flatten(ChannelSelector.params)}
    sent = {"notes_on": [], "notes_off": [], "cc": [], "pb": [], "at": [], "pc": []}
    p._send_note_on = lambda ch, n, v: sent["notes_on"].append((ch, n, v))
    p._send_note_off = lambda ch, n: sent["notes_off"].append((ch, n))
    p._send_cc = lambda ch, c, v: sent["cc"].append((ch, c, v))
    p._send_pitchbend = lambda ch, v: sent["pb"].append((ch, v))
    p._send_aftertouch = lambda ch, v: sent["at"].append((ch, v))
    p._send_program_change = lambda ch, prog: sent["pc"].append((ch, prog))
    return p, sent


def _flatten(params):
    out = []
    for item in params:
        if hasattr(item, "children"):
            out.extend(item.children)
        else:
            out.append(item)
    return out


def test_default_labels_cover_off_plus_128_ccs():
    p, _ = _make()
    # value 0 -> "—", value 128 -> "CC 127"
    from raspimidihub_plugin_channel_selector import _CC_LABELS  # noqa
    assert _CC_LABELS[0] == "—"
    assert _CC_LABELS[1] == "CC 0"
    assert _CC_LABELS[128] == "CC 127"
    assert len(_CC_LABELS) == 129


def test_input_channel_ignored_notes_restamped_to_active():
    p, sent = _make()
    p._param_values["active_ch"] = 5
    p.on_note_on(channel=9, note=60, velocity=100)  # came in on ch 10 (0-based 9)
    assert sent["notes_on"] == [(4, 60, 100)]        # out on active ch 5 (0-based 4)


def test_selector_cc_switches_active_and_is_swallowed():
    p, sent = _make()
    p._param_values["cc_ch2"] = 22  # Ch 2 bound to CC 21 (value 22 -> CC 21)
    p.on_cc(channel=0, cc=21, value=127)
    assert p.get_param("active_ch") == 2
    assert sent["cc"] == []  # selector CC must not pass through


def test_selector_release_below_threshold_swallowed_no_switch():
    p, sent = _make()
    p._param_values["cc_ch3"] = 31  # CC 30
    p._param_values["active_ch"] = 1
    p.on_cc(channel=0, cc=30, value=0)  # release
    assert p.get_param("active_ch") == 1  # no switch on release
    assert sent["cc"] == []               # still swallowed


def test_unbound_cc_passes_through_on_active_channel():
    p, sent = _make()
    p._param_values["active_ch"] = 4
    p.on_cc(channel=0, cc=74, value=64)  # CC 74 bound to nothing
    assert sent["cc"] == [(3, 74, 64)]


def test_note_off_returns_to_original_channel_after_switch():
    p, sent = _make()
    p._param_values["active_ch"] = 1
    p._param_values["cc_ch8"] = 51  # CC 50 -> Ch 8
    p.on_note_on(channel=0, note=64, velocity=100)   # held on ch 1 (0-based 0)
    p.on_cc(channel=0, cc=50, value=127)             # switch to ch 8
    p.on_note_off(channel=0, note=64)
    assert sent["notes_on"] == [(0, 64, 100)]
    assert sent["notes_off"] == [(0, 64)]            # off on original channel, not 7


def test_velocity_zero_note_on_is_note_off():
    p, sent = _make()
    p._param_values["active_ch"] = 2
    p.on_note_on(channel=0, note=60, velocity=100)
    p.on_note_on(channel=0, note=60, velocity=0)  # running-status note off
    assert sent["notes_off"] == [(1, 60)]


def test_learn_captures_next_cc_into_active_channel_slot():
    p, sent = _make()
    p._param_values["active_ch"] = 6
    p.on_param_change("learn", True)   # arm
    p.on_cc(channel=0, cc=42, value=127)
    # value 43 stored => CC 42
    assert p.get_param("cc_ch6") == 43
    assert sent["cc"] == []            # captured CC not forwarded
    # next press of that CC now switches (slot is bound)
    p._param_values["active_ch"] = 1
    p.on_cc(channel=0, cc=42, value=127)
    assert p.get_param("active_ch") == 6


def test_pitchbend_and_pc_restamped():
    p, sent = _make()
    p._param_values["active_ch"] = 3
    p.on_pitchbend(channel=9, value=8192)
    p.on_program_change(channel=9, program=5)
    assert sent["pb"] == [(2, 8192)]
    assert sent["pc"] == [(2, 5)]
