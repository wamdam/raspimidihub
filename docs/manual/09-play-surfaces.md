# Play Surfaces

Four plugins live on the **Play** bottom-nav tab: the **Arpeggiator**,
the **Euclidean**, the **Cartesian**, and the **Tracker**. All are
routable in the matrix like any other plugin (add from **Add → Play**)
and additionally render a fullscreen play surface for live
performance.

- **Arpeggiator** -- plays a held chord as a rhythmic pattern; seven
  pattern modes plus a step grid with per-step on/off, accent and
  offset.
- **Euclidean** -- algorithmic rhythms: Bjorklund pulses over N
  steps, masked by a window-wave, with a scale quantiser +
  tune-spread randomiser. Polyrhythm = two instances on one clock.
- **Cartesian** -- René-style 2D sequencer: a held root note plus a
  2×2…4×4 grid of semitone offsets swept by two clocks and stamped
  by a scale-aware Fill Voicing knob.
- **Tracker** -- classical tracker: 8 voices × 16 rows × up to 16
  pages, per-step note + velocity + CC; live-recordable,
  clock-master capable.

Shared behaviour:

**Pattern bank.** An 8-slot bank (P1..P8) at the bottom of every
surface; each slot snapshots the play-surface parameters. Tap a slot
to switch. On the Arpeggiator, Euclidean and Cartesian the switch is
immediate (it can rewrite the pattern under a pedal-held chord), held
notes / sustain persist, and edits auto-write to the active slot --
no Store action. On the Tracker the switch queues to the next page-0
boundary while playing (Shift+Tap forces it). Long-press a slot (or
right-click) for a menu: **Overwrite from current** copies the active
slot into the long-pressed one; **Reset to default** wipes it to
plugin defaults (if it was the active slot, live state reloads too).

**Slot triggering from MIDI.** A **Ctrl Ch** wheel in each setup
panel (`Off` / `1..16`; named **Pt. Ctrl Ch** on the Tracker)
reserves a channel for slot triggering: every note on it is consumed
(no melody, no pass-through) and matched against eight MIDI-Learnable
NoteSelects in the **Pattern Notes** group -- tap **Learn**, play the
note to capture. A match switches slots like a screen tap; the
Tracker adds launch modes (**Trigger Mode**, below).

**Dirty state.** Switching the active pattern -- tap or
control-channel launch (above) -- is performance, not an edit:
it changes no stored slot, marks nothing dirty (no Routing asterisk)
and triggers no autosave (chapter 11.6). **Save Config** still writes
the active pattern; content edits (recording, Overwrite, Reset) dirty
as usual.

Routing-matrix appearance, instance lifecycle and config-panel chrome
follow chapter 7; parameter tables are in **Appendix A**.

## The Arpeggiator

**Pattern** and **Rate** are wide wheels at the top; the four shapers
(**Steps / Accent Vel. / Gate % / Octaves**) sit in one row; the
**Step Pattern** editor fills the bottom. Setup-only parameters
(channel filter, sync + BPM, Ctrl Ch + trigger notes) live in the
device-detail panel's **Setup** group.

![Arpeggiator play surface: Pattern + Rate wide wheels, four shapers, Step Pattern grid.](../screenshots/arpeggiator-play.png){width=42%}

### Pattern Modes

How the held-note buffer is voiced per step:

- **up** / **down** -- next held note ascending / descending.
- **up-down** -- ping-pong; reverses at the highest / lowest note.
- **random** -- a random held note each step.
- **as-played** -- press order (C-E-G plays back C-E-G even if F is
  added later).
- **programmed** -- live step-sequencer: each keypress writes the
  next-to-fire step; presses between ticks fan into consecutive slots
  (chord-spread). Slots persist while any key or sustain is held;
  full release clears them for a fresh phrase.
- **chord** -- every held note fires each step; per-step offset,
  accent and gate apply to the whole burst; `Octaves > 1` doubles the
  chord into higher octaves.

### The Step Grid

- Tap a cell's **head** to cycle `off → on → on+accent → off`.
  On-steps play the next note from the Pattern wheel; off-steps are
  rests.
- Drag (or wheel-scroll) its **mini-wheel** for a per-step semitone
  offset (-24..+24).

`Steps` (1..32) sets the cell count; the cycle wraps after it.

