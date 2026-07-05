# UI Controls

Across every panel the UI uses the same small set of touch-first
controls. The shapes and gestures are consistent across the routing
matrix, the plugin configuration panels, the controller surfaces,
the Tracker, and the **Settings** page. Knowing how each control
behaves once -- here -- pays off in every chapter that follows.

Every control renders against the active theme (see chapter 16,
**Settings → Display → Theme**). In dark mode they read as
backlit studio gear -- charcoal wheels with bright values, chrome
faders in dark wells. In light mode the same gestures sit on pale
brushed-aluminium surfaces with dark values. The behaviour is
identical; only the skin changes.

## Wheel

A vertical scrollable drum, used for any value with discrete steps
and a meaningful order: note pitch, BPM, MIDI channel, depth
percentage. Drag the drum up or down; the value snaps to a tick.

Wheels are the default for parameters that benefit from rotary
feedback -- the visible "drum" makes it clear how much range is
above and below the current value. Some wheels display labels
instead of numbers where words make more sense; the **Scale
Remapper** root selector, for example, shows note names (`C`,
`C#`, `D`, ...) instead of integers.

A wheel can also display a scaled value -- the **CC LFO**'s
**Frequency** wheel stores `5` internally but displays it as
`0.5 Hz`.

## Fader

A horizontal or vertical mixer-style slider, used for continuous
values where the metaphor of a "level" applies: volume, depth, mix,
LFO rate. Drag the thumb to set; the value follows the finger
without interpolation lag.

Faders carry a tick sound on each integer step (subtle, optional;
toggle in **Settings → Display**) and a metallic thumb that
catches the eye when scanning a panel of many controls. The
**CC LFO** rate fader is the canonical example -- displayed as
`0.5 Hz`, stored as a raw integer.

