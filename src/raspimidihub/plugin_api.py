"""Plugin API for RaspiMIDIHub virtual instruments.

Plugin authors import from this module to create plugins. Each plugin is a
Python class that inherits from PluginBase and declares params, callbacks,
and I/O metadata. The framework handles threading, ALSA ports, UI rendering,
clock distribution, and persistence.

Example::

    from raspimidihub.plugin_api import (
        PluginBase, Group, Radio, Wheel, Button, Fader,
    )

    class MyPlugin(PluginBase):
        NAME = "My Plugin"
        DESCRIPTION = "Does something cool"
        AUTHOR = "You"
        VERSION = "1.0"

        params = [
            Group("Controls", [
                Wheel("speed", "Speed", min=1, max=10, default=5),
                Button("active", "Active", default=True, color="green"),
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
    # Grid-column footprint in the param-row. Default 1u; set to 2/3/4
    # for wider controls (e.g. a fat horizontal fader spanning the row).
    span: int = field(default=1, kw_only=True)
    # If True, this param is shown only in the device-config panel
    # (Routing tab) and hidden on play surfaces (Controller fullscreen
    # page). Used for instance-level meta config like background colour.
    config_only: bool = field(default=False, kw_only=True)

    def to_dict(self) -> dict:
        d = {"type": self.__class__.__name__.lower(), "name": self.name, "label": self.label}
        if self.visible_when:
            d["visible_when"] = {"param": self.visible_when[0], "value": self.visible_when[1]}
        if self.span and self.span > 1:
            d["span"] = self.span
        if self.config_only:
            d["config_only"] = True
        return d


@dataclass
class Wheel(Param):
    """Scrollable drum wheel with momentum, tick sound, and boundary thud."""
    min: int = 0
    max: int = 127
    default: int = 0
    display_factor: float = 0  # if >0, display value*factor (e.g. 0.1 for Hz tenths)
    unit: str = ""  # suffix shown after value (e.g. "Hz", "%")
    labels: list[str] = field(default_factory=list)  # if set, show labels[value-min] instead of number

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"min": self.min, "max": self.max, "default": self.default})
        if self.labels:
            d["labels"] = self.labels
        if self.display_factor:
            d["display_factor"] = self.display_factor
        if self.unit:
            d["unit"] = self.unit
        return d


@dataclass
class Knob(Param):
    """Round knob with value text in the middle, indicator mark on the body,
    and an LED arc around it that lights up to the current value's angle."""
    min: int = 0
    max: int = 127
    default: int = 0
    display_factor: float = 0
    unit: str = ""
    labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"min": self.min, "max": self.max, "default": self.default})
        if self.labels:
            d["labels"] = self.labels
        if self.display_factor:
            d["display_factor"] = self.display_factor
        if self.unit:
            d["unit"] = self.unit
        return d


@dataclass
class Fader(Param):
    """Mixer-strip fader with metallic thumb and tick feedback."""
    min: int = 0
    max: int = 127
    default: int = 0
    vertical: bool = False
    display_format: str = ""  # Python format string, e.g. "{:.1f} Hz" with display_factor
    display_factor: float = 0  # if >0, thumb shows value*factor formatted by display_format

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"min": self.min, "max": self.max, "default": self.default,
                  "vertical": self.vertical})
        if self.display_factor:
            d["display_factor"] = self.display_factor
        if self.display_format:
            d["display_format"] = self.display_format
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
class StepEditor(Param):
    """Grid of steps with on/off dots and mini-wheel note offsets."""
    length_param: str = ""  # Wheel/Radio param name that controls step count
    default_length: int = 16
    default_on: bool = False  # default on/off state for new steps

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"length_param": self.length_param, "default_length": self.default_length,
                  "default_on": self.default_on})
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
    learnable: bool = True  # show a MIDI Learn button below the wheel

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["default"] = self.default
        d["learnable"] = self.learnable
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
class Button(Param):
    """Rubber push button with colored LED indicator. Boolean value.

    Two modes:
      - Latching (default, `trigger=False`): click flips value. LED follows
        value. Off/On text shown.
      - Trigger (`trigger=True`): click always sends True. LED flashes
        for ≥100 ms regardless, then follows value (server is expected
        to reset value to False after handling, broadcast back via SSE).
        No Off/On text. Used for one-shot fire actions (Panic, Drop pad).
    """
    default: bool = False
    color: str = "green"  # LED color: green, yellow, red, blue
    trigger: bool = False  # momentary fire-mode if True

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"default": self.default, "color": self.color,
                  "trigger": self.trigger})
        return d


