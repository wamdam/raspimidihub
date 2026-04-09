# RaspiMIDIHub — Virtual Instruments / Plugin System

**Branch:** `feature/virtual-instruments`
**Target:** v2.0.0
**Date:** 2026-04-09

---

## Vision

Plugins are **virtual MIDI devices** that live inside RaspiMIDIHub. They appear in the connection matrix exactly like USB devices — you wire them with the same tap/long-press interface, apply filters, mappings, and chain them together.

A keyboard player on stage can:
1. Create an **Arpeggiator** plugin
2. Wire: `Keyboard → Arp IN` and `Arp OUT → Synth`
3. Configure the arp pattern, rate, octave range on their phone
4. Incoming notes get arpeggiated, output goes to the synth
5. All existing matrix features work on both connections (channel filter, CC mapping, etc.)

Plugins are written as simple Python classes by 3rd-party developers. Each plugin lives in its own directory with a single Python file. The framework handles threading, ALSA ports, UI rendering, clock distribution, and persistence. Plugin code should be ~50-200 lines for typical instruments.

---

## User Stories

### Arpeggiator
> "I hold a chord on my keyboard. The arp plugin plays the notes back as a pattern (up, down, up-down, random) at 1/8th note speed, synced to my drum machine's MIDI clock. The arp output goes to my synth through the matrix, where I also remap it to channel 3."

### Note Splitter
> "I want my 61-key keyboard split at C4. Notes below go to my bass synth on channel 1, notes above go to my lead synth on channel 2. I set this up by creating a Splitter plugin and wiring: `Keyboard → Splitter IN`, `Splitter OUT → Bass` (with channel filter: ch1 only), `Splitter OUT → Lead` (ch2 only)."

### CC LFO
> "I want a slow triangle wave on CC#1 (mod wheel) going to my synth pad for a wobble effect. I create an LFO plugin, set it to triangle, 0.5 Hz, CC#1, channel 1. I wire `LFO OUT → Synth`. I can even control the LFO speed via a CC from my controller by wiring `Controller → LFO IN` and setting CC#74 as the frequency input."

### Chaining
> "I split my keyboard at C4, send the upper half to the arp, and the arp output to the synth. Lower half goes direct to bass. All through the matrix."
```
Keyboard → Splitter IN
Splitter OUT (ch2, upper) → Arp IN
Arp OUT → Synth
Splitter OUT (ch1, lower) → Bass
```

### Multiple Instances
> "I have two arp plugins — one for 1/8th notes going to pad synth, one for 1/16th notes going to lead. Both receive from the same keyboard."

---

## Architecture

### Plugin = Virtual ALSA Device

Each plugin instance creates its own **ALSA sequencer client** with an IN port and an OUT port. The main engine discovers these like any USB device via hotplug events.

```
┌─────────────────────────────────────────────────────────────┐
│ RaspiMIDIHub Process                                        │
│                                                             │
│  Main Thread (asyncio)          Plugin Threads              │
│  ┌───────────────────┐         ┌──────────────────┐        │
│  │ MIDI Engine        │         │ Arp Instance 1   │        │
│  │ - ALSA event loop  │  ALSA   │ - own seq client │        │
│  │ - routing matrix   │◄───────►│ - IN port        │        │
│  │ - filter engine    │  ports   │ - OUT port       │        │
│  │ - hotplug detect   │         │ - own thread     │        │
│  └───────────────────┘         └──────────────────┘        │
│                                 ┌──────────────────┐        │
│  ┌───────────────────┐         │ LFO Instance 1   │        │
│  │ Web Server         │         │ - own seq client │        │
│  │ - Plugin API       │         │ - own thread     │        │
│  │ - Plugin UI        │         └──────────────────┘        │
│  └───────────────────┘                                      │
└─────────────────────────────────────────────────────────────┘
```

**Isolation:** Each plugin runs in its own thread with its own ALSA client. If a plugin is slow or crashes, only its virtual device stops working. The main engine continues routing all other devices normally.

**Discovery:** When a plugin instance starts, the engine detects the new ALSA client via hotplug and adds it to the matrix. When stopped, it disappears.

### Clock Distribution

