# RaspiMIDIHub Roadmap

Living doc for upcoming work — discuss + adjust before any implementation.
Items listed are **proposals**, not commitments.

**Markers used in this doc:**
- `**TODO:**` — items that need a design discussion or
  implementation pass. `grep -n "TODO:" docs/ROADMAP.md` lists every
  open item in the doc.
- `✓ Done (YYYY-MM-DD)` on a phase header — that phase has
  shipped; commit hashes are in the body.

---

## 1. Rhythm Sequencer plugin ("Drum Groover")

### Goal

Drop-in drum patterns for live jams. User picks a genre + groove template,
hears the pattern on their hardware, and can swap/randomize individual
drum tracks without rebuilding the whole beat.

### User stories
- "I want instant Techno with a 4-on-the-floor kick, rumbling sub, and
  open/closed hat interplay — pick template, play."
- "Good kick, but I'm bored of the hat — hit Randomize on the hat track
  only, keep everything else."
- "I want to re-map the snare from GM note 38 to my drum machine's pad 3 at
  channel 10, note 62 — once, persist with the preset."

### Scope

- **Up to 8 instrument tracks** per instance (typical drum set: kick,
  snare, clap, closed hat, open hat, tom, ride, perc).
- **Steps**: 16, 32, or 64 selectable; default 16.
- **Per-track state**:
  - `name` (display only — also the key for the per-instrument
    pattern library)
  - `channel` (1-16), `note` (0-127), `velocity` (default, 1-127)
  - `mute` toggle
  - `pattern`: list of step cells (`.` / `X` / `A`)
  - `randomize` button — picks a different named pattern from the
    current genre's library for this instrument (see below)
- **Per-pattern state**:
  - `genre` (Radio): Techno, House, Tech-House, Minimal, Trance, Acid,
    DnB, Jungle, Breakbeat, Dubstep, Trap, Hip-Hop, Lo-Fi, Boom-Bap,
    Reggaeton, Afrobeats, Amapiano, Funk, Disco, Garage, Footwork.
  - `preset` (Radio): named presets for the current genre (≥5 each).
  - `swing` (Wheel, 0-75%).
  - `rate` (Radio): same set as the arp (1/4 … 1/32 + triplets).
  - `sync_mode`: Free / Tempo / Transport (identical to Arpeggiator).
- **Sync**: MIDI clock (24 PPQ) via existing ClockBus, same sync modes
  as the Arpeggiator.
- **Output**: note on + matching note off (short gate ~30ms, configurable).
  Uses `send_note_on/off` — no aftertouch or CC yet.
- **Randomize**: replaces the pattern of a single instrument with a
  different pattern picked at random from the genre's library for
  that instrument. Doesn't mutate the existing pattern — swaps it for
  a different hand-authored variant. So "randomize the kick in Techno"
  still produces a Techno-flavoured kick because every file in
  `templates/techno/kick/` was authored to fit the genre. User-invoked
  only.

### Template format

Two file kinds, both human-readable text under
`plugins/rhythm_sequencer/templates/`:

- **Pattern files** — single 16-step row, one per file. Tiny.
- **Preset files** — recipe combining one pattern per instrument
  with channel/note/velocity bindings. The thing the
  GenreTemplatePicker shows.

Tree:

```
plugins/rhythm_sequencer/templates/
  techno/
    kick/
      4-on-the-floor.grv
      rumble.grv
      broken.grv
    snare/
      backbeat.grv
      half-time.grv
      …
    clap/   …
    ch/     …
    oh/     …
    perc/   …
    presets/
      classic.grv
      rumbling.grv
      broken.grv
      …
  house/
    …
```

**Pattern file** (e.g. `techno/kick/4-on-the-floor.grv`):

```
# 4-on-the-floor
X . . .  X . . .  X . . .  X . . .
```