@dataclass
class Display(Param):
    """Inline display output placeholder — references a display_output by name."""
    display_name: str = ""  # name of the display_output to render here

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["display_name"] = self.display_name
        return d


@dataclass
class Group:
    """Titled section grouping related params."""
    title: str
    children: list = field(default_factory=list)
    cols: int | None = None  # override default 4-col grid for this group's inline row

    def to_dict(self) -> dict:
        d = {
            "type": "group",
            "title": self.title,
            "children": [c.to_dict() for c in self.children],
        }
        if self.cols is not None:
            d["cols"] = self.cols
        return d


@dataclass
class DropButtonRow(Param):
    """Row of N quarter-width snapshot buttons with per-button mode.

    Replaces DropPad on the §5 Controller plugins. Each button:
      - long-press → capture current state into THIS button's snapshot
      - short-press →
          mode=immediately: fire snapshot now
          mode=bar / 4bar: schedule fire at next bar / 4-bar boundary
      - second short-press while scheduled → cancel
    Only one drop on the controller can be `scheduled` at a time;
    scheduling on any button cancels the others' schedules.

    Wire format: the param's value is an action signal of shape
    `{"button_id": 0..N-1, "action": "fire" | "capture" | "cancel"}`.
    Server resets to `{"action": "idle"}` after handling. The actual
    per-button state (idle / captured / scheduled / firing), labels,
    modes, snapshots, and the controller-wide schedule reference live
    in sibling auxiliary params (see ControllerBase setup).
    """
    count: int = 4
    default: dict = field(default_factory=lambda: {"action": "idle"})
    # Names of sibling params that hold per-button auxiliary state.
    # The frontend reads these to render labels, modes, captured flags
    # and the currently-scheduled button + progress.
    states_param: str | None = None       # dict[str(id) -> 'idle'|'captured'|'scheduled'|'firing']
    snapshots_param: str | None = None    # dict[str(id) -> {cell_name: value}]
    modes_param: str | None = None        # dict[str(id) -> 'immediately'|'bar'|'4bar']
    labels_param: str | None = None       # dict[str(id) -> str (display name)]
    schedule_param: str | None = None     # {button_id, set_at_tick, fire_at_tick, progress}|null

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["count"] = self.count
        if self.states_param:
            d["states_param"] = self.states_param
        if self.snapshots_param:
            d["snapshots_param"] = self.snapshots_param
        if self.modes_param:
            d["modes_param"] = self.modes_param
        if self.labels_param:
            d["labels_param"] = self.labels_param
        if self.schedule_param:
            d["schedule_param"] = self.schedule_param
        return d


@dataclass
class XYPad(Param):
    """Square pad with a draggable dot. Two-axis value stored as
    `{"x": int, "y": int}`. Used inside LayoutGrid templates as a touch-
    friendly dual-CC controller cell."""
    min: int = 0
    max: int = 127
    default_x: int = 64
    default_y: int = 64

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"min": self.min, "max": self.max,
                  "default_x": self.default_x, "default_y": self.default_y})
        return d


