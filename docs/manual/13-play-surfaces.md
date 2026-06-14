# Play Surfaces

Four plugins live on the **Play** bottom-nav tab and share the
same surface-carousel pattern: the **Arpeggiator**, the
**Euclidean**, the **Cartesian**, and the **Tracker**. They are
routable in the matrix like any other plugin
(`SURFACE_KIND = "play"`; add them from **Add → Play**) and
additionally render a fullscreen play surface designed for live
performance.

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
- **Cartesian** -- you want a René-style 2D sequencer: a held note
  is the root and a square grid (2×2…4×4) of semitone offsets is
  swept by *two* clocks -- X steps through the cells along a Path
  (rows / cols / diagonal / knight / spiral / random), Y advances
  the chord inversion. A scale-aware Fill Voicing knob stamps the
  grid (Unison → 5th → Triad → 7th → Scale) so you can play whole
  chord-arpeggios from one finger plus two knobs.
- **Tracker** -- you want a step sequencer in the classical
  music-tracker sense: 8 voices × 16 rows × up to 16 pages, with
  per-step note + velocity + CC. Live-recordable; clock-master
  capable.

All four carry an 8-slot **pattern bank** (P1..P8) at the
bottom of their play surface. Tapping a slot switches the active
pattern; on the Arpeggiator, Euclidean and Cartesian the switch is
immediate and held notes / sustain persist across the change, on
the Tracker the switch queues to the next page-0 boundary while
playing (Shift+Tap forces an immediate switch). Long-press any
slot for an **Overwrite from current / Reset to default** menu.

Switching the active pattern -- by tapping a slot, or by a
control-channel launch (chapter 13.3) -- is treated as pure
*performance*, not an edit: it moves the active-pattern pointer
but changes none of the stored slots, so it does **not** mark the
config dirty (no Routing asterisk) and does **not** trigger an
autosave (chapter 15.6). The active pattern is still written by a
deliberate **Save Config**. Editing a slot's content (recording,
Overwrite, Reset) is a real edit and dirties as usual.

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

## The Cartesian

A two-dimensional sequencer in the spirit of the Make Noise René:
instead of a linear step row, the cells sit in a square grid that
two independent clocks sweep along separate axes. It does not play
a fixed melody -- it **voices a held note**, like an arpeggiator, so
the whole figure transposes with whatever you play.

### Concept

A note held on **Play Ch** is the *root*. Every grid cell carries a
semitone **offset**, and the sequencer plays `root + offset`. So a
cell holding `+7` plays a fifth above the held note; play a C and it
sounds G, play an E and it sounds B -- the grid is a relative
voicing, not absolute notes.

Two independent clocks drive it:

- **Rate** (the step clock) -- fires the next cell along the chosen
  **Path**.
- **Inv. Rate** (the inversion clock) -- advances the inversion lap,
  re-voicing the whole grid one chord-inversion further. It is *not* a
  second spatial axis: **Rate** drives the entire spatial sweep (the
  Path, diagonals included), while **Inv. Rate** only walks the
  inversions — and does nothing while Inversion = 0. With a fast Rate
  and a slow Inv. Rate you sweep a chord that slowly climbs through its
  inversions.

### The Play Surface

The live controls fill one fullscreen panel in three rows: the **Fill
live** toggle, **Fill Voicing**, **Inversion** and its **Inv. Rate**
(the inversion clock sits right next to the setting it drives); then
**Scale**, **Root** and **Path**; then the utility row — the step
**Rate**, **Gate %**, **Accent Vel.** and **Grid** (size). The 2D grid
fills the centre, and the 8-slot pattern bank sits at the bottom. The
setup-only parameters (sync, the two channels, Ctrl Ch and the trigger
notes) live in the device-detail panel.

Each grid cell works exactly like an Arpeggiator step cell: tap the
head to cycle **off → on → accent → off**, drag the mini-wheel to
set a manual per-cell offset.

### Fill Voicing

The **Fill Voicing** wheel stamps the grid with a chord, walking up
the overtone series so the wheel sweeps from thin to rich:

| Voicing | Chord tones (relative to the root) |
|---------|------------------------------------|
| **Unison** | root only (climbs in octaves across the cells) |
| **5th** | root + fifth (power chord) |
| **Triad** | root + third + fifth |
| **7th** | root + third + fifth + seventh |
| **Scale** | the full scale, degree by degree |

The thirds and sevenths are taken from the **Scale** wheel, so a
Triad is major on a major scale and minor on a minor scale with no
extra control.

The chord tones climb across the cells (`offset = chord_tone(x + y)`),
so a 4×4 grid already reads as a ladder of inversions: row 0 is the
root position, row 1 the first inversion, and so on.

### Root: chordal vs diatonic harmony

The **Root** wheel doubles as the harmony selector — its first
position is **No root**, the rest are the twelve keys:

