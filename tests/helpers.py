"""Shared test helpers for RaspiMIDIHub."""

import os
import sys

# Add src and plugins to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "plugins"))

from raspimidihub.alsa_seq import MidiEventType, SndSeqEvent
from raspimidihub.plugin_api import PluginBase, get_defaults


def make_event(
    ev_type: int,
    channel: int = 0,
    note: int = 60,
    velocity: int = 100,
    cc: int = 0,
    value: int = 0,
    src_client: int = 1,
    src_port: int = 0,
    dst_client: int = 128,
    dst_port: int = 0,
) -> SndSeqEvent:
    """Build a SndSeqEvent ctypes struct for testing."""
    ev = SndSeqEvent()
    ev.type = ev_type
    ev.source.client = src_client
    ev.source.port = src_port
    ev.dest.client = dst_client
    ev.dest.port = dst_port

    if ev_type in (MidiEventType.NOTEON, MidiEventType.NOTEOFF):
        ev.data.note.channel = channel
        ev.data.note.note = note
        ev.data.note.velocity = velocity
    elif ev_type in (MidiEventType.CONTROLLER, MidiEventType.PITCHBEND,
                     MidiEventType.PGMCHANGE):
        ev.data.control.channel = channel
        ev.data.control.param = cc
        ev.data.control.value = value

    return ev


class PluginHarness:
    """Test harness that wraps a plugin with send callback collectors."""

    def __init__(self, plugin: PluginBase):
        self.plugin = plugin
        self.sent: list[tuple] = []

        plugin._send_note_on = lambda ch, n, v: self.sent.append(("note_on", ch, n, v))
        plugin._send_note_off = lambda ch, n: self.sent.append(("note_off", ch, n))
        plugin._send_cc = lambda ch, cc, v: self.sent.append(("cc", ch, cc, v))
        plugin._send_pitchbend = lambda ch, v: self.sent.append(("pitchbend", ch, v))
        plugin._send_aftertouch = lambda ch, v: self.sent.append(("aftertouch", ch, v))
        plugin._send_program_change = lambda ch, p: self.sent.append(("program_change", ch, p))
        plugin._send_clock = lambda: self.sent.append(("clock",))
        plugin._send_start = lambda: self.sent.append(("start",))
        plugin._send_stop = lambda: self.sent.append(("stop",))
        plugin._send_continue = lambda: self.sent.append(("continue",))
        plugin._notify_param_change = lambda iid, name, val: None
        plugin._notify_display = lambda name, val: None

    def clear(self):
        self.sent.clear()

    @property
    def note_ons(self) -> list[tuple]:
        return [(ch, n, v) for t, ch, n, v in self.sent if t == "note_on"]

    @property
    def note_offs(self) -> list[tuple]:
        return [(ch, n) for t, ch, n in self.sent if t == "note_off"]

    @property
    def ccs(self) -> list[tuple]:
        return [(ch, cc, v) for t, ch, cc, v in self.sent if t == "cc"]


def make_plugin(plugin_class):
    """Create a plugin instance with defaults and a test harness."""
    plugin = plugin_class()
    plugin._param_values = get_defaults(plugin_class.params)
    harness = PluginHarness(plugin)
    # Call on_start to initialize internal state (like _active, _lock, etc.)
    plugin.on_start()
    harness.clear()  # discard any output from on_start
    return plugin, harness