@dataclass
class LayoutCell:
    """One positioned cell in a LayoutGrid: a Param + (col, row, span).

    Optional `channel` + `cc` declare the cell's default MIDI binding —
    used by Controller plugins. Channel is 0-based internally (matches
    ALSA seq); the UI displays 1-based. For XY pad cells the X axis
    uses (channel, cc) and the Y axis uses (channel_y, cc_y); when
    channel_y is None the Y axis falls back to the X channel. The user
    can override any of the four via the LayoutGrid's `bindings_param`
    dict at runtime.
    """
    param: Param
    col: int  # 1-based column
    row: int  # 1-based row
    span_cols: int = 1
    span_rows: int = 1
    channel: int | None = None    # 0-based default MIDI channel (X axis on XY)
    cc: int | None = None         # default CC number (0-127); X axis on XY pads
    channel_y: int | None = None  # XY-pad-only: default Y-axis channel (None = same as X)
    cc_y: int | None = None       # XY-pad-only: default Y-axis CC (0-127)


@dataclass
class LayoutGrid:
    """Fixed-position grid of cells (Knob / Fader / Button / XYPad).

    Used by the §5 Controller plugin templates. Each cell declares its
    (col, row) and optional span, so an XYPad can claim 2×2 while
    surrounding knobs are 1×1. Cells render via the existing renderParam
    dispatcher — LayoutGrid is a structural container, not a value-
    holding param.

    `labels_param` / `bindings_param` / `learn_param`: optional names of
    sibling params holding per-cell user overrides — these ARE server-
    stored (so renames + rebinds + Learn captures sync across browsers).
    Edit-mode is purely local React state owned by the JS component, so
    toggling "Edit cells" on one browser does NOT propagate.
    """
    name: str
    label: str
    cols: int = 8
    rows: int = 4
    cells: list = field(default_factory=list)  # list[LayoutCell]
    labels_param: str | None = None
    bindings_param: str | None = None
    learn_param: str | None = None  # str-valued: "" idle, "<cell_name>" learning

    def to_dict(self) -> dict:
        d = {
            "type": "layoutgrid",
            "name": self.name,
            "label": self.label,
            "cols": self.cols,
            "rows": self.rows,
            "cells": [
                {
                    "col": c.col, "row": c.row,
                    "span_cols": c.span_cols, "span_rows": c.span_rows,
                    "param": c.param.to_dict(),
                    **({"channel": c.channel} if c.channel is not None else {}),
                    **({"cc": c.cc} if c.cc is not None else {}),
                    **({"channel_y": c.channel_y} if c.channel_y is not None else {}),
                    **({"cc_y": c.cc_y} if c.cc_y is not None else {}),
                }
                for c in self.cells
            ],
        }
        if self.labels_param:
            d["labels_param"] = self.labels_param
        if self.bindings_param:
            d["bindings_param"] = self.bindings_param
        if self.learn_param:
            d["learn_param"] = self.learn_param
        return d


# ---------------------------------------------------------------------------
# Param serialization helpers
# ---------------------------------------------------------------------------

def params_to_dicts(params: list) -> list[dict]:
    """Serialize a params list to JSON-friendly dicts."""
    return [p.to_dict() for p in params]


def get_all_params(params: list) -> list[Param]:
    """Flatten params list, extracting Params from Groups and LayoutGrids."""
    result = []
    for p in params:
        if isinstance(p, Group):
            result.extend(get_all_params(p.children))
        elif isinstance(p, LayoutGrid):
            result.extend(get_all_params([c.param for c in p.cells]))
        elif isinstance(p, Param):
            result.append(p)
    return result


