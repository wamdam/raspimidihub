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
    mini: bool = False  # half-height variant for dense edit panels

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"min": self.min, "max": self.max, "default": self.default})
        if self.labels:
            d["labels"] = self.labels
        if self.display_factor:
            d["display_factor"] = self.display_factor
        if self.unit:
            d["unit"] = self.unit
        if self.mini:
            d["mini"] = True
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
    # Optional sibling-param name holding per-slot MIDI note numbers
    # (or None per slot). When set, the StepEditor renders the note
    # name (e.g. C4) under each step — used by the Arpeggiator's
    # `programmed` pattern mode to show what's loaded into each slot.
    slot_notes_param: str | None = None

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"length_param": self.length_param, "default_length": self.default_length,
                  "default_on": self.default_on})
        if self.slot_notes_param:
            d["slot_notes_param"] = self.slot_notes_param
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
    """Wheel for MIDI channel 1-16. Set `allow_any=True` to add a
    leading "Any" tick at value 0 — used by channel filters where 0
    means "accept all channels". Plugins reading the value should
    treat 0 as "no filter" and otherwise subtract 1 for the ALSA
    0-based channel index."""
    default: int = 1
    allow_any: bool = False

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["default"] = self.default
        if self.allow_any:
            d["allow_any"] = True
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
    mini: bool = False  # half-height variant for dense edit panels

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({"default": self.default, "color": self.color,
                  "trigger": self.trigger})
        if self.mini:
            d["mini"] = True
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
    """Titled section grouping related params. `config_only=True`
    hides the entire group (title + children) from a play surface —
    use it when every child is config-only and you don't want an
    empty title leaking through to the play view."""
    title: str
    children: list = field(default_factory=list)
    cols: int | None = None  # override default 4-col grid for this group's inline row
    config_only: bool = False
    # Same shape as Param.visible_when — (param_name, value_or_list).
    # When set, the whole group (title + children) hides if the named
    # param's current value doesn't match.
    visible_when: tuple | None = None

    def to_dict(self) -> dict:
        d = {
            "type": "group",
            "title": self.title,
            "children": [c.to_dict() for c in self.children],
        }
        if self.cols is not None:
            d["cols"] = self.cols
        if self.config_only:
            d["config_only"] = True
        if self.visible_when:
            d["visible_when"] = {"param": self.visible_when[0], "value": self.visible_when[1]}
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
    # New per-button toggles + note-trigger (Phase 5 polish).
    sync_param: str | None = None         # dict[str(id) -> bool] — quantize to bar grid (default true)
    fade_param: str | None = None         # dict[str(id) -> bool] — interpolate cells press→fire instead of hard-snap
    notes_param: str | None = None        # dict[str(id) -> int|null] — incoming-note number that fires this button
    note_press_param: str | None = None   # dict[str(id) -> bool] — trigger-note currently held (drives press-fill animation)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["count"] = self.count
        for attr in ("states_param", "snapshots_param", "modes_param",
                     "labels_param", "schedule_param", "sync_param",
                     "fade_param", "notes_param", "note_press_param"):
            v = getattr(self, attr)
            if v:
                d[attr] = v
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
class TrackerGrid:
    """Tracker-style sequencer grid: 16 hex-numbered step rows × 1..8
    voice columns, paged up to 16 pages, with an always-visible
    data-entry keypad below.

    Used by the §6 Tracker plugin (and any future sequencer surface
    sharing the same UI). Like LayoutGrid, this is a structural element
    rather than a value-holding Param — actual sequencer state lives
    in sibling auxiliary params named here.

    `pages_param`: list of page dicts. Each page is
      `{"rows": [{"voices": [VoiceCell × N]}, ...]}`
      where VoiceCell is
      `{"note": str, "vel": int|str, "cc_num": int|str, "cc_val": int|str}`.
    `current_page_param`: int (0..MAX_PAGES-1) — visible page.
    `cursor_row_param`, `cursor_track_param`: ints — edit-cursor focus.
    `octave_param`: int (0..9) — sticky octave on the keypad.
    """
    name: str
    label: str
    track_count: int = 8
    max_pages: int = 16
    max_rows: int = 16
    pages_param: str | None = None
    current_page_param: str | None = None
    cursor_row_param: str | None = None
    cursor_track_param: str | None = None
    cursor_half_param: str | None = None
    octave_param: str | None = None
    rate_param: str | None = None
    playhead_param: str | None = None  # {page, row, playing} broadcast per step
    track_channels_param: str | None = None  # base name; per-track lookup as <name>_<idx>
    cmd_play_param: str | None = None  # bool, frontend → backend trigger
    cmd_stop_param: str | None = None  # bool, frontend → backend trigger
    send_clock_param: str | None = None  # bool, latching toggle
    note_preview_param: str | None = None  # int (MIDI note), frontend → backend trigger
    # Pattern bank -- 8 stored grids per Tracker instance, with one
    # currently selected + (optionally) one queued for the next
    # boundary. See TrackerBase / PatternRow for the full flow.
    patterns_param: str | None = None               # list[list[Page]]: stored grids
    selected_pattern_param: str | None = None       # int 0..N-1
    queued_pattern_param: str | None = None         # int 0..N-1 or -1 (none)
    pattern_status_param: str | None = None         # list[bool]: has-content per slot
    cmd_pattern_select_param: str | None = None     # dict {pattern, mode}, frontend → backend
    pattern_count: int = 8

    def to_dict(self) -> dict:
        d = {
            "type": "trackergrid",
            # `play_only` is a hint to the renderparam dispatcher: the
            # tracker grid + keypad only make sense on the play
            # surface (not the device-detail config card), so the
            # frontend skips it when displayCtx.playOnly is false.
            "play_only": True,
            "name": self.name,
            "label": self.label,
            "track_count": self.track_count,
            "max_pages": self.max_pages,
            "max_rows": self.max_rows,
            "pattern_count": self.pattern_count,
        }
        for attr in ("pages_param", "current_page_param", "cursor_row_param",
                     "cursor_track_param", "cursor_half_param",
                     "octave_param", "rate_param", "playhead_param",
                     "track_channels_param", "cmd_play_param",
                     "cmd_stop_param", "send_clock_param",
                     "note_preview_param", "patterns_param",
                     "selected_pattern_param", "queued_pattern_param",
                     "pattern_status_param", "cmd_pattern_select_param"):
            v = getattr(self, attr)
            if v:
                d[attr] = v
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

    XY-pad-only spring fields: `spring_force` (0..127, 0 = no spring,
    127 = very fast snap-back) and `spring_home` ("bottom_left" or
    "center") drive a client-side animation that returns the dot to
    home on touch release. Purely a UI behaviour — the value updates
    flow through the same onChange → PATCH path as a manual drag.
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
    spring_force: int = 0         # XY-pad-only: 0 = off, 1..127 = spring strength
    spring_home: str = "bottom_left"  # XY-pad-only: "bottom_left" or "center"


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
                    **({"spring_force": c.spring_force} if c.spring_force else {}),
                    **({"spring_home": c.spring_home} if c.spring_home != "bottom_left" else {}),
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
        elif isinstance(p, TrackerGrid):
            # No cells to flatten — TrackerGrid's data is in sibling
            # params declared elsewhere in the plugin's params list.
            continue
        elif isinstance(p, Param):
            result.append(p)
    return result


