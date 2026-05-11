# Controllers and Play Surfaces

Controllers are fullscreen tap-to-play surfaces that send CCs over
MIDI. They live in the **Controller** tab, which appears in the
bottom navigation as soon as at least one controller instance has
been added. This chapter covers the cross-controller features --
the play surface, the drop buttons, the themes, the configuration
panel. The per-controller layout reference is in **Appendix B**.

## The Four Templates

Four controller templates ship out of the box. Each is added from
the **Add → Controller** section of the routing matrix overlay.

| Controller | Layout | Default CC range |
|------------|--------|------------------|
| **Mixer 8** | 24 knobs / 8 faders / 16 buttons | CC 16--63 ch 1 |
| **FX 6** | 18 knobs / 6 faders / 6 buttons | CC 16--45 ch 1 |
| **Performance 16** | 16 macro knobs + 4 scene buttons | CC 16--35 ch 1 |
| **XY 4** | 2 XY pads + 8 knobs + 4 buttons | CC 16--31 ch 1 |

Multiple instances of the same template can coexist. The
**Controller** tab shows them with a top-bar selector; swipe
left / right or use the arrows / dropdown to switch between
instances. The last-viewed instance is remembered across reloads.

![Mixer 8 -- 24 knobs, 8 faders, 16 buttons.](../screenshots/controller-mixer-8.png){width=42%}

![FX 6 -- 18 knobs, 6 faders, 6 buttons.](../screenshots/controller-fx-6.png){width=42%}

![Performance 16 -- 16 macro knobs and 4 scene buttons.](../screenshots/controller-performance-16.png){width=42%}

![XY 4 -- 2 XY pads, 8 knobs, 4 buttons.](../screenshots/controller-xy-4.png){width=42%}

## The Play Surface

Each controller template renders a different surface. What is
universal:

- **Every cell sends one CC** on one channel, with an **On** value
  and an **Off** value. Knobs and faders send the dragged value;
  buttons toggle between On and Off; XY pads send two CCs (one
  per axis).
- **Every cell is renameable** -- tap the label to edit inline.
- **Every cell is MIDI-Learnable** -- a hardware control can drive
  the on-screen cell, with the cell's CC then being forwarded to
  the destination.
- **XY pads have per-axis MIDI Learn** -- each axis captures
  separately.

The configuration -- which CC, which channel, what name, what
theme -- lives in the controller's *plugin config* panel,
described in section 12.7.

## Drop Buttons

Each controller has a row of four **drop buttons** above the play
surface. A drop button is a *snapshot trigger*: long-press it to
capture the current state of every cell on the controller, then
tap to fire that snapshot back.

The drop-button row is part of the controller surface, not a
separate widget. It is always visible while the controller is
shown.

### Capturing

Long-press a drop button for around 600 ms. The button flashes
once to confirm; the current values of every cell on the
controller are captured into that button's slot. The capture also
fires when a learned MIDI trigger note arrives (see *Trigger
notes* below).

### Firing

A tap on the captured drop button fires the snapshot. What
"firing" means depends on the mode and the sync state:

- **Mode = Now** with **Sync = off** -- every cell jumps to its
  captured value immediately.
- **Mode = Bar / 2-Bar / 4-Bar / 8-Bar / 16-Bar** with
  **Sync = on** -- the snapshot is pre-scheduled to land *at* the
  next bar (or 2/4/8/16-bar) boundary of the master clock. The
  ALSA queue handles the scheduling for sub-millisecond accuracy.
- **Fade-on-fire = on** -- the snapshot is interpolated over the
  cycle instead of being applied in one step. Each cell sweeps
  smoothly from its current value to the captured value across
  the bar (or 2/4/8/16-bar) length.
- **Fade-on-fire = off** -- the snapshot is applied in a single
  step at the scheduled boundary.

### The Progress Ring

A segmented arc around the drop button shows the progress of a
scheduled fire. It peach-pulses while the snapshot is scheduled
but not yet fired and freezes if MIDI Stop arrives mid-cycle.

### Trigger Notes

A drop button can be armed by a learned MIDI note: receive the
note on any channel routed to the controller, and the button
fires (or captures, depending on which Learn flow you used) just
as if you tapped it.

### Dual-Slot Scheduling

One **fade** and one **hard drop** can be queued side by side --
useful for, say, fading a filter sweep while pre-scheduling a
hard cut on the next bar. Two fades cannot overlap; the second
overrides the first.

## Themes

Each controller carries its own theme. Eight dark themes ship:

- Default
- Navy
- Forest
- Wine
- Plum
- Teal
- Sienna
- Slate

Theme is **per controller instance**, not global. A Mixer 8 in
Forest and an FX 6 in Wine can sit side by side in the bottom-nav
without affecting each other. The theme is chosen from the
controller's plugin config panel.

## XY Pad Spring

XY pads (on the **XY 4** controller) optionally spring back to a
home position when released. Per-cell:

- **Force** -- 0--127. Zero disables the spring; higher values
  pull the dot back faster.
- **Home** -- Bottom-left or Centre. The position the dot returns
  to when released.

With spring on, releasing the pad fires a CC event for each axis
as the dot returns. With spring off, releasing leaves the dot
where it was; the next CC event happens only when the pad is
touched again.

## The Controller Tab

The **Controller** tab is the fullscreen play surface. Top-bar
controls:

- **Instance selector** -- name of the current controller, with
  arrows / swipe / dropdown to switch.
- **Pencil icon** -- opens the controller's *plugin config* in
  the device-detail panel without leaving the controller tab.

The bottom of the tab shows the standard MIDI activity bar
(section 6.9) when enabled in Settings.

## The Configuration Panel

Tapping the pencil on the controller tab (or tapping the
controller's row / column header in the routing matrix) opens the
*plugin config* view. It is a flat list of every cell on the
controller, each with:

- **Ch** wheel (1--16)
- **CC** wheel (0--127)
- **On** wheel (the value sent on press / drag-end-up)
- **Off** wheel (the value sent on release / drag-end-down)
- **Learn** button (captures from hardware)

Each of the four drop buttons gets its own card with:

- **Sync to bars** toggle
- **Fade on fire** toggle
- **Mode** radio (Now / Bar / 2-Bar / 4-Bar / 8-Bar / 16-Bar)
- **Trg. Note** field + Learn button

A **Maximize** button at the top of the config panel jumps back
to the fullscreen Controller tab.

## Routing a Controller

In the routing matrix, a controller is a **row** (it sends MIDI)
but is **not** typically a destination column -- it does not
*receive* MIDI in the conventional sense. The exception is
MIDI-Learn capture and drop-button trigger notes; those require
the relevant source to be routed *to* the controller for the
note/CC to reach it.

For most setups, route the controller's row to the destination
device (a hardware synth, the DAW, a plugin like the **CC
Smoother**) and that is all.

## Saving Controller State

Cell renames, learned CCs, theme choices, and captured drop-button
snapshots are part of the project state. **Save Config** persists
them; **Export Config** captures them in a JSON snapshot (chapter
15). Removing a controller instance discards its state; cloning
it (Copy → Paste-as-new from the header menu) duplicates the
state.

