# Play Surfaces

Three plugins live on the **Play** bottom-nav tab and share the
same surface-carousel pattern: the **Arpeggiator**, the
**Euclidean**, and the **Tracker**. They are routable in the
matrix like any other plugin (`SURFACE_KIND = "play"`; add them
from **Add → Play**) and additionally render a fullscreen play
surface designed for live performance.

When to reach for which:

- **Arpeggiator** -- you want to hold a chord and have it played
  back as a rhythmic pattern (the classic "up / down / random"
  arp), with an optional drawn step grid on top for per-step
  on/off, accent and offset. Seven pattern modes (incl. `chord`
  for drum-style stabs) + a live step-sequencer mode
  (`programmed`).
- **Euclidean** -- you want algorithmic rhythms: the Bjorklund
  distribution generates evenly-spaced hits over N steps from a
  pulse count, optionally masked by a window-wave that limits
  where in the cycle hits are allowed. Internal scale quantiser
  + tune-spread randomiser layer melody on top. Polyrhythm comes
  from running two instances on the same clock.
- **Tracker** -- you want a step sequencer in the classical
  music-tracker sense: 8 voices × 16 rows × up to 16 pages, with
  per-step note + velocity + CC. Live-recordable; clock-master
  capable.

All three carry an 8-slot **pattern bank** (P1..P8) at the
bottom of their play surface. Tapping a slot switches the active
pattern; on the Arpeggiator and Euclidean the switch is
immediate and held notes / sustain persist across the change, on
the Tracker the switch queues to the next page-0 boundary while
playing (Shift+Tap forces an immediate switch). Long-press any
slot for an **Overwrite from current / Reset to default** menu.

Routing-matrix appearance, instance lifecycle, and config-panel
chrome all follow chapter 11; this chapter is the surface-and-
workflow reference for each plugin.

The per-plugin parameter table -- range, default, type -- lives
in **Appendix A** alongside every other plugin.

## The Arpeggiator

Plays the held notes as a pattern with a step sequencer on top.
The **Play** surface puts the live controls in one fullscreen
panel: **Pattern** and **Rate** are wide wheels at the top so a
finger flick on stage moves them; the four shapers
(**Steps / Accent Vel. / Gate % / Octaves**) sit in one row
above the step grid; the **Step Pattern** editor fills the
bottom for per-step on/off, offset and accent. The setup-only
parameters (channel filter, sync mode + BPM, Ctrl Ch + the 8
learnable trigger notes) live in the device-detail panel under
the **Setup** group -- touched on initial wiring, never during a
set.

![Arpeggiator play surface: Pattern + Rate wide wheels, four shapers, Step Pattern grid.](../screenshots/arpeggiator-play.png){width=42%}

### Pattern Modes

The Pattern wheel selects how the held-note buffer is voiced
per step:

- **up** -- next held note ascending each step (the classic).
- **down** -- ditto, descending.
- **up-down** -- ping-pong; reverses direction at the highest /
  lowest held note.
- **random** -- pick a held note at random each step.
- **as-played** -- press order (a chord played C-E-G plays back
  C-E-G even if F is added later).
- **programmed** -- a live step-sequencer mode added in v3.0.5.
  Each keypress writes the next-to-fire step slot; multiple
  presses between ticks fan into consecutive slots (chord-
  spread). Slots persist while any key or the sustain pedal is
  held; once every input is released the slots clear and re-
  pressing starts a fresh phrase.
- **chord** -- every held note fires simultaneously each step.
  Per-step offset, accent and gate apply to the whole burst;
  `Octaves > 1` doubles the chord into the higher octaves. Good
  for stab-style sequencing where you want the full chord on
  every hit.

### The Step Grid

The grid below the wide wheels is the step pattern. Each cell
has a head and a mini-wheel:

- Tap the **head** to cycle the step state:
  `off → on → on+accent → off`. On-steps play the next note
  from the Pattern wheel; off-steps are rests.
- Drag (or wheel-scroll on desktop) the **mini-wheel** to set a
  per-step semitone offset (-24..+24), applied on top of
  whatever pitch the Pattern wheel picked for this step.

`Steps` (1..32) controls how many cells appear in the grid. The
cycle wraps automatically after the configured step count.

### The Pattern Bank

