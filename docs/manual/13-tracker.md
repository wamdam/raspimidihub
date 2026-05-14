# The Tracker

The **Tracker** is an 8-voice step sequencer on its own **Play** tab.
It lives in the routing matrix like any other addable instance --
add it from **Add → Play** -- but its surface is rich enough to
warrant its own chapter. Routing-matrix appearance, instance
lifecycle, and config-panel mechanics all follow chapter 11; this
chapter is the surface-and-workflow reference.

![The Tracker play surface: 8 voice columns (T1..T8), 16 hex-numbered rows per page, up to 16 pages.](../screenshots/tracker.png){width=42%}

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

The configuration panel has two independent clock toggles:

- **Send Clock** -- when on, the Tracker becomes a clock *master*.
  It runs an internal 24-PPQ generator at the configured **BPM**
  and emits clock to OUT, so any downstream gear sees the same
  clock. The Tracker drives its own playhead from this generator,
  too -- no external clock source is needed. When this toggle is
  off, the Tracker listens for external MIDI Clock instead; with
  no external clock routed in, the playhead is silent. A **BPM**
  wheel (40--300, default 120) appears in the panel only when
  Send Clock is on.
- **Send Transport** -- when on, the Tracker forwards incoming
  START / STOP / CONTINUE to OUT, *and* emits its own START /
  STOP / CONTINUE when the on-screen Play / Stop buttons fire, so
  downstream slaves bar-align with the Tracker whether the
  transport originated upstream or inside the Tracker itself.

The two toggles are independent: the Tracker can generate clock
without forwarding transport (rare), forward transport without
generating clock (when an upstream source already provides the
clock), or both (the common live-rig case where the Tracker is
the master). External clock is ignored while Send Clock is on --
the Tracker's own clock takes priority so downstream gear never
sees two competing sources.

## Editing

The cursor is a moving caret on one cell. Move it with the arrow
keys. The right side of the action row has cursor controls
(Up / Down / Left / Right) for touch-only operation.

### Routing incoming MIDI to tracks

Incoming notes and CCs are routed by their MIDI channel. There
are two modes that can run side by side:

- **Auto Ch.** -- one designated channel (set via the **Auto Ch.**
  wheel on the Tracker's config card; values `Off` / 1..16,
  default `Off`). Notes arriving on this channel land on the
  **cursor track** and a held chord spreads from the cursor
  rightwards across consecutive tracks up to T8. This is the
  historic "I'll point at the track, you record what I play"
  workflow.
- **Direct routing** -- every other channel is matched against
  the per-track output channels in the **Track Channels** group
  (T1..T8). A note on channel *N* lands on the lowest-numbered
  track configured for *N*. If several tracks share *N*, a
  chord on *N* fills those tracks in T1 → T8 order (one note per
  matching track; extra notes drop). This lets you live-record
  without watching the screen -- just change channel on the
  keyboard to pick a track.

If an incoming channel matches neither **Auto Ch.** nor any
configured track, the event is silently dropped: nothing is
recorded and nothing is forwarded to OUT. When you set
**Auto Ch.** to `Off` and don't configure track channels for
anything you actually play on, the Tracker won't react. This is
intentional -- it makes "wrong channel = silence" the feedback
that you changed channel by accident.

### Step-record (stopped)

When the Tracker is stopped, playing a note from a routed MIDI
keyboard (or from the on-screen keyboard, or from QWERTY keyboard
entry; see 13.6) writes the note into the **cursor row** of the
routed track and advances the cursor by one row. Held notes
record their length: pressing `C` and holding for three rows
writes `C-3`, `---`, `---`, then `Off` on the next.

The cursor auto-advances once per chord, no matter how many
notes the chord contains or how many channels they span. A chord
stays open as long as **any** played key is still held; the next
chord starts only when every key is released and a new note
arrives. This means a slowly-played chord still records as a
chord and a fast arpeggio still records as a sequence -- the
gate is held-notes, not a fixed millisecond window. (If a
note-off goes missing the gate self-recovers after about two
seconds of inactivity, so a stuck chord won't pin recording to
one row indefinitely.)

CCs touched while stopped write into the CC field at the cursor
row of the routed track. CCs never auto-advance the cursor and
never spread (only the first matching track receives them).

### Live recording (playing)

When the Tracker is playing, MIDI events that arrive land on the
row whose events are *currently sounding* -- not the row the
cursor is on. The cursor stays where you left it. This means you
can play in a part during a loop and have the part stick to the
beat it was played on. Routing (cursor track via Auto Ch., or a
specific matched track via the incoming channel) works the same
way as in step-record.

CCs touched during play also land on the currently-sounding row
of the routed track.

