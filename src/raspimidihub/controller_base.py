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
        # Derived from the schema once per instance.
        self._defaults: dict[str, tuple[int, int]] = {}
        self._cell_types: dict[str, str] = {}
        self._cell_default_values: dict[str, Any] = {}
        for p in self.__class__.params:
            if isinstance(p, LayoutGrid):
                for c in p.cells:
                    name = c.param.name
                    if c.channel is not None and c.cc is not None:
                        self._defaults[name] = (c.channel, c.cc)
                    self._cell_types[name] = type(c.param).__name__.lower()
                    if hasattr(c.param, "default"):
                        self._cell_default_values[name] = c.param.default

    # --- Helpers ---

    def _effective_binding(self, cell_name: str) -> tuple[int, int] | None:
        """User override (if set + complete) > schema default."""
        overrides = self._param_values.get("cell_bindings") or {}
        ov = overrides.get(cell_name)
        if isinstance(ov, dict):
            ch = ov.get("channel")
            cc = ov.get("cc")
            if isinstance(ch, int) and isinstance(cc, int):
                return (ch, cc)
        return self._defaults.get(cell_name)

    @staticmethod
    def _cell_value_to_cc(cell_type: str, value: Any) -> int | None:
        """Translate a cell's stored value to a 0..127 CC byte."""
        if cell_type == "button":
            return 127 if bool(value) else 0
        if isinstance(value, bool):
            return 127 if value else 0
        if isinstance(value, int):
            return max(0, min(127, value))
        return None

    def _store_cc_into_cell(self, cell_name: str, cc_value: int) -> Any:
        """Translate an incoming CC byte into the right Python type for
        a cell's stored value."""
        if self._cell_types.get(cell_name) == "button":
            return cc_value >= 64
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
        cc_val = self._cell_value_to_cc(self._cell_types.get(name, ""), value)
        if cc_val is None:
            return
        ch, cc = binding
        self.send_cc(ch, cc, cc_val)

    def on_cc(self, channel, cc, value):
        """MIDI Learn capture (if armed for a cell), else bidirectional
        sync — silently update the matching cell, no OUT re-emit."""
        learn_target = self._param_values.get("cell_learn") or ""
        if learn_target and learn_target in self._defaults:
            bindings = dict(self._param_values.get("cell_bindings") or {})
            bindings[learn_target] = {"channel": channel, "cc": cc}
            self.set_param("cell_bindings", bindings)
            self.set_param("cell_learn", "")
            return
        for name in self._defaults:
            binding = self._effective_binding(name)
            if binding is None:
                continue
            ch, cn = binding
            if ch != channel or cn != cc:
                continue
            new_val = self._store_cc_into_cell(name, value)
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
            ch, cc = binding
            cc_val = self._cell_value_to_cc(self._cell_types.get(cell_name, ""), v)
            if cc_val is None:
                continue
            self.send_cc(ch, cc, cc_val)
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
            ch, cc = binding
            default = self._cell_default_values.get(name, 0)
            if self._param_values.get(name) == default:
                continue
            self._param_values[name] = default
            cc_val = self._cell_value_to_cc(self._cell_types.get(name, ""), default)
            if cc_val is not None:
                self.send_cc(ch, cc, cc_val)
            if self._notify_param_change:
                try:
                    self._notify_param_change(name, default)
                except Exception:
                    pass