The strip at the end of the surface (P1..P8) is an 8-slot bank.
Each slot carries a snapshot of every play-surface param --
Pattern, Rate, Steps, Accent Vel., Gate, Octaves and the Step
Pattern grid. Tap a slot to switch; the change is **immediate**
(no quantise to bar) and held notes plus sustain state survive
the switch, so a slot change can rewrite the pattern under a
chord held with the pedal.

Edits to any play-surface knob auto-write back to the active
slot (no Store action). The bank tracks your live working
state -- pick a slot, sculpt the pattern, move on. Long-press
any slot for:

- **Overwrite from current** -- copy the currently-active
  slot's contents into the long-pressed slot. Useful for
  forking a pattern as a starting point for a variation.
- **Reset to default** -- wipe the slot back to plugin
  defaults. If the cleared slot is the active one, live state
  reloads too.

### The Setup Panel

Opens when you tap the Arpeggiator's row or column header in
the matrix. The play-surface controls are hidden here
(`play_only`); only the wiring choices live in this panel:

- **Sync** -- `free` / `tempo` / `transport`. In **tempo** mode
  the Arpeggiator advances one step per clock subdivision; in
  **transport** mode advance only happens while external START
  is asserted (stop pauses the playhead at its current step).
  In **free** mode the plugin runs its own clock at the **BPM**
  wheel (40..300, visible only when Sync = free).
- **Arp Ch** -- `Any` / `1..16`. Restricts which incoming notes
  count as melody input. Useful when one keyboard plays the arp
  on ch1 and another sends pattern-trigger notes on ch16: set
  Arp Ch = 1 and Ctrl Ch = 16.
- **Ctrl Ch** -- `Off` / `1..16`. When set, this channel is
  reserved for **pattern slot triggering**: every note that
  arrives on it is consumed (no melody input, no pass-through)
  and matched against the 8 learnable notes in the **Pattern
  Notes** group, which appears below this wheel. Each P1..P8
  is an independently MIDI-Learnable NoteSelect; the matched
  note switches the active slot exactly as a screen tap would.

### CC Automation

Block CC 70..83 covers every play-surface knob, mirroring the
Euclidean's mapping so a hardware controller wired for one
plugin drives the matching knob on the other identically:

| CC | Parameter | CC | Parameter |
|----|-----------|----|-----------|
| 70 | Pattern   | 74 | Rate |
| 71 | Octaves   | 75 | Gate % |
| 73 | Steps     | 83 | Accent Vel. |

Discrete-enum params (Pattern is integer-indexed into
`_PATTERN_OPTIONS`, Rate into `_RATE_OPTIONS`) accept the same
0..127 CC -- the host scales the 0..127 value across the
param's min..max and snaps to the matching option.

### Input / Output / Clock

**Input.** Notes (held-note buffer), CC 64 (sustain pedal --
released keys keep arping until pedal lift), CC 70..83
(parameter automation), Clock + Transport (when **Sync** is
`tempo` or `transport`), and the 8 learnable notes on **Ctrl
Ch** when set (each picks a pattern slot; consumed, not
arpeggiated).
**Output.** Notes (the arpeggiated stream). Aftertouch and Pitch
Bend pass through unchanged.
**Clock.** Consumes external clock when **Sync** is `tempo`
(free-running advance per tick) or `transport` (advance only
while external START..STOP is asserted); free-runs at **BPM**
when **Sync** is `free`.

![Arpeggiator device-detail panel: same play controls plus the Setup group.](../screenshots/09-plugin-arpeggiator.png){width=35%}

## The Euclidean

Holds incoming notes and plays them as an evenly-distributed
(Bjorklund) pattern over the configured **Steps**. The play
surface is denser than the Arpeggiator's -- the Euclidean
exposes more shaping knobs because its rhythm is computed, not
drawn -- but the same finger-flick wheels at the top carry the
"set on stage" choices: Pattern and Rate.

Polyrhythm comes from running two instances on the same clock
with co-prime pulse / step counts, e.g. 5-against-7. The
Euclidean does not have polyrhythm as a single-instance
feature; the routing matrix is how you compose multiple
rhythmic layers.

![Euclidean play surface: five rows of shapers above the step grid; P1..P8 bank at the bottom.](../screenshots/euclidean-play.png){width=42%}

### The Three Layers

The pattern is built in three stacked layers; each tick, the
plugin asks "should this step fire?" and the answer is the
composition of all three:

