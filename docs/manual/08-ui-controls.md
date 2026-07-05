# UI Controls

Every panel shares one small set of touch-first controls, from the
routing matrix through plugin config panels and controller surfaces
to **Settings**. Controls render against the active theme
(**Settings → Display → Theme**) — dark mode reads as backlit studio
gear, light mode as pale brushed aluminium — with identical
behaviour in both.

## Wheel

A vertical scrollable drum for discrete ordered values: note pitch,
BPM, MIDI channel, depth percentage. Drag up or down; the value
snaps to a tick, and the drum shows the range above and below.
Wheels may show labels (the **Scale Remapper** root selector shows
note names) or scaled values (the **CC LFO** **Frequency** wheel
stores `5`, displays `0.5 Hz`).

## Fader

A horizontal or vertical mixer-style slider for continuous "level"
values (volume, depth, mix, LFO rate); the value follows the finger
without lag and may display scaled.

*Fine* faders (marked per parameter by the plugin, e.g. the CC LFO's
Depth) step and display at fractional precision — `63.7` instead of
`64` — and follow a bound MIDI 2.0 controller at full resolution.

## Knob

The circular control on controller surfaces (chapter 12) only:
vertical drag changes the value, the pointer angle shows it,
mouse-wheel / two-finger scroll nudges one step. The matching "set
Ch / CC / On / Off" controls on a controller's *configuration* panel
are wheels — knobs are for performance, wheels for setup.

## Radio

Pill-shaped tap-to-select for small enumerations (waveform shape,
scale type, drop-button mode, arpeggiator pattern): the selected
pill is filled, the others outlined. Used wherever there are five
options or fewer.

## Step Editor

A step-sequencer row of cells: on/off dot, optional per-step note
offset, optional accent flag. Tap a cell to cycle its state; drag
vertically to set the note offset; a surrounding length parameter
greys out cells beyond it. The **Arpeggiator** cycles default → on →
on+accent → default; the **Euclidean** uses a four-state variant on
an algorithm-underlay preview (default → FORCE_ON → FORCE_ON+accent
→ FORCE_OFF → default); the **Tracker** a larger, specialised
variant (chapter 13).

## Cartesian Grid

The two-dimensional Step Editor of the **Cartesian** play surface
(chapter 13): the same cells — on/off dot, accent, per-cell
mini-wheel offset, identical tap cycle — in a square grid
(2×2 … 4×4). A size parameter sets the side length; the cell under
the X-clock playhead is outlined bright as the two clocks sweep the
grid.

## Curve Editor

A drawable 128-point canvas, one value per MIDI integer 0--127, used
by the **Velocity Curve** plugin. Draw with finger or stylus; the
curve re-samples cleanly between control points. Edge presets
(linear, ease-in, ease-out, S-curve, ...) set a starting curve to
draw on top of.

## XY Pad

A two-dimensional drag surface, used by the **XY 4** controller: the
X axis sends one CC, the Y axis another, each with independent MIDI
Learn. Pads can **spring** back to a home position (centre or
bottom-left) on release, with per-cell spring force, firing a CC on
the return home as well as when dragged away.

## Scope

A live waveform of plugin output: the **CC LFO** shows what it
generates, the **CC Smoother** two traces (in / out). Scopes scroll
right-to-left over a fixed window of about two seconds.

## Meter

A segmented level / beat indicator: the **Master Clock** shows the
beat within the bar on four segments; generic level meters scale
0--127 across the segments. No history, no scroll.

## Button

A rubber push-button with a coloured LED, in two flavours:

- **Latching** (default) — one tap toggles on, the next off; the
  LED follows the value. **Sync to Clock** (CC LFO), **Play**
  (Master Clock), **Send Clock** / **Send Trnsp.** (Tracker),
  **Retrig** (Euclidean), and similar.
- **Trigger** (momentary) — each tap fires an action, the LED
  flashes, the value self-resets. The red **Panic!** button and
  drop-button captures on controller surfaces.

Colour is a cue: green normal, yellow "are you sure?", red
destructive.

## Note Select

A wheel rendering note names (`C-2` to `G8`) instead of raw 0--127,
used wherever a parameter *is* a note — the **Hold** plugin's
release note, the **Note Splitter** split point.

## Channel Select

A wheel rendering MIDI channels 1--16 (the stored value is 0--15).

## Group

A labelled section grouping related parameters in a config panel;
layout only. The **Arpeggiator** and **Euclidean** each use a
`Setup` group (config-only) for channel filters, sync mode and
per-slot trigger notes; the **Tracker** uses **Track Channels**,
**Pattern Notes** and so on.

## MIDI Learn

The universal capture flow: every parameter that takes a MIDI source
(a mapping's source CC, a drop button's trigger note, an XY axis CC,
a controller cell's CC) has a Learn button. Tap it (it shows
**Listening...**), then play a note or move a knob; the first
recognised event fills the source fields and Learn turns off. Learn
disarms on its own if nothing arrives (10 s in the filter/mapping
panel, 30 s in the CC-binding popups); tap again to cancel early.

## CC Automation Feedback

When a hardware CC drives a plugin parameter (through a **CC → CC**
mapping, or a CC the plugin accepts directly), turning the hardware
knob animates the on-screen control in real time. Touching the UI
while the hardware is active resolves to exactly one value — no
fight between sources.

## The Four Ways an Overlay Closes

Every modal overlay accepts the same four dismiss gestures:

1. **Swipe down** on the overlay header.
2. **Tap the dark overlay** outside the panel.
3. **Press `ESC`** if a physical keyboard is connected.
4. **Tap the `X`** button at the top of the overlay.

There is no fifth way.

## Tick / Haptic Feedback

Wheels and faders click on each integer step — optional, via the
**knob / wheel tick sounds** toggle in **Settings → Display**.
