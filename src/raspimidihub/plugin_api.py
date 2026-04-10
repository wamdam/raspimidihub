"""Plugin API for RaspiMIDIHub virtual instruments.

Plugin authors import from this module to create plugins. Each plugin is a
Python class that inherits from PluginBase and declares params, callbacks,
and I/O metadata. The framework handles threading, ALSA ports, UI rendering,
clock distribution, and persistence.

Example::

    from raspimidihub.plugin_api import (
        PluginBase, Group, Radio, Wheel, Toggle, Fader,
    )

    class MyPlugin(PluginBase):
        NAME = "My Plugin"
        DESCRIPTION = "Does something cool"
        AUTHOR = "You"
        VERSION = "1.0"

        params = [
            Group("Controls", [
                Wheel("speed", "Speed", min=1, max=10, default=5),
                Toggle("active", "Active", default=True),
            ]),
        ]

        def on_note_on(self, channel, note, velocity):
            self.send_note_on(channel, note, velocity)
"""

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Parameter types — declare UI controls, framework renders them
# ---------------------------------------------------------------------------

@dataclass
class Param:
    """Base for all param types."""
    name: str
    label: str
    visible_when: tuple | None = field(default=None, kw_only=True)  # (param_name, value_or_list)

    def to_dict(self) -> dict:
        d = {"type": self.__class__.__name__.lower(), "name": self.name, "label": self.label}
        if self.visible_when:
            d["visible_when"] = {"param": self.visible_when[0], "value": self.visible_when[1]}
        return d


@dataclass
class Wheel(Param):
    """Scrollable drum wheel with momentum, tick sound, and boundary thud."""
    min: int = 0
    max: int = 127
    default: int = 0

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"min": self.min, "max": self.max, "default": self.default})
        return d


@dataclass
class Fader(Param):
    """Mixer-strip fader with metallic thumb and tick feedback."""
    min: int = 0
    max: int = 127
    default: int = 0
    vertical: bool = False

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"min": self.min, "max": self.max, "default": self.default,
                  "vertical": self.vertical})
        return d


@dataclass
class Radio(Param):
    """Tap-to-select pill buttons."""
    options: list[str] = field(default_factory=list)
    default: str = ""

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"options": self.options, "default": self.default})
        return d


@dataclass
class Toggle(Param):
    """Metal switch with LED indicator."""
    default: bool = False

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["default"] = self.default
        return d


@dataclass
class StepEditor(Param):
    """Grid of steps with on/off dots and mini-wheel note offsets."""
    length_param: str = ""  # Radio param name that controls step count
    default_length: int = 16

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"length_param": self.length_param, "default_length": self.default_length})
        return d


@dataclass
class CurveEditor(Param):
    """128-point draw-on-canvas curve with presets."""

    def to_dict(self) -> dict:
        return super().to_dict()


@dataclass
class NoteSelect(Param):
    """Wheel with MIDI note names (C-2 to G8)."""
    default: int = 60  # Middle C

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["default"] = self.default
        return d


@dataclass
class ChannelSelect(Param):
    """Wheel for MIDI channel 1-16."""
    default: int = 1

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["default"] = self.default
        return d


@dataclass
class Group:
    """Titled section grouping related params."""
    title: str
    children: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": "group",
            "title": self.title,
            "children": [c.to_dict() for c in self.children],
        }


# ---------------------------------------------------------------------------
# Param serialization helpers
# ---------------------------------------------------------------------------

def params_to_dicts(params: list) -> list[dict]:
    """Serialize a params list to JSON-friendly dicts."""
    return [p.to_dict() for p in params]


def get_all_params(params: list) -> list[Param]:
    """Flatten params list, extracting Params from Groups."""
    result = []
    for p in params:
        if isinstance(p, Group):
            result.extend(get_all_params(p.children))
        elif isinstance(p, Param):
            result.append(p)
    return result


def get_defaults(params: list) -> dict[str, Any]:
    """Extract default values from all params."""
    defaults = {}
    for p in get_all_params(params):
        if isinstance(p, StepEditor):
            length = p.default_length
            defaults[p.name] = [{"on": False, "offset": 0} for _ in range(length)]
        elif isinstance(p, CurveEditor):
            defaults[p.name] = list(range(128))  # linear by default
        elif hasattr(p, "default"):
            defaults[p.name] = p.default
    return defaults


# ---------------------------------------------------------------------------
# PluginBase — all plugins inherit from this
# ---------------------------------------------------------------------------

class PluginBase:
    """Base class for RaspiMIDIHub plugins.

    Subclass this, set NAME/DESCRIPTION/params, and implement event handlers.
    The framework calls handlers on the plugin's own thread.
    Output methods (send_*) are injected by the host before on_start().
    """

    # --- Metadata (override in subclass) ---
    NAME: str = "Unnamed Plugin"
    DESCRIPTION: str = ""
    AUTHOR: str = ""
    VERSION: str = "1.0"

    # --- Parameter declarations (override in subclass) ---
    params: list = []

    # --- CC I/O declarations ---
    cc_inputs: dict[int, str] = {}   # CC# -> param name
    cc_outputs: list[int] = []       # CC numbers this plugin may send

    # --- Human-readable I/O descriptions ---
    inputs: list[str] = []
    outputs: list[str] = []

    # --- Clock ---
    clock_divisions: list[str] = []  # e.g. ["1/8", "1/16"]

    def __init__(self):
        self._param_values: dict[str, Any] = {}
        # Injected by host:
        self._send_note_on = None
        self._send_note_off = None
        self._send_cc = None
        self._send_pitchbend = None
        self._send_aftertouch = None
        self._send_program_change = None
        self._notify_param_change = None  # callback to notify UI of param update

    # --- Current param values ---

    def get_param(self, name: str) -> Any:
        """Get current value of a parameter."""
        return self._param_values.get(name)

    # --- Event handlers (override in subclass) ---

    def on_note_on(self, channel: int, note: int, velocity: int) -> None:
        pass

    def on_note_off(self, channel: int, note: int) -> None:
        pass

    def on_cc(self, channel: int, cc: int, value: int) -> None:
        pass

    def on_tick(self, division: str) -> None:
        pass

    def on_aftertouch(self, channel: int, value: int) -> None:
        pass

    def on_pitchbend(self, channel: int, value: int) -> None:
        pass

    def on_program_change(self, channel: int, program: int) -> None:
        pass

    def on_param_change(self, name: str, value: Any) -> None:
        pass

    def on_start(self) -> None:
        pass

    def on_stop(self) -> None:
        pass

    # --- Output methods (call from handlers to send MIDI out) ---

    def send_note_on(self, channel: int, note: int, velocity: int) -> None:
        if self._send_note_on:
            self._send_note_on(channel, note, velocity)

    def send_note_off(self, channel: int, note: int) -> None:
        if self._send_note_off:
            self._send_note_off(channel, note)

    def send_cc(self, channel: int, cc: int, value: int) -> None:
        if self._send_cc:
            self._send_cc(channel, cc, value)

    def send_pitchbend(self, channel: int, value: int) -> None:
        if self._send_pitchbend:
            self._send_pitchbend(channel, value)

    def send_aftertouch(self, channel: int, value: int) -> None:
        if self._send_aftertouch:
            self._send_aftertouch(channel, value)

    def send_program_change(self, channel: int, program: int) -> None:
        if self._send_program_change:
            self._send_program_change(channel, program)