def schema_param_keys(params: list) -> set[str]:
    """Return every key the schema declares as a valid `_param_values`
    entry. Used by `PluginBase._tidy_param_values()` to drop strandeed
    keys carried over from older plugin versions.

    Collects:
      - Every `Param.name` (top-level + Group children + LayoutGrid cells)
      - Every auxiliary-pointer attribute (any string attr ending in
        `_param`, e.g. `labels_param`, `bindings_param`, `learn_param`,
        `states_param`, `snapshots_param`, `modes_param`,
        `schedule_param`, `length_param`, …) — these point at sibling
        param names like `cell_labels`, `drop_states`, etc.
      - Recursively into Group.children / LayoutGrid.cells.
    The generic `*_param` walk means new auxiliary patterns added on
    future Param subclasses are picked up automatically without needing
    to update this list."""
    keys: set[str] = set()

    def collect_aux(p: Param) -> None:
        for attr_name in dir(p):
            if not attr_name.endswith("_param") or attr_name.startswith("_"):
                continue
            try:
                val = getattr(p, attr_name)
            except AttributeError:
                continue
            if isinstance(val, str) and val:
                keys.add(val)

    def walk(items: list) -> None:
        for p in items:
            if isinstance(p, Group):
                walk(p.children)
                continue
            if isinstance(p, LayoutGrid):
                # The grid itself doesn't have a single name to track,
                # but its cells' params and its auxiliary pointers do.
                collect_aux(p)
                walk([cell.param for cell in p.cells])
                continue
            if isinstance(p, TrackerGrid):
                # Structural — its data lives in the sibling *_param
                # entries declared on the TrackerGrid itself.
                collect_aux(p)
                continue
            if isinstance(p, Param):
                if p.name:
                    keys.add(p.name)
                collect_aux(p)
    walk(params)
    return keys


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

    # --- Surface kind ---
    # Which top-level UI panel this plugin's instances appear in:
    #   None         — matrix-only plugin (default)
    #   "controller" — fullscreen play surface in /controller
    #   "play"       — fullscreen play surface in /play (sequencers)
    # The /plugins/instances API echoes this back to the frontend as
    # `kind`, replacing the old startswith("controller_") prefix filter.
    SURFACE_KIND: str | None = None

    # --- Display outputs (declared in subclass, framework renders read-only) ---
    # Each entry: {"name": str, "type": "meter"|"text", "label": str, "min": 0, "max": 127}
    display_outputs: list[dict] = []

    def __init__(self):
        self._param_values: dict[str, Any] = {}
        self._display_values: dict[str, Any] = {}
        # Param names whose changes should NOT mark the routing state
        # dirty. Used by Controller plugins so live-play motion (fader
        # / knob / XY positions, drop-button transient states like
        # fire / cancel signals) doesn't paint the bottom-nav Routing
        # asterisk red — only edits to cell bindings, labels, drop
        # button settings, theme, etc. are config and worth flagging.
        # Empty for ordinary plugins; ControllerBase populates it in
        # on_start from its own LayoutGrid + drop-state names.
        self.transient_params: set[str] = set()
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
        # Scheduled-event hooks. Set by the host alongside the immediate
        # send_* counterparts. Plugins use these to land MIDI at exact
        # future moments (drop snapshots ahead of the bar boundary,
        # arpeggiator notes pre-scheduled, MIDI Delay echoes, etc.) —
        # ALSA's queue dispatches at the right tick regardless of
        # Python latency. None means the host couldn't allocate a queue
        # for this instance; plugins should fall back to immediate sends.
        self._send_cc_at = None
        self._send_note_on_at = None
        self._send_note_off_at = None
        self._send_clock_at = None
        self._send_start_at = None
        self._send_stop_at = None
        self._send_continue_at = None
        self._cancel_scheduled = None
        # Bulk SysEx output. Set by the host; the SysEx Sender plugin
        # uses this to stream a user-uploaded .syx file out the OUT port.
        # Returns the byte count actually transmitted.
        self._send_sysex = None
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

    def tidy_param_values(self) -> list[str]:
        """Drop entries from self._param_values whose key isn't declared
        by the current schema. Removes stranded state from older plugin
        versions so the next config save doesn't carry it forward.

        Returns the list of keys removed (empty when nothing was
        stranded). Called by the plugin host after on_start, so
        subclasses' setdefault calls run BEFORE we strip — anything
        the schema doesn't declare is genuinely stranded.

        Subclasses normally don't override this; the helper is
        schema-driven (`schema_param_keys`) and so handles whatever
        param mix they declare automatically."""
        valid = schema_param_keys(type(self).params)
        dropped = [k for k in self._param_values if k not in valid]
        for k in dropped:
            del self._param_values[k]
        return dropped

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

    def send_sysex(self, payload: bytes) -> int:
        """Stream a complete SysEx message out the OUT port. Bytes
        are chunked + paced inside the host so old synths' input
        buffers don't overrun. Returns bytes transmitted (0 if no
        host hook is wired)."""
        if self._send_sysex:
            return self._send_sysex(payload)
        return 0

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

    # --- Scheduled-event API (ALSA queue) ---
    # Call these to land an event at an exact monotonic-time moment in
    # the future. `tag` is 1..255 (0 = no tag); pass the same tag value
    # to cancel_scheduled() to remove all pending events with that tag.
    # Falls back to immediate sends if the host couldn't allocate a queue.

    def send_cc_at(self, when_monotonic: float, channel: int, cc: int,
                   value: int, tag: int = 0) -> None:
        if self._send_cc_at:
            self._send_cc_at(when_monotonic, channel, cc, value, tag)
        elif self._send_cc:
            self._send_cc(channel, cc, value)

    def send_note_on_at(self, when_monotonic: float, channel: int, note: int,
                        velocity: int, tag: int = 0) -> None:
        if self._send_note_on_at:
            self._send_note_on_at(when_monotonic, channel, note, velocity, tag)
        elif self._send_note_on:
            self._send_note_on(channel, note, velocity)

    def send_note_off_at(self, when_monotonic: float, channel: int, note: int,
                         tag: int = 0) -> None:
        if self._send_note_off_at:
            self._send_note_off_at(when_monotonic, channel, note, tag)
        elif self._send_note_off:
            self._send_note_off(channel, note)

    def send_clock_at(self, when_monotonic: float, tag: int = 0) -> None:
        if self._send_clock_at:
            self._send_clock_at(when_monotonic, tag)
        elif self._send_clock:
            self._send_clock()

    def send_start_at(self, when_monotonic: float, tag: int = 0) -> None:
        if self._send_start_at:
            self._send_start_at(when_monotonic, tag)
        elif self._send_start:
            self._send_start()

    def send_stop_at(self, when_monotonic: float, tag: int = 0) -> None:
        if self._send_stop_at:
            self._send_stop_at(when_monotonic, tag)
        elif self._send_stop:
            self._send_stop()

    def send_continue_at(self, when_monotonic: float, tag: int = 0) -> None:
        if self._send_continue_at:
            self._send_continue_at(when_monotonic, tag)
        elif self._send_continue:
            self._send_continue()

    def cancel_scheduled(self, tag: int) -> None:
        """Remove all pending queued events tagged `tag` from this plugin's
        ALSA output queue."""
        if self._cancel_scheduled:
            self._cancel_scheduled(tag)