- **No root** (default) -- *chordal*: the *played* note is the tonic
  and the **Scale** wheel only sets the chord *quality*, which
  transposes with the note. Play C with Scale = major → C major; play
  E → E major. There is no key; every root gets the same shape. Good
  for parallel-chord planing.
- **A root C..B** -- *diatonic*: Root + Scale define a *key*. The
  played note picks a *degree* of that key and the voicing is
  harmonised in-key, so the chord *quality follows the degree*. In C
  major: play C → C major (I), play E → E **minor** (iii), play G → G
  major (V), play D → D minor (ii). The whole grid stays in the key no
  matter what you play -- one finger walks diatonic chords.

Note that diatonic ≠ Scale = chromatic. `chromatic` changes the
*interval content* of the voicing (a Triad collapses to a 0/+2/+4
cluster); a Root constrains the playing *into a key*. They sit on
different axes.

In Live the grid re-voices as you change the played note (the offsets
track the root); in Latch the stamped offsets freeze and simply
transpose with whatever you play.

### Inversion

The **Inversion** wheel is bidirectional (-4 … 0 … +4). It does not
stack octaves -- it **re-voices**: each step lifts the lowest voice
an octave (or, for negative values, drops the highest), keeping the
figure in a tight register with smooth voice-leading instead of
octave leaps. The **Inv. Rate** clock walks through the inversions:
with Inversion = +2 the grid cycles root position → 1st inversion →
2nd inversion and back, one step per Inv. Rate tick. (Inv. Rate has no
effect while Inversion = 0.)

### Fill live

A latching toggle (LED) that decides whether the voicing is generative
or frozen:

- **On** (default) -- *live*: **Fill Voicing**, **Scale**, **Root**,
  **Grid** and **Inversion** act immediately (all CC-bindable) and
  re-stamp the cell offsets, *preserving* your on/off + accent mask.
  You keep the rhythm and accents you drew and sweep only the harmony
  with one knob and one held note. The Inv. Rate clock animates the
  inversions live. This is the performance mode: a held note + two CCs
  is a full instrument.
- **Off** -- the grid **freezes exactly as it is the moment you switch
  it off** — turning it off *is* the commit, there is no separate Apply
  step. You can then hand-edit individual cell offsets freely; the
  edits persist and the inversion sweep is paused (the grid plays
  exactly as drawn). Turn **Fill live** back on to re-derive a clean
  voicing from the wheels again.

While Fill live is on, re-stamping only ever touches the **offset**
field, never on/off or accent, so sweeping voicings never disturbs
your groove.

### Two Channels

The Cartesian listens on two separate channels (both in the Setup
panel), so one keyboard can play it while another fills it:

- **Play Ch** (0 = Any) -- notes here are the played root; the most
  recently pressed note transposes the grid. Releasing all keys
  silences the surface.
- **Fill Ch** (Off / 1..16) -- a recording channel. Hold notes and
  each one writes its interval (relative to the first note of the
  gesture) into the next cell along the Path, programmed-Arp style.
  Touching the Fill Ch turns **Fill live** off (freezing the grid) so
  the recording isn't overwritten by the live fill.

### The Path

The **Path** wheel changes how the Rate clock sweeps the active grid:

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

Clock-consuming, like the Arpeggiator and Euclidean. **Sync** =
`transport` follows the upstream transport, `tempo` free-wheels off
the incoming clock, and `free` runs both axes off the internal
**BPM**. Route a clock source (Master Clock or external) into the
instance for X and Y to advance.

Screenshots needed:

- `cartesian-play.png` -- the Cartesian play surface: the Fill live /
  Fill Voicing / Inversion / Inv. Rate row, the Scale / Root / Path
  row, the Rate / Gate / Accent / Grid row, and the 2D grid with the
  playhead highlighting the swept cell. Add a `_open_cartesian` scene to
  `scripts/screenshots/run.py` so it regenerates with
  `make screenshots`.
- `cartesian-config.png` -- the device-detail Setup panel showing the
  Play Ch + Fill Ch + Ctrl Ch channels and the 8 trigger notes.

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

**Shift+Play** (hold Shift while tapping Play, or `Shift`+`Space`)
starts a **single-page loop** instead of running the whole
sequence: only the page you are viewing plays, repeating at its
end. The loop *follows the page you view* -- navigate to another
page and the loop moves there at the next wrap. This is a
composing aid for working on one page at a time. **Stop**, or a
plain **Play**, returns to normal full-sequence playback.

The configuration panel has three independent transport toggles:

- **Send Clock** -- when on, the Tracker becomes a clock
  *master*. It runs an internal 24-PPQ generator at the
  configured **BPM** and emits clock to OUT, so any downstream
  gear sees the same clock. The Tracker drives its own playhead
  from this generator, too -- no external clock source is
  needed. When this toggle is off, the Tracker listens for
  external MIDI Clock instead; with no external clock routed
  in, the playhead is silent. A **BPM** wheel (40--300, default
  120) appears in the panel only when Send Clock is on.