#### Layer 1 -- Bjorklund distribution

Three knobs:

- **Pulses** (0..32, capped by Steps) -- number of "on" steps
  per cycle.
- **Steps** (1..32) -- length of one cycle.
- **Rotate** (-16..+16) -- rotates the pulse positions inside
  the cycle.

These are the knobs of a Bjorklund-style spread. `Pulses=4,
Steps=16, Rotate=0` → `X . . . X . . . X . . . X . . .` --
four-on-the-floor at sixteenth rate. `Pulses=3, Steps=8` →
`X . . X . . X .` -- the tresillo. `Pulses=5, Steps=8` →
`X . X X . X X .` -- the cinquillo.

#### Layer 2 -- Window wave

A sine threshold that masks which steps are allowed to fire.
Three knobs:

- **Phase** (0..31) -- where the wave's peak sits, in steps.
- **Cycles** (0.5 / 1 / 2 / 3 / 4) -- how many wave periods
  fit in one pattern cycle.
- **Open** (0..100) -- how much of the wave sits above the
  "open" threshold. `Open = 100` makes the layer transparent
  (the Bjorklund pattern plays unmasked); `Open = 0` closes the
  gate entirely.

The window subsumes a bunch of common "sub-range" use cases --
fixed start / length, slow density swells, chases across the
pattern -- without a separate start / length pair.

#### Layer 3 -- Manual overrides

The step grid below the knobs is the override layer. Each
cell's head cycles through four states on tap:

- **default** -- algorithm decides. Renders empty when the
  algorithm + window agree the step should be off, or a
  subdued underlay tint when they agree it should fire. The
  tint is what tells you, at a glance, *what the generator
  would do here if I left it alone*.
- **FORCE_ON** -- fully lit. The step plays regardless of what
  the algorithm wants.
- **FORCE_ON + accent** -- brighter / hue-shifted. Forced-on
  with an accent on top.
- **FORCE_OFF** -- dim / struck-through. Silent regardless of
  what the algorithm wants.

The inline **MiniWheel** below each head is the per-step
semitone offset, just like the Arpeggiator's grid.

### Pitch Model

Pitch is sourced from **held notes** (same shape as the
Arpeggiator). When no notes are held, the plugin goes silent.

The **Pattern** wheel picks how the held buffer is voiced:
`up` / `down` / `up-down` / `random` / `as-played` / `chord`.
`chord` fires every held note simultaneously each step.

Output is quantised to the internal **Scale + Root** (9 scales:
major / minor / dorian / mixolydian / pentatonic / blues /
harmonic m / whole tone / chromatic). Setting Scale =
`chromatic` makes the quantiser a pass-through.

**Tune Spread + Snap** randomly transpose each step. Tune
Spread (0..100) is both the probability of a non-zero
transpose and the size of the jump. Snap pre-quantises the
jump:

- `free` -- any semitone within ±12.
- `octaves` -- ±12 / ±24 / 0.
- `5ths+oct.` -- ±5 / ±7 / ±12 / ±19 / ±24 / 0.

The Scale quantiser runs *after* the spread, so a
fifths-and-octaves jump stays in scale by construction.

### Time Model

- **Rate** -- same 15 values as the Arpeggiator (`4/1` ..
  `1/32`). Default `1/16`.
- **Gate %** (10..100) -- note length as a percentage of one
  step duration. 100 = legato, 10 = staccato.
- **Jitter %** (0..100) -- random per-step micro-timing offset
  as a percentage of one step duration. Re-rolled every step.
  0 = grid-tight; 100 = the step can land anywhere inside half
  its own duration.
- **Fade In** (0..16 firing steps) -- when the pattern
  transitions from idle to playing, the first N **firing**
  steps scale velocity from 0% to 100%. Counts firing steps
  (not grid positions) so the swell time feels musical
  regardless of how dense the pattern is.
- **Fade Out** (0..16 firing steps) -- when every key is
  released (and sustain is up), the next N firing steps scale
  velocity from 100% to 0% before silencing. Key-on during a
  fade-out cancels it and snaps back to full.

### Retrig

The Setup-group **Retrig** button (default **on**) controls
what happens when you start a fresh phrase (released-all-keys
→ press-a-key):

