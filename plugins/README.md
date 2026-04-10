# RaspiMIDIHub Plugin Developer Guide

This guide covers everything you need to create plugins for RaspiMIDIHub.

## Quick Start

1. Create a directory under `plugins/` with your plugin name (e.g. `plugins/my_plugin/`).
2. Add an `__init__.py` that inherits from `PluginBase`.
3. Set the required metadata, declare parameters, and implement callbacks.

Here is the minimal plugin -- a pass-through that forwards all MIDI unchanged:

```python
from raspimidihub.plugin_api import PluginBase


class PassThrough(PluginBase):
    NAME = "Pass-Through"
    DESCRIPTION = "Forwards all MIDI from IN to OUT unchanged"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"

    params = []

    inputs = ["All MIDI events"]
    outputs = ["All MIDI events (unchanged)"]

    def on_note_on(self, channel, note, velocity):
        self.send_note_on(channel, note, velocity)

    def on_note_off(self, channel, note):
        self.send_note_off(channel, note)

    def on_cc(self, channel, cc, value):
        self.send_cc(channel, cc, value)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(channel, value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(channel, value)

    def on_program_change(self, channel, program):
        self.send_program_change(channel, program)
```

The framework auto-discovers your plugin at startup. No registration step is needed.


## Plugin API Reference

### Metadata (required)

Every plugin must set these class attributes:

| Attribute     | Type   | Description                        |
|---------------|--------|------------------------------------|
| `NAME`        | `str`  | Display name shown in the UI       |
| `DESCRIPTION` | `str`  | One-line summary                   |
| `AUTHOR`      | `str`  | Author name                        |
| `VERSION`     | `str`  | Version string (e.g. `"1.0"`)     |

### Event Callbacks

Override any of these to handle incoming MIDI. Unimplemented callbacks silently
discard the event (no pass-through by default).

| Callback | Arguments | Description |
|----------|-----------|-------------|
| `on_note_on(channel, note, velocity)` | `int, int, int` | Note pressed. Velocity 1-127. |
| `on_note_off(channel, note)` | `int, int` | Note released. |
| `on_cc(channel, cc, value)` | `int, int, int` | Control Change message. |
| `on_aftertouch(channel, value)` | `int, int` | Channel pressure (aftertouch). |
| `on_pitchbend(channel, value)` | `int, int` | Pitch bend wheel. |
| `on_program_change(channel, program)` | `int, int` | Program change. |
| `on_tick(division)` | `str` | Clock tick at a given division (e.g. `"1/8"`). |
| `on_param_change(name, value)` | `str, Any` | A parameter was changed by the user or CC automation. |
| `on_start()` | -- | Plugin activated. Initialize state here. |
| `on_stop()` | -- | Plugin deactivated. Clean up here. |

### Output Methods

Call these from your callbacks to send MIDI to the plugin's output port:

- `self.send_note_on(channel, note, velocity)`
- `self.send_note_off(channel, note)`
- `self.send_cc(channel, cc, value)`
- `self.send_pitchbend(channel, value)`
- `self.send_aftertouch(channel, value)`
- `self.send_program_change(channel, program)`

### Reading Parameters

Call `self.get_param(name)` to read the current value of any declared parameter.
Returns the type appropriate to the parameter (int, str, bool, list, etc.).


## Parameter Types

Import parameter types from the plugin API:

```python
from raspimidihub.plugin_api import (
    PluginBase, Group, Radio, Wheel, Fader, Toggle,
    StepEditor, CurveEditor, NoteSelect, ChannelSelect,
)
```

Declare parameters as a `params` class attribute (a list).

### Wheel

Numeric scroll wheel with momentum.

```python
Wheel("gate", "Gate %", min=10, max=100, default=80)
```

### Fader

Mixer-style fader, horizontal by default.

```python
Fader("depth", "Depth", min=0, max=127, default=127)
Fader("volume", "Volume", min=0, max=127, default=100, vertical=True)
```

### Radio

Pill-style tap-to-select buttons.

```python
Radio("pattern", "Pattern", ["up", "down", "up-down", "random"], default="up")
```

### Toggle

Metal switch with LED indicator. Boolean value.

```python
Toggle("sync", "Sync to Clock", default=True)
```

### StepEditor

Step sequencer grid with on/off dots and per-step note offsets.

```python
StepEditor("steps", "Steps", length_param="length", default_length=16)
```

The `length_param` references a Radio or Wheel parameter name that controls how
many steps are active.

### CurveEditor

