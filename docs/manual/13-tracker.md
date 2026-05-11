# The Tracker

The **Tracker** is an 8-voice step sequencer on its own **Play** tab.
It is implemented as a plugin internally, but its workflow is
involved enough to warrant its own chapter. Routing-matrix
appearance, instance lifecycle, and config-panel mechanics all
follow chapter 11; this chapter is the surface-and-workflow
reference.

## Concept

The Tracker is a grid:

- **8 voice columns** (T1..T8).
- **16 hex-numbered rows** per page (0..F).
- **Up to 16 pages** chained linearly. After the last page the
  Tracker loops back to page 0.

Each cell on the grid is *one event per voice per step*. Cells are
edited in place; play moves the cursor down through the rows at the
clock rate.

## The Cell Format

Each cell is four mini-fields:

| Field | Width | Values |
|-------|-------|--------|
| **Note** | 3 chars | Pitch (e.g. `C-4`, `D#3`), `Off` (note off), `End` (page end), `---` (hold) |
| **Velocity** | hex | `00`..`7F` |
| **CC#** | hex | `00`..`7F`, or `.` for "no CC" |
| **CC Val** | hex | `00`..`7F`, ignored when CC# is `.` |

The note and the CC are *independent* on each step. A cell can
fire only a note, only a CC, both, or neither. `---` in the Note
field holds the previous note (no new Note On is fired); `Off`
sends a Note Off; `End` ends the page early and jumps to the next
page.

## Per-Track Output Channel

Each of T1..T8 routes to its own MIDI channel. By default all eight
tracks emit on channel 1; the per-track channel can be remapped in
the Tracker's device-detail panel. The track header on the play
surface reads `T1 [Ch 3]` etc. when a remap is active.

This lets a single Tracker instance drive a multi-timbral synth on
eight different channels, or drive eight separate synths from one
sequencer.

## Transport

The header has a **Play / Stop** toggle. Tap to start or stop
playback; the `Space` key does the same. When stopped, the cursor
stays where you left it; when started, the cursor advances at the
clock rate and the page-end-of-page wraps to the next page.

The Tracker honours external MIDI Clock when one is routed in. With
no external clock, the Play button starts an internal clock at the
configured BPM. The configuration panel shows which mode is in use.

A **Send Clock + Transport** toggle in the config panel makes the
Tracker forward incoming `CLOCK / START / STOP / CONTINUE` through
to OUT, so downstream gear can slave off the Tracker even if the
Tracker is itself slaving off something upstream.

## Editing

The cursor is a moving caret on one cell. Move it with the arrow
keys. The right side of the action row has cursor controls
(Up / Down / Left / Right) for touch-only operation.

### Step-record (stopped)

When the Tracker is stopped, playing a note from a routed MIDI
keyboard (or from the on-screen keyboard, or from QWERTY keyboard
entry; see 13.6) writes the note into the current cell and advances
the cursor by one row. Held notes record their length: pressing
`C` and holding for three rows writes `C-3`, `---`, `---`, then
`Off` on the next.

CCs touched while stopped write into the CC field of the current
cell.

### Live recording (playing)

When the Tracker is playing, MIDI events that arrive land on the
row whose events are *currently sounding* -- not the row the
cursor is on. The cursor stays where you left it. This means you
can play in a part during a loop and have the part stick to the
beat it was played on.

CCs touched during play also land on the currently-sounding row.

### Selection

Holding `Shift` while moving the cursor extends a sub-cell
selection rectangle. The selection can span multiple voices and
multiple rows. The action row shows the cell count on the right
when a selection is active.

### Cut / Copy / Paste

The action row left-to-right reads **Shift / Cut / Copy / Paste**.
With a selection active:

- **Cut** -- copy the selection into the paste buffer and clear it
  from the grid. (Non-destructive: the paste buffer remains until
  the next Cut or Copy.)
- **Copy** -- copy the selection into the paste buffer; the grid
  is unchanged.
- **Paste** -- paste the buffer at the cursor. A
  half-compatibility check ensures a Note-only paste does not
  overwrite CCs on the destination, and vice versa.

`Shift+Cut` / `Shift+Copy` target the whole current page instead
of the current selection. **Del** is **Cut** (copy + clear) rather
than destructive delete -- the paste buffer is updated so an
accidental Del can be undone with Paste.

## Keyboard Note Entry

Notes can be typed on the physical keyboard. The layout is the
standard tracker / piano-key mapping:

| Key | Note |
|-----|------|
| `q` `2` `w` `3` `e` | C C# D D# E |
| `r` `5` `t` `6` `y` `7` `u` | F F# G G# A A# B |

The implementation uses `event.code`, so the *physical* key
position is what counts. **QWERTY and QWERTZ keyboards both work
unchanged.** A German keyboard's `z` key (which is in the QWERTY
`y` position) writes an A; the layout follows the keycaps that an
English speaker would expect, not the OS keymap.

`Space` toggles Play / Stop regardless of cursor focus.

The octave a typed note lands on follows the **OCT** wheel
(visible in the note-half of the keypad). `+` and `-` on the
keyboard nudge that wheel up or down one octave at a time,
clamped to 0..9. `=` and `_` work too so US-layout users don't
need to hold Shift to hit `+`. If the focused cell already holds
a real pitch when you press `+` or `-`, the cell's note moves
along with the wheel — useful when you've recorded a phrase a
little too high or low and want to transpose just the one cell
without retyping it.

## Pages

Pages run linearly from 0 to F (up to 16 pages). The page strip at
the top of the surface shows the active page; tap a page button to
jump.

Page buttons are renameable. The action row buttons that bear on
page operations (insert a page, delete a page, etc.) reflect the
current page navigation state; see the surface for the exact
labels in the running build.

After the last page the Tracker loops back to page 0. `End` in a
note cell ends the page early and jumps to the next page; useful
for variable-length patterns.

## The Configuration Panel

Open the Tracker's row or column header in the matrix to access
its plugin-config panel:

- **Per-track channel mapping** -- eight ChannelSelect wheels, one
  per track.
- **Internal BPM** -- used when no external clock is routed in.
- **Send Clock + Transport** -- the forwarding toggle described in
  13.4.
- **Help button** -- the standard `?` HELP text.

## Saving Tracker State

The grid contents, the page count, the per-track channels, the
**Send Clock + Transport** state, and the cursor position are all
part of the plugin instance state. **Save Config** persists them
with the rest of the project; **Export Config** captures them in a
JSON snapshot (chapter 15).

Cloning a Tracker (Copy → Paste-as-new from the header menu) makes
a second Tracker instance with the same grid -- useful for
splitting a song into "A part" and "B part" Trackers that you swap
between with a controller drop button.

## Screenshots referenced {.unnumbered}

- `../screenshots/tracker.png` -- the play surface.
- `../screenshots/28-plugin-tracker-config.png` -- the
  configuration panel with the per-track channel wheels.

## Screenshots needed {.unnumbered}

- `tracker-selection.png` -- the play surface mid-edit with a
  shift-extended selection rectangle visible.
- `tracker-live-record.png` -- the play surface during live
  recording with a Note On landing on the currently-sounding row.