### The Pattern Bank

Slots snapshot Pattern, Rate, Steps, Accent Vel., Gate, Octaves and
the step grid.

### The Setup Panel

Opens from the Arpeggiator's row or column header in the matrix:

- **Sync** -- `free` / `tempo` / `transport`. `tempo`: one step per
  clock subdivision. `transport`: advance only while external START
  is asserted (stop pauses the playhead). `free`: internal clock at
  the **BPM** wheel (40..300, shown only when Sync = free).
- **Arp Ch** -- `Any` / `1..16`; which incoming notes count as
  melody.
- **Ctrl Ch** + **Pattern Notes** -- slot triggering (chapter intro).

### CC Automation

Block CC 70..83 covers every play-surface knob, mirroring the
Euclidean so one controller drives both identically:

| CC | Parameter | CC | Parameter |
|----|-----------|----|-----------|
| 70 | Pattern   | 74 | Rate |
| 71 | Octaves   | 75 | Gate % |
| 73 | Steps     | 83 | Accent Vel. |

Discrete-enum params (Pattern, Rate) accept the same 0..127 CC,
scaled across the param's range and snapped to the nearest option.

### Input / Output / Clock

**Input.** Notes (held buffer), CC 64 (sustain -- released keys keep
arping until pedal lift), CC 70..83, Clock + Transport (Sync `tempo`
/ `transport`), the 8 learnable notes on **Ctrl Ch** (consumed).
**Output.** Notes; Aftertouch and Pitch Bend pass through.
**Clock.** External (`tempo` / `transport`) or internal **BPM**
(`free`).

![Arpeggiator device-detail panel: same play controls plus the Setup group.](../screenshots/09-plugin-arpeggiator.png){width=35%}

## The Euclidean

Holds incoming notes and plays them as an evenly-distributed
(Bjorklund) pattern over **Steps**, with the same Pattern and Rate
wheels at the top. For polyrhythm see 9.2.9.

![Euclidean play surface: five rows of shapers above the step grid; P1..P8 bank at the bottom.](../screenshots/euclidean-play.png){width=42%}

### The Three Layers

Whether a step fires is the composition of three layers:

#### Layer 1 -- Bjorklund distribution

- **Pulses** (0..32, capped by Steps) -- "on" steps per cycle.
- **Steps** (1..32) -- cycle length.
- **Rotate** (-16..+16) -- rotates the pulse positions.

`Pulses=4, Steps=16` → `X . . . X . . . X . . . X . . .`
(four-on-the-floor); `Pulses=3, Steps=8` → `X . . X . . X .`
(tresillo); `Pulses=5, Steps=8` → `X . X X . X X .` (cinquillo).

#### Layer 2 -- Window wave

A sine threshold masking which steps may fire:

- **Phase** (0..31) -- position of the wave's peak, in steps.
- **Cycles** (0.5 / 1 / 2 / 3 / 4) -- wave periods per pattern cycle.
- **Open** (0..100) -- how much of the wave is above the "open"
  threshold; 100 = transparent, 0 = gate closed.

Covers fixed start / length, density swells and chases.

#### Layer 3 -- Manual overrides

Each step-grid head cycles on tap:

- **default** -- algorithm decides: empty when algorithm + window
  agree the step is off, a subdued underlay tint when they agree it
  fires.
- **FORCE_ON** -- fully lit; plays regardless.
- **FORCE_ON + accent** -- brighter / hue-shifted.
- **FORCE_OFF** -- dim / struck-through; silent regardless.

The MiniWheel below each head is the per-step semitone offset, as on
the Arpeggiator.

### Pitch Model

Pitch comes from **held notes**; silence when none are held. The
**Pattern** wheel voices the buffer: `up` / `down` / `up-down` /
`random` / `as-played` / `chord` (every held note each step).

Output is quantised to the internal **Scale + Root** (9 scales: major
/ minor / dorian / mixolydian / pentatonic / blues / harmonic m /
whole tone / chromatic); `chromatic` passes through.

**Tune Spread + Snap** randomly transpose each step. Tune Spread
(0..100) is both the probability and the size of the jump. Snap
pre-quantises it:

- `free` -- any semitone within ±12.
- `octaves` -- ±12 / ±24 / 0.
- `5ths+oct.` -- ±5 / ±7 / ±12 / ±19 / ±24 / 0.

The quantiser runs *after* the spread, so jumps stay in scale.

### Time Model

- **Rate** -- same 15 values as the Arpeggiator (`4/1`..`1/32`),
  default `1/16`.
- **Gate %** (10..100) -- note length as % of one step; 100 = legato,
  10 = staccato.
- **Jitter %** (0..100) -- random per-step micro-timing offset,
  re-rolled each step; 100 = up to half a step.
- **Fade In** (0..16 firing steps) -- on idle → playing, the first N
  **firing** steps (not grid positions) ramp velocity 0% → 100%.
- **Fade Out** (0..16 firing steps) -- on all-keys-released (sustain
  up), N firing steps ramp 100% → 0% before silencing; a key-on
  cancels the fade at full velocity.

### Retrig

Setup-group button, default **on**; governs a fresh phrase (all keys
released → key pressed):

- **on** -- the cycle restarts from step 1 per new phrase.
- **off** -- the cycle free-wheels across rest gaps; re-triggering
  picks up where the clock would have landed, keeping the pattern
  locked to bar time.

### The Pattern Bank

Slots snapshot every play-surface param: pattern, rate, all three
rhythm layers, scale + root, spread + fade envelope, step grid.

### The Setup Panel

- **Sync** -- as on the Arpeggiator.
- **Arp Ch** -- `Any` / `1..16`; filters melody input.
- **Ctrl Ch** -- slot triggering (chapter intro).
- **Retrig** -- see above.
- **BPM** -- shown only when Sync = free.

### CC Automation

Block CC 70..88 (skipping CC 84 = GM Portamento Control):

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

Discrete-enum params (Pattern / Snap / Scale / Root) scale 0..127
across the range, as on the Arpeggiator.

### Input / Output / Clock

**Input.** Notes (held buffer), CC 64 (sustain holds the chord across
release), CC 70..83 / 85..88, 8 learnable notes on **Ctrl Ch**
(consumed), Clock + Transport.
**Output.** Notes (Bjorklund-voiced, scale-quantised); Aftertouch and
Pitch Bend pass through.
**Clock.** External (`tempo` / `transport`) or internal **BPM**
(`free`).

### Polyrhythm

A routing-matrix configuration, not a parameter: two instances on one
clock with co-prime pulse / step counts.

```
[Keyboard ch1] → [Euclidean A: pulses=5 steps=16 @ 1/16] ─┐
[Keyboard ch1] → [Euclidean B: pulses=7 steps=12 @ 1/16] ─┴→ [Synth]
[Master Clock] ─→ both
```

Each instance quantises independently; set both to `chromatic` when a
shared downstream `Scale Remapper` is wanted instead.

![Euclidean device-detail panel: Setup group with the 8 learnable trigger notes expanded.](../screenshots/30-plugin-euclidean-config.png){width=35%}

## The Cartesian

A 2D sequencer in the spirit of the Make Noise René: a square grid of
cells swept by two independent clocks. It plays no fixed melody -- it
**voices a held note**, so the whole figure transposes with what you
play.

### Concept

A note held on **Play Ch** is the *root*; each cell carries a
semitone **offset**; the sequencer plays `root + offset` -- a `+7`
cell sounds a fifth above whatever is held.

- **Rate** (step clock) -- fires the next cell along the **Path**;
  drives the entire spatial sweep, diagonals included.
- **Inv. Rate** (inversion clock) -- steps the grid through chord
  inversions (see Inversion below); not a spatial axis. Fast Rate +
  slow Inv. Rate sweeps a chord that slowly climbs its inversions.

### The Play Surface

Three control rows: **Fill live** toggle, **Fill Voicing**,
**Inversion**, **Inv. Rate**; then **Root**, **Scale**, **Path**;
then **Rate**, **Gate %**, **Accent Vel.**, **Grid** (size). The 2D
grid fills the centre, the pattern bank the bottom. Setup-only
parameters (sync, the two channels, Ctrl Ch + trigger notes) live in
the device-detail panel.

Cells work like Arpeggiator step cells: tap the head to cycle
**off → on → accent → off**, drag the mini-wheel for a manual
per-cell offset.