- **on** -- the cycle restarts from step 1 each time a new
  phrase begins. Every chord you play kicks off the pattern
  from the top.
- **off** -- the cycle keeps free-wheeling across rest gaps,
  so re-triggering after silence picks up wherever the clock
  would have landed if you'd kept holding. Useful when you
  want the pattern locked to bar time regardless of when you
  stab a chord.

### The Pattern Bank

Same shape as the Arpeggiator's bank: 8 slots, each carrying a
snapshot of every play-surface param (pattern, rate, all three
rhythm layers, scale + root, spread + fade envelope, the step
grid). Tap a slot to switch immediately; held notes and sustain
persist. Edits auto-write to the active slot. Long-press for
**Overwrite from current** / **Reset to default**.

### The Setup Panel

- **Sync** -- `free` / `tempo` / `transport` (same as Arp).
- **Arp Ch** -- `Any` / `1..16`. Filters melody input.
- **Ctrl Ch** -- `Off` / `1..16`. Reserves a channel for the 8
  learnable slot-trigger notes; same shape as the Arpeggiator.
- **Retrig** -- see above.
- **BPM** -- visible only when Sync = free.

### CC Automation

The full block CC 70..88 (skipping CC 84 = GM Portamento
Control) covers every play-surface knob:

| CC | Parameter | CC | Parameter |
|----|-----------|----|-----------|
| 70 | Pattern    | 80 | Fade In |
| 71 | Octaves    | 81 | Fade Out |
| 72 | Pulses     | 82 | Jitter |
| 73 | Steps      | 83 | Accent Vel. |
| 74 | Rate       | 85 | Tune Spread |
| 75 | Gate %     | 86 | Snap |
| 76 | Open       | 87 | Scale |
| 77 | Phase      | 88 | Root |
| 78 | Cycles     |    |    |
| 79 | Rotate     |    |    |

CC 74 (Rate) and CC 75 (Gate) match the Arpeggiator so a
single controller wired for the Arp drives both. Discrete-enum
params (Pattern / Snap / Scale / Root) accept the same 0..127
CC -- the host scales 0..127 across the param's min..max.

### Input / Output / Clock

**Input.** Notes (held buffer), CC 64 (sustain pedal -- holds
the input chord across release), CC 70..83 / CC 85..88
(parameter automation), 8 learnable notes on **Ctrl Ch** when
set (each picks a pattern slot; consumed, not arpeggiated),
Clock + Transport (when Sync is `tempo` or `transport`).
**Output.** Notes (Bjorklund-voiced, scale-quantised).
Aftertouch and Pitch Bend pass through unchanged.
**Clock.** Consumes external clock when **Sync** is `tempo` or
`transport`; free-runs at **BPM** when **Sync** is `free`.

### Polyrhythm

Polyrhythm is **not a parameter** -- it's a routing-matrix
configuration. Two Euclidean instances on the same clock with
co-prime pulse / step counts give you a 5-against-7
cross-rhythm:

```
[Keyboard ch1] → [Euclidean A: pulses=5 steps=16 @ 1/16] ─┐
[Keyboard ch1] → [Euclidean B: pulses=7 steps=12 @ 1/16] ─┴→ [Synth]
[Master Clock] ─→ both
```

Both instances quantise to the same key independently;
setting them both to `chromatic` is the escape hatch when a
shared downstream `Scale Remapper` is wanted instead.

![Euclidean device-detail panel: Setup group with the 8 learnable trigger notes expanded.](../screenshots/30-plugin-euclidean-config.png){width=35%}

## The Tracker

The **Tracker** is an 8-voice step sequencer with the richest
play surface of the three -- 8 voice columns, 16 hex-numbered
rows per page, up to 16 pages chained linearly, and 8 stored
patterns. Used as a song-section sequencer (drum line + bass +
chord stabs all in one Tracker instance) or as a fully
hands-free clock master / transport source.

![The Tracker play surface: 8 voice columns (T1..T8), 16 hex-numbered rows per page, up to 16 pages.](../screenshots/tracker.png){width=42%}

### Concept

The Tracker is a grid:

- **8 voice columns** (T1..T8).
- **16 hex-numbered rows** per page (0..F).
- **Up to 16 pages** chained linearly. After the last page the
  Tracker loops back to page 0.

Each cell on the grid is *one event per voice per step*. Cells
are edited in place; play moves the cursor down through the
rows at the clock rate.