- One line of 16 cells (or 32, 64) — must match the preset's `steps`.
- `.` = off, `X` = on at track default velocity, `A` = on with
  accent (uses preset's `accent_vel`).
- Whitespace between cells is ignored; two-space gaps every 4 cells
  by convention (countable beats).
- Optional `# Display name` first comment line — defaults to the
  filename slug if absent.

**Preset file** (e.g. `techno/presets/classic.grv`):

```
# Techno · Classic
bpm: 128
steps: 16
accent_vel: 30

# instrument  ch  note  vel  pattern
Kick          10  36    120  4-on-the-floor
Sub           10  35     90  off-beat
Clap          10  39    110  classic
CH            10  42     80  classic-off-beat
OH            10  46     90  open-on-eighth
Perc          10  40     70  sparse
```

- `key: value` lines for header (`bpm`, `steps`, `accent_vel`,
  `swing`).
- Then one line per instrument row: `instrument` is the directory
  name under the genre (lowercased — file system convention),
  `pattern` is the basename of the .grv file in
  `<genre>/<instrument>/`. Channel/note/vel are the runtime defaults
  for that instrument when this preset loads.
- Comments start with `#` at line start.

Filenames map to display names by reversing slug rules
(`4-on-the-floor.grv` → "4 on the floor"); the optional `#` comment
inside the file overrides that.

### Library coverage requirement

Each genre ships **at least 3 pattern variants per instrument** so
randomize always has something to swap to. Hard floor; nothing
prevents shipping more (Techno kicks could easily justify 8+).

If an instrument folder has only 1 pattern file, the Randomize
button on that row is disabled with a tooltip "no other variants
in this genre" — predictable, not a no-op surprise.

### Pattern UI

The on-screen DrumGrid shows the same three cell states as the
file format:

| state | file char | UI cell |
|-------|-----------|---------|
| off   | `.` | empty |
| on    | `X` | filled (track colour) |
| accent| `A` | filled + brighter highlight |

Tap a cell to cycle off → on → accent → off. Long-press to clear a
whole row. No per-step velocity numbers in the UI — three states is
enough; per-track default velocity covers the rest.

### UI (new param types we'll need)

- **`DrumGrid` param** — 8 rows × N steps cell grid with:
  - per-row label + (ch, note) mini-editor + default-velocity wheel
  - per-cell tap to cycle off → on → accent → off
  - per-row long-press to clear the row
  - per-row **Randomize** button (greyed out if the current genre's
    instrument library has only 1 variant)
  - per-row Mute toggle
- **`GenreTemplatePicker` param** — two-level Radio: genre → preset.
  Selecting a preset rewrites the whole `DrumGrid` (every row's
  pattern + ch/note/vel).

Both live under `static/components/` per the previous UI controls refactor.

### Persistence

`serialize_instances` already dumps `_param_values`. The full
`DrumGrid` state (tracks + patterns) is a single nested list inside
`_param_values["grid"]`. The currently-selected `genre` and
`preset` names are also persisted — useful for the Randomize button
to know which instrument library to pick from on next load.

### Open questions

1. **Shuffle/swing implementation**: delay every odd 16th by X ticks, or
   only odd 8ths?
2. **Fill / break**: should "break each 16 steps" be a preset, or a
   mode flag on top of any preset? Simpler: ship both shapes as
   separate presets.
3. **Gate length**: fixed ~30ms, or per-track configurable? Default
   fixed, promote to param later if needed.
4. **Pattern length mismatch**: what if a pattern file has 16 cells
   but the preset's `steps` is 32? Loop the pattern, error, or pad
   with zeros? Simplest: error during load, ship matched lengths.

---

## 2. Tracker Sequencer plugin ("Tracker") ✓ Done (2026-05-11)

Shipped. The plugin grew per-track output channels, manual
Play/Stop + Space-bar toggle, live recording during playback (notes
land on the playhead row instead of the cursor row), Cut/Copy/Paste
with sub-cell selection, keyboard note entry (QWERTY+QWERTZ via
event.code), audible note preview, and forward-clock toggle on top
of the spec below. Screenshots: `docs/screenshots/tracker.png` +
`docs/screenshots/28-plugin-tracker-config.png`.

### Goal

8-voice step sequencer on a single MIDI channel with always-on
record, full-cell editing of note + velocity + CC pair per voice,
and 1..16 pages chained linearly with looping back to page 0.
Lives in the new "Play" panel alongside the Controllers.

### User stories
- "I want to sketch an 8-voice arrangement on phone: tap a cell, set
  the note + vel + CC live with the always-visible keypad, walk the
  cursor row by row."
- "Record what I'm playing on my external keyboard into the
  sequencer in real time without losing the pass-through to my
  synth."
- "Build a song from up to 16 pages of patterns, each with its own
  length set by an `End` marker, and just let it loop back to page 0
  when the last page finishes."

### Surface — "Play" panel

Lives in a new bottom-nav entry, **Play**, that takes the slot the
removed Presets feature used to occupy. Plugins with
`SURFACE_KIND = "play"` appear there; existing controllers
(`SURFACE_KIND = "controller"`) keep their own panel and ◂surface▸
carousel. Tracker UI inherits the same fullscreen + carousel
navigation.

Underlying refactor: the `pages/controller.js` filter on the type
prefix `controller_*` is replaced with a server-side `kind` field
on the instance dict that comes from `SURFACE_KIND` on the plugin
class.

### Voices, channel, output

- **8 voices**, all on the same MIDI channel (default 1, remappable
  in the config panel). One plugin instance, one channel out — to
  multi-channel, instance multiple Trackers and route via the matrix.
- Each voice cell per row holds: `Note` (or `---` / `Off` / `End`),
  `Velocity` (hex 00..7F or `--`), `CC#` (hex 00..7F or `.`),
  `CC Val` (hex 00..7F or `--`). Note and CC events fire
  independently per step.
- Note format: 3 chars strict — `<letter><-|#><single-digit-octave>`.
  Wheel covers `C..B` × octaves 0..9, so MIDI notes 12..127 are
  representable; sub-audio bottom octave (0..11) intentionally
  unreachable.
- Output uses the ALSA queue with scheduled note-offs (same path the
  Arpeggiator uses) for ~zero jitter.

### Pages

- Up to **16 pages per instance**, hex-numbered 0..F, linearly chained,
  looping back to page 0 after the last page.
- `[Add page]` inserts a blank page after the current; `[Del page]`
  removes the current. No song-mode chain pointers — order = array
  index.
- Each page has 1..16 rows. Length is implicit, terminated by `End`
  on voice 1's Note column (or row 16 if no `End` is set). `End`
  is exclusive to voice 1; voices 2..8 don't get it on their wheel.
- `[Copy page]` / `[Paste page]` use a session-local clipboard.

### Recording, playback, transport

- **Always recording** (no toggle in MVP). External notes + CCs on
  IN are written to the row currently under the edit cursor and
  passed through to OUT (so the user hears their playing once; no
  double-trigger). Single note → focused (row, track). Chord of K
  notes → focused track and the next K-1 tracks; notes past track 8
  are dropped silently. CCs always go to the focused track only.
- **Note preview while editing**: turning the Note wheel fires the
  picked note out the OUT port so the user hears what they're
  scrolling to. Recording (external MIDI capture) does not
  re-trigger.
- Playback walks pages 0 → N-1 → loops to 0, stepping rows at the
  selected `Rate` (same set as Arp: 1/4 down to 1/32 + triplets).
- Same Free / Tempo / Transport sync modes as the Arp.
- Playhead `▶` shown only on the page currently being viewed; no
  auto-jump when the playing page changes (optional `[Follow]`
  button for an explicit one-shot snap is post-MVP).

### UI

New `TrackerGrid` component under `static/components/`:

- Header row 1: `Rate`, `Page ◂N▸ N/M`, `[Add page]`, `[Del page]`,
  `[Copy page]`, `[Paste page]`.
- Header row 2: `Show: [2] [4] [8]` — how many tracks visible at a
  time. Cursor's track is always kept in view; ←/→ scrolls the
  viewport when the cursor crosses an edge. Font scales to fit the
  device width within the chosen viewport.
- Track-header row above the steps shows `T1..Tn` for the visible
  window, with the cursor's track highlighted (same colour as the
  focused cell) so the user always knows the absolute track number.
- 16 step rows, hex-numbered 0..F, monospace, full-cell colour
  highlight on the focused cell.

Always-visible bottom data-entry keypad (never moves, layout never
shifts):

- **Note wheel**: 15 positions —
  `--- → Off → End → C → C# → D → D# → E → F → F# → G → G# → A → A# → B`.
  Pitch only.