### Fill Voicing

Stamps the grid with a chord, thin to rich:

| Voicing | Chord tones (relative to the root) |
|---------|------------------------------------|
| **Unison** | root only (climbs in octaves across the cells) |
| **5th** | root + fifth (power chord) |
| **Triad** | root + third + fifth |
| **7th** | root + third + fifth + seventh |
| **Scale** | the full scale, degree by degree |

Thirds and sevenths follow the **Scale** wheel (a Triad is major on a
major scale, minor on a minor one). Chord tones climb across the
cells (`offset = chord_tone(x + y)`), so a 4×4 grid reads as a ladder
of inversions: row 0 root position, row 1 first inversion, etc.

### Root: chordal vs diatonic harmony

The **Root** wheel is the harmony selector -- first position
**No root**, then the twelve keys:

- **No root** (default) -- *chordal*: the *played* note is the tonic;
  **Scale** only sets the chord *quality*, which transposes with the
  note (C → C major, E → E major). No key; good for parallel-chord
  planing.
- **A root C..B** -- *diatonic*: Root + Scale define a *key*; the
  played note picks a *degree*, harmonised in-key, so quality follows
  the degree. In C major: C → C major (I), E → E **minor** (iii),
  G → G major (V), D → D minor (ii).

Diatonic ≠ Scale = chromatic: `chromatic` changes the *interval
content* (a Triad collapses to a 0/+2/+4 cluster); a Root constrains
the playing *into a key*.

With Autofill on, the grid re-voices as the played note changes; off,
the frozen offsets simply transpose.

### Inversion

Bidirectional (-4 … 0 … +4). It does not stack octaves -- it
**re-voices**: each step lifts the lowest voice an octave (negative
values drop the highest), keeping a tight register with smooth
voice-leading. **Inv. Rate** walks the inversions: at Inversion = +2
the grid cycles root → 1st → 2nd inversion and back, one step per
tick; no effect while Inversion = 0.

### Autofill

A latching toggle (LED):

- **On** (default) -- *live*: **Fill Voicing**, **Scale**, **Root**,
  **Grid** and **Inversion** act immediately (all CC-bindable) and
  re-stamp the cell offsets; Inv. Rate animates inversions live.
- **Off** -- the grid **freezes exactly as it is at switch-off**;
  turning it off *is* the commit (no Apply). Hand-edit cell offsets
  freely; edits persist and the inversion sweep pauses. Re-enable to
  re-derive a clean voicing from the wheels.

Re-stamping only ever touches the **offset** field, never on/off or
accent -- sweeping voicings never disturbs your groove.

### Two Channels

Two listen channels (Setup panel), so one keyboard plays while
another fills:

- **Play Ch** (0 = Any) -- the played root; the most recent press
  transposes the grid, releasing all keys silences the surface.
- **Fill Ch** (Off / 1..16) -- a recording channel: each held note
  writes its interval (relative to the first note of the gesture)
  into the next cell along the Path, programmed-Arp style. Touching
  the Fill Ch turns **Autofill** off so the recording isn't
  overwritten.

### The Path

How the Rate clock sweeps the grid:

| Path | Order |
|------|-------|
| **Rows →** | left-to-right, top-to-bottom |
| **Cols ↓** | top-to-bottom, left-to-right |
| **Diagonal** | along the anti-diagonals |
| **Knight** | a knight's-move tour of the cells |
| **Spiral in** | clockwise from the outer ring inward |
| **Spiral out** | from the centre outward |
| **Random** | a fresh random cell every X tick |

### Time Model

**Sync** as on the Arpeggiator: `transport` follows the upstream
transport, `tempo` free-wheels off the incoming clock, `free` runs
both axes off the internal **BPM**. Route a clock source into the
instance for X and Y to advance.

![Cartesian play surface: the Autofill / Fill Voicing / Inversion / Inv. Rate row, the Root / Scale / Path row, the Rate / Gate / Accent / Grid row, and the 2D grid.](../screenshots/cartesian-play.png){width=42%}

![Cartesian device-detail Setup panel: Play Ch + Fill Ch + Ctrl Ch channels and the trigger notes.](../screenshots/cartesian-config.png){width=35%}

## The Tracker