### The Cell Format

Each cell is four mini-fields:

| Field | Width | Values |
|-------|-------|--------|
| **Note** | 3 chars | Pitch (e.g. `C-4`, `D#3`), `Off` (note off), `End` (page end), `---` (hold) |
| **Velocity** | hex | `00`..`7F` |
| **CC#** | hex | `00`..`7F`, or `.` for "no CC" |
| **CC Val** | hex | `00`..`7F`, ignored when CC# is `.` |

The note and the CC are *independent* on each step. A cell can
fire only a note, only a CC, both, or neither. `---` in the
Note field holds the previous note (no new Note On is fired);
`Off` sends a Note Off; `End` ends the page early and jumps to
the next page.

### Per-Track Output Channel

Each of T1..T8 routes to its own MIDI channel. By default all
eight tracks emit on channel 1; the per-track channel can be
remapped in the Tracker's device-detail panel. The track header
on the play surface reads `T1 [Ch 3]` etc. when a remap is
active.

This lets a single Tracker instance drive a multi-timbral synth
on eight different channels, or drive eight separate synths from
one sequencer.

### Transport

The header has a **Play / Stop** toggle. Tap to start or stop
playback; the `Space` key does the same. When stopped, the
cursor stays where you left it; when started, the cursor
advances at the clock rate and the page-end-of-page wraps to
the next page.

The configuration panel has two independent clock toggles:

- **Send Clock** -- when on, the Tracker becomes a clock
  *master*. It runs an internal 24-PPQ generator at the
  configured **BPM** and emits clock to OUT, so any downstream
  gear sees the same clock. The Tracker drives its own playhead
  from this generator, too -- no external clock source is
  needed. When this toggle is off, the Tracker listens for
  external MIDI Clock instead; with no external clock routed
  in, the playhead is silent. A **BPM** wheel (40--300, default
  120) appears in the panel only when Send Clock is on.
- **Send Transport** -- when on, the Tracker forwards incoming
  START / STOP / CONTINUE to OUT, *and* emits its own START /
  STOP / CONTINUE when the on-screen Play / Stop buttons fire,
  so downstream slaves bar-align with the Tracker whether the
  transport originated upstream or inside the Tracker itself.

The two toggles are independent: the Tracker can generate clock
without forwarding transport (rare), forward transport without
generating clock (when an upstream source already provides the
clock), or both (the common live-rig case where the Tracker is
the master). External clock is ignored while Send Clock is
on -- the Tracker's own clock takes priority so downstream gear
never sees two competing sources.

### Editing

The cursor is a moving caret on one cell. Move it with the
arrow keys. The right side of the action row has cursor
controls (Up / Down / Left / Right) for touch-only operation.

#### Routing incoming MIDI to tracks

Incoming notes and CCs are routed by their MIDI channel. There
are two modes that can run side by side:

- **Auto Ch.** -- one designated channel (set via the **Auto
  Ch.** wheel on the Tracker's config card; values `Off` /
  1..16, default `Off`). Notes arriving on this channel land
  on the **cursor track** and a held chord spreads from the
  cursor rightwards across consecutive tracks up to T8. This
  is the historic "I'll point at the track, you record what I
  play" workflow.
- **Direct routing** -- every other channel is matched against
  the per-track output channels in the **Track Channels** group
  (T1..T8). A note on channel *N* lands on the lowest-numbered
  track configured for *N*. If several tracks share *N*, a
  chord on *N* fills those tracks in T1 → T8 order (one note
  per matching track; extra notes drop). This lets you
  live-record without watching the screen -- just change
  channel on the keyboard to pick a track.

If an incoming channel matches neither **Auto Ch.** nor any
configured track, the event is silently dropped: nothing is
recorded and nothing is forwarded to OUT. When you set
**Auto Ch.** to `Off` and don't configure track channels for
anything you actually play on, the Tracker won't react. This
is intentional -- it makes "wrong channel = silence" the
feedback that you changed channel by accident.

#### Step-record (stopped)

When the Tracker is stopped, playing a note from a routed MIDI
keyboard (or from the on-screen keyboard, or from QWERTY
keyboard entry) writes the note into the **cursor row** of the
routed track and advances the cursor by one row. Held notes
record their length: pressing `C` and holding for three rows
writes `C-3`, `---`, `---`, then `Off` on the next.