The framework provides a **clock bus** that plugins subscribe to. The bus receives MIDI clock from whichever device sends it (detected by the main engine's clock monitoring) and translates it into musical divisions:

```python
class Plugin:
    def on_tick(self, division):
        """Called on musical divisions. division is one of:
        '1/1', '1/2', '1/4', '1/8', '1/16', '1/32', '1/4T', '1/8T', '1/16T'
        """
        pass
```

The clock bus runs on a dedicated thread, counts incoming MIDI clock ticks (24 PPQ), and calls `on_tick()` at the subscribed divisions. For free-running mode, an internal clock generates ticks from a BPM value.

### Plugin File Structure

```
plugins/
├── arpeggiator/
│   ├── __init__.py          # Plugin class
│   └── README.md            # Plugin documentation
├── note_splitter/
│   ├── __init__.py
│   └── README.md
├── cc_lfo/
│   ├── __init__.py
│   └── README.md
└── _example/
    ├── __init__.py          # Minimal example for developers
    └── README.md
```

Each `__init__.py` exports a single class that inherits from `PluginBase`.

---

## Plugin API

### Base Class

```python
from raspimidihub.plugin_api import PluginBase, Param, StepEditor, Select, Knob, Toggle

class MyPlugin(PluginBase):
    """One-line description shown in the plugin browser."""

    NAME = "My Plugin"
    DESCRIPTION = "What this plugin does"
    AUTHOR = "Developer Name"
    VERSION = "1.0"

    # --- Declare parameters (rendered as UI automatically) ---
    params = [
        Select("pattern", "Pattern", ["up", "down", "up-down", "random"], default="up"),
        Select("rate", "Rate", ["1/4", "1/8", "1/16", "1/32", "1/8T"], default="1/8"),
        Knob("gate", "Gate %", min=10, max=100, default=80),
        Knob("octaves", "Octaves", min=1, max=4, default=1),
        Toggle("sync", "Sync to Clock", default=True),
        Knob("bpm", "BPM (free)", min=40, max=300, default=120, visible_when=("sync", False)),
        StepEditor("steps", "Step Pattern", length=16, params=["on", "velocity", "octave"]),
    ]

    # --- Declare MIDI I/O ---
    cc_inputs = {
        74: "rate",       # CC#74 controls the rate parameter
        75: "gate",       # CC#75 controls the gate parameter
    }
    cc_outputs = [1]      # List of CC numbers this plugin may send
    outputs = ["Notes (arpeggiated)", "Aftertouch", "Pitch Bend"]  # Human-readable output description

    # --- Clock subscription ---
    clock_divisions = ["1/8", "1/16"]  # Which divisions to receive

    # --- Event handlers (called on plugin thread) ---

    def on_note_on(self, channel, note, velocity):
        """Incoming note on."""
        pass

    def on_note_off(self, channel, note):
        """Incoming note off."""
        pass

    def on_cc(self, channel, cc, value):
        """Incoming CC (not mapped to a param)."""
        pass

    def on_tick(self, division):
        """Clock tick at subscribed division."""
        pass

    def on_aftertouch(self, channel, value):
        """Channel aftertouch."""
        pass

    def on_pitchbend(self, channel, value):
        """Pitch bend."""
        pass

    def on_param_change(self, name, value):
        """UI parameter changed by the user."""
        pass

    def on_start(self):
        """Plugin instance started."""
        pass

    def on_stop(self):
        """Plugin instance stopping."""
        pass

    # --- Output methods (provided by framework) ---
    # self.send_note_on(channel, note, velocity)
    # self.send_note_off(channel, note)
    # self.send_cc(channel, cc, value)
    # self.send_pitchbend(channel, value)
    # self.send_aftertouch(channel, value)
```

### UI Parameter Types

The framework renders the UI automatically from the `params` list. Plugin authors never write HTML/JS.

| Type | Renders as | Example |
|------|-----------|---------|
| `Select(name, label, options, default)` | Dropdown | Pattern: up/down/up-down |
| `Knob(name, label, min, max, default)` | Slider + number | Gate: 10-100% |
| `Toggle(name, label, default)` | Switch | Sync to Clock: on/off |
| `StepEditor(name, label, length, params)` | Grid of steps | 16-step pattern editor |
| `NoteSelect(name, label, default)` | Note picker (C0-G10) | Split point: C4 |
| `ChannelSelect(name, label, default)` | Channel picker (1-16) | Output channel: 3 |

`visible_when=(param_name, value)` conditionally shows/hides a parameter based on another parameter's value. Example: BPM knob only shows when sync is off.

### StepEditor Detail

The step editor is the most complex UI element. It renders as a touch-friendly grid:

```
Step:  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16
On:    ●  ●  ○  ●  ●  ○  ●  ○  ●  ●  ○  ●  ●  ○  ●  ○
Vel:   █  █     █  ▄     █     █  █     █  ▄     █
Oct:   0  0     +1 0     0     -1 0     +1 0     0
```

- Tap a step to toggle on/off
- Drag up/down on velocity to set level
- Tap octave to cycle through -2..+2
- Swipe left/right to scroll if >8 steps visible
- Step count configurable: 8, 16, or 32
- Optional: per-step note offset from root (for chord arps)

### CC Input Mapping

Plugins declare which CCs control which parameters via `cc_inputs`. The framework:
1. Listens for incoming CC events on the plugin's IN port
2. Maps the CC value (0-127) to the parameter's range
3. Calls `on_param_change()` with the new value
4. Updates the UI in real-time via SSE

This allows hardware knobs to control plugin parameters without any extra wiring — just connect a controller to the plugin's IN port in the matrix.

---

## UI Design

### Navigation Change

The bottom nav changes from 4 to 4 tabs — **Status is replaced by Devices**:

```
Before:  Routing | Presets | Status   | Settings
After:   Routing | Presets | Devices  | Settings
```

System info (hostname, version, CPU, RAM, uptime, IPs) moves to the top of Settings.

### Devices Page (replaces Status)

A unified screen for **all** devices — USB, Bluetooth, and virtual. They are equals.

```
DEVICES (7)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ● Elektron Digitone II       1 port ›
  ● Impact GX49                2 ports ›
  ● KeyStep mk2                1 port ›
  ● LCXL3 1                    4 ports ›
  ● S-1                        1 port ›
  ● Ṿ Arp 1                   Arpeggiator ›
  ● Ṿ Soft Touch              Velocity Curve ›

[+ Add Virtual Device]
```

- All devices sorted alphabetically, virtual mixed in with Ṿ prefix
- USB/BT show port count, virtual show plugin type name
- Green dot = online/running, gray = offline/stopped/crashed
- Tap any device → device panel slides up
- **[+ Add Virtual Device]** at bottom opens plugin type browser

### Add Virtual Device Sheet

```
ADD VIRTUAL DEVICE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Arpeggiator
  Plays held notes as a pattern             [Add]

  Velocity Curve
  Remap velocity response                   [Add]

  Note Splitter
  Split keyboard at a note                  [Add]

  CC LFO
  Generate CC waveforms                     [Add]
  ...
```

Tapping [Add] creates an instance with a default name, starts it (ALSA port appears, matrix updates via SSE), and opens its device panel.

### Device Panel — USB/Bluetooth (unchanged)

Tapping a USB or Bluetooth device opens the same panel as today:

```
LCXL3 1                                       ✕
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Device
  Client: 20    USB: 1235:0148    Ports: 4

  Name: [LCXL3 1                ]

Ports
  IN/OUT  [LCXL3 1 MIDI In          ]
  IN/OUT  [LCXL3 1 DAW In           ]
  OUT     [LCXL3 Octa               ]
  OUT     [LCXL3 1 To DIN Out 2     ]

MIDI Monitor
  Waiting for MIDI...

MIDI Test Sender
  Channel [1 ▾]    Port [MIDI In ▾]
  [piano keyboard]    [CC slider]
```

No changes — rename device, rename ports, MIDI monitor, test sender.

### Device Panel — Virtual Device (extended)

Tapping a virtual device opens the same panel but with a **plugin config section** between the name and the MIDI monitor:

```
Ṿ ARPEGGIATOR — "Arp 1"                      ✕
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Name: [Arp 1                   ]

━━ Plugin Config ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Pattern:  [Up          ▾]
Rate:     [1/8         ▾]
Gate:     [====●=====] 80%
Octaves:  [==●=======] 1
Sync:     [●] On

Step Pattern:
┌─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┐
│●│●│○│●│●│○│●│○│●│●│○│●│●│○│●│○│
└─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┘

━━ CC Inputs ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CC#74 → Rate
  CC#75 → Gate %

━━ Outputs ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Notes (arpeggiated), Aftertouch, Pitch Bend

━━ MIDI Monitor ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Note On ch1 C3 vel=100
  Note On ch1 E3 vel=95

MIDI Test Sender
  Channel [1 ▾]
  [piano keyboard]    [CC slider]

                                [Delete Plugin]
```

The panel has everything a USB device has (rename, MIDI monitor, test sender) PLUS the plugin config section. The test sender is useful for debugging — play notes into the plugin to see what it outputs in the monitor.

### Settings Page (updated)

System info moves here from the old Status page:

```
Settings:
  [System: hostname, version, CPU, RAM, uptime, IPs]
  [WiFi]
  [Bluetooth MIDI]
  [ETH0]
  [MIDI Routing: default routing for new devices]
  [Display: MIDI activity bar toggle]
  [Software Update]
  [Reboot]
```

---

## Implementation Phases

### Phase 1: Framework + Built-in Plugins

**Goal:** Complete plugin system with framework, UI, and 8-10 built-in plugins. Ship as v2.0.

#### Step 1.1: Plugin API + Host (`plugin_api.py`, `plugin_host.py`)

```
src/raspimidihub/
├── plugin_api.py        # PluginBase, Param types, clock bus, output methods
├── plugin_host.py       # Discovery, instance lifecycle, threads, ALSA ports
```

**`plugin_api.py`:**
- `PluginBase` class with all callbacks (`on_note_on`, `on_tick`, etc.)
- `Param` types: `Select`, `Knob`, `Toggle`, `StepEditor`, `NoteSelect`, `ChannelSelect`, `CurveEditor`
- `visible_when` conditional visibility
- `cc_inputs` / `cc_outputs` / `outputs` declarations
- `send_note_on/off`, `send_cc`, `send_pitchbend`, `send_aftertouch` output methods
- Plugin metadata: `NAME`, `DESCRIPTION`, `AUTHOR`, `VERSION`, `MIN_HOST_VERSION`

**`plugin_host.py`:**
- `discover_plugins()` — scan `plugins/` directory, validate metadata, import
- `create_instance(plugin_type, name)` — create ALSA seq client, start thread
- `stop_instance(id)` — stop thread, destroy ALSA client, remove from config
- `get_instances()` / `get_instance(id)` — status + serialized params
- `set_param(id, name, value)` — update param, notify plugin via `on_param_change`
- Plugin thread loop: read ALSA IN → dispatch to callbacks → plugin calls `self.send_*` → write ALSA OUT
- Crash isolation: `try/except` around all callbacks, log error, mark instance as crashed

**Clock bus (in `plugin_host.py`):**
- Dedicated thread, receives MIDI clock (24 PPQ) from engine
- Counts ticks, fires `on_tick(division)` for: `1/1`, `1/2`, `1/4`, `1/8`, `1/16`, `1/32`, `1/4T`, `1/8T`, `1/16T`
- Free-running mode: internal tick generator from BPM value
- Auto-detect: if external clock present, sync to it; otherwise use free-running

#### Step 1.2: API Endpoints

```
GET    /api/plugins                    # List available plugin types (from plugins/ dir)
GET    /api/plugins/instances          # List running instances + status
POST   /api/plugins/instances          # Create {type, name}
DELETE /api/plugins/instances/{id}     # Stop and remove
GET    /api/plugins/instances/{id}     # Config + params + cc_inputs + outputs
PATCH  /api/plugins/instances/{id}     # Update params {name: value}
```

#### Step 1.3: Unified Devices Tab + Config UI

- Rename **Status** tab to **Devices** in bottom nav
- Move system info (hostname, CPU, RAM, uptime, IPs) to Settings page top
- Unified device list: USB, Bluetooth, and virtual devices sorted together
- Virtual devices show Ṿ prefix and plugin type name instead of port count
- **[+ Add Virtual Device]** button opens plugin type browser sheet
- Device panel (slide-up) extended for virtual devices:
  - Rename (same as USB)
  - **Plugin config section** rendered from `params` declaration
  - CC inputs/outputs section (auto-generated from plugin declarations)
  - MIDI monitor + test sender (same as USB — useful for debugging plugins)
  - **[Delete Plugin]** button at bottom
  - All param changes applied immediately via PATCH API
- **Ṿ prefix** on virtual device labels in the connection matrix
- `device_id.py`: `plugin-{instance_id}` stable IDs, `is_plugin=True` flag

#### Step 1.4: UI Components for Params

All components are framework-provided. Plugins never write JS.

| Param Type | UI Component | Use Case |
|-----------|-------------|----------|
| `Select` | Dropdown | Pattern, waveform, scale type |
| `Knob` | Slider + value label | Gate %, depth, BPM |
| `Toggle` | Switch | Sync on/off, passthrough |
| `NoteSelect` | Note picker (tap → piano roll or dropdown C0-G10) | Split point, root note |
| `ChannelSelect` | Channel dropdown (1-16) | Output channel |
| `StepEditor` | Touch grid (8/16/32 steps, per-step on/vel/oct) | Arp patterns |
| `CurveEditor` | Touch-draggable curve (X=input, Y=output, 0-127) | Velocity curves |

**StepEditor detail:**
- Tap step → toggle on/off
- Drag vertically on velocity → set level
- Tap octave → cycle -2..+2
- Horizontal scroll for >8 steps
- Configurable: 8, 16, or 32 steps
- Per-step params declared by plugin (on, velocity, octave, note offset, etc.)

**CurveEditor detail:**
- 128×128 grid (rendered as touch-friendly bezier curve)
- Preset curves: linear, exponential, logarithmic, S-curve, hard
- Drag control points to customize
- X axis = input value (0-127), Y axis = output value (0-127)

#### Step 1.5: Built-in Plugins (8-10)

All in `plugins/` directory, each in its own subdirectory:

**1. Arpeggiator** (`plugins/arpeggiator/`)
- Hold notes → play as pattern (up, down, up-down, random, as-played)
- Rate synced to clock or free BPM, gate %, octave range 1-4
- 16-step editor for custom velocity/octave per step
- Pass through aftertouch, pitch bend
- CC inputs: rate, gate
- ~150 lines

**2. Note Splitter** (`plugins/note_splitter/`)
- Split point (NoteSelect), lower notes → channel A, upper → channel B
- Optional overlap (notes at split point go to both)
- CC input: split point (for live adjustment)
- ~60 lines

**3. CC LFO** (`plugins/cc_lfo/`)
- Waveforms: sine, triangle, square, saw, random S&H
- Frequency: Hz (free) or synced (1/4, 1/8, etc.)
- Output: configurable CC number and channel
- Depth (0-127), center offset
- CC input: frequency, depth
- ~80 lines

**4. Velocity Curve** (`plugins/velocity_curve/`)
- CurveEditor for input→output velocity mapping
- Preset curves: linear, soft, hard, exponential, compressed
- Fixes cheap keyboards with bad velocity response
- Passes through all other events unchanged
- ~40 lines

**5. Chord Generator** (`plugins/chord_generator/`)
- Input note → output chord (root + intervals)
- Scale selector: major, minor, 7th, maj7, min7, sus2, sus4, custom
- Inversion selector (root, 1st, 2nd)
- Velocity scaling for added notes
- ~80 lines

**6. MIDI Delay** (`plugins/midi_delay/`)
- Delays notes by configurable time (ms or synced divisions)
- Feedback: 0-100% (repeats)
- Optional velocity decay per repeat
- CC input: delay time, feedback
- ~90 lines

**7. Channel Router** (`plugins/channel_router/`)
- Routes all input from any channel to a fixed output channel
- Or: maps channel A→B, C→D (configurable mapping table)
- Simpler than the matrix channel remap — a dedicated tool
- ~40 lines

**8. CC Smoother** (`plugins/cc_smoother/`)
- Smooths incoming CC values to remove jitter
- Configurable smoothing amount (response time)
- Input CC → output CC (same or different number)
- Useful for noisy controllers
- ~50 lines

**9. Panic Button** (`plugins/panic/`)
- When activated, sends All Notes Off + All Sound Off on all channels
- Can be triggered by a specific CC input (e.g., a footswitch)
- Outputs on its OUT port — wire to all devices that need it
- ~30 lines

**10. Monitor/Logger** (`plugins/monitor/`)
- No audio processing — just logs all incoming MIDI to a scrollable list in its config screen
- Useful for debugging: wire any device → Monitor to see what it sends
- Config screen shows live event log (like device detail, but for any connection)
- ~40 lines

#### Step 1.6: Config Persistence

- Plugin instances saved in `config.json` under `"plugins"` key
- Restored on boot: host recreates instances, applies saved params
- Instance params updated on every PATCH (not just on "Save Config")
- Presets include plugin instance state

#### Step 1.7: Developer Documentation

- `plugins/README.md` — How to create a plugin (tutorial style)
- API reference for PluginBase, all Param types, clock divisions
- Annotated `plugins/_example/` with comments on every method

### Phase 2: Plugin Store (future)

**Goal:** Discover and install community plugins from a GitHub directory.

1. **Plugin registry** — A `plugins.json` file in a GitHub repo listing available plugins with:
   - Name, description, author, version, min host version
   - Download URL (GitHub release or raw file)
   - Screenshot/preview
2. **Store UI** — New section in Plugins tab: "Browse Community Plugins"
   - Fetches registry, shows available plugins
   - Install button: downloads to `plugins/`, auto-discovers
   - Update button: checks version, re-downloads
3. **Plugin validation** — On install, check `MIN_HOST_VERSION` against current version
4. **Plugin hot-reload** — Stop instance, reimport module, restart with same config

---

## Config Schema

Plugin instances and all their parameter values are saved in `config.json`. They are included in config export/import and in presets. When loading a config or preset, plugin instances are recreated with their saved params.

```json
{
  "plugins": [
    {
      "id": "arp-1",
      "type": "arpeggiator",
      "name": "Arp 1",
      "params": {
        "pattern": "up",
        "rate": "1/8",
        "gate": 80,
        "octaves": 1,
        "sync": true,
        "bpm": 120,
        "steps": [
          {"on": true, "velocity": 100, "octave": 0},
          {"on": true, "velocity": 100, "octave": 0},
          {"on": false}
        ]
      }
    },
    {
      "id": "vel-1",
      "type": "velocity_curve",
      "name": "Soft Touch",
      "params": {
        "curve": [0, 5, 12, 20, 30, ...],
        "preset": "exponential"
      }
    }
  ]
}
```

**Save/Export flow:** When the user taps Save Config or Export Config, the current plugin instance list with all params is serialized into the config. When importing or loading, instances are stopped and recreated from the saved data. Missing plugin types (e.g., plugin not installed) are silently skipped with a warning.

---

## Key Design Principles

1. **Plugins must not crash the engine.** Each runs in its own thread with try/except around all callbacks. A crashed plugin logs the error and marks itself as stopped. The ALSA port disappears, the matrix updates, everything else keeps running.

2. **Plugin code is simple.** A developer implements `on_note_on`, `on_tick`, calls `self.send_note_on`. No ALSA knowledge, no threading knowledge, no UI code. The framework does everything else.

3. **UI is declarative.** Plugins declare params, the framework renders them. No HTML, no JS, no CSS in plugins. The step editor, knobs, dropdowns are all framework-provided components that render consistently on mobile.

4. **CC inputs are first-class.** Any numeric parameter can be controlled by a CC. This means hardware knobs → plugin parameters → sound changes. Declared in one line: `cc_inputs = {74: "rate"}`.

5. **Clock is easy.** `clock_divisions = ["1/8"]` and implement `on_tick("1/8")`. The framework handles PPQ counting, tempo detection, free-running fallback.

6. **Matrix integration is free.** Plugins are ALSA devices. All existing features (routing, filtering, channel mapping, presets, save/load, offline persistence) work without any plugin-specific code.

---

## Open Questions for Later

- Should plugins be able to declare multiple ports (e.g., Arp with separate "clock in" and "note in")?
- MIDI 2.0 / MPE support in plugins?
- Plugin sandboxing (restrict file system access, network, etc.)?
- Should plugin params be automatable via MIDI program change (switch presets)?