- **Send Trnsp.** (Send Transport) -- when on, the Tracker forwards incoming
  START / STOP / CONTINUE to OUT, *and* emits its own START /
  STOP / CONTINUE when the on-screen Play / Stop buttons fire,
  so downstream slaves bar-align with the Tracker whether the
  transport originated upstream or inside the Tracker itself.
- **Rcv Trnsp.** (Receive Transport) -- on by default. When on,
  incoming transport from a clock master or another instrument
  (a START / STOP / CONTINUE on the global clock) starts, stops
  and continues the Tracker's playhead -- the usual behaviour
  where the whole rig starts together. Turn it **off** to
  decouple the Tracker from the rig's transport: it then ignores
  foreign START / STOP / CONTINUE and is driven only by its own
  Play / Stop buttons (and the launch trigger modes, see below).
  It still follows the shared *clock* for tempo -- only the
  start/stop is decoupled -- so you can let one Tracker free-run
  while the rest of the rig stops and starts around it. The Play
  and Stop buttons always work regardless of this toggle.

Send Clock / Send Trnsp. are independent: the Tracker can
generate clock without forwarding transport (rare), forward
transport without generating clock (when an upstream source
already provides the clock), or both (the common live-rig case
where the Tracker is the master). External clock is ignored
while Send Clock is on -- the Tracker's own clock takes priority
so downstream gear never sees two competing sources.

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
routed track and advances the cursor by one row. This is pure
step entry -- one cell per note -- so the *length* of a held
key is irrelevant when stopped; durations are only captured
during live recording (below), where the clock supplies the
rows to span.

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

When the Tracker is playing, each MIDI event lands on the row
whose events are *currently sounding* -- the row under the
playhead at the instant it arrives -- not the row the cursor is
on. The cursor stays where you left it. So you can play a part
during a loop and have every note stick to the beat it was
played on. Unlike step-record there is **no chord window**: a
note held across several steps does not pull a later note onto
its row -- each note-on records exactly where the playhead was
when you pressed it. Notes that fall on the *same* step still
spread across consecutive tracks (a live-strummed chord fills
tracks the way step-record does). Routing (cursor track via
Auto Ch., or a specific matched track via the incoming channel)
works the same way as in step-record.

**Note-offs are recorded too.** When you release a key, an
explicit `Off` is written to the row under the playhead, on the
same track the note was recorded to -- so the recorded note
gets its real length instead of ringing until the next note.
Releases land per-track, so each voice of a chord ends where
you lifted that finger. A note played and released within a
single step still gets a clean ending: its `Off` lands on the
**next** step, giving the stab a one-step length. In every case
an `Off` is only written into an otherwise-empty cell, so a new
note recorded on the same track is never overwritten by an
older note's release.

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

#### Transpose

As soon as a selection covers two or more cells, the keypad's
note-half swaps its usual Note / Velocity / OCT controls for a
single **TRANSPOSE** wheel (-24..+24 semitones). Each tick on
the wheel shifts every real-pitch note inside the selection by
one semitone in that direction -- velocities, CCs, and rests
are left untouched. The wheel position reads as the cumulative
shift since this selection became active; spinning back to 0
restores the pitches the selection started with.

