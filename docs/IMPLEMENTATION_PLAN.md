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
    cc_outputs = []       # List of CC numbers this plugin sends

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

### Plugins Page (new tab in bottom nav)

New bottom nav icon between Presets and Status:

```
Routing | Presets | Plugins | Status | Settings
```

The Plugins page shows:

```
PLUGIN INSTANCES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ● Arp 1                    [Edit] [✕]
  ● LFO Mod                  [Edit] [✕]
  ○ Note Split (stopped)     [▶]   [✕]

[+ Add Plugin]
```

### Add Plugin Sheet

Tapping "Add Plugin" opens a selection sheet:

```
ADD PLUGIN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Arpeggiator
  Plays held notes as a pattern
                                [Add]

  Note Splitter
  Split keyboard at a note
                                [Add]

  CC LFO
  Generate CC waveforms
                                [Add]
```

### Plugin Edit Panel

Tapping "Edit" opens the plugin config panel (same slide-up style as device detail):

```
ARPEGGIATOR — "Arp 1"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Name: [Arp 1                    ]

Pattern:  [Up      ▾]
Rate:     [1/8     ▾]
Gate:     [====●=====] 80%
Octaves:  [==●=======] 1
Sync:     [●] On

Step Pattern:
┌─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┐
│●│●│○│●│●│○│●│○│●│●│○│●│●│○│●│○│  On/Off
├─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┤
│█│█│ │█│▄│ │█│ │█│█│ │█│▄│ │█│ │  Velocity
├─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┼─┤
│0│0│ │1│0│ │0│ │-│0│ │1│0│ │0│ │  Octave
└─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┘

CC Inputs:
  CC#74 → Rate
  CC#75 → Gate
```

---

## Implementation Phases

### Phase 1: Plugin Framework (foundation)

**Goal:** Framework that can load, run, and manage plugin instances. No plugins yet, but the skeleton works end to end.

Files to create:
```
src/raspimidihub/
├── plugin_api.py        # PluginBase class, Param types, clock bus
├── plugin_host.py       # Loads plugins, manages instances, threads, ALSA ports
plugins/
└── _example/
    └── __init__.py      # Minimal "pass-through" plugin for testing
```

Steps:
1. **`plugin_api.py`** — Define `PluginBase`, `Param` types (Select, Knob, Toggle, StepEditor, NoteSelect, ChannelSelect), `visible_when` logic, CC input/output declarations
2. **`plugin_host.py`** — `PluginHost` class:
   - `discover_plugins()` — scan `plugins/` directory, import each `__init__.py`
   - `create_instance(plugin_type, name)` — create ALSA seq client (via `AlsaSeq`), start plugin thread, wire event reader
   - `stop_instance(instance_id)` — stop thread, destroy ALSA client
   - `get_instances()` — list running instances with status
   - Plugin thread loop: read ALSA events from IN port → dispatch to `on_note_on/off/cc/etc` → plugin calls `self.send_*` → write to OUT port
3. **Clock bus** — Dedicated thread that receives MIDI clock (24 PPQ), maintains tick counter, calls `on_tick(division)` on subscribed plugins at correct divisions. Supports free-running mode with configurable BPM.
4. **`_example` plugin** — Minimal pass-through: receives notes, sends them out unchanged. Proves the framework works.
5. **Config persistence** — Save/load plugin instances and their params in `config.json` under `"plugins"` key. Restore on boot.

### Phase 2: API & Plugin Management UI

**Goal:** Create/delete plugin instances from the web UI. Configure params. See plugins in the matrix.

Steps:
1. **API endpoints:**
   ```
   GET    /api/plugins                    # List available plugin types
   GET    /api/plugins/instances          # List running instances
   POST   /api/plugins/instances          # Create instance {type, name}
   DELETE /api/plugins/instances/{id}     # Stop and remove
   GET    /api/plugins/instances/{id}     # Get instance config + params
   PATCH  /api/plugins/instances/{id}     # Update params {name: value}
   ```
2. **Plugins tab** in bottom nav — list instances, add/remove buttons
3. **Plugin type browser** — shows available plugins from `plugins/` dir with name, description, author
4. **Basic param rendering** — Select, Knob (slider), Toggle rendered from param declarations. No StepEditor yet.
5. **Plugin labels in matrix** — prefix with `♦` or similar icon to distinguish from hardware devices. Extend `device_id.py` for `plugin-{instance_id}` stable IDs.

### Phase 3: Arpeggiator Plugin

**Goal:** First real plugin. Proves the framework works for time-based instruments.

Steps:
1. **`plugins/arpeggiator/__init__.py`** — Implement:
   - Hold notes in a sorted list
   - On `on_tick("1/8")` (or configured rate): advance step, output next note in pattern
   - Patterns: up, down, up-down, random, as-played
   - Gate: schedule note-off after gate% of step duration
   - Octave range: cycle through octaves per pattern cycle
   - Pass through aftertouch, pitch bend to output
   - Respond to CC inputs for rate/gate control
2. **Step editor UI** — implement StepEditor param type in frontend:
   - Touch-friendly grid (min 44px per cell)
   - Tap to toggle step on/off
   - Vertical drag for velocity
   - Tap octave to cycle
   - Horizontal scroll for >8 steps
3. **Clock sync** — Arp syncs to external MIDI clock by default. Falls back to free-running BPM if no clock detected.

### Phase 4: More Plugins + Polish

**Goal:** Prove the framework supports diverse plugin types.

1. **Note Splitter plugin** — Split point selector (NoteSelect param), outputs lower range on channel A, upper on channel B
2. **CC LFO plugin** — Waveform (sine/triangle/square/saw), frequency (Hz or synced), CC number, channel, depth. CC input for frequency modulation.
3. **Plugin docs** — Developer guide with API reference, tutorial for creating a plugin from scratch
4. **Plugin hot-reload** — Stop instance, reimport module, restart with same config (for development)

---

## Config Schema

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
          {"on": false},
          ...
        ]
      }
    }
  ]
}
```

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
- Should there be a "plugin store" or just a plugins/ directory?
- Should plugins be installable as separate .deb packages?
- MIDI 2.0 / MPE support in plugins?