Drawable 128-point curve (one value per MIDI value 0-127). Returns a list of
128 ints. Linear by default.

```python
CurveEditor("curve", "Velocity Curve")
```

Usage in a callback:

```python
def on_note_on(self, channel, note, velocity):
    curve = self.get_param("curve")
    if curve and 0 <= velocity <= 127:
        velocity = max(1, min(127, curve[velocity]))
    self.send_note_on(channel, note, velocity)
```

### NoteSelect

MIDI note wheel displaying note names (C-2 to G8). Returns a MIDI note number
(0-127).

```python
NoteSelect("root", "Root Note", default=60)  # Middle C
```

### ChannelSelect

MIDI channel wheel (1-16). Note: the displayed value is 1-based, so subtract 1
when passing to send methods which use 0-based channels.

```python
ChannelSelect("out_ch", "Output Channel", default=1)
```

Usage:

```python
out_ch = (self.get_param("out_ch") or 1) - 1
self.send_note_on(out_ch, note, velocity)
```

### Group

Titled section that visually groups related parameters.

```python
Group("Timing", [
    Toggle("sync", "Sync to Clock", default=False),
    Wheel("bpm", "BPM", min=40, max=300, default=120),
])
```

Groups can contain any parameter types. They affect layout only -- they do not
create a namespace.

### Conditional Visibility: visible_when

Any parameter accepts `visible_when=(param_name, value)` to show/hide it based
on another parameter's current value.

```python
params = [
    Toggle("sync", "Sync to Clock", default=False),
    Wheel("bpm", "BPM", min=40, max=300, default=120, visible_when=("sync", False)),
    Radio("rate", "Rate", ["1/4", "1/8", "1/16"], default="1/4",
          visible_when=("sync", True)),
]
```

In this example, "BPM" only appears when sync is off, and "Rate" only appears
when sync is on.


## CC Automation

Map incoming CC messages to parameters with the `cc_inputs` dict. The framework
automatically updates the parameter and calls `on_param_change`.

```python
cc_inputs = {74: "rate", 75: "gate"}
```

Key is the CC number (0-127), value is the parameter name.

Declare `cc_outputs` as a list of CC numbers your plugin may send, for
documentation and routing purposes:

```python
cc_outputs = [1]
```


## Clock

To receive clock ticks, declare which divisions your plugin cares about:

```python
clock_divisions = ["1/4", "1/8", "1/16", "1/32", "1/4T", "1/8T", "1/16T"]
```

Then implement `on_tick`:

```python
def on_tick(self, division):
    rate = self.get_param("rate") or "1/8"
    if division != rate:
        return
    # Do something on this beat subdivision
```

The framework distributes clock from an external MIDI source or internal
transport. Your plugin receives only the divisions declared in
`clock_divisions`.


## I/O Metadata

Declare `inputs` and `outputs` as lists of human-readable strings describing
what your plugin accepts and produces. These are shown in the UI for
documentation.

```python
inputs = ["Notes", "CC#74 (rate)", "CC#75 (gate)", "Clock"]
outputs = ["Notes (arpeggiated)", "Aftertouch (pass-through)"]
```


## Threading

- Each plugin runs in its own thread. All callbacks (`on_note_on`, `on_cc`,
  etc.) are called on that thread.
- Callbacks are synchronous -- process the event and return promptly.
- Output methods (`send_note_on`, etc.) are thread-safe and can be called from
  any thread.
- You do not need any ALSA knowledge. The framework handles all MIDI port
  management.
- If you spawn your own threads (e.g. a free-running LFO or arpeggiator timer),
  use `threading.Lock` to protect shared state and set threads as daemon
  (`daemon=True`).


## Sandbox Restrictions

Plugins run in a restricted environment. The following are **not permitted**:

- Filesystem access (no reading or writing files)
- Network access (no sockets, HTTP, etc.)
- Subprocess creation (no `os.system`, `subprocess`, etc.)
- Arbitrary imports

**Allowed imports:** `math`, `random`, `collections`, `dataclasses`, `enum`,
`threading`, `time`.

Keep plugins focused on MIDI processing. All persistence (parameter values,
presets) is handled by the framework.


## Full Example: Arpeggiator

For a comprehensive example showing Groups, Radio, Wheel, Toggle, cc_inputs,
clock_divisions, on_start/on_stop lifecycle, on_tick, on_param_change,
threading, and conditional visibility, see `plugins/arpeggiator/__init__.py`.

For a simpler example using CurveEditor, see `plugins/velocity_curve/__init__.py`.
