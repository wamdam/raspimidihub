# Controller Reference

The per-controller layout, default CC assignments, and template-
specific mechanics. The conceptual model -- drop buttons, themes,
maximisation -- is in chapter 12; this appendix is the cell-by-
cell cheat sheet.

## Mixer 8

| Trait | Value |
|-------|-------|
| Name | Controller -- Mixer 8 |
| Description | 8-wide mixer: 24 knobs / 8 faders / 16 buttons |
| Default CC range | 16--63 on channel 1 |
| Default On / Off | 127 / 0 |

**Layout.**

- **3 rows of 8 knobs each** -- 24 knobs total. The three rows
  cover typical send / send / channel-volume layouts on a hardware
  mixer.
- **1 row of 8 faders** -- the eight channel faders.
- **2 rows of 8 buttons each** -- 16 buttons total. The two rows
  typically cover mute / solo per channel.

Default channel for every cell is 1. Per-cell override is allowed
on the configuration panel (Ch wheel per cell).

The four drop buttons sit above the play surface.

![Mixer 8 play surface.](../screenshots/controller-mixer-8.png){width=40%}

![Mixer 8 config panel.](../screenshots/23-controller-mixer-8-config.png){width=40%}

## FX 6

| Trait | Value |
|-------|-------|
| Name | Controller -- FX 6 |
| Description | 6-wide FX: 18 knobs / 6 faders / 6 buttons |
| Default CC range | 16--45 on channel 1 |
| Default On / Off | 127 / 0 |

**Layout.**

- **3 rows of 6 knobs each** -- 18 knobs total. Typically the
  three knobs of an FX unit (e.g. delay time / feedback / mix)
  for six FX channels.
- **1 row of 6 faders** -- per-FX channel level.
- **1 row of 6 buttons** -- per-FX bypass / enable.

![FX 6 play surface.](../screenshots/controller-fx-6.png){width=40%}

![FX 6 config panel.](../screenshots/25-controller-fx-6-config.png){width=40%}

## Performance 16

| Trait | Value |
|-------|-------|
| Name | Controller -- Performance 16 |
| Description | 4-wide performance: 16 macros + 4 scene buttons |
| Default CC range | 16--35 on channel 1 |
| Default On / Off | 127 / 0 |

**Layout.**

- **4 rows of 4 knobs each** -- 16 macro knobs. Each knob is
  intended as a "macro" -- a single knob mapped to multiple
  destination parameters at the routing-mappings level.
- **1 row of 4 buttons** -- the four scene buttons.

The drop-button row remains separate and sits above the play
surface.

![Performance 16 play surface.](../screenshots/controller-performance-16.png){width=40%}

![Performance 16 config panel.](../screenshots/26-controller-performance-16-config.png){width=40%}

## XY 4

| Trait | Value |
|-------|-------|
| Name | Controller -- XY 4 |
| Description | Performance: 2 XY pads / 8 knobs / 4 buttons |
| Default CC range | 16--31 on channel 1 |
| Default On / Off | 127 / 0 |

**Layout.**

- **2 large XY pads** at the top. Each pad sends two CCs (one per
  axis); per-axis MIDI Learn is supported.
- **2 rows of 4 knobs each** in the middle -- 8 knobs total.
- **1 row of 4 buttons** along the bottom.

**XY pad specifics:**

- Each pad has per-cell **Force** (0--127, 0 disables spring) and
  **Home** (Bottom-left or Centre).
- The dot returns to **Home** when released (if Force > 0).
- Releasing fires a CC event for each axis as the dot returns to
  home.

![XY 4 play surface.](../screenshots/controller-xy-4.png){width=40%}

![XY 4 config panel.](../screenshots/24-controller-xy-4-config.png){width=40%}

## Drop Buttons -- Complete Reference

Every controller carries a row of four drop buttons. The drop-
button system is identical across templates; only the snapshot
contents differ (a Mixer 8 snapshot is bigger than an FX 6
snapshot).

| Per-button parameter | Type | Values |
|----------------------|------|--------|
| **Mode** | Radio | Now / Bar / 2-Bar / 4-Bar / 8-Bar / 16-Bar |
| **Sync to bars** | Button (latching) | on / off |
| **Fade on fire** | Button (latching) | on / off |
| **Trg. Note** | NoteSelect + Learn | The MIDI note that triggers a fire |

**Behaviour table:**

| Sync | Fade | What happens on tap |
|------|------|---------------------|
| off | off | Snapshot applies instantly to all cells |
| off | on | Snapshot interpolates over the configured mode's bar length, starting now |
| on | off | Snapshot applies on the next mode-boundary (Bar / 2-Bar / 4-Bar / 8-Bar / 16-Bar) |
| on | on | Snapshot interpolates over the next mode-boundary cycle |

**Capture vs fire.** Long-press the button (~600 ms) to capture
the current state into the slot. Tap to fire the captured
snapshot. A captured drop button shows a filled dot; an empty
slot shows a hollow dot.

**MIDI-note trigger.** With **Trg. Note** set, receiving that note
on any channel routed to the controller triggers the drop button
just as if you tapped it.

**Dual-slot scheduling.** One fade and one hard drop can be
queued at once. Two fades cannot overlap; queueing a second fade
overrides the first.

**Progress ring.** A segmented arc around the drop button
indicates progress within the scheduled cycle. The arc:

- Peach-pulses while waiting for the boundary.
- Fills the cycle in real time once the fire starts (for fade
  mode).
- Freezes if MIDI Stop arrives mid-cycle.

## Themes

Eight dark themes ship with every controller. Theme is **per
controller instance**, not global.

| Theme | Accent colour |
|-------|---------------|
| Default | Cyan / turquoise |
| Navy | Deep blue |
| Forest | Green |
| Wine | Burgundy red |
| Plum | Purple |
| Teal | Blue-green |
| Sienna | Burnt orange |
| Slate | Cool grey |

The theme is chosen in the controller's plugin-config panel.
Changing themes is instant; the running surface re-renders with
the new accent colour.

**Screenshot needed.** `controller-themes-grid.png` -- a single
controller in all eight themes, side by side, for visual
comparison.

## Saved State

The controller's full state is part of the project state:

- Per-cell rename
- Per-cell CC, channel, On / Off values
- Per-cell learned MIDI source
- Per-axis configuration (XY 4 spring / home)
- All four drop-button captured snapshots
- Per-drop-button **Mode**, **Sync**, **Fade**, **Trg. Note**
- The chosen theme

**Save Config** persists it; **Export Config** captures it in a
JSON snapshot (chapter 15); cloning the instance (Copy →
Paste-as-new from the header menu) duplicates it with a fresh
instance ID.