The wheel returns to 0 the moment the selection clears or its
bounds change, so a fresh selection always begins at zero
(notes are not snapped back -- the wheel just stops tracking
the previous selection's state). The TRANSPOSE wheel is the
multi-cell counterpart to the `+` / `-` keyboard nudge
described in *Keyboard Note Entry* below, which moves a single
focused cell.

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

A selection always takes priority: while one is active, Cut and
Copy act on the **selection**, never the page. Both also end
selection mode (the on-screen **Shift** toggle releases) and
drop the cursor on the selection's **top-left** cell, so the
next edit starts from a predictable spot. With no selection,
`Shift+Cut` / `Shift+Copy` (hold the physical Shift, or tap the
on-screen Shift without moving the cursor) target the whole
current page, and a plain Cut / Copy acts on the focused cell.
**Del** is **Cut** (copy + clear) rather than destructive delete
-- the paste buffer is updated so an accidental Del can be
undone with Paste.

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

Pages run linearly from 0 to F (up to 16 pages). There is no
separate page strip -- the current page shows up as the hex
prefix on the row labels (`20`..`2F` means page 2). Navigation:

- `PgUp` / `PgDn` move one page in either direction (wrapping
  at the ends), keeping the row index where it is.
- Walking the cursor off the top or bottom of the current page
  (`↑` on row 0, `↓` on row F) flips to the previous / next
  page and lands on the wrap-around row.
- **+ page** and **− page** buttons next to the BPM/Rate
  controls insert a fresh page after the current one or delete
  the current page. The − button disables when only one page is
  left; the + button disables at the 16-page ceiling.

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
channels, the BPM, and the **Send Clock** / **Send Trnsp.**
toggles stay on the Tracker instance and apply to whichever
pattern is playing. So the eight patterns share routing and
tempo; they differ only in what they sequence.

#### Pattern switching from a MIDI controller

Hands-free pattern switching from a keyboard or pad controller
is opt-in via the **Pt. Ctrl Ch** (Pattern Ctrl Ch) wheel in the
configuration panel. Set it to **Off** (the default) and
nothing changes. Set it to a MIDI channel `1..16` and that
channel becomes reserved for pattern control: a Group of eight
**P1..P8** NoteSelect wheels appears, one per pattern slot.

Each P*N* row has a **Learn** button: tap it, then play the
note on the controller to capture it. The channel-reservation
means nothing else on this channel reaches the tracker -- no
recording, no pass-through, not even CCs. Pick a channel that
the rest of the routing matrix is not already using for a
track.

If a control channel and **Auto Ch.** or a per-track channel
overlap, control wins. This keeps the reserved channel
reserved.

##### Trigger Mode

What a trigger note *does* is set by the **Trigger Mode** wheel,
a single per-Tracker setting (not per-slot) that appears next to
**Pt. Ctrl Ch** once a control channel is chosen. Four modes:

- **Switch** (the default) -- the historic behaviour described
  above: a press selects the pattern, queued to the next page-0
  boundary while playing and immediate while stopped. The
  on-screen blink shows a queued press still pending. Configs
  made before Trigger Mode existed load as Switch, so nothing
  changes for them.
- **One-shot** -- a press *launches* the pattern: it starts
  playing from row 0 on the next clock step, runs once through
  to its end (the End marker, or the last row of the last page),
  then stops. There is no need to press Play first -- the launch
  rides whatever clock the Tracker is following (an external
  clock, or its own when **Send Clock** is on).
- **Hold** -- the pattern launches while you hold the key and
  loops for as long as it is held; releasing the key stops it.
- **Toggle** -- a press launches the pattern; pressing the same
  key again stops it.

In the three launch modes the pattern always starts from row 0
on the **next step** at the grid's rate (1/16 by default), so a
phrase fires wherever you are in the song while staying locked to
the clock -- it does not wait for bar 1. Launching is monophonic:
pressing a new trigger replaces the one in flight. These modes
govern the MIDI control-channel triggers only; tapping a pattern
slot on screen always behaves as Switch (you cannot hold an
on-screen tap, and the slot row is the editing interface).

A launch **takes over** from normal playback: if the Tracker is
already running (from its Play button or external transport),
firing a trigger stops that and the launch becomes the sole
driver of the playhead. So in **Hold** mode the key is the gate
-- press to sound, release to silence -- regardless of whether
transport was running underneath.

A common live use: split a pad row or a low keyboard zone onto
the control channel, learn one pad per phrase, set **Hold** or
**One-shot**, and fire melodies or fills you could not play by
hand -- in sync -- while the rest of the keyboard records into
your sequencer as usual.

### The Configuration Panel

Open the Tracker's row or column header in the matrix to
access its plugin-config panel:

- **Per-track channel mapping** -- eight ChannelSelect wheels,
  one per track.
- **Auto Ch.** -- recording-routing wheel.
- **Send Clock** + **BPM** -- clock-master mode.
- **Send Trnsp.** -- forward START / STOP / CONTINUE in
  either direction.
- **Rcv Trnsp.** -- on by default; when off the Tracker ignores
  external transport and only its own Play / Stop buttons (and
  launch triggers) start it.
- **Pt. Ctrl Ch** -- channel reserved for hands-free
  pattern switching from a controller. Off by default; when
  set, the **Trigger Mode** wheel and the **Pattern Notes**
  group with eight learnable P1..P8 NoteSelects appear below.
- **Trigger Mode** -- Switch / One-shot / Hold / Toggle; how a
  control-channel trigger behaves (see "Trigger Mode" above).
  Only shown once **Pt. Ctrl Ch** is set.
- **Help button** -- the standard `?` HELP text.

### Saving Tracker State

The grid contents, the page count, the per-track channels, the
**Send Clock** / **Send Trnsp.** / **Rcv Trnsp.** toggles, and
the cursor position are
all part of the plugin instance state. **Save Config** persists
them with the rest of the project; **Export Config** captures
them in a JSON snapshot (chapter 15).

Cloning a Tracker (Copy → Paste-as-new from the header menu)
makes a second Tracker instance with the same grid -- useful
for splitting a song into "A part" and "B part" Trackers that
you swap between with a controller drop button.