### Selection

On the keyboard, hold `Shift` while moving the cursor to extend a
sub-cell selection rectangle. On the on-screen action row, tap
**Shift** once to toggle selection mode on (it stays engaged
across multiple cursor moves), tap it again to release. The
on-screen button is a *toggle* rather than press-and-hold so
multi-touch finger-drift can't accidentally drop it mid-select.

While selection mode is engaged, the cursor wraps within the
current page at the row-0 / row-F boundary instead of stepping
to the previous / next page -- otherwise the cursor and the
anchor would land on different pages and the selection rectangle
would disappear. The selection can span multiple voices and
multiple rows on the visible page. The action row shows the cell
count on the right when a selection is active.

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

## Patterns

Each Tracker instance stores **8 numbered patterns**. A pattern is
a full grid (pages + cells). The currently-selected pattern is the
one on screen and the one playback runs against; tapping a
different slot switches between them.

The Pattern row sits below the action row (Shift / Cut / Copy /
Paste), eight slots labelled 1--8. Visually:

- **Outline** -- empty slot (a single default page with no events).
- **Dim fill** -- has content, idle.
- **Accent fill** -- the selected pattern.
- **Coral fill** -- the selected pattern *and* the playhead is
  running.
- **Blinking** -- a tap has queued a switch; the slot will become
  selected at the next pattern boundary.

### Tap

- **Stopped** -- tapping a slot loads it immediately. The view
  switches to that pattern's grid; the cursor jumps to page 0,
  row 0.
- **Playing** -- tapping a slot *queues* the switch. The tapped
  slot blinks. At the next time the playhead wraps from the last
  row of the last page back to page 0 row 0, the swap happens in
  one step: the view changes and the new pattern starts playing
  from row 0 of page 0. Tapping the currently-playing slot
  cancels a pending queue.

### Shift + Tap

Switches immediately while playing -- no queue, no waiting for
the boundary. The playhead tries to land on the **same (page,
row)** position in the new pattern. If the new pattern is shorter
and that page doesn't exist, the playhead falls back to **page 0
at the same row index**, keeping the beat-grid alignment. The
cursor stays where you had it.

While stopped, Shift + Tap behaves the same as Tap (cursor
resets to page 0 row 0).

### Long-press

Long-press a slot to open its context menu:

- **Overwrite from selected** -- copies the currently-selected
  pattern into the long-pressed slot. The selection / view does
  not change. Useful for cloning a working pattern as a starting
  point for a variation.
- **Clear pattern** -- empties the slot back to a single default
  page. If the cleared slot is the currently-selected one, the
  view updates and the cursor jumps to page 0 row 0.

Right-click on a slot also opens the menu.

### What each pattern stores

Only the **grid** (pages + cells). The per-track output channels,
the BPM, and the **Send Clock** / **Send Transport** toggles stay
on the Tracker instance and apply to whichever pattern is playing.
So the eight patterns share routing and tempo; they differ only in
what they sequence.

### Pattern switching from a MIDI controller

Hands-free pattern switching from a keyboard or pad controller is
opt-in via the **Pattern Ctrl Ch** wheel in the configuration
panel. Set it to **Off** (the default) and nothing changes. Set it
to a MIDI channel `1..16` and that channel becomes reserved for
pattern control: a Group of eight **P1..P8** NoteSelect wheels
appears, one per pattern slot.

Pressing the configured note for slot *N* on the control channel
behaves exactly like tapping slot *N* on screen -- queued to the
next page-0 boundary while playing, immediate while stopped. The
on-screen blink during the queued window matches a controller
tap, so a player can see at a glance whether a press already
landed or is still pending.

Each P*N* row has a **Learn** button: tap it, then play the note
on the controller to capture it. The channel-reservation means
nothing else on this channel reaches the tracker -- no recording,
no pass-through, not even CCs. Pick a channel that the rest of
the routing matrix is not already using for a track.

If a control channel and **Auto Ch.** or a per-track channel
overlap, control wins. This keeps the reserved channel reserved.

## The Configuration Panel

Open the Tracker's row or column header in the matrix to access
its plugin-config panel:

- **Per-track channel mapping** -- eight ChannelSelect wheels, one
  per track.
- **Auto Ch.** -- recording-routing wheel; see 13.6.1.
- **Send Clock** + **BPM** -- clock-master mode; see 13.5.
- **Send Transport** -- forward START / STOP / CONTINUE in either
  direction; see 13.5.
- **Pattern Ctrl Ch** -- channel reserved for hands-free pattern
  switching from a controller. Off by default; when set, the
  **Pattern Notes** group with eight learnable P1..P8 NoteSelects
  appears below.
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