The cursor auto-advances once per chord, no matter how many
notes the chord contains or how many channels they span. A
chord stays open as long as **any** played key is still held;
the next chord starts only when every key is released and a
new note arrives. This means a slowly-played chord still
records as a chord and a fast arpeggio still records as a
sequence -- the gate is held-notes, not a fixed millisecond
window. (If a note-off goes missing the gate self-recovers
after about two seconds of inactivity, so a stuck chord won't
pin recording to one row indefinitely.)

CCs touched while stopped write into the CC field at the
cursor row of the routed track. CCs never auto-advance the
cursor and never spread (only the first matching track
receives them).

#### Live recording (playing)

When the Tracker is playing, MIDI events that arrive land on
the row whose events are *currently sounding* -- not the row
the cursor is on. The cursor stays where you left it. This
means you can play in a part during a loop and have the part
stick to the beat it was played on. Routing (cursor track via
Auto Ch., or a specific matched track via the incoming channel)
works the same way as in step-record.

CCs touched during play also land on the currently-sounding
row of the routed track.

#### Selection

On the keyboard, hold `Shift` while moving the cursor to
extend a sub-cell selection rectangle. On the on-screen action
row, tap **Shift** once to toggle selection mode on (it stays
engaged across multiple cursor moves), tap it again to release.
The on-screen button is a *toggle* rather than press-and-hold
so multi-touch finger-drift can't accidentally drop it
mid-select.

While selection mode is engaged, the cursor wraps within the
current page at the row-0 / row-F boundary instead of stepping
to the previous / next page -- otherwise the cursor and the
anchor would land on different pages and the selection
rectangle would disappear. The selection can span multiple
voices and multiple rows on the visible page. The action row
shows the cell count on the right when a selection is active.

#### Cut / Copy / Paste

The action row left-to-right reads
**Shift / Cut / Copy / Paste**. With a selection active:

- **Cut** -- copy the selection into the paste buffer and
  clear it from the grid. (Non-destructive: the paste buffer
  remains until the next Cut or Copy.)
- **Copy** -- copy the selection into the paste buffer; the
  grid is unchanged.
- **Paste** -- paste the buffer at the cursor. A
  half-compatibility check ensures a Note-only paste does not
  overwrite CCs on the destination, and vice versa.

`Shift+Cut` / `Shift+Copy` target the whole current page
instead of the current selection. **Del** is **Cut** (copy +
clear) rather than destructive delete -- the paste buffer is
updated so an accidental Del can be undone with Paste.

### Keyboard Note Entry

Notes can be typed on the physical keyboard. The layout is the
standard tracker / piano-key mapping:

| Key | Note |
|-----|------|
| `q` `2` `w` `3` `e` | C C# D D# E |
| `r` `5` `t` `6` `y` `7` `u` | F F# G G# A A# B |

The implementation uses `event.code`, so the *physical* key
position is what counts. **QWERTY and QWERTZ keyboards both
work unchanged.** A German keyboard's `z` key (which is in the
QWERTY `y` position) writes an A; the layout follows the
keycaps that an English speaker would expect, not the OS
keymap.

`Space` toggles Play / Stop regardless of cursor focus.

The octave a typed note lands on follows the **OCT** wheel
(visible in the note-half of the keypad). `+` and `-` on the
keyboard nudge that wheel up or down one octave at a time,
clamped to 0..9. `=` and `_` work too so US-layout users don't
need to hold Shift to hit `+`. If the focused cell already
holds a real pitch when you press `+` or `-`, the cell's note
moves along with the wheel — useful when you've recorded a
phrase a little too high or low and want to transpose just the
one cell without retyping it.

### Pages

Pages run linearly from 0 to F (up to 16 pages). The page strip
at the top of the surface shows the active page; tap a page
button to jump.

Page buttons are renameable. The action row buttons that bear
on page operations (insert a page, delete a page, etc.) reflect
the current page navigation state; see the surface for the
exact labels in the running build.

After the last page the Tracker loops back to page 0. `End` in
a note cell ends the page early and jumps to the next page;
useful for variable-length patterns.

### Patterns

Each Tracker instance stores **8 numbered patterns**. A pattern
is a full grid (pages + cells). The currently-selected pattern
is the one on screen and the one playback runs against;
tapping a different slot switches between them.