def get_defaults(params: list) -> dict[str, Any]:
    """Extract default values from all params."""
    defaults = {}
    for p in get_all_params(params):
        if isinstance(p, StepEditor):
            length = p.default_length
            defaults[p.name] = [{"on": p.default_on, "offset": 0} for _ in range(length)]
        elif isinstance(p, CurveEditor):
            defaults[p.name] = list(range(128))  # linear by default
        elif isinstance(p, XYPad):
            defaults[p.name] = {"x": p.default_x, "y": p.default_y}
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
    DESCRIPTION: str = ""  # short one-liner for plugin browser
    HELP: str = ""  # longer help text with examples, shown via ? button
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
    # True only for plugins that GENERATE clock from scratch (Master Clock).
    # When True, the plugin's emitted CLOCK / START / CONTINUE / STOP feeds
    # the global ClockBus so that bus-following plugins (Arpeggiator, CC LFO,
    # MIDI Delay) can sync to it. Default False — clock-processing plugins
    # like Clock Divider must not feed the bus or they'd pollute the
    # system's tempo perception with their own divided output.
    feeds_clock_bus: bool = False

    # --- Display outputs (declared in subclass, framework renders read-only) ---
    # Each entry: {"name": str, "type": "meter"|"text", "label": str, "min": 0, "max": 127}
    display_outputs: list[dict] = []

    def __init__(self):
        self._param_values: dict[str, Any] = {}
        self._display_values: dict[str, Any] = {}
        # Injected by host:
        self._send_note_on = None
        self._send_note_off = None
        self._send_cc = None
        self._send_pitchbend = None
        self._send_aftertouch = None
        self._send_program_change = None
        self._send_clock = None
        self._send_start = None
        self._send_stop = None
        self._send_continue = None
        self._notify_param_change = None  # callback to notify UI of param update
        self._notify_display = None  # callback to push display updates to UI

    # --- Current param values ---

    def get_param(self, name: str) -> Any:
        """Get current value of a parameter."""
        return self._param_values.get(name)

    def set_param(self, name: str, value: Any) -> None:
        """Update a parameter value from inside the plugin and push the
        change to the UI via SSE. Use this for trigger-style buttons that
        reset their value after firing (e.g. Panic, Drop pad)."""
        self._param_values[name] = value
        if self._notify_param_change:
            try:
                self._notify_param_change(name, value)
            except Exception:
                pass

    # --- Display output (push live state to UI) ---

    def set_display(self, name: str, value: Any) -> None:
        """Update a display output value. Pushed to UI via SSE."""
        self._display_values[name] = value
        if self._notify_display:
            try:
                self._notify_display(name, value)
            except Exception:
                pass

    # --- Event handlers (override in subclass) ---

    def on_note_on(self, channel: int, note: int, velocity: int) -> None:
        pass

    def on_note_off(self, channel: int, note: int) -> None:
        pass

    def on_cc(self, channel: int, cc: int, value: int) -> None:
        pass

    def on_transport_start(self) -> None:
        """MIDI Start received — reset to beginning."""
        pass

    def on_transport_stop(self) -> None:
        """MIDI Stop received."""
        pass

    def on_transport_continue(self) -> None:
        """MIDI Continue received — resume without resetting position."""
        pass

    # Source-routed clock callbacks (delivered when CLOCK / START / CONTINUE
    # / STOP arrives at *this plugin's IN port* via the matrix). Use these
    # instead of the global ClockBus when you need per-source clock — e.g.
    # a Clock Divider that should only tick from clock actually wired to
    # it, not from any clock the engine happens to see.

    def on_clock(self) -> None:
        """A MIDI Clock (24 PPQ) arrived on this plugin's IN port."""
        pass

    def on_clock_start(self) -> None:
        """A MIDI Start arrived on this plugin's IN port."""
        pass

    def on_clock_continue(self) -> None:
        """A MIDI Continue arrived on this plugin's IN port."""
        pass

    def on_clock_stop(self) -> None:
        """A MIDI Stop arrived on this plugin's IN port."""
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

    def panic(self) -> None:
        """Release all internal state so the plugin stops producing notes.

        Called by the global Panic action. Override in plugins that hold
        internal note state (Hold, Arp, Chord Generator, Note-to-CC toggle)
        to silence any sustaining output. Default is a no-op — stateless
        plugins (Transpose, CC LFO, etc.) don't need to do anything.
        """
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

    def send_clock(self) -> None:
        """Send MIDI Clock tick (24 PPQ)."""
        if self._send_clock:
            self._send_clock()

    def send_start(self) -> None:
        """Send MIDI Start (transport)."""
        if self._send_start:
            self._send_start()

    def send_stop(self) -> None:
        """Send MIDI Stop (transport)."""
        if self._send_stop:
            self._send_stop()

    def send_continue(self) -> None:
        """Send MIDI Continue (transport)."""
        if self._send_continue:
            self._send_continue()