An 8-voice step sequencer, the richest surface of the four: a
song-section sequencer (drums + bass + stabs in one instance) or a
hands-free clock master / transport source.

![The Tracker play surface: 8 voice columns (T1..T8), 16 hex-numbered rows per page, up to 16 pages.](../screenshots/tracker.png){width=42%}

### Concept

**8 voice columns** (T1..T8) × **16 hex-numbered rows** per page
(0..F) × **up to 16 pages** chained linearly, looping to page 0 after
the last. Each cell is one event per voice per step; play moves the
playhead down the rows at the clock rate.

### The Cell Format

Four mini-fields per cell:

| Field | Width | Values |
|-------|-------|--------|
| **Note** | 3 chars | Pitch (e.g. `C-4`, `D#3`), `Off` (note off), `End` (page end), `---` (hold) |
| **Velocity** | hex | `00`..`7F` |
| **CC#** | hex | `00`..`7F`, or `.` for "no CC" |
| **CC Val** | hex | `00`..`7F`, ignored when CC# is `.` |

Note and CC are independent: a cell can fire either, both, or
neither. `---` sends no new Note On; `End` jumps to the next page
early.

### Per-Track Output Channel

Each of T1..T8 routes to its own MIDI channel (default: all channel
1), remappable in the device-detail panel; the track header reads
`T1 [Ch 3]` when remapped -- one Tracker can drive a multi-timbral
synth on eight channels, or eight separate synths.

### Transport

The header **Play / Stop** toggle (or `Space`) starts / stops
playback. Stopped, the cursor stays put; playing, the playhead
advances at the clock rate and wraps page to page.

**Shift+Play** (or `Shift`+`Space`) starts a **single-page loop**:
only the viewed page plays, repeating, and the loop *follows the page
you view* (it moves at the next wrap) -- a composing aid. **Stop** or
plain **Play** returns to full-sequence playback.

Three independent transport toggles in the configuration panel:

- **Send Clock** -- makes the Tracker a clock *master*: an internal
  24-PPQ generator at the **BPM** wheel (40--300, default 120; shown
  only when Send Clock is on) drives the playhead and downstream gear
  via OUT. External clock is ignored while on, so downstream never
  sees two competing sources. Off, the Tracker listens for external
  MIDI Clock (none routed in = silent playhead).
- **Send Trnsp.** -- forwards incoming START / STOP / CONTINUE to OUT
  *and* emits its own when the on-screen Play / Stop fire, so
  downstream slaves bar-align either way.
- **Rcv Trnsp.** -- on by default: incoming transport starts / stops
  / continues the playhead. Off, the Tracker ignores foreign
  transport (own Play / Stop and launch triggers only) but still
  follows the shared *clock* for tempo, so one Tracker can free-run
  while the rig stops and starts around it. Play and Stop always
  work.

Send Clock and Send Trnsp. are independent -- either, neither, or
both.

### Editing

The cursor is a caret on one cell, moved with the arrow keys or the
action row's on-screen Up / Down / Left / Right.

#### Routing incoming MIDI to tracks

Two modes run side by side, keyed on MIDI channel:

- **Auto Ch.** -- one designated channel (config-card wheel, `Off` /
  1..16, default `Off`). Notes on it land on the **cursor track**; a
  held chord spreads rightwards across consecutive tracks up to T8.
- **Direct routing** -- every other channel is matched against the
  per-track output channels (**Track Channels**). A note on channel
  *N* lands on the lowest-numbered track configured for *N*; tracks
  sharing *N* fill chord notes in T1 → T8 order (one note per track,
  extras drop) -- change channel on the keyboard to pick a track.

A channel matching neither is silently dropped -- nothing recorded,
nothing forwarded to OUT.

#### Step-record (stopped)

While stopped, a note from a routed MIDI keyboard (or the on-screen
keyboard, or QWERTY entry) writes into the **cursor row** of the
routed track and advances the cursor one row. Key hold length is
irrelevant; durations are captured only during live recording.

The cursor advances once per chord, however many notes or channels it
spans: a chord stays open while **any** key is held; the next chord
starts when all keys are released and a new note arrives. A missing
note-off self-recovers after about two seconds.

CCs touched while stopped write into the CC field at the cursor row;
they never auto-advance the cursor and never spread (only the first
matching track receives them).

#### Live recording (playing)