The pattern bank sits below the action row
(Shift / Cut / Copy / Paste), eight slots labelled P1--P8.
Visually:

- **Outline** -- empty slot (a single default page with no
  events).
- **Dim fill** -- has content, idle.
- **Accent fill** -- the selected pattern.
- **Coral fill** -- the selected pattern *and* the playhead is
  running.
- **Blinking** -- a tap has queued a switch; the slot will
  become selected at the next pattern boundary.

#### Tap

- **Stopped** -- tapping a slot loads it immediately. The view
  switches to that pattern's grid; the cursor jumps to page 0,
  row 0.
- **Playing** -- tapping a slot *queues* the switch. The
  tapped slot blinks. At the next time the playhead wraps from
  the last row of the last page back to page 0 row 0, the swap
  happens in one step: the view changes and the new pattern
  starts playing from row 0 of page 0. Tapping the
  currently-playing slot cancels a pending queue.

#### Shift + Tap

Switches immediately while playing -- no queue, no waiting
for the boundary. The playhead tries to land on the **same
(page, row)** position in the new pattern. If the new pattern
is shorter and that page doesn't exist, the playhead falls
back to **page 0 at the same row index**, keeping the
beat-grid alignment. The cursor stays where you had it.

While stopped, Shift + Tap behaves the same as Tap (cursor
resets to page 0 row 0).

#### Long-press

Long-press a slot to open its context menu (same shape as on
the Arp and Euclidean):

- **Overwrite from current** -- copies the currently-selected
  pattern into the long-pressed slot. The selection / view
  does not change. Useful for cloning a working pattern as a
  starting point for a variation.
- **Reset to default** -- empties the slot back to a single
  default page. If the cleared slot is the currently-selected
  one, the view updates and the cursor jumps to page 0 row 0.

Right-click on a slot also opens the menu.

#### What each pattern stores

Only the **grid** (pages + cells). The per-track output
channels, the BPM, and the **Send Clock** / **Send Transport**
toggles stay on the Tracker instance and apply to whichever
pattern is playing. So the eight patterns share routing and
tempo; they differ only in what they sequence.

#### Pattern switching from a MIDI controller

Hands-free pattern switching from a keyboard or pad controller
is opt-in via the **Pattern Ctrl Ch** wheel in the
configuration panel. Set it to **Off** (the default) and
nothing changes. Set it to a MIDI channel `1..16` and that
channel becomes reserved for pattern control: a Group of eight
**P1..P8** NoteSelect wheels appears, one per pattern slot.

Pressing the configured note for slot *N* on the control
channel behaves exactly like tapping slot *N* on screen --
queued to the next page-0 boundary while playing, immediate
while stopped. The on-screen blink during the queued window
matches a controller tap, so a player can see at a glance
whether a press already landed or is still pending.

Each P*N* row has a **Learn** button: tap it, then play the
note on the controller to capture it. The channel-reservation
means nothing else on this channel reaches the tracker -- no
recording, no pass-through, not even CCs. Pick a channel that
the rest of the routing matrix is not already using for a
track.

If a control channel and **Auto Ch.** or a per-track channel
overlap, control wins. This keeps the reserved channel
reserved.

### The Configuration Panel

Open the Tracker's row or column header in the matrix to
access its plugin-config panel:

- **Per-track channel mapping** -- eight ChannelSelect wheels,
  one per track.
- **Auto Ch.** -- recording-routing wheel.
- **Send Clock** + **BPM** -- clock-master mode.
- **Send Transport** -- forward START / STOP / CONTINUE in
  either direction.
- **Pattern Ctrl Ch** -- channel reserved for hands-free
  pattern switching from a controller. Off by default; when
  set, the **Pattern Notes** group with eight learnable P1..P8
  NoteSelects appears below.
- **Help button** -- the standard `?` HELP text.

### Saving Tracker State

The grid contents, the page count, the per-track channels, the
**Send Clock + Transport** state, and the cursor position are
all part of the plugin instance state. **Save Config** persists
them with the rest of the project; **Export Config** captures
them in a JSON snapshot (chapter 15).

Cloning a Tracker (Copy → Paste-as-new from the header menu)
makes a second Tracker instance with the same grid -- useful
for splitting a song into "A part" and "B part" Trackers that
you swap between with a controller drop button.
