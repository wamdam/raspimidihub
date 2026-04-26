"""Shared base class for §5 Controller plugins.

Each Controller template (Mixer 8, Performance 16, FX 6, …) is a thin
subclass that just declares NAME / DESCRIPTION / HELP and a `params`
list containing one LayoutGrid + the standard DropPad + edit Button
siblings. All the cell ↔ CC plumbing lives here:

  - on_param_change → emit CC for the cell's effective binding
  - on_cc → MIDI Learn capture (if armed) or bidirectional sync
  - drop pad capture / fire across every bound cell
  - panic resets every cell to its declared default + emits the CC

The plugin loader filters discovered classes by `__module__` so this
base — even though it's a `PluginBase` subclass — is *not* picked up
as a plugin in its own right.
"""

from typing import Any

from raspimidihub.plugin_api import LayoutGrid, PluginBase


class ControllerBase(PluginBase):
    """Common cell/binding/drop-pad logic for §5 Controller templates.

    Subclasses override metadata (NAME / DESCRIPTION / HELP / VERSION /
    AUTHOR) and `params`. `params` MUST contain exactly one LayoutGrid
    whose cells declare `channel` and `cc` defaults; the LayoutGrid
    SHOULD point at sibling params named `cell_labels`, `cell_bindings`,
    `cell_learn` and `pad` (a DropPad) for full functionality."""

    inputs = ["CC (bidirectional sync — silent UI updates, no re-emit)"]
    outputs = ["CC per cell — see HELP for default channel/cc bindings"]

    # Eight predefined dark backgrounds the user can pick per instance.
    # Strings are user-facing; the JS lower-cases them to derive a
    # `.bg-<name>` class on the Controller page surface.
    BG_OPTIONS = ["Default", "Navy", "Forest", "Wine", "Plum", "Teal", "Sienna", "Slate"]

    def on_start(self):
        """Initialise non-schema state on first start (and after restore).

        Subclasses can override; if they do, they should call
        `super().on_start()` so the cached lookups stay populated."""
        self._param_values.setdefault("cell_labels", {})
        self._param_values.setdefault("cell_bindings", {})
        self._param_values.setdefault("cell_learn", "")
        self._param_values.setdefault("bg", "Default")
        self._param_values.setdefault("pad_snapshot", {})
        # The pad value reflects whether a snapshot is currently loaded.
        # Derive it from pad_snapshot on every start so the armed-glow on
        # the UI matches reality from the moment the plugin instance comes
        # back up — no surprising "tap reveals a stale snapshot" jump.
        # Snapshots themselves persist across Save Config / restart, which
        # is what the user wants ("I'd not like to always have to rebuild
        # these").
        self._param_values["pad"] = "captured" if self._param_values["pad_snapshot"] else "idle"
        # Derived from the schema once per instance.
        self._defaults: dict[str, tuple[int, int]] = {}
        self._defaults_y: dict[str, int] = {}  # XY-pad Y-axis CC
        self._defaults_y_channel: dict[str, int] = {}  # XY-pad Y-axis channel (if separate)
        self._cell_types: dict[str, str] = {}
        self._cell_default_values: dict[str, Any] = {}
        for p in self.__class__.params:
            if isinstance(p, LayoutGrid):
                for c in p.cells:
                    name = c.param.name
                    if c.channel is not None and c.cc is not None:
                        self._defaults[name] = (c.channel, c.cc)
                    if c.cc_y is not None:
                        self._defaults_y[name] = c.cc_y
                    if c.channel_y is not None:
                        self._defaults_y_channel[name] = c.channel_y
                    self._cell_types[name] = type(c.param).__name__.lower()
                    if hasattr(c.param, "default"):
                        self._cell_default_values[name] = c.param.default
                    elif type(c.param).__name__.lower() == "xypad":
                        self._cell_default_values[name] = {
                            "x": getattr(c.param, "default_x", 0),
                            "y": getattr(c.param, "default_y", 0),
                        }

    # --- Helpers ---

    # Default on / off CC values for button cells. The user can override
    # both per cell via the edit-mode UI (e.g. on=64, off=0 for a partial
    # toggle, or 0/127 to invert the polarity).
    _BUTTON_DEFAULT_ON = 127
    _BUTTON_DEFAULT_OFF = 0

    def _effective_binding(self, cell_name: str) -> dict | None:
        """Return a dict `{channel, cc, [on, off for buttons], [cc_y for
        xypads]}` with the user's per-cell override layered over the
        schema's default. Only complete overrides take effect — partial
        dicts fall back to the schema."""
        default = self._defaults.get(cell_name)
        if default is None:
            return None
        ch, cc = default
        cell_type = self._cell_types.get(cell_name, "")
        is_button = cell_type == "button"
        is_xypad = cell_type == "xypad"
        binding: dict = {"channel": ch, "cc": cc}
        if is_button:
            binding["on"] = self._BUTTON_DEFAULT_ON
            binding["off"] = self._BUTTON_DEFAULT_OFF
        if is_xypad:
            if cell_name in self._defaults_y:
                binding["cc_y"] = self._defaults_y[cell_name]
            # Y channel defaults to X channel unless the schema or
            # an override sets it otherwise.
            binding["channel_y"] = self._defaults_y_channel.get(cell_name, ch)
        ov = (self._param_values.get("cell_bindings") or {}).get(cell_name)
        if isinstance(ov, dict):
            if isinstance(ov.get("channel"), int):
                binding["channel"] = ov["channel"]
            if isinstance(ov.get("cc"), int):
                binding["cc"] = ov["cc"]
            if is_button:
                if isinstance(ov.get("on"), int):
                    binding["on"] = max(0, min(127, ov["on"]))
                if isinstance(ov.get("off"), int):
                    binding["off"] = max(0, min(127, ov["off"]))
            if is_xypad:
                if isinstance(ov.get("cc_y"), int):
                    binding["cc_y"] = max(0, min(127, ov["cc_y"]))
                if isinstance(ov.get("channel_y"), int):
                    binding["channel_y"] = max(0, min(15, ov["channel_y"]))
        return binding

    def _cell_value_to_cc(self, cell_name: str, value: Any, binding: dict) -> int | None:
        """Translate a cell's stored value to a 0..127 CC byte."""
        if self._cell_types.get(cell_name) == "button":
            return binding["on"] if bool(value) else binding["off"]
        if isinstance(value, bool):
            return 127 if value else 0
        if isinstance(value, int):
            return max(0, min(127, value))
        return None

    def _store_cc_into_cell(self, cell_name: str, cc_value: int, binding: dict) -> Any:
        """Translate an incoming CC byte into the right Python type for
        a cell's stored value. For buttons, "closer to on or off?" wins —
        so it works whether the user picks 0/127 or e.g. 0/64."""
        if self._cell_types.get(cell_name) == "button":
            on = binding.get("on", self._BUTTON_DEFAULT_ON)
            off = binding.get("off", self._BUTTON_DEFAULT_OFF)
            return abs(cc_value - on) < abs(cc_value - off)
        return cc_value

    # --- Event handlers ---

    def on_param_change(self, name, value):
        """User moved a cell -> emit its CC, OR drop pad fired -> dispatch."""
        if name == "pad":
            self._handle_pad_action(value)
            return
        binding = self._effective_binding(name)
        if binding is None:
            return
        if self._cell_types.get(name) == "xypad":
            self._emit_xypad(value, binding)
            return
        cc_val = self._cell_value_to_cc(name, value, binding)
        if cc_val is None:
            return
        self.send_cc(binding["channel"], binding["cc"], cc_val)

    def _emit_xypad(self, value: Any, binding: dict) -> None:
        """Emit X (channel, cc) and Y (channel_y, cc_y) CCs for an xypad
        cell whose stored value is a `{"x": int, "y": int}` dict."""
        if not isinstance(value, dict):
            return
        ch = binding["channel"]
        x = value.get("x")
        if isinstance(x, int):
            self.send_cc(ch, binding["cc"], max(0, min(127, x)))
        cc_y = binding.get("cc_y")
        y = value.get("y")
        if cc_y is not None and isinstance(y, int):
            ch_y = binding.get("channel_y", ch)
            self.send_cc(ch_y, cc_y, max(0, min(127, y)))

    def on_cc(self, channel, cc, value):
        """MIDI Learn capture (if armed for a cell), else bidirectional
        sync — silently update the matching cell, no OUT re-emit."""
        learn_target = self._param_values.get("cell_learn") or ""
        if learn_target and learn_target in self._defaults:
            bindings = dict(self._param_values.get("cell_bindings") or {})
            # Learn captures the X axis (channel, cc); preserve any
            # existing Y-axis fields so toggling Learn on an XY pad
            # doesn't blow away the user's Y configuration.
            prev = bindings.get(learn_target) or {}
            new = {"channel": channel, "cc": cc}
            for k in ("cc_y", "channel_y", "on", "off"):
                if k in prev:
                    new[k] = prev[k]
            bindings[learn_target] = new
            self.set_param("cell_bindings", bindings)
            self.set_param("cell_learn", "")
            return
        for name in self._defaults:
            binding = self._effective_binding(name)
            if binding is None:
                continue
            cell_type = self._cell_types.get(name, "")
            if cell_type == "xypad":
                # Match either axis on its own (channel, cc); update only
                # that axis in the cell's {x, y} dict. Other axis stays
                # where it was. X uses (channel, cc); Y uses
                # (channel_y, cc_y), where channel_y falls back to
                # channel when not set explicitly.
                axis = None
                if binding["channel"] == channel and binding["cc"] == cc:
                    axis = "x"
                elif (binding.get("channel_y", binding["channel"]) == channel
                      and binding.get("cc_y") == cc):
                    axis = "y"
                if axis is None:
                    continue
                cur = self._param_values.get(name)
                if not isinstance(cur, dict):
                    cur = {"x": 0, "y": 0}
                if cur.get(axis) == value:
                    return
                new_val = {**cur, axis: value}
                self._param_values[name] = new_val
                if self._notify_param_change:
                    try: self._notify_param_change(name, new_val)
                    except Exception: pass
                return
            if binding["channel"] != channel or binding["cc"] != cc:
                continue
            new_val = self._store_cc_into_cell(name, value, binding)
            if self._param_values.get(name) == new_val:
                return
            self._param_values[name] = new_val
            if self._notify_param_change:
                try:
                    self._notify_param_change(name, new_val)
                except Exception:
                    pass
            return

    # Pass-through silence for the other event types — the matrix routes
    # them however the user's wired the plugin's IN port.
    def on_note_on(self, channel, note, velocity): pass
    def on_note_off(self, channel, note): pass
    def on_pitchbend(self, channel, value): pass
    def on_aftertouch(self, channel, value): pass
    def on_program_change(self, channel, program): pass

    # --- Drop pad ---

    def _handle_pad_action(self, action):
        """Dispatch on the DropPad action value sent by the UI. After
        processing, reset `pad` to 'captured' (snapshot exists) or 'idle'."""
        if action == "fire":
            self._fire_snapshot()
        elif action == "capture":
            self._capture_snapshot()
        else:
            return  # 'idle' / 'captured' echoed back from server, no-op
        new_state = "captured" if self._param_values.get("pad_snapshot") else "idle"
        self.set_param("pad", new_state)

    def _capture_snapshot(self):
        """Read every bound cell's current value into pad_snapshot."""
        snap = {}
        for cell_name in self._defaults:
            v = self._param_values.get(cell_name)
            if v is not None:
                snap[cell_name] = v
        self._param_values["pad_snapshot"] = snap

    def _fire_snapshot(self):
        """Re-emit each captured CC + snap on-screen cells to the
        captured value. No-op if no snapshot has been taken yet."""
        snap = self._param_values.get("pad_snapshot") or {}
        if not snap:
            return
        for cell_name, v in snap.items():
            binding = self._effective_binding(cell_name)
            if binding is None:
                continue
            if self._cell_types.get(cell_name) == "xypad":
                self._emit_xypad(v, binding)
            else:
                cc_val = self._cell_value_to_cc(cell_name, v, binding)
                if cc_val is None:
                    continue
                self.send_cc(binding["channel"], binding["cc"], cc_val)
            if self._param_values.get(cell_name) != v:
                self._param_values[cell_name] = v
                if self._notify_param_change:
                    try:
                        self._notify_param_change(cell_name, v)
                    except Exception:
                        pass

    # --- Panic ---

    def panic(self):
        """Reset every cell to its declared default + emit the CC."""
        for name in self._defaults:
            binding = self._effective_binding(name)
            if binding is None:
                continue
            default = self._cell_default_values.get(name, 0)
            if self._param_values.get(name) == default:
                continue
            self._param_values[name] = default
            if self._cell_types.get(name) == "xypad":
                self._emit_xypad(default, binding)
            else:
                cc_val = self._cell_value_to_cc(name, default, binding)
                if cc_val is not None:
                    self.send_cc(binding["channel"], binding["cc"], cc_val)
            if self._notify_param_change:
                try:
                    self._notify_param_change(name, default)
                except Exception:
                    pass