*Fine* faders (marked per parameter by the plugin, e.g. the CC
LFO's Depth) step and display at fractional precision -- `63.7`
instead of `64` -- and follow a bound MIDI 2.0 controller at its
full resolution.

## Knob

The circular control used on the controller surfaces. Vertical
drag changes the value; the pointer angle reflects the current
value. Mouse-wheel / two-finger scroll nudges by one step.

Knobs only appear on controller surfaces (chapter 12). The matching
"set Ch / CC / On / Off" controls on a controller's *configuration*
panel are wheels, not knobs -- knobs are for performance, wheels
are for setup.

## Radio

Pill-shaped tap-to-select for small enumerations: waveform shape,
scale type, drop-button mode, arpeggiator pattern. Each option is
its own pill; the selected one is filled, the others are outlined.
Tap to switch. No scrolling, no submenus.

Radios are preferred over dropdowns wherever the option count is
five or fewer.

## Step Editor

A step-sequencer grid: a row of cells, each with an on/off dot, an
optional per-step note offset, and an optional accent flag. The
**Arpeggiator** uses it for the pattern (three-state cycle:
default → on → on+accent → default); the **Euclidean** uses a
four-state variant on top of an algorithm-underlay preview
(default → FORCE_ON → FORCE_ON+accent → FORCE_OFF → default);
the **Tracker** uses a larger and more specialised variant
(chapter 13).

Tap a cell to toggle on or off. Drag vertically on a step to set
its note offset. A surrounding length parameter controls how many
cells are active; cells beyond the length appear greyed.

## Cartesian Grid

The two-dimensional sibling of the Step Editor, used by the
**Cartesian** play surface (chapter 13). The same cells -- on/off
dot, accent, per-cell mini-wheel offset, identical three-state tap
cycle -- but arranged in a square grid (2×2 … 4×4) instead of a
row. A surrounding size parameter sets the side length; the cell
currently under the X-clock playhead is highlighted with a bright
outline as the two clocks sweep the grid.

## Curve Editor

A drawable 128-point canvas, one value per MIDI integer 0--127.
Used by the **Velocity Curve** plugin and any plugin that needs a
per-MIDI-value lookup. Draw with a finger or stylus; the curve
re-samples cleanly between control points.

Curve editors include shape presets along the edge of the canvas
(linear, ease-in, ease-out, S-curve, ...). Tapping a preset sets
the curve and you can then draw on top of it.

## XY Pad

A two-dimensional drag surface, used by the **XY 4** controller.
Drag the dot anywhere on the pad; the X axis sends one CC, the Y
axis sends another. Each axis has independent MIDI Learn.

XY pads optionally **spring** back to a home position (centre or
bottom-left) when released. Spring force is configurable per cell.
The spring is the difference between an XY pad and two faders that
happen to share a surface: with spring on, the XY pad fires a CC
event when released *back* to home as well as when dragged away
from it.

## Scope

A live waveform display showing plugin output over time. The **CC
LFO** uses one to show what the LFO is generating; the **CC
Smoother** uses two (in / out) to show the smoothing effect on a
noisy input.

Scopes scroll right-to-left with a fixed time window (typically
two seconds). The browser renders the trace at its natural frame
rate while the plugin pushes new values in real time.

## Meter

A segmented level / beat indicator. The **Master Clock** uses one
to show the current beat within the bar (four segments, the active
one lit). Generic level meters scale 0--127 across the segments.

Meters are simpler than scopes -- no history, no scroll -- and
cheaper to render at high update rates.

## Button

A rubber push-button with a coloured LED on its face. Buttons come
in two flavours:

- **Latching** (the default). One tap toggles on, the next tap
  toggles off. The LED follows the value. This is the on/off
  switch used for **Sync to Clock** on the **CC LFO**, **Play**
  on the **Master Clock**, **Send Clock** / **Send Trnsp.** on
  the **Tracker**, **Retrig** on the **Euclidean**, and so on.
- **Trigger** (momentary). Each tap fires an action and the LED
  flashes briefly; the value self-resets back to off. This is the
  red **Panic!** button on the **Panic Button** plugin, and the
  drop-button captures on the controller surfaces.

Colour is a visual cue -- green for normal actions, yellow for
"are you sure?", red for destructive.

## Note Select

A wheel specialised for MIDI notes. Renders note names (`C-2` to
`G8`) instead of raw 0--127 integers. Used wherever a parameter is
*a* note -- the **Hold** plugin's release-note Learn, the **Note
Splitter** split point.

## Channel Select

A wheel specialised for MIDI channels. Renders 1--16 (one-based),
even though the underlying value is 0--15 (zero-based). Used
wherever a parameter selects a MIDI channel.

## Group

Not really a control -- a labelled section that visually groups
related parameters in the config panel. The **Arpeggiator** and
the **Euclidean** each use a `Setup` group (config-only) to
bundle channel filters, sync mode and the per-slot trigger notes
out of the way of the live **Play** surface; the **Tracker**
uses **Track Channels**, **Pattern Notes** and so on for the
same purpose. Groups affect layout only.

## MIDI Learn

The universal capture flow. Every parameter that takes a *MIDI
source* (a mapping's source CC, a drop button's trigger note, an
XY axis CC, a controller cell's CC) has a Learn button. Tap it
once -- the button changes to **Listening...** -- then play a note
or move a knob on hardware. The first recognised event fills in
the source fields and Learn turns off.

If you want to cancel, tap the Learn button a second time. The
Learn state does not time out on its own; it stays armed until
either an event arrives or you turn it off.

## CC Automation Feedback

When a hardware CC drives a plugin parameter (either through a
**CC → CC** mapping or because the plugin accepts that CC
directly), turning the hardware knob animates the on-screen
control in real time. A wheel spins, a fader slides, a knob
rotates. No polling, no flicker.

The control source is unambiguous: the *hardware* is moving the
*UI*. Touching the UI while the hardware is also active produces
exactly one resolved value, with no fight between sources.

## The Four Ways an Overlay Closes

Every modal overlay in the UI accepts the same four dismiss
gestures:

1. **Swipe down** on the overlay header.
2. **Tap the dark overlay** outside the panel.
3. **Press `ESC`** if a physical keyboard is connected.
4. **Tap the `X`** button at the top of the overlay.

There is no fifth way. Knowing all four means you can always close
something without hunting for the close button.

## Tick / Haptic Feedback

The wheel and fader controls produce a small click sound on each
integer step. The sound is optional and lives behind the **knob /
wheel tick sounds** toggle in **Settings → Display**.