- **Octave knob**: 0..9, default 3. Sticky across cells.
- **Velocity vertical fader**: hex 00..7F.
- **CC# wheel**: `.`, `00`, …, `7F`. `.` = no CC event this step.
- **CC Val vertical fader**: hex 00..7F.
- **Cursor**: inverted-T cluster (↑ on top, ← ↓ → on bottom).
  ↑/↓ = row prev/next. ←/→ = voice prev/next. Sub-cell focus
  (Note/Vel/CC#/CC Val) is direct-touch only — the keypad's four
  controls always reflect the focused voice cell.
- **Del shortcut** under the Note wheel: clears Note + Vel of the
  focused cell (sets them to `---` / `--`). Octave knob unaffected.
- **Del shortcut** under the CC# wheel: clears CC# + CC Val
  (`.` / `--`).
- Wheel commit-on-release (no per-detent writes); no autoadvance on
  entry.
- Cells are tappable to focus.

One-line **Help row** sits above the keypad and never changes height:

- Idle (≥ 2 s since last control change): static
  `Help: Note | Velocity | CC# | CC Val`.
- While a control is being changed: shows the control's name + live
  value, e.g. `Help: CC Val 2A (42)` (decimal in parens for hex
  columns; pitch and decimal vel show their natural form).
- Reverts to the static line after 2 s of inactivity.

### Persistence

```python
{
  "channel": 1,
  "rate": "1/16",
  "sync_mode": "transport",
  "show_tracks": 4,
  "pages": [
    {"rows": [
      {"voices": [
        {"note": "C-3", "vel": 90, "cc_num": 1, "cc_val": 127},
        ...8 voices
      ]},
      ...up to 16 rows
    ]},
    ...up to 16 pages
  ]
}
```

`---`/`Off`/`End` and `.`/`--` are encoded as their string sentinels.
Numerics are stored as decimal ints even though the UI displays them
in hex. Total worst-case JSON ~ a few KB — well within the boot-
partition save path.

### Architecture

```python
# raspimidihub/tracker_base.py (new)
class TrackerBase(PluginBase):
    SURFACE_KIND = "play"
    TRACK_COUNT = 8       # subclass override hook for phase 2
    MAX_PAGES = 16
    MAX_ROWS_PER_PAGE = 16

# plugins/tracker/__init__.py
class Tracker(TrackerBase):
    NAME = "Tracker"
    DESCRIPTION = "8-voice step sequencer, single channel, paged"
    TRACK_COUNT = 8
```

`SURFACE_KIND` is a new class attribute on `PluginBase`. Default
`None` (matrix-only plugin). `ControllerBase` sets `"controller"`;
`TrackerBase` sets `"play"`. The `/plugins/instances` endpoint
serves `kind` per instance so the frontend can filter without magic
prefix matching.

### Phase 2 (deferred — architecture supports each)

- **Euclidean generator** — applies to one track of one page; bakes
  pulse pattern into the existing `voices` cells so the user can
  generate-then-edit. Lives behind a button on the keypad (won't
  enlarge the always-visible footprint).
- **Pattern file format + loader** — `.trkr` files; the load path
  must run off the asyncio loop so live playback isn't disrupted.
- **Larger voice counts / track-kind extensions** — `TRACK_COUNT`
  bump, plus a `TRACK_KINDS` class attribute when CC-only or drum-
  cell tracks are introduced.
- **Record-mode toggle** (overdub / replace / off) — currently
  always-on.
- **Auto-advance on entry** — currently off.
- **"Follow play" view-jump** — optional one-shot snap to playing
  page.

---

## 3. Matrix Undo / Redo

> **Deferred to the very end of the roadmap.** Section number kept
> stable so existing cross-references don't break. Implement only
> after every other section (sequencers included) has shipped — the
> Command-stack approach below will need to wrap whatever final shape
> the API ends up in, so we want the API to be settled first.

### Goal

Ctrl+Z (and a visible Undo/Redo pair on the matrix toolbar) that
reverses the last action, with history up to ~100 steps. Each entry
has a human label so the toast on Undo/Redo tells you **what** just
got reversed ("Undid: Added mapping CC1 → CC10 on `Keyboard → Synth`").

### Scope — what's undoable

- Connect / disconnect a pair in the matrix
- Add / remove / edit a mapping
- Edit a connection filter
- Create / delete a plugin instance
- Rename a device / plugin
- Paste (undoes the whole paste atomically)

### Scope — what's NOT undoable (MVP)

- Plugin param changes (the user fiddles wheels constantly — infinite
  history noise). Plugins already expose Edit/Revert at the instance
  level.
- Live MIDI routing state changes from hotplug.
- Config Save / Load / Import / Export — these are the explicit escape
  hatch.

### Where the stack lives

**Client side.** Every user-initiated action that goes through the API
wraps into a `Command` object:

```js
class Command {
  label: string;          // "Added mapping CC1 → CC10 on Keyboard → Synth"
  do():   Promise<void>;  // idempotent on a clean state
  undo(): Promise<void>;  // restores the state before do()
}
```

Stack = `[ undoStack: Command[], redoStack: Command[] ]`. Cap at 100;
drop oldest. Redo clears on any non-undo action.

Persistence: **not persisted** — restart = empty history. Matches
typical DAW behaviour and avoids needing a disk log.

Server-side state is authoritative. Commands call the existing REST
endpoints in both `do()` and `undo()`. SSE broadcasts reconcile any
out-of-band changes; if an undo's target (e.g. the connection) no
longer exists, the command is dropped from history with a toast.

### UI

- Two buttons on the matrix toolbar: `↶ Undo` / `↷ Redo`, disabled when
  their stack is empty.
- Hover title shows the next label.
- Toast on action: "Undid: …" or "Redid: …".
- Keyboard: Ctrl+Z (Cmd+Z on macOS), Ctrl+Shift+Z for redo.

### Open questions

1. **Coalescing.** Rapid sequential actions of the same kind (e.g.
   three connect-toggles in 1 second) — coalesce into one undo step?
   MVP: no, keep each atomic.
2. **Stacking Paste.** Paste of a connection performs multiple server
   calls (filter + N mappings). Treat as one atomic command (single
   undo step).
3. **Redo after external change.** If SSE tells us a connection
   disappeared (another client deleted it), do we drop just the
   affected redo entries or the whole redo stack? MVP: whole redo
   stack on any external change.

---

## 4. Routing graph smoothness ✓ Partly done (2026-04-30)

> **The presets feature was removed entirely 2026-05-09.** The
> original section title was "Preset switch smoothness"; renamed
> because the surviving consumers of the graph-swap path are
> manual "Load Config" + hot-plug today (and any future graph-swap
> mechanism — Preset Trigger is now stale, see Pending design).
>
> What shipped (2026-04-30):
> - `apply_edge_diff(target_edges)` — diff + apply in
>   `midi_engine.py`; used by `api_load_config` and friends.
> - Per-edge note refcount (`MidiEngine._active_notes`) — note-on
>   increments, note-off decrements, edge removal flushes the right
>   note-offs.
>
> What's still pending: the **soft vs hard panic split** + panic
> state machine below. The Panic button today still does the full
> hard CC 123 + CC 120 + plugin `panic()` blast on every tap.

### Goal

Loading a config (or any future feature that swaps the routing
graph) used to rip down every subscription and rebuild. That caused:

1. **Hung notes** on destinations whose only inbound edge was removed
   (their note-offs never arrive).
2. **A ~tens-of-milliseconds gap** in MIDI forwarding that desyncs
   downstream sequencers, glitches delay/reverb tails, and pauses
   clock/transport mid-bar.

Both make preset changes during a live take feel surgical and unsafe.
This pass makes them feel like nothing happened, except where the
graph actually changed.

### User stories
- "I press a Preset Trigger note mid-bar to swap to the chorus
  routing — the verse's reverb tail keeps ringing through the
  switch and the drum machine doesn't lose a clock pulse."
- "Whatever notes were sounding when I switched get a clean note-off,
  not a stuck drone."
- "If I just want emergency-stop, the existing Panic button still
  shuts everything up immediately."

### Approach: incremental edge-diff instead of teardown

Replace the current `disconnect_all()` + `_apply_saved_config()` pair
with a diff-and-apply algorithm:

1. Compute current edge set: `(src_stable, src_port, dst_stable,
   dst_port, filter_dict, mapping_list)` for every active subscription.
2. Compute target edge set from the new preset.
3. **Removed edges** = current − target.
4. **Added edges** = target − current.
5. **Changed edges** (same endpoints, different filter/mappings) =
   intersection where filter or mappings differ.
6. **Untouched edges** = the rest. Leave alone.

For each *removed* edge, in this order:
   a. Look up notes currently in flight on this edge (engine tracks
      `(channel, note)` reference counts per edge — see below).
   b. Send a `note_off` for each tracked active note.
   c. Send `CC 123` (All Notes Off) on each channel that had any
      activity on this edge in the last second.
   d. Unsubscribe.

For each *added* edge: subscribe + install filter/mappings.

For each *changed* edge: update filter/mappings in-place; if the
change requires switching between direct ALSA subscription and
userspace forwarding, do an unsubscribe/resubscribe in that
sub-step only.

For *untouched* edges: do nothing. Crucially, this means clock,
transport, delay/reverb feeds, and any unrelated routing keep flowing
without interruption.

### Engine plumbing — per-edge note tracking

A small refcount table inside `MidiEngine`:

```python
_active_notes: dict[edge_id, dict[(channel, note), int]]
```

Incremented on note-on (when forwarding through the edge),
decremented on note-off, evicted when reaching zero. Cheap — only
note-on / note-off events touch it; no overhead for CCs / clock.

Resolves a current bug independently: if a sender disappears
mid-note (USB unplug, plugin delete) the destination today is left
with a stuck note. With the table the engine can flush every edge
that disappears.

### Soft vs hard panic

The current Panic button does CC 123 + CC 120 + plugin `panic()` on
every destination. That's correct for the "rescue me from a stuck
drone" case but it cuts delay/reverb tails too. Split:

- **Soft panic** (1st tap on the Panic button — default)
  - For each edge: emit `note_off` for tracked active notes.
  - `CC 123` (All Notes Off) on each used channel.
  - Plugins still get `panic()` so internal state (Hold, Arp) clears.
  - **Does not send `CC 120`** (All Sound Off) — delay / reverb tails
    keep ringing.
- **Hard panic** (2nd tap while the panic state is `soft-panicked`)
  - Soft panic + `CC 120` on every channel of every destination.
  - For when the rig is genuinely stuck and you don't care about
    tails.

### Panic state machine (Elektron-style)

The button is a 3-state machine driven by taps and Transport Start:

```
        idle  ── tap ──▶  soft-panicked  ── tap ──▶  hard-panicked
         ▲                      │                        │
         │ Transport Start      │ Transport Start        │
         └──────────────────────┴────────────────────────┘
                                                         │ tap
                                                         ▼
                                                   (back to idle —
                                                    one hard is enough)
```

Rules:
- `idle` → tap → emits **soft panic**, state becomes `soft-panicked`.
- `soft-panicked` → tap → emits **hard panic**, state becomes
  `hard-panicked`.
- `hard-panicked` → tap → emits soft panic again, state becomes
  `soft-panicked` (so the user can ramp-up again).
- **Transport Start** (incoming MIDI Start) at any state →
  `idle`. Matches Elektron behaviour: pressing Play "rearms" Stop.

No timeout — state persists across long pauses. Only Transport Start
resets it.

### UI feedback for the panic button

- `idle`: standard red button labelled `Panic`.
- `soft-panicked`: pulsing red outline + helper text under it,
  "Press again for full Sound Off". Makes the second press feel
  intentional.
- `hard-panicked`: brief solid red flash, then back to standard
  appearance after ~600 ms.

### Where this plugs in

- `MidiEngine.apply_edge_diff(target_edges)` — the new core operation.
- `MidiEngine.panic(hard=False)` — replaces the current `panic()`,
  gains the `hard` flag.
- `api.api_load_config` and the (future) Preset Trigger plugin call
  `apply_edge_diff` instead of disconnecting first.
- `api.api_panic` POST body gains `{"hard": bool}` (default False).
  The state machine itself lives client-side — the API just emits
  whichever flavour the client requests.

### Testing

- Synthetic edge-diff tests over hand-crafted before/after edge sets,
  covering: removed-only, added-only, both, changed-filter,
  changed-mappings, untouched.
- Refcount tests: note-on increments, note-off decrements, edge
  removal flushes the right note-offs.
- An end-to-end Pi test that loads a preset while a synthesised note
  is sounding on a soon-to-be-removed edge, asserts the destination
  receives the note-off, and asserts the destinations of unchanged
  edges receive no extra messages.

### Open questions

1. **Delay/reverb tail responsibility**. Soft panic relies on the
   downstream FX device honouring CC 123 (note-off-style behaviour)
   and not interpreting it as CC 120. Most synths do the right
   thing; document the exception list as we encounter it.
2. **Preset Trigger plugin interaction**. With smooth presets,
   panic-before-load becomes unnecessary in normal cases. The
   Preset Trigger plugin can default to "no panic, smooth diff" and
   leave hard panic as a manual user action.

---

## 5. Drawable LFO (`CC Curve LFO`)

### Goal

A second LFO plugin whose waveform is a user-drawn 128-point curve
instead of a preset shape. Same timing / output controls as `cc_lfo`,
just with the existing `CurveEditor` param driving the shape.

### User stories
- "I want a custom LFO shape — a slow attack with a sharp drop, or
  three little humps then a long tail — that I can sketch with my
  finger and have it loop forever."
- "I want to drop a starting shape (sine / saw / linear / exp) into
  the editor and tweak from there."
- "After scribbling, I want to **smooth** the curve with one tap; tap
  again to smooth more."

### Plugin shape

Near-clone of `cc_lfo`. Same timing knobs (`sync`, `rate`, `freq`),
output target (`cc_num`, `out_ch`), amplitude (`depth`, `center`),
and clock-bus subscription. The only swap: instead of choosing a
mathematical wave, the user draws.

| Param | Type | Notes |
|-------|------|-------|
| `wave` | `CurveEditor(wrap=True, shapes=[...])` | 128-point curve, looping |
| `sync`, `rate`, `freq`, `cc_num`, `out_ch`, `depth`, `center` | as in `cc_lfo` | unchanged |

At each emit step, sample the curve at index `int(phase × 128) % 128`
and map through `depth` / `center` like the existing LFO. Phase
advances per 1/16 tick (synced) or per free-runner step.

### CurveEditor extensions (shared with `velocity_curve`)

The drawable canvas grows a few things any current or future drawable
benefits from. Implemented once on the `CurveEditor` param.

1. **`wrap: bool`** flag (default `False`) on the dataclass. Drawable
   LFO sets `wrap=True`; the smoothing kernel and the canvas's
   "left of x=0" / "right of x=127" preview both wrap accordingly.
   `velocity_curve` keeps the default — endpoints are clamped, so the
   "0 → 0, 127 → 127" reference line stays meaningful.

2. **`shapes: list[str]`** field. Each consumer declares its starting
   shapes. Replaces the current preset pills (Linear/S-Curve/Exp/Log)
   with a single Shape pulldown. Default lists per consumer:
   - `velocity_curve`: `["Linear", "S-Curve", "Exp", "Log"]`
   - `cc_curve_lfo`: `["Sine", "Saw", "Triangle", "Square", "Linear", "Exp Up", "Exp Down"]`

3. **Smooth button**, in the same row as the Shape pulldown. Each tap
   applies one pass of 3-point Gaussian smoothing
   (`new[i] = 0.25·left + 0.5·this + 0.25·right`) using the wrap flag
   for edge handling. Repeated taps converge toward the mean —
   user-throttled by simply tapping more or less.

UI row layout:

```
[ Shape: Sine ▼ ]   [ Smooth ]
```

Picking a shape from the pulldown overwrites the curve with that
shape. Smooth is non-destructive in the sense that the user can
always reset by re-picking a shape.

### Persistence

`_param_values["wave"]` already holds a 128-int list (existing
StepEditor / CurveEditor convention). No schema change.

### Open questions

1. **Number-of-passes control on Smooth.** Single button vs stepped
   `[Smooth ×N]` wheel. Default to single button — taps are cheap.
2. **Shape rendering on the pulldown options** — show a tiny preview
   thumbnail next to each shape name? Nice-to-have; not blocker.

---

## Shared concerns

- **New param types.** Both plugins need UI components that don't exist
  yet (`DrumGrid`, `GenreTemplatePicker`, `TrackerGrid`). These land in
  `plugin-controls.js` and `renderParam` / `INLINE_TYPES` wiring in
  the same file, plus their Python dataclasses in `plugin_api.py`.
- **Latency.** Both plugins run inside a plugin thread that's woken by
  clock ticks via the existing pipe/queue mechanism. 24 PPQ means each
  tick is ~20ms at 128 BPM — well within the current path's budget.
- **Testing.**
  - Rhythm Sequencer: parametrized tests over every shipped pattern
    and preset file (lex/parse, pattern-length matches preset
    `steps`, channels 1–16, notes 0–127, vel 1–127). Coverage:
    every genre has ≥3 patterns per used instrument so Randomize
    has something to do; snapshot a seeded randomize result.
  - Tracker: recorded-note placement (quantize / overdub / replace),
    playback emits note-on then note-off within gate window, tie
    extends the previous note.
- **Panic**: both plugins implement `panic()` to release any currently
  sounding notes (already required by v2.0.5).

---

## Phased rollout

Features ship independently — these are proposed orderings, not
dependencies.

**Sequencer track**
1. Rhythm Sequencer MVP — plugin + `DrumGrid` + `GenreTemplatePicker`,
   5 genres (Techno, House, DnB, Hip-Hop, Trap) × ≥5 presets each ×
   ≥3 patterns per instrument per genre.
2. Rhythm Sequencer genre expansion — full 21 genres, same coverage
   floor.
3. ✓ **Tracker MVP** (2026-05-11) — plugin + `TrackerGrid`, steps,
   play, record-while-playing, clear. Shipped with more than the
   original MVP: per-track output channels, Cut/Copy/Paste with
   sub-cell selection, keyboard typing, audible note preview,
   forward-clock toggle, Play/Stop button + Space toggle.
4. Tracker polish — copy/paste bars ✓, paginator ✓ (page-prefix
   row labels + Add/Del/Copy/Paste in header), transpose
   (pending), live pass-through toggle (pending; current behaviour
   is always pass-through during recording).

**Workflow track** (independent of the sequencer track, can slot in
first if preferred)
1. Matrix Context Menu — Edit / Copy / Paste / Remove scaffolding and
   the popover itself.
2. Clipboard for connections — filter + mappings stack.
3. Clipboard for plugins — paste-as-new + paste-over-instance.
4. Undo / Redo — client-side `Command` stack, toolbar buttons,
   keyboard shortcuts, labelled toasts.

**Surface track** (new; depends on the CC observatory)
1. CC observatory in the engine — track last value per
   `(client, port, ch, cc)`, expose via SSE.
2. `LayoutGrid` + `PluginXYPad` UI param types.
3. Controller plugin MVP — Knob / Fader / Toggle / XY pad cells, OUT
   port emit, IN port for MIDI Learn + bidirectional sync, drop pad
   with long-press capture and short-press fire (no autodrop yet).
4. Controller fullscreen mode + top-nav entry, last-viewed
   localStorage persistence.
5. Autodrop — bar-quantized fire scheduling.
6. Preview mode — ghost indicators on cells.

**Engine track** (new; can slot in any time)
1. ✓ Per-edge note refcount table (`MidiEngine._active_notes`).
2. ✓ Edge-diff `apply_edge_diff(target_edges)` replacing
   teardown-and-rebuild in `api_load_config`.
3. Soft vs hard panic split (long-press = hard) — still pending.

**Modulator track** (new)
1. CurveEditor extensions — `wrap` flag, `shapes` pulldown
   replacement of the preset pills, Smooth button. Shared with
   `velocity_curve`.
2. Drawable LFO plugin (`CC Curve LFO`) — uses the extended
   CurveEditor.
3. `cc_lfo` per-cycle gate pattern (still TBD).
4. Clock Divider plugin — needs the `"tick"` entry in
   `DIVISION_TICKS` and the new `on_transport_continue` plugin
   callback.

---

## Recommended implementation order

This is the suggested phasing — independent of the looser "tracks"
above, which describe theme groupings. Each phase ends in a release.

### Phase 7 — Modulator (≈ 0.5–1 sprint)

Creative, niche, no other dependencies.

1. **CurveEditor extensions**: `wrap` flag, `shapes` pulldown
   replacing preset pills, Smooth button. `velocity_curve` benefits
   for free.
2. **Drawable LFO** (`CC Curve LFO`, §5).

### Phase 8 — Sequencers (≈ 3 sprints)

The biggest pieces but the lowest live-performance urgency. Most
users will use Arp + Hold for sequencing while these mature.

1. **Rhythm Sequencer MVP** (§1). 5 genres (Techno, House, DnB,
   Hip-Hop, Trap), ≥5 presets per genre, ≥3 pattern variants per
   instrument per genre. Patterns + presets ship as `.grv` text
   files under `plugins/rhythm_sequencer/templates/`.
2. ✓ **Tracker MVP** (§2) — shipped 2026-05-11.
3. **Generalize step grid**. Pull common code out of `DrumGrid` /
   `TrackerGrid` into a reusable component. Worth revisiting once
   Rhythm Sequencer is in flight — the actual shared surface area
   between drum grid (boolean per cell × N tracks) and tracker
   (rich voice cell × N tracks) is narrower than it first looked.
4. **CC Sequencer** (pending design — finalise spec just before
   this step). The Tracker already covers per-step CC writes via
   the cc-num/cc-val columns, so a separate CC Sequencer may now
   only be worthwhile if the use case wants live CC recording
   into a denser per-step grid that isn't paired with notes.
5. **Rhythm Sequencer genre expansion**. Round out to 21 genres.
6. **Tracker polish** — transpose + live-monitor toggle remain.
   Copy/paste bars and paginator already shipped with the MVP.

### Phase 9 — Undo / Redo (≈ 0.5–1 sprint)

Last on purpose: the Command-stack abstraction (§3) wraps the REST
API surface, so we want every other feature's endpoints to be
finalised before we commit to wrapping them.

1. Client-side `Command` class + dual-stack history (cap 100).
2. Wrap every existing mutating call site (matrix toggle, mapping
   add/remove/edit, plugin add/remove, rename, paste).
3. Toolbar Undo/Redo buttons + Ctrl+Z / Ctrl+Shift+Z bindings.
4. Labelled toasts ("Undid: …").
5. SSE reconciliation: drop redo stack on any external change.

### Risk callouts

- **Phase 8 (Sequencers)** has the highest sunk-time risk —
  templates and genre profiles are content work. Time-box at 5×5
  if interest fades.

---

## Pending design — sketched, not yet specified

These have been discussed at idea-level but need another design pass
before implementation.

- **TODO: midi.guide instrument library** — turn "what does CC 17 do
  on a JX-08" from a manual lookup into a one-click pick. Surfaced
  2026-04-27 — user wants to "choose his instrument and select CCs by
  name / function" instead of typing numbers.

  **Source.** https://midi.guide — maintained by Pencil Research as
  https://github.com/pencilresearch/midi (314 stars, last updated
  2026-04-25, actively maintained). 110 manufacturers, 376 devices.

  **Licence (verified 2026-04-27).** **CC-BY-SA 4.0**. Repo's GitHub
  metadata confirms `"licenseInfo.key": "cc-by-sa-4.0"`. Site footer
  says the same. README adds the standard "portions referring to
  specific devices may be owned by manufacturers" carve-out — a
  factual-data disclaimer, not an additional restriction.

  **What CC-BY-SA 4.0 means for us:**
  - We may ship the unmodified CSVs in our deb. Required: an
    attribution string visible to the user, e.g. *"MIDI mappings ©
    MIDI Guide community, used under CC-BY-SA 4.0"* with a link to
    the upstream repo.
  - **Share-alike applies to derivative works of THE DATA**, not to
    raspimidihub's code. Mere aggregation (shipping the CSVs in the
    same .deb as our GPL/MIT/whatever Python) does not infect the
    code's licence — that's settled CC-BY-SA practice.
  - If we transform the data (e.g. CSV → indexed JSON for fast
    pickers), the **transformed file is itself a derivative work**
    and must be made available under CC-BY-SA 4.0. Easiest path:
    publish the transform script + the generated bundle in our
    public repo, with a clear `LICENSE.midiguide` next to it.
  - User-authored extensions (their custom CC names for unmapped
    parameters) are NOT derivative of midi.guide and stay under
    raspimidihub's licence.

  **Data shape (already nice for us).** One CSV per device at
  `<Vendor>/<Device>.csv`, e.g. `Elektron/Digitone II.csv`. Columns:
  `manufacturer, device, section, parameter_name,
  parameter_description, cc_msb, cc_lsb, cc_min_value, cc_max_value,
  cc_default_value, nrpn_msb, nrpn_lsb, nrpn_min/max/default,
  orientation, notes, usage`. The `section` column groups parameters
  (Track / Trig / Synth / Filter / FX / …) — gives us free
  categorisation in the picker UI. **Verified the user's gear**:
  Elektron Digitone II is in the library (Trig / Synth: Generic /
  Filter / Amp pages, fully populated CC + NRPN).

  **Data model sketch.** Two layers:
  1. **Library** (read-only, ships with the app under
     `/usr/share/raspimidihub/midiguide/`): the upstream CSVs
     verbatim plus a generated `index.json` mapping
     `"<vendor>/<device>"` → row counts + section list, for fast
     picker rendering without parsing every CSV.
  2. **Per-device assignment** (user state, in `config.data`): each
     device (or each connection's destination) carries
     `instrument_profile: "Elektron/Digitone II"`. Multiple devices
     may share a profile — only the assignment is per-device, not
     the data.

  **UX sketch.**
  - **Routing tab → device-detail panel**: a new "Instrument" row
    with a picker. Empty by default. Tapping opens a searchable list
    grouped by vendor; instant search by typing model name. Clearing
    removes the assignment.
  - **Controller cell config**: when a binding's destination has an
    instrument profile assigned, the **CC field becomes a combo box**
    — type-ahead by parameter_name (`"Cutoff"`, `"Resonance"`) OR by
    number; both resolve to the same numeric CC. Section labels
    (`Filter`, `Amp`, `FX`) appear as group headers in the dropdown.
    Cell label pre-fills with `parameter_name` when picked from the
    library, but the user's typed override always wins.
  - **Tooltip on the CC number input**: if there's a profile, hover
    shows `"CC 40 — Page 1 Parameter A (Digitone II / Synth: Generic)"`
    so existing numeric bindings self-annotate without changing data.
  - **No profile assigned**: pickers degrade to plain numeric inputs
    — no regression for users who don't care about the library.
  - **User overrides**: a "+ Custom CC" entry in the picker lets the
    user add a name for a CC the library doesn't know (stored in
    `config.data.user_cc_names[device_id][cc] = "name"`). Future
    cell pickers see both library + user names. These overrides are
    NOT derivative of midi.guide — stay under raspimidihub's licence.
  - **Attribution surface**: a small footer in the instrument picker
    *"Mappings: MIDI Guide community, CC-BY-SA 4.0"* linked to the
    upstream repo. About / Settings page also lists it.

  **Shipping form.** Snapshot at deb-build time rather than live
  fetch — the Pi is often offline (AP mode), and upstream churns
  slowly. Build step:
  ```
  scripts/refresh-midiguide.sh    # git clone --depth=1 upstream into data/midiguide/
                                  # generate data/midiguide/index.json
  ```
  Then `Makefile` deb step copies `data/midiguide/` →
  `/usr/share/raspimidihub/midiguide/` plus a `LICENSE.midiguide`
  (the upstream LICENSE file verbatim). The `data/midiguide/`
  directory IS committed in our repo — the share-alike clause means
  if we distribute it (in the deb + GitHub releases), we must also
  distribute the data publicly, which committing it satisfies.
  Settings card could show *"Library: 376 devices, snapshot from
  2026-04-25 — refresh?"* with a manual refresh that requires
  client-mode WiFi (ties in with Phase 5.5 Transient WiFi).

  **Automap from ALSA device name (verified).** midi.guide's CSVs
  carry no USB VID/PID or alias columns — just `manufacturer` +
  `device` strings, mirrored in the path `<Vendor>/<Device>.csv`.
  The good news: ALSA's `default_name` (the original USB product
  string, before any user rename) usually matches that shape
  directly. Verified on the test Pi:

  | ALSA default_name        | match           | path                                |
  | ------------------------ | --------------- | ----------------------------------- |
  | `Elektron Digitone II`   | exact           | `Elektron/Digitone II.csv`          |
  | `S-1`                    | device-only     | `Roland/S-1.csv`                    |
  | `LCXL3 1`                | none (intended) | (controller — not a CC destination) |
  | `Impact GX49`            | none (intended) | (controller)                        |
  | `U6MIDI Pro`             | none (intended) | (USB MIDI interface)                |

  **Algorithm:**
  1. Build a sorted-longest-first list of all vendor dir names in
     the library (one-time, at startup, from `index.json`).
  2. For each newly-seen ALSA device, run on its `default_name`
     (NOT `name` — `name` may be the user's custom rename):
     - **Vendor-prefix match**: if name starts with a known vendor
       V (case-insensitive, longest match wins so "Modal
       Electronics" beats "Modal"), candidate is
       `<V>/<rest of name>.csv`. Match if file exists.
     - **Device-only match**: name has no recognised vendor prefix.
       Look up the bare name in a `device → [vendors...]` index;
       single hit auto-applies, multiple hits become a "Pick the
       right one" prompt in the device-detail panel.
     - **No match**: silent — picker stays empty, user can pick
       manually. Don't be noisy; controllers / interfaces
       legitimately have no profile.
  3. Auto-applied profiles are still recorded in
     `config.data.devices[stable_id].instrument_profile` so the
     user can override or clear them.

  **VID/PID upgrade path (deferred).** A separate `usb.ids`-based
  lookup would be more reliable than name parsing for edge cases
  (renamed firmware, generic USB-MIDI bridges). Not worth the
  complexity for v1 — name-based automap covers the common case
  and a manual picker covers the rest.

  **NRPN + sysex coverage** is rich in midi.guide and would be
  useful for §5 (CC Curve LFO destinations) and a future SysEx
  sender plugin, but out of scope for v1 — start with CC only and
  use the same data set for NRPN later.

  **Good-citizen contribution loop.** When the user adds a custom CC
  name for an instrument that IS in the library (filling a gap),
  show a "📤 Contribute to MIDI Guide" button that copies the CSV
  row to clipboard and links to the upstream's "send a CSV by email"
  form (`midi@midi.guide`) or the GitHub edit URL. Two-way street.

- **TODO: `cc_lfo` per-cycle gate pattern** — `StepEditor`-style 1–32
  step pattern that mutes/un-mutes whole LFO cycles for ducking-style
  effects (e.g. `0111` = first cycle off, next three on). Behaviour
  during an off step (silent / hold-last / configurable rest value)
  TBD.
- **TODO: CC Sequencer** — step-based plugin emitting up to 4
  `(channel, cc, value)` per step, with arm-and-record from the CC
  observatory. Step grid UI shared with the Tracker. Note: the
  shipped Tracker already covers per-step CC writes (cc-num /
  cc-val columns, per-track channel routing, live recording of
  CCs). The remaining differentiator for a separate plugin would
  be a denser CC-only grid + multiple CC streams per step without
  the note-side overhead.
- **TODO: CC Pickup / Relative plugin** — single virtual instrument
  with `mode = pickup | relative`, re-introducing the classic synth
  pickup/scale modes. Depends on the Phase-4 destination-keyed CC
  cache prereq above. Use case: user is editing a synth from the
  web-UI Controller (the Controller plugin, shipped), then wants to grab a hardware controller
  and continue twisting *the same parameter* without value jumps.

  **Topology** (single IN, single OUT): `Physical Ctrl → Pickup IN`,
  `Pickup OUT → Synth`. The on-screen Controller (Mixer 8 / FX 6 / Performance 16 / XY 4) keeps its own
  parallel wire to the synth. When the user moves a UI knob, the
  engine routes the CC to the synth, the destination-keyed cache
  records "Synth received (ch, cc) = N", and Pickup's reference
  reads from there. No matrix wire between Virtual Controller and
  Pickup is needed. Plugin help text must document this — the
  routing is the non-obvious bit.

  **Per-(ch, cc) state**: `current` (initial reference, seeded from
  destination-keyed cache on first touch) + `engaged` flag (Pickup
  mode only).

  **Modes:**
    - **Pickup**: incoming CC suppressed until controller raw value
      crosses `current`. Once crossed, engage and forward 1:1 until
      an external write to the destination resets the reference.
    - **Relative** (a.k.a. scale): two-segment linear scaling hinged
      at the touch-point. At first touch, raw `r0` ≡ `current`; raw
      above `r0` maps linearly to `[current..127]`, raw below `r0`
      maps to `[0..current]`. So with `current=100, r0=20`, raw
      20..127 → 100..127 and raw 0..20 → 0..100. Reference resets
      whenever the destination-keyed cache shows another source
      moved the value.

  **First-touch behaviour**: when the very first CC for a given
  `(ch, cc)` arrives, query `engine.last_cc_to(my_destination, ch,
  cc)` once and seed `current` from it. Do *not* pre-fetch at
  instantiation. Do *not* "first-touch = no-transform" — that would
  let the controller snap the synth to its raw value on first
  touch and defeat the whole point of pickup.

  **Scope**: wildcard — any CC arriving on IN is transformed. No
  per-(ch, cc) whitelist.

  **UI**: no engaged/armed indicator on the plugin itself. The on-screen
  Virtual Controller already shows live values, which gives the
  user the visual feedback they need.

  **Still open**: how the plugin discovers its destination
  `(client, port)` — iterate the plugin's OUT-port matrix wires at
  first-touch time and pick the unique destination; fall back to
  "no reference, suppress until external write" when ambiguous
  (multiple destinations) or disconnected.
- **TODO (obsolete?): Preset Trigger** plugin — used to be
  `(channel, note) → preset_name` calling the matrix preset-load
  API on note-on. **The Presets feature was removed entirely
  2026-05-09** (page, API, persistence), so the original premise
  is gone. If a graph-swap-on-MIDI-note trigger is still wanted,
  the design needs a replacement target — e.g. swapping between
  saved snapshots of `config.json` or some other persisted form.
  Park until the need re-emerges.
- ✓ **SysEx Sender** plugin — Done 2026-05-01. Shipped as a
  parameter-less plugin with a custom file-input UI in the
  device-detail panel. Browser POSTs raw bytes to
  `POST /api/plugins/instances/<id>/sysex`; the host streams them
  out the OUT port in 256-byte SYSEX events with 5 ms gaps. No disk
  persistence, no params, no recall — pick the file again to resend.
  Hex-string paste deferred (no demand yet); throttling baked in
  rather than exposed (defaults work for DX7-class hardware).
- **TODO: Per-version changelog in the Settings update card** — the
  Settings → "All versions" list (driven by the existing update-check
  /  `UpgradeCard`) already enumerates available `raspimidihub`
  releases; this would expand each row with the matching body from
  the top-level `CHANGELOG.md` so users see "what changed" inline
  instead of jumping to GitHub. Two delivery options, not yet
  decided: (a) ship the rendered changelog inside the deb so the UI
  reads it locally with no internet — offline-friendly but only
  covers up to the version the deb was built from; (b) fetch from
  GitHub Release notes through the existing update-check path —
  always current but needs connectivity. Open: Markdown-or-plain
  rendering, and whether per-version sections are folded
  (expand-on-click) or shown as one big scrollable list.
- **TODO: per-device clock-master selector** — when multiple external
  devices send MIDI Clock at once they all feed the global ClockBus
  and tempo perception breaks. Add a UI toggle on each device's
  detail panel ("this device drives the system clock") that gates
  whether its Clock events feed the bus. Plugins already opt in via
  `feeds_clock_bus`; the same shape should extend to hardware. Decide
  whether multiple-clock-masters is allowed (probably not — first
  active wins, others ignored) and how the choice persists across
  hotplug.

- **TODO: MIDI path latency probe + Settings stats card** — current
  Settings page shows four aggregate latency metrics (`loop_lag`,
  `midi_in_sse_out`, `midi_in_midi_out`, `control_in_midi_out`), all
  running-max snapshots over a 1 s window. None of them tell you the
  round-trip time of a *specific* chain like Impact → VelEQ → Hold →
  Arp → Digitone → S-1 — direct kernel-routed cells contribute zero
  to `midi_in_midi_out` because the filter engine never sees them.
  Design: a new `runtime/probe.py` `MidiProbe` helper owning a
  dedicated ALSA seq client with `probe-out` + `probe-watch` ports.
  A run subscribes `probe-out` to the same downstream subscribers as
  the user-chosen source port, subscribes `probe-watch` to the same
  upstream feeders as the destination port, sends a uniquely-tagged
  event (sysex with a 4-byte nonce, or a CC119 hi/lo pair) from
  `probe-out`, and records the time delta on `probe-watch`. Works
  uniformly across kernel-direct, filtered, and multi-plugin chains
  because the watcher sees the event the instant any actual upstream
  of the destination would. Add `POST /api/probe/run` (synchronous,
  ≤200 ms timeout, returns `{status, latency_ms, hops_seen}`) and a
  history ring buffer surfaced via `GET /api/probe/history`. UI: a
  "MIDI Path Latency" card in Settings below the existing aggregate
  stats — two device pickers (From / To), a Probe button, last
  result inline, table of last 10 probes. Reuse the existing
  `snd_seq_query_subscribe_*` ctypes bindings (already in
  `alsa_seq.py:302-308`); same `time.monotonic()` clock as the
  other latency probes so results are directly comparable. Verify
  on (a) two plugins wired direct (≤1 ms expected), (b) same wired
  through a filter (~1-3 ms userspace add), (c) the user's
  Impact → S-1 chain (multi-hop through plugins). Also useful for
  reproducing the boot-warmup pattern — probe immediately after
  service restart and watch results decrease over the first ~2 min.
  Full design notes in `~/.claude/plans/tranquil-enchanting-sonnet.md`.

## Dropped

- **USB Network gadget** (now dropped). Pi 3 routes USB through a
  LAN9514 hub that doesn't expose OTG / peripheral mode, so there's
  no way to make the Pi appear as a USB-Ethernet device on the
  current target hardware. Pi 4 / 5 / Zero would support it, but
  not the deploy target. Spec preserved in git history if we ever
  switch hardware.

- **Cell preview while a drop is scheduled** (formerly Phase 5.2).
  The premise was that with a single drop pad the user couldn't tell
  what was about to happen, so every cell needed a ghost arc / ghost
  thumb / ghost dot showing its scheduled target. The four-button row
  shipped in Phase 5.1 — with per-button names, per-button mode
  badges, per-button rings, and now per-button fade indicators —
  already answers that question at the *button* level: which of A/B/
  C/D is firing, with what mode, and how long until it fires. The
  cell-level preview would re-encode information the user can already
  read off the buttons, while painting ghost marks across every knob/
  fader/XY pad on the surface every time a drop is queued. Net: more
  visual noise, no real win. Dropped 2026-04-29.

## Not planned right now (but noted for later)

- Multi-pattern chains / song mode.
- MIDI file import/export of patterns.
- Per-track effects (delay, stutter) inside the rhythm sequencer — do
  that via the matrix by chaining the existing `MIDI Delay` plugin.
- Tracker: per-step CC automation column.
- Live-coded patterns (e.g. Tidal-style).