While playing, each event lands on the row under the playhead at the
instant it arrives -- not the cursor row (the cursor stays put) -- so
every note sticks to its beat. There is **no chord window**: each
note-on records exactly where the playhead was; notes on the *same*
step still spread across consecutive tracks. Routing works as in
step-record.

**Note-offs are recorded too.** A release writes an explicit `Off`
under the playhead on the note's own track, so recorded notes keep
their real length. A note released within one step gets its `Off` on
the **next** step (a one-step stab). An `Off` is only written into an
otherwise-empty cell, never overwriting a newer note.

CCs touched during play land on the currently-sounding row.

#### Selection

Hold `Shift` while moving the cursor to extend a selection rectangle.
On the on-screen action row, tap **Shift** once to toggle selection
mode on (it stays engaged across cursor moves), again to release --
a toggle, not press-and-hold.

While engaged, the cursor wraps within the current page at the row-0
/ row-F boundary instead of flipping pages (anchor and cursor must
share a page). A selection can span multiple voices and rows on the
visible page; the action row shows the cell count.

#### Transpose

Once a selection covers two or more cells, the keypad's note-half
swaps its Note / Velocity / OCT controls for a **TRANSPOSE** wheel
(-24..+24 semitones). Each tick shifts every real-pitch note in the
selection one semitone; velocities, CCs and rests are untouched. The
wheel reads the cumulative shift since the selection became active;
spinning back to 0 restores the starting pitches. It resets to 0 when
the selection clears or its bounds change (notes are not snapped
back). TRANSPOSE is the multi-cell counterpart of the `+` / `-`
single-cell nudge below.

#### Cut / Copy / Paste

The action row reads **Shift / Cut / Copy / Paste**. With a selection
active:

- **Cut** -- copy the selection into the paste buffer and clear it
  from the grid (the buffer persists until the next Cut or Copy).
- **Copy** -- copy into the buffer; grid unchanged.
- **Paste** -- paste at the cursor. A half-compatibility check keeps
  a Note-only paste from overwriting destination CCs, and vice versa.

A selection takes priority: Cut / Copy act on the **selection**,
never the page, end selection mode (on-screen **Shift** releases) and
drop the cursor on the selection's **top-left** cell. With no
selection, `Shift+Cut` / `Shift+Copy` (hold physical Shift, or tap
on-screen Shift without moving the cursor) target the whole current
page; plain Cut / Copy acts on the focused cell. **Del** is **Cut**
(copy + clear), not destructive -- an accidental Del undoes with
**Paste**.

### Keyboard Note Entry

Standard tracker mapping on the physical keyboard:

| Key | Note |
|-----|------|
| `q` `2` `w` `3` `e` | C C# D D# E |
| `r` `5` `t` `6` `y` `7` `u` | F F# G G# A A# B |

The mapping follows the *physical* key position, so **QWERTY and
QWERTZ both work unchanged** (a German `z` in the QWERTY `y` position
writes an A).

`Space` toggles Play / Stop regardless of cursor focus.

The octave of a typed note follows the **OCT** wheel in the keypad's
note-half. `+` / `-` nudge it one octave, clamped to 0..9; `=` / `_`
also work so US layouts need no Shift. If the focused cell already
holds a real pitch, `+` / `-` also moves that cell's note --
transpose one recorded cell without retyping.

### Pages

Pages run linearly 0 to F; the current page is the hex prefix on the
row labels (`20`..`2F` = page 2). Navigation:

- `PgUp` / `PgDn` move one page either way (wrapping at the ends),
  keeping the row index.
- Walking the cursor off the top or bottom of a page (`↑` on row 0,
  `↓` on row F) flips to the adjacent page at the wrap-around row.
- **+ page** / **− page** buttons next to the BPM/Rate controls
  insert a page after the current one or delete the current page;
  − disables at one page, + at the 16-page ceiling.

`End` in a note cell ends the page early -- variable-length patterns.

### Patterns

Each Tracker stores **8 numbered patterns**; a pattern is a full grid
(pages + cells). The selected pattern is on screen and is what
playback runs against. Slot states:

- **Outline** -- empty (one default page, no events).
- **Dim fill** -- has content, idle.
- **Accent fill** -- selected.
- **Coral fill** -- selected *and* the playhead is running.
- **Blinking** -- a queued switch, pending the next pattern boundary.

#### Tap

- **Stopped** -- loads the slot immediately; cursor jumps to page 0,
  row 0.
- **Playing** -- *queues* the switch (slot blinks); when the playhead
  wraps back to page 0 row 0 the swap happens and the new pattern
  plays from the top. Tapping the currently-playing slot cancels a
  pending queue.

#### Shift + Tap

Switches immediately while playing. The playhead tries to land on the
**same (page, row)** in the new pattern, falling back to **page 0 at
the same row index** if that page doesn't exist -- beat-grid
alignment is kept. The cursor stays put. Stopped, behaves like Tap.

#### Long-press

The standard bank menu (chapter intro). Tracker specifics:
**Overwrite from current** changes neither selection nor view;
**Reset to default** empties the slot to a single default page (if it
was the selected one, the view updates and the cursor jumps to page 0
row 0).

#### What each pattern stores

Only the **grid** (pages + cells). Per-track channels, BPM and the
**Send Clock** / **Send Trnsp.** toggles stay on the instance: the
eight patterns share routing and tempo.

#### Pattern switching from a MIDI controller

Opt-in via the **Pt. Ctrl Ch** (Pattern Ctrl Ch) wheel in the
configuration panel -- the Tracker's variant of the shared **Ctrl
Ch** mechanism (chapter intro). `Off` (default) changes nothing; a
channel `1..16` shows the eight **P1..P8** NoteSelect wheels with
**Learn** buttons.

The reservation is total: nothing else on this channel reaches the
Tracker -- no recording, no pass-through, not even CCs. Pick a
channel no track uses; if the control channel overlaps **Auto Ch.**
or a per-track channel, control wins.

##### Trigger Mode

The **Trigger Mode** wheel (a per-Tracker setting, shown next to
**Pt. Ctrl Ch** once a channel is chosen) sets what a trigger note
does:

- **Switch** (default) -- selects the pattern exactly like an
  on-screen Tap (queued while playing, immediate while stopped).
  Configs from before Trigger Mode existed load as Switch.
- **One-shot** -- *launches* the pattern: starts from row 0 on the
  next clock step, runs once to its end (the `End` marker or the last
  row of the last page), then stops. No Play press needed -- the
  launch rides whatever clock the Tracker follows (external, or its
  own when **Send Clock** is on).
- **Hold** -- launches and loops while the key is held; release
  stops.
- **Toggle** -- a press launches; the same key stops.

The three launch modes start from row 0 on the **next step** at the
grid's rate
(1/16 by default) -- clock-locked, not waiting for bar 1 -- and are
monophonic: a new trigger replaces the one in flight. They govern
MIDI triggers only; an on-screen tap always behaves as Switch. A
launch **takes over** from normal playback: a trigger stops a running
Play / external transport and drives the playhead alone -- in
**Hold** mode the key is the gate regardless of transport underneath.

Common live use: learn one pad per phrase on the control channel, set
**Hold** or **One-shot**, and fire in-sync fills while the rest of
the keyboard records as usual.

### The Configuration Panel

Open the Tracker's row or column header in the matrix:

- **Per-track channel mapping** -- eight ChannelSelect wheels.
- **Auto Ch.** -- recording-routing wheel.
- **Send Clock** + **BPM** -- clock-master mode.
- **Send Trnsp.** -- transport forwarding.
- **Rcv Trnsp.** -- external-transport coupling; on by default.
- **Pt. Ctrl Ch** -- pattern-control channel; when set, the
  **Trigger Mode** wheel and the **Pattern Notes** group (eight
  learnable P1..P8 NoteSelects) appear below.
- **Trigger Mode** -- Switch / One-shot / Hold / Toggle.
- **Help button** -- the standard `?` HELP text.

### Saving Tracker State

Grid contents, page count, per-track channels, the **Send Clock** /
**Send Trnsp.** / **Rcv Trnsp.** toggles and the cursor position are
instance state: **Save Config** persists them, **Export Config**
captures them in a JSON snapshot (chapter 11).

Cloning a Tracker (Copy → Paste-as-new from the header menu) makes a
second instance with the same grid -- an "A part" / "B part" pair for
a controller drop button.
