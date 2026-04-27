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

Both live under `static/components/` per §11.

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

## 2. Tracker Sequencer plugin ("Tracker")

### Goal

Step-by-step melodic/polyphonic sequencer with record-as-you-play and
a tracker-style grid view. Up to 4 bars of 16ths by default, extensible
to 16 bars (256 steps).

### User stories
- "I want a 4-bar bassline: arm record, play it in, step through and
  fix the off-beats."
- "I recorded a one-bar riff, now overdub a counterpoint on the same
  track without erasing what's there."
- "I want to play 256-step evolving lines during a live set, stepped by
  the clock."

### Scope

- **Steps**: 16 … 256, selectable (Wheel). Default 64 (4 bars × 16ths).
- **Step rate**: same rate Radio as Arp/Rhythm (1/4 down to 1/32 + T).
- **Per step** (MVP — single column, polyphonic):
  - `notes`: list of `{note, velocity}` (0…n notes per step; typical 0 or 1)
  - `tie` flag (don't retrigger, let previous ring)
- **Transport**: Free / Tempo / Transport sync, same as Arp.
- **Record**:
  - Toggle `Record` (Button). While on, incoming notes land at the
    currently-playing step position.
  - `Overdub` toggle — when on, recorded notes are **added** to whatever
    is at that step; when off, they **replace** the step's contents.
  - `Quantize` toggle — on by default: round incoming-note timing to
    the nearest step. Off: write to the step that's active at the
    moment the note arrives (effectively quantize to step-boundary too
    since playback is stepped — keep the toggle for future sub-step
    resolution).
  - Each drawn note gets a note-off at step end unless `tie` is set on
    the next step.
- **Playback**: standard stepped playback, `gate %` param controls note
  length per step (same semantics as Arp).
- **Edit mode** (not recording):
  - Tap a cell to toggle on/off using the last-pressed note.
  - Scroll / paginate in 16-step pages.
- **Controls**: Clear, Copy bar, Paste bar, Transpose ±1 / ±12.
- **Output**: `send_note_on/off`.

### UI (new param type needed)

- **`TrackerGrid` param** — paginated step grid showing one row of
  cells; each cell shows note name + velocity. Tap to edit. Playback
  cursor highlights the active step.
- Fits the same plugin-config panel, but is tall (one row) — so the
  paginator ("bar 1/4" buttons) sits above.

Page-based so 256 steps don't swamp mobile screens: **16 steps per page**,
bars 1…16. Keyboard/MIDI-driven record means most users never scroll.

### Persistence

- `steps` (int), `rate` (str), `sync_mode` (str), `gate` (int),
  `quantize` (bool), `overdub` (bool)
- `data`: list of step dicts `[{ "notes": [{"n":60,"v":100}], "tie": false }, ...]`

At 256 steps × typical ~1 note/step, the JSON is small — no concern for
the boot-partition save path.

### Open questions

1. **Polyphony cap per step**: hard limit (e.g. 4) or unbounded? Hard
   limit keeps the UI cell size predictable.
2. **Per-step CC column**: useful for filter sweeps / velocity curves.
   MVP = no. Promote to v2 if asked.
3. **Chains / song mode**: link multiple Tracker instances? Out of
   scope for MVP — user can wire two Trackers in series through the
   matrix if they want A/B patterns.
4. **Live-play input while recording**: pass through input to the
   output (monitor) so the user hears themselves, or only write to
   buffer? Default pass-through, with a "local off" toggle.

---

## 3. Matrix Context Menu + Copy / Paste

### Goal

Replace the current "long-press a connection → jump straight into the
filter panel" shortcut with a small popover that offers **Edit**,
**Copy**, **Paste**. Same menu for plugin (instrument) headers with
item-type-appropriate entries. Clipboard carries all the settings so
you can move a filter + mapping stack between connections, or clone a
configured plugin into a new instance.

### User stories
- "I set up three CC→CC mappings on `Keyboard → Arp` and now I want
  the same stack on `Keyboard → Hold`. Long-press the original, Copy;
  long-press the other cell, Paste."
- "I got the Arpeggiator exactly how I want it. Right-click the Arp
  row header, Copy; press the Add Plugin button, Paste — a new Arp
  appears with all params identical."
- "I want to tweak the second mapping on `Keyboard → Synth` — Edit
  does what long-press does today."

### Menu triggers

- Mobile: **long-press** a matrix cell (connection) or row/column header
  (device / plugin) → popover at touch point. Long-press on empty cells
  shows only an "Add connection" item.
- Desktop: **right-click** same targets. Escape / outside-tap closes.

### Menu items

| Target | Items |
|--------|-------|
| Connection cell (active) | Edit · Copy · Paste (if compat) · Remove |
| Connection cell (empty)  | Paste (if compat) · Add connection |
| Plugin row/column header | Edit · Copy · Paste-as-new · Delete |
| Hardware row/column header | Rename · (no copy — hardware is physical) |
| **Mapping row** (in FilterPanel) | **Edit · Copy · Remove** |

**Edit** on a connection cell is today's long-press behaviour (opens
the filter/mapping panel). **Edit** on a plugin header opens the
plugin config panel (same as tap).

For **mapping rows** specifically:
- **Single tap** opens the inline mapping Edit form (replaces the
  current "Edit" button — a single tap is the obvious interaction
  for "I want to edit this thing").
- **Long tap** opens the popover menu (Edit · Copy · Remove). Edit
  is duplicated for muscle-memory consistency with other rows.
- Paste is **not** in the row's menu. Instead, when the clipboard
  holds a `kind: "mapping"` payload, a `[ + Paste Mapping ]` button
  appears next to the existing `[ + Add Mapping ]` button at the
  bottom of the mapping list. Paste **appends a new mapping** as-is
  if it fits (e.g. pasted to a different instrument where the dst CC
  is free) and **only auto-bumps when there's a real conflict** —
  scanning forward through the destination field's range until a
  free slot is found (see Clipboard shape below). Avoids the
  ambiguous "does paste replace this row or insert?" question that
  Paste-on-row would raise.

The current inline **Edit** and **Delete** buttons on each mapping
row are **removed**. Edit is single-tap; Delete becomes Remove in
the long-tap menu.

### Clipboard shape

One slot, type-tagged. Keeps the UX simple — Paste is enabled only
when the target can accept the clipboard's type.

```js
clipboard = {
  kind: "connection",   // or "plugin"
  payload: { /* type-specific */ }
}
```

- **kind: "connection"** — `payload = { filter: {...}|null, mappings: [...] }`.
  Paste target: any connection cell (existing or empty). Empty target
  first creates the connection via the normal route, then applies the
  filter/mappings.
- **kind: "plugin"** — `payload = { type: "arpeggiator", params: {...} }`.
  Paste target: the "+ Add Plugin" button (create new with these
  params) **or** another plugin row of the same type (replace its
  params). Name is NOT copied — the new instance gets an auto-name so
  two clones don't collide.
- **kind: "mapping"** — `payload = <full mapping dict>`. Paste target:
  the same connection's mapping list, **or any other connection's
  mapping list**. The mapping is pasted as-is when it doesn't conflict
  (e.g. pasted onto a different instrument where the same dst CC is
  free). When the duplicate-check rejects it, the paste retries with
  the relevant destination field bumped by +1, then +2, …, up to the
  field's range, until a free slot is found:
  - **CC→CC**: bump `dst_cc_num` (search 0..127, clamped)
  - **Note→CC / Note→CC-toggle**: bump `dst_cc` (search 0..127)
  - **Channel Map**: bump `dst_channel` (search 0..15, modulo 16)
  If every value collides (the user has saturated the entire field
  range with mappings — vanishingly rare in practice), the paste
  fails with a toast asking the user to adjust manually.

Clipboard lives in client state (Preact). Shared across devices via the
existing SSE bus — **out of scope for MVP**; single-browser clipboard only.

### API surface

No new server routes for MVP: the client reads the source
filter/mappings via `GET /api/mappings/:conn_id` + the connection's
filter payload (already returned), then on Paste calls the existing
`PUT /api/filters/:conn_id` + `POST /api/mappings/:conn_id` sequence.

Plugin clipboard uses `POST /api/plugins/instances` to create a clone,
then `PATCH /api/plugins/instances/:id` to set params — all existing
endpoints.

### Open questions

1. **Paste replaces vs merges.** Replace wins for simplicity (mirrors
   what the user sees on the source). Add a "Paste mappings only" /
   "Paste filter only" submenu later if needed.
2. **Cross-source paste safety.** Mappings carry `src_channel` with no
   explicit source-device binding — copying a "ch 1 only" mapping to a
   connection whose source is already filtered to ch 2 will silently
   never fire. Flag this in the toast?
3. **Plugin paste onto different plugin type.** Refuse (types differ) —
   show a toast explaining.

---

## 4. Matrix Undo / Redo

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

## 5. Controller plugin

### Goal

A virtual MIDI device whose value is its **on-screen control surface**.
Drop a `Controller` instance into the matrix, fill it with knobs / faders
/ toggles / XY pads bound to `(channel, cc)` targets, and use them as a
fast remote for the rest of your rig — on a tablet, on stage, in
fullscreen, with a built-in drop pad for snapshot / build-up / drop
performance moves.

### User stories
- "I want a 4×4 knob page on my tablet to ride filter, reverb, delay
  feedback and master volume — twist them in real time, no menus."
- "I want one button (the Drop pad) that captures the current state of
  every control on this page; later I tap it and the whole page snaps
  back to that snapshot — instant build-up + drop."
- "I want the drop to fire exactly on the next bar so it lands clean."
- "I want the controller's knobs to mirror what my synth sends, so I
  can twist either side and stay in sync."
- "I want a Mixer page, an FX page and a Pads page, and swipe between
  them in fullscreen during the gig."

### Layout

```
┌───────────────────────────────────────────────┐
│ [ DROP ]  autodrop:[Off ▼]   ✓ captured       │  always-there pad row
├───────────────────────────────────────────────┤
│ [Knob][Knob][Knob][Knob]                      │
│ [XY pad 2×2]   [Fader][Fader][Toggle]         │
└───────────────────────────────────────────────┘
```

- One `Controller` instance = one page. Multiple instances = multiple
  pages.
- A `LayoutGrid` param type holds the page's `cols × rows` and the cell
  list. Cell types in v1: **Knob**, **Fader**, **Button**, **XY pad**.
  Each cell stores a **user-rename­able label** (e.g. M1 → "Cutoff"),
  color, and one or two `(channel, cc)` bindings (XY pad has two — one
  per axis). Templates ship with placeholder labels (M1, F1, B1…); the
  user overrides per cell at configure time. The label is per-instance
  (stored in `_param_values`), so two instances of the same template
  can rename their cells independently. (Deferred from Phase-3 throwaway
  controller-template review 2026-04-26.)
- The drop-pad row is hard-coded above the user grid and not editable
  away — it's a property of the Controller, not a cell type.

### Drop pad

Built-in, always-there, single-per-instance.

- **Short press** → fire the stored snapshot. The MIDI for every cell
  is emitted on the OUT port, and the on-screen controls snap to the
  captured values.
- **Long press** (≥500 ms with progress ring on the pad) → capture the
  current value of every control on this Controller. No CC list
  configuration needed — the pad is implicitly scoped to its parent.
- **Autodrop** dropdown next to the pad: `Off` (default — fire
  immediately), `Next 1/4`, `Next 1/2`, `Next bar`, `Next 2 bars`,
  `Next 4 bars`, `Next 8 bars`. Uses the existing `ClockBus`. If
  transport is stopped, the pad fires immediately regardless.
- **Preview mode** toggle: when on, every control renders a faint ghost
  indicator at the snapshot value, so the user can see "where I'll be
  after the drop" while tweaking around.
- **Tap a pending pad again** → cancel the autodrop schedule.

### MIDI I/O — IN and OUT ports

Each Controller exposes two ALSA ports:

- **OUT** — emits CC when the user touches a control in the UI. Routed
  through the matrix to wherever the user wires it.
- **IN** — receives CC, used for two things:
  1. **MIDI Learn**: tap "Learn" on a knob/fader/toggle (or "Learn X"
     / "Learn Y" on an XY pad), then twist the source synth's knob.
     The next incoming CC binds that cell to its `(channel, cc)`.
  2. **Bidirectional sync**: any incoming CC matching a cell's
     binding silently updates the on-screen value. **Does not
     re-emit on OUT** — only user-driven UI moves emit. So wiring
     `Synth OUT → Controller IN` and `Controller OUT → Synth IN`
     keeps both sides in sync without feedback loops.

### Fullscreen play mode

A new top-level navigation entry, second from the left:

```
[ Routing ]  [ Controller ]  [ Presets ]  [ Settings ]
```

Tap behaviour:
- **0 instances** → empty state with `[ + Create Controller ]` button;
  tapping creates one and drops the user into fullscreen edit mode.
- **1+ instances** → opens the **last-viewed** Controller in
  fullscreen play mode immediately.

Fullscreen layout:
```
┌──────────────────────────────────────────────┐
│ ←   Mixer page   →     ✎ config       ✕      │  thin top bar
├──────────────────────────────────────────────┤
│  …drop pad row + grid of controls…           │
└──────────────────────────────────────────────┘
```

- `←` / `→` and **horizontal swipe** cycle between Controller
  instances in **creation order** (matches how plugins already sort
  in the matrix). Other plugin types are skipped.
- `✎ config` opens this Controller's edit panel inline (the existing
  plugin config UI) — overlays without leaving fullscreen.
- `✕` returns to whichever page the user came from (typically
  Routing).
- Layout is **fixed-grid** (no scrolling). Cells autosize to the
  device's actual viewport.

### Last-viewed persistence

`localStorage["raspimidihub:lastController"]` stores the instance id
last shown in fullscreen. Reasons for client-side over server-side:
- Each device (phone, laptop) has its own preferred view.
- Survives reload without backend round-trip.
- Auto-falls-back to the first Controller if the stored id no longer
  exists.

### Engine plumbing

- **CC observatory**: the engine already monitors all device output
  via the monitor port. Add a `last_value: dict[(client, port, ch,
  cc), int]` cache populated as events flow. The Controller's IN
  handler consumes from the per-port stream as today; the cache is
  exposed via SSE (`cc-snapshot` events) for the UI to redraw cells
  out-of-band when external sources move them.
- **Drop pad capture**: at long-press time, the UI just iterates its
  own cell values (already in client state) and snapshots them — no
  observatory round-trip needed for capture; observatory is only
  required for the bidirectional sync side.
- **Drop pad fire**: client emits `set_param(name, value)` for each
  cell (which already broadcasts via SSE), then the plugin emits the
  matching CC on OUT. Same path the user's manual touches use.

### New UI param types

- **`LayoutGrid`** — Python dataclass + JS renderer. Edit mode shows a
  cell-placement editor (drag to fill, tap a cell to configure, tap
  empty cell to add). Play mode shows live, fixed-size, big-target
  controls.
- **`PluginXYPad`** — JS only; a square cell with a draggable dot and
  axis-tick rendering. Two MIDI Learn buttons (X / Y) in its config
  popup.

### Persistence

Standard `serialize_instances` path. The cell list is one big list
inside `_param_values["layout"]`; the drop pad's snapshot is
`_param_values["pad_snapshot"]` (dict of cell-id → value).
Preview-mode toggle is `_param_values["preview"]`.

### Open questions

1. **Empty state of the drop pad**: before the first long-press, the
   pad has no snapshot. Short-press = no-op + toast "long-press to
   capture", or short-press silently does nothing? I'd toast.
2. **XY pad value range** — full 0..127 each axis for v1. Sub-range
   per axis (e.g. cutoff 30..120) is a v2 nice-to-have.
3. **Autodrop reference**: assume 4/4. Adding a meter selector later
   is a 2-line change.
4. **Should fullscreen survive a refresh?** localStorage covers that
   automatically — re-entering the page restores the same instance.

---

## 6. Preset switch smoothness

### Goal

Loading a preset (matrix preset, future Preset Trigger plugin, manual
"Load Config" button — anything that swaps the routing graph) currently
rips down every subscription and rebuilds. That causes:

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

## 7. Drawable LFO (`CC Curve LFO`)

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

## 8. Clock Divider plugin

### Goal

Slow a connected device down by an integer factor without affecting
anything else in the chain. Wire `Master clock → Divider IN`, then
`Divider OUT → slave instrument`, set `Divide by` to N, and the
slave receives 1 clock tick for every N the master sends.

### User stories
- "I want my arpeggiator to play half-speed against the master DAW
  clock without changing the DAW tempo."
- "I want a four-bar pad to retrigger a quarter as often as the
  drums, without doing any maths in my head."

### Plugin shape

Tiny — one knob plus boilerplate.

| Param | Type | Range / default |
|-------|------|-----------------|
| `divide_by` | `Wheel` | 2..32, default 2 |

I/O: standard plugin IN + OUT ports.

Behaviour:
- For every N-th `MIDI Clock` arriving on IN, emit one `MIDI Clock`
  on OUT. All other Clock ticks are dropped.
- Forward `Start`, `Continue`, `Stop` **intact** (no division).
- On `Start` or `Continue`, reset the internal counter to 0 so the
  first emitted tick lines up with downbeat.
- Pass through every other event type (notes, CC, etc.) unchanged —
  so the divider can also sit in a notes path without breaking it.

### Engine plumbing

Plugins today receive *musical-division* ticks (`1/4`, `1/8`, …) via
the existing `ClockBus`, not raw 24-PPQ ticks. To divide every Nth
raw clock we need one of:

- **(A) New "tick" division** — add `"tick": 1` to `DIVISION_TICKS`.
  A plugin declaring `clock_divisions = ["tick"]` then receives
  `on_tick("tick")` on every raw clock. Tiny one-line change.
- **(B) New `on_raw_clock` callback** — bypass the ClockBus and let
  the dispatcher deliver `MIDI Clock` events directly to opting-in
  plugins. More invasive.

I'd take **(A)** — one extra map entry, no API surface change. The
Clock Divider becomes:

```python
clock_divisions = ["tick"]

def on_tick(self, division):
    self._n += 1
    if self._n >= self.get_param("divide_by"):
        self._n = 0
        self.send_clock()

def on_transport_start(self):
    self._n = 0
    self.send_start()

def on_transport_stop(self):
    self.send_stop()
```

### One small infrastructure addition

Plugins currently get `on_transport_start` and `on_transport_stop`
but not `on_transport_continue`. The ClockBus's `on_continue` only
flips its internal `_running` flag and doesn't notify plugins. Add
`_notify_transport("_continue")` and `on_transport_continue()`
default-no-op on `PluginBase` so the divider (and future
clock-aware plugins) handle Continue correctly.

### Open questions

1. **Phase offset** — should the user be able to pick which raw tick
   the output falls on (e.g. divide-by-4 starting on tick 0, 1, 2,
   or 3)? I'd skip for v1; reset-on-Start is enough for typical
   live use.
2. **CC `divide_by` automation** — `cc_inputs = {74: "divide_by"}`?
   Cheap to add; useful for build-up/drop performance moves.

---

## 9. UI element sizing & grid scaling

### Goal

A consistent, grid-friendly layout language for every interactive
control across the app — used by plugin config panels today and by
the Controller's `LayoutGrid` tomorrow. Cells line up cleanly,
fullscreen modes scale predictably to the device, and the visual
language stays uniform.

### Base unit (`1u`)

Every UI control declares its footprint as **integer multiples of a
shared base unit**. No fractional sizes.

| Control | Footprint (`w × h` in units) | Notes |
|---------|--------------------------------|-------|
| Wheel | `1 × 1` |  |
| Knob | `1 × 1` | (new in §5) |
| Toggle | `1 × 1` |  |
| Pad / Button | `1 × 1` |  |
| Display (meter) | `2 × 1` |  |
| Display (scope) | `3 × 1` |  |
| Fader (vertical) | `1 × 3` | tall thin |
| Fader (horizontal) | `3 × 1` | wide thin |
| XY pad | `2 × 2` | (new in §5) |
| StepEditor (8 steps) | `4 × 1` | scales with step count |
| CurveEditor | `4 × 4` | square canvas |
| ChannelSelect | `1 × 1` | thumb-driven wheel |
| NoteSelect | `1 × 1` | thumb-driven wheel |
| Group title | `N × 0` | spans full width, no height in the grid sense |

Larger variants exist where it makes sense (a `2 × 1` Wheel for
`split_point`-style ranges; a `2 × 3` Fader for the master volume
in fullscreen). Plugins may declare them via the existing param
dataclasses; the renderer just snaps to the requested grid.

### `1u` value at render time

Computed at render time from the viewport — the base unit is **not
a fixed pixel count**. Two contexts:

- **Config panels in matrix view**: `1u` defaults to ~80 px on
  desktop, ~64 px on phone. Picked to make a 4-column control row
  feel right on both.
- **Controller fullscreen play mode**: the grid is **logical, not
  physical**. The user picks `cols × rows` once when building the
  Controller, and that pair is fixed regardless of device. At render
  time:

  ```
  1u = min( viewport_w / cols ,  viewport_h / rows )
  ```

  No scrolling — the grid always fits. A `4 × 3` Controller on a
  phone gets ~125 px cells; the same layout on an iPad Pro gets
  ~280 px cells. **Designed once, scales naturally — bigger devices
  get bigger knobs, not more knobs.**

### `1u` cap

Without an upper bound, a small grid on a huge display produces
comically large controls. `1u` is capped at **200 px**; when the
cap is hit the grid centres with margin around it.

### Phone preview in edit mode

When configuring a Controller on a tablet or desktop, a small
**Phone preview** toggle in the edit panel constrains the preview
viewport to a phone-sized box (390 × 844 by default). Avoids the
"looks great on my desktop, tiny on my phone" trap before the
layout ships.

### Recommended `cols × rows` picks

| Picks | Cells | Use case |
|-------|-------|----------|
| `4 × 2` | 8 | Compact mixer page |
| `4 × 3` | 12 | Standard "all your knobs" page — the sweet spot |
| `3 × 3` | 9 | Drum-pad style (drop pad row above) |
| `6 × 3` | 18 | Tablet-optimised — phone users get tinier touch targets |
| `2 × 2` (XY pad) | 1 | Single big XY pad for touch performance |

The renderer doesn't enforce these — it'll scale anything — but
`4 × 3` is the layout that feels right on a phone and luxurious on
a tablet.

### Orientation behaviour

If the user designs a landscape-flavoured layout (e.g. `4 × 2`) and
rotates the phone to portrait, the grid **stays exact** — the same
`cols × rows`, the same cell positions, the renderer just leaves
margins above/below. The expectation is that performance use is in
landscape; portrait is a fallback that shouldn't surprise the user
by re-arranging cells.

### Open questions

1. **Per-device override**. Should the user be able to nudge the
   base unit up/down in Settings? Probably v2.
2. **Phone preview viewport size**. 390 × 844 (iPhone-ish) is
   default; a small dropdown for `iPhone SE`, `Pixel 7`, etc. would
   be a nice-to-have if multiple users compare designs.

---

## 10. UI Demo plugin

### Goal

A plugin whose only purpose is to **showcase every UI param type at
its canonical size**, on a real `LayoutGrid`. Created like any
plugin via "+ Add Plugin"; doesn't emit MIDI. Functions as:

- a **visual reference** for the sizing rules (§9) — Knob next to
  Fader next to XY pad on the same screen, see them in proportion;
- an **acceptance surface** for the UI controls refactor (§11) —
  the demo plugin renders all controls; if it looks right, the
  refactor didn't regress;
- a **sandbox** where new control designs (Knob, XY pad, future
  ones) can iterate before they get used in real plugins.

### Contents

A single `LayoutGrid` containing one of each control type, plus an
inline `Display` showing live values fed by simple internal logic
(LFO ticking against the wheel, square XY pad updating both axes,
etc.). All bound to a virtual no-op output — wiring this plugin to
anything in the matrix produces silence.

### Lives in

`plugins/ui_demo/__init__.py`. Tests are visual — covered by the
demo's own existence and by exercising it during Phase 3 of the
implementation plan.

---

## 11. UI controls refactor

### Goal

`plugin-controls.js` is currently one ~950-line file holding every
control. New controls (Knob, XY pad, LayoutGrid) are about to be
added; before that lands, split the existing components into
per-component files so each new control gets its own file too.

### Layout after refactor

```
src/raspimidihub/static/
  plugin-controls.js          ← thin shim: imports + re-exports
  components/
    common.js                 ← shared helpers (tickFeedback,
                                thudFeedback, drum animation, etc.)
    render-param.js           ← the dispatcher (renderParam,
                                INLINE_TYPES, renderParamGroup,
                                renderParamList)
    wheel.js                  ← PluginWheel
    fader.js                  ← PluginFader
    radio.js                  ← PluginRadio
    toggle.js                 ← PluginToggle
    button.js                 ← PluginButton
    note-select.js            ← PluginNoteSelect
    channel-select.js         ← PluginChannelSelect
    step-editor.js            ← PluginStepEditor
    curve-editor.js           ← PluginCurveEditor
    display.js                ← PluginScope, PluginMeter
    knob.js                   ← new in §5
    xy-pad.js                 ← new in §5
    layout-grid.js            ← new in §5
```

Each file ≤ ~200 lines. `plugin-controls.js` stays as the public
entry point so existing imports (`./plugin-controls.js`) keep
working — no changes outside this directory.

### Rule going forward

**New components always land as their own file** under
`components/`. `plugin-controls.js` only ever grows by one
`export` line.

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
3. Tracker MVP — plugin + `TrackerGrid`, steps, play, record, overdub,
   clear.
4. Tracker polish — copy/paste bars, transpose, paginator, live
   pass-through toggle.

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
1. Per-edge note refcount table.
2. Edge-diff `apply_edge_diff(target_edges)` replacing
   teardown-and-rebuild in `api_load_config`.
3. Soft vs hard panic split (long-press = hard).

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

### Phase 1 — Foundation + small win (≈ 1 sprint) ✓ Done (2026-04-25)

Small, mostly-mechanical work that delivers a couple of visible
things and de-risks the bigger Engine changes in Phase 2.

1. ✓ **Clock Divider plugin** (§8) — shipped in `fd08762`. Landed
   the new `"tick": 1` entry in `DIVISION_TICKS` and the
   `on_transport_continue` plugin callback + ClockBus
   `_notify_transport("_continue")`.
2. ✓ **Per-edge note refcount table** (§6) — shipped earlier in
   `bb806e1` / `9f1f336`. Engine tracks `(edge_id, channel, note) →
   count` and flushes NoteOff on edge removal.
3. ✓ **Soft / hard panic with the double-tap state machine** (§6) —
   shipped in `ec86811`. Engine `panic(hard=False)` splits CC 123
   from CC 120 and emits per-edge NoteOff for tracked notes. Client
   state machine in `pages/routing.js` (idle → soft → hard, hard
   auto-decays after 600 ms, incoming MIDI Start resets to idle via
   the new `transport-start` SSE event).

### Phase 2 — Engine smoothness (≈ 1 sprint) ✓ Done (2026-04-25)

The big invasive Engine change. **Highest test coverage of any
phase** — it touches the live MIDI hot path.

1. ✓ `MidiEngine.apply_edge_diff(target_edges)` shipped in
   `7b67a29`. Diff-and-apply core with helpers `_remove_edge_smoothly`,
   `_add_edge`, `_send_all_notes_off`. Removed edges flush tracked
   NoteOffs and emit CC 123 on used channels; in-place
   userspace-mode updates avoid resubscribe; mode switches
   tear down + rebuild cleanly.
2. ✓ Synthetic edge-diff tests in `tests/test_edge_diff.py`
   covering added-only, removed-only, both, untouched, in-place
   changed-mappings, mode-switch, NoteOff + CC 123 emission, and
   unresolved-stable-id skipping (9 tests).
3. ✓ Wired into `POST /api/config/load` (`c119351`). Live verified
   on the Pi: reload-with-no-changes touched 0 of 8 edges.
4. End-to-end Pi test with a sounding note across a removed edge:
   relies on user-side reproduction; skipped as automated test
   (no MIDI test rig in CI).

`api_preset_action` and the hotplug rescan path still use the
old `disconnect_all + apply_saved_config` pair — preset activation
involves plugin instance teardown that invalidates cached client
IDs, and the hotplug path has its own snapshot-merge logic. Both
are tracked as follow-ups, not part of Phase 2:

- **TODO: wire `apply_edge_diff` into `api_preset_action`** —
  needs a strategy for the plugin restore step (skip restore if
  the preset's plugin set is identical to current; otherwise
  fall back to the teardown path).
- **TODO: wire `apply_edge_diff` into hotplug `_scan_and_connect`**
  — the offline-snapshot merge logic needs a careful pass before
  the diff replaces it.

After this, Preset Trigger is essentially a 30-line plugin —
stays in pending until requested.

### Phase 3 — Foundation for Controllers (≈ 0.5 sprint) ✓ Done (2026-04-25)

Foundation work the Controller MVP depends on. Nothing user-visible
ships in this phase alone, but everything in 4 builds on it.

1. ✓ **UI controls refactor** (§11) — shipped in `8c31e5c` /
   `a400bcf`. `plugin-controls.js` is now a thin shim that
   re-exports the per-component files in `static/components/`.
2. ✓ **UI sizing rules** (§9) — shipped on the `ui/grid-sizing`
   branch (merged in `19b9c73`). The actual implementation went
   with a CSS `repeat(4, minmax(0, 1fr))` grid + a `span`
   attribute on the param schema, instead of fixed `size_w` /
   `size_h` pixel sizes baked into the dataclasses. The grid is
   responsive (4 cells across at any viewport ≥ ~320 px) and any
   control can declare it occupies 1, 2, 3 or 4 cells.
3. ✓ **UI Demo plugin** (§10) — shipped in `d229b7c` and extended
   with knobs, vertical-fader rows, and span demos.
4. ✓ **CC observatory** (§5 engine plumbing) — shipped in
   `566bd43`. Cache last-seen value per `(client, port, ch, cc)`,
   broadcast on change via SSE `cc-snapshot`.

Knob control (a §5 Phase 4 item) actually landed during Phase 3
since it was needed to validate the grid sizing — 1 of the 3
Phase 4 §5 controls is therefore done early. **TODO: LayoutGrid
and PluginXYPad** still remain for Phase 4.

### Phase 4 — Controller MVP (≈ 1 sprint) ✓ Done (2026-04-26)

Biggest user-visible win for performance.

0. ✓ **Done (2026-04-26):** Destination-keyed CC observatory.
   `_cc_dest_cache: dict[(dst_client, dst_port, ch, cc), int]`
   populated at the engine routing site, exposed via
   `engine.last_cc_to(dst, ch, cc)` and the `cc-changes` SSE
   delta-push fired once per second from the rate_meter loop.
   The source-keyed observatory was removed in the same pass.
1. ✓ **Done (2026-04-26):** `LayoutGrid` + `XYPad` param types.
   Knob already shipped in Phase 3; LayoutGrid is a fixed-position
   container with `(col, row, span_cols, span_rows)` per cell;
   XYPad is a square pad with a draggable dot, value
   `{x: int, y: int}`, multi-touch-safe (uses the same
   `activeTouchId` pattern as Fader/Knob). Validated via a 6×4
   demo grid in `ui_demo` mixing knobs / faders / mute buttons /
   2×2 XY pad / row-spanning master fader.
2. ✓ **Done (2026-04-26):** Controller plugin — Knob / Fader /
   Button / XY pad cells, OUT port emit, IN port for MIDI Learn +
   bidirectional sync (consumes destination-keyed cache). Drop pad
   with short-press fire / long-press capture **only** — autodrop
   and preview indicators deferred to Phase 5.
   - ✓ **4.2.a (2026-04-26):** Controller — Mixer 8 plugin shipped
     with hard-coded bindings (ch 1, CC 16-39). OUT emits on cell
     change, IN silently mirrors matching CCs into the on-screen
     cells with no re-emit (no feedback loops). Replaces throwaway
     controller_a.
   - ✓ **4.2.b (2026-04-26):** Drop pad shipped — `DropPad` param
     type with short-press fire / long-press (≥500 ms) capture +
     visible progress ring. Snapshot stored in
     `_param_values["pad_snapshot"]`. Fire re-emits captured CCs +
     snaps cells back. Pad value cycles 'idle' / 'capture' / 'fire'
     / 'captured' so the UI knows when a snapshot is armed.
   - ✓ **4.2.c (2026-04-26):** Per-cell rename + per-cell rebind UI +
     MIDI Learn buttons.
     - ✓ **4.2.c.1 (2026-04-26):** Per-cell rename. LayoutGrid
       gained `edit_param` + `labels_param` fields; "Edit names"
       toggle on the Controller swaps cells for text inputs that
       persist via `_param_values["cell_labels"]`. Display mode
       reads overrides and renders them over the schema label.
       Watchdog now does deep-equality so dict-valued params don't
       loop on identity mismatch.
     - ✓ **4.2.c.2 (2026-04-26):** Per-cell channel + CC rebind.
       LayoutCell schema gained optional `channel` + `cc` fields
       (the default binding); LayoutGrid gained `bindings_param`
       pointing at a sibling dict of `{cell_name: {channel, cc}}`
       overrides. Edit mode now shows a small `ch` + `cc` input
       under the rename input. Plugin uses
       `_effective_binding(name)` (override > default) for both
       OUT emit and IN sync. Channel is 0-based on the wire and
       1-based in the UI.
     - ✓ **4.2.c.3 (2026-04-26):** Per-cell MIDI Learn. LayoutGrid
       gained `learn_param` (a sibling string-valued param;
       cell_name = currently learning, "" = idle). Each edit-mode
       cell has a small `L` button that arms learning for that
       cell. The plugin's `on_cc` checks `cell_learn` first — if
       set and matches a known cell, the next incoming CC's
       (channel, cc) is captured into `cell_bindings` and learn
       state is cleared, otherwise the CC flows into normal
       bidirectional sync. Frontend treats `learn_param` as
       trigger-style (PATCH only, no optimism / watchdog) so the
       server-side reset on capture doesn't loop.
   - ✓ **4.2.d (2026-04-26):** Performance 16 + FX 6 templates
     shipped as real Controllers (4-wide 16-macro / 4-scene; and
     6-wide knobs/faders/buttons). All three templates now share a
     `raspimidihub.controller_base.ControllerBase` class — cell
     plumbing, drop pad, MIDI Learn, panic all live there;
     subclasses just declare metadata + a LayoutGrid. Plugin
     discovery tightened to filter by `__module__` so the imported
     base class is never picked as a plugin in its own right.
     Throwaway controller_b / controller_c removed.
   - ✓ **4.2.e (2026-04-26):** Controller — XY 4 plugin shipped
     (2× 2×2 XY pads on top + 8 knobs + 4 buttons; CC 16-31 ch 1).
     Per-axis Ch + CC config: LayoutCell gained `channel_y` and
     `cc_y` so an XY pad can route X and Y to different synths or
     different MIDI channels. Edit-mode card now lays the XY pad
     out as two axis rows ("X: Ch / CC / Learn", "Y: Ch / CC");
     Y channel defaults to X when not set. Learn captures the X
     axis only — type Y manually.
   - ✓ **4.2.f (2026-04-26):** Controller — per-cell on / off
     CC values for button cells (defaults 127 / 0); pair can be
     inverted or set to any half-value pair (e.g. 64 / 0). ↔ swap
     button next to the values flips them in one tap. Bidirectional
     sync uses "closer to on or off?" matching so any pair works.
   - ✓ **4.2.g (2026-04-26):** Per-controller background colour.
     8 dark themes (Default, Navy, Forest, Wine, Plum, Teal,
     Sienna, Slate) selectable in the device-detail Plugin Config;
     the picker previews live as you choose, the Controller page
     itself stays uncluttered.
3. ✓ **Done (2026-04-26):** Top-nav "Controller" entry, fullscreen
   mode, `localStorage` last-viewed persistence. Implementation
   used a dropdown + ‹ › arrow buttons for instance switching;
   horizontal-swipe-between-instances landed in a follow-up pass
   the same day (touch handler at the page root, controls
   stopPropagation so a touch on a knob never reaches it).
   URL routing also moved into the same pass — `/controller`,
   `/controller/<instance_id>`, `/routing/d/<device_id>` etc. now
   reflect what's on screen so back/forward + bookmarks work.
   Param management extracted into a shared `usePluginParams` hook
   so the Controller page and the device panel both go through the
   same coalesced PATCH + SSE settle pipeline.

4. ✓ **Done (2026-04-26):** Streaming-controller perf round.
   Surfaced when the user drove 4 simultaneous LaunchControl faders
   into Mixer 8 with 4 connected browsers and the asyncio loop
   pinned at 100+% CPU with 50-75 ms loop lag. Rather than a single
   change, this turned out to be a stack of bugs + bottlenecks
   layered on each other; all fixed in 2026-04-26's commits:
   - `TrailingCoalescer` extracted as a shared abstraction for
     last-value-wins rate caps (was duplicated, all three copies
     had the same trailing-value bug — a fader stopping between
     two windows left the UI on a stale value forever). Applied
     to plugin-param + plugin-display SSE streams.
   - Per-view SSE subscription model. Each view declares its
     interest via `useSSESubscription(events, instances)`;
     `SubscriptionManager` unions per-hook contributions and
     sends to `/api/sse/subscribe`. Server filters per recipient.
     Idle browsers no longer eat the active controller's flood;
     traffic scales with what you're looking at, not with what
     every other client is doing. Killed `_handle_sse` from the
     CPU profile entirely.
   - SSE keep-alive heartbeat (30 s comment line per outbox) to
     surface dead sockets — the subscription model exposed a
     latent leak where queues that never wrote could never
     detect a dead TCP socket.
   - Plugin host now caches `get_plugin_client_ids()` (was
     called per ALSA event, building a fresh set each time).
   - Engine event loop holds a single persistent fd reader
     instead of registering/unregistering per iteration.
   - LED sysfs writes off the asyncio loop via run_in_executor;
     midi-blink rate-cap from 20 Hz to 1 Hz.
   - Plugin schema cached per class so PATCH responses don't
     re-serialise on every knob drag.
   - `/api/plugins/instances` returns a light shape with a 500 ms
     TTL cache + invalidation on lifecycle mutations. Resolves
     custom names through the device registry so the Controller
     dropdown matches the Routing tab.
   - Top-bar build-token badge ("v2.0.9·<token>") with a "stale,
     reload" link when the loaded JS bundle's token doesn't
     match the server's. Per-restart token in `?v=` busts the
     module cache on every redeploy.
   - Closure-id rekey bug fixed — coalescer closures captured
     `instance.id` at definition time, which broke after
     `restore_instances` rekeyed to the saved id. Closures now
     dereference `instance.id` at call time.
   - Net result: same 4-fader load now sits at 47-74 % CPU with
     single-digit-ms loop lag, ~95 SSE/s (down from 1478),
     zero backlog, even with 7 connected browsers.

### Phase 5 — Controller polish (≈ 0.5 sprint)

1. **Autodrop**. Bar-quantized fire scheduling via the existing
   ClockBus. Free now that 1.1 added the new tick infrastructure.
2. **Preview / drop-snapshot indicator on the cells themselves**
   (replaces the original "ghost indicators" sketch with the
   concrete UX surfaced during Phase 4.2.b review):
   - **Knobs**: render the captured snapshot value on the LED arc
     in a contrasting color (turquoise against the live-value's
     warm accent), so the arc shows BOTH the current value *and*
     where the drop will jump it. Difference between current and
     snapshot reads as the in-between arc length.
   - **Faders**: re-purpose / add a colored bar near the track to
     mark the snapshot value at the same scale as the thumb.
   - **Buttons**: less obvious — option A: an extra small dot on
     the LED in turquoise that only shows if "snap value !=
     current". Option B: a thin border tint while armed.
   - **XY pads**: a second faint dot at the snapshot (x, y).
   - **Wheels**: a coloured tick on the side of the wheel at the
     captured value (or skip — Wheel is rarely on a Controller,
     mostly internal-plugin UI).
   This is a much better "armed" affordance than the per-cell
   tinting we initially considered, and survives multi-browser
   (every connected browser reads the same `pad_snapshot` over
   SSE, so the indicators stay in sync without depending on the
   user's local action).
   Surfaced 2026-04-26 during Phase 4.2.b review when the user
   noticed the drop pad's local flash didn't propagate to other
   browsers and felt insufficient as the only "this is loaded"
   cue.
3. **Whatever the MVP usage in Phase 4 surfaced.** As of 2026-04-26
   nothing user-facing is open — the day's session ran four
   simultaneous LC faders into Mixer 8 across multiple browsers and
   identified a stack of bottlenecks rather than UX issues. Open
   technical follow-ups parked here:
   - **Optional: Rust port of `read_event` + the engine drain.**
     After the Phase 4.4 perf round, ALSA reading + the Python
     drain-and-classify loop are the dominant non-fundamental cost
     (~26 % CPU under 4-fader load: 14.9 % syscall + 11.7 %
     iter-and-branch). A `pyo3` extension exposing
     `drain_events(seq_handle, max_events) -> List[Event]` could
     collapse it to ~5-8 %. Probably 200-300 lines of Rust and a
     few days of work. **Not urgent** — the system runs at 47-74 %
     CPU on a Pi 4 under the heaviest measured load, with plenty
     of headroom. Reach for it only if a real ceiling appears
     (e.g. driving 4 hardware destinations through filter chains
     while running a CC LFO on every knob).
   - **Closure-rekey lesson**: `restore_instances` re-keys an
     instance from the transient create-time id to the saved id;
     closures that captured `instance.id` at definition time
     stayed pointing at the dead transient id. Both coalescer
     closures had this bug. Pattern to remember: capture the
     OBJECT, dereference `.id` at call time. Worth a code-review
     reflex check on any new closure added under
     `_create_instance` / `_setup_plugin_callbacks`.

### Phase 5.5 — Transient WiFi for updates (≈ 0.5 sprint)

Slotted in after Phase 5 because the building blocks already exist
(AP/client mode switching in `wifi.py`, the update flow in
`scripts/raspimidihub-update.sh` running outside the service so it
survives a dpkg restart) and the feature unblocks the "Pi sitting on
guest WiFi 24/7" privacy concern.

**User story:** I want to store a real-WiFi SSID + password, hit
"Check for updates", let the Pi temporarily join that WiFi to fetch
+ install the deb, then come back to AP mode automatically. With an
opt-in setting for "stay on the real WiFi forever" (today's
behaviour) so I don't lose anything.

**Config shape**: add `client_persistence: "permanent" | "update_only"`
to the stored WiFi config. Default `permanent` for users who already
configured client mode. Setting it to `update_only` keeps the
credentials but skips client connect on boot.

**Trigger flow** (manual only in v1; scheduled auto-update is a future
follow-up):
1. User taps "Check for updates" in Settings.
2. **Confirmation dialog with a visible 60–90 s countdown timer**:
   "The Pi will go offline for up to 90 seconds while it joins your
   home WiFi to check. Your phone will lose its connection to the
   Pi during this window — that's expected. Reconnect to the
   `RaspiMIDIHub-XXXX` AP afterwards. Don't close this tab — the
   result appears here automatically when the Pi is back."
3. User confirms → Pi switches to client mode, runs update-check,
   and if a deb is available downloads + installs it (which
   auto-reboots into AP mode since `update_only` skips client on
   boot). If no update is available, Pi explicitly switches back to
   AP after the check.
4. **UI persists through the disconnection window** — must keep the
   "checking…" surface mounted until a result arrives. The user is
   instructed to wait through the timeout without navigating away.
   While SSE is down, the page shows a live countdown: "checking
   for updates… (Xs remaining)" so the wait feels deterministic.
5. **If the timer expires and the Pi is still unreachable**, the UI
   swaps to a help card: "Can't reach the Pi. Check your phone's
   WiFi is connected to `RaspiMIDIHub-XXXX` and reload this page."
   Crucially: when the user reconnects to the AP, the page
   auto-updates without a manual reload — existing SSE reconnect
   logic detects the new connection and fires a refresh.
6. **On AP-return the UI MUST surface a clear, specific outcome**.
   Either success ("Updated to v2.0.10" or "Already up to date —
   v2.0.9") or a *concrete* error stating what failed:
     - `Couldn't join "HomeWiFi": wrong password`
     - `Joined "HomeWiFi" but no IP address (DHCP failed)`
     - `Got an IP but no internet — check the router`
     - `GitHub unreachable (timeout) — try again later`
     - `Download interrupted at 45 % — check your connection`
     - `Install failed: <dpkg error excerpt>`
   Never a generic "update failed" toast. The user must know which
   step broke so they can fix it (re-enter password / move closer to
   the router / wait and retry).
7. **Hard watchdog on the Pi (3 min budget)**: an independent
   process (systemd one-shot or `at`-scheduled job) that *always*
   forces the Pi back to AP mode regardless of what failed. Without
   this watchdog, a single failure leaves the user with a Pi stuck
   on a WiFi they can't see from their phone, and no recourse short
   of physical access.

**Failure cases the watchdog must cover** (each must produce a
distinct, surfaceable error string per step 6):
- WiFi credentials are wrong → `wpa_supplicant` never associates.
- WiFi associates but no DHCP lease.
- DHCP lease but no internet routing.
- Internet but GitHub API rate-limited or down.
- Download starts but is interrupted (network drops mid-stream).
- Download completes but `dpkg -i` fails (signature, dependency).

In every case the watchdog falls back to AP, leaves a structured
status breadcrumb (e.g. JSON `{step: "wifi_assoc", error: "auth
failed"}`) in `/run/raspimidihub/update-status` that the AP-mode UI
reads on reconnect to render the per-step message above.

**Out of scope for v1** (capture as future follow-ups):
- Scheduled auto-update on a cron (e.g. weekly at 03:00). Easy to
  add once the manual flow is proven, but invisible to the user
  during the gap so the watchdog has to be rock-solid first.
- Multiple stored networks (try home WiFi → fall back to phone
  hotspot). Single SSID is fine for v1.
- Background "stayed on AP" check-only mode that polls GitHub via
  the user's phone WiFi if the phone is providing internet via the
  AP itself. Architecturally cleaner but needs Pi-as-router
  changes.

### Phase 6 — Workflow (≈ 1 sprint)

Quality-of-life, not blocking anything live.

1. **Matrix context menu** (§3). Long-press / right-click popover
   on cells, headers, **mapping rows** (with single-tap = Edit
   shortcut). Removes the inline Edit/Delete buttons on mapping
   rows; adds the `[ + Paste Mapping ]` button next to `[ + Add
   Mapping ]`.
2. **Connection clipboard**. Copy filter + mappings; paste onto
   another connection.
3. **Plugin clipboard**. Paste-as-new + paste-over-instance.
4. **Mapping clipboard**. Append-as-is when free; bump-on-conflict
   with a forward search through the destination field's range
   (semantics from §3).

### Phase 7 — Modulator (≈ 0.5–1 sprint)

Creative, niche, no other dependencies.

1. **CurveEditor extensions** (§7). `wrap` flag, `shapes` pulldown
   replacing preset pills, Smooth button. `velocity_curve` benefits
   for free.
2. **Drawable LFO** (`CC Curve LFO`, §7).

### Phase 8 — Sequencers (≈ 3 sprints)

The biggest pieces but the lowest live-performance urgency. Most
users will use Arp + Hold for sequencing while these mature.

1. **Rhythm Sequencer MVP** (§1). 5 genres (Techno, House, DnB,
   Hip-Hop, Trap), ≥5 presets per genre, ≥3 pattern variants per
   instrument per genre. Patterns + presets ship as `.grv` text
   files under `plugins/rhythm_sequencer/templates/`.
2. **Tracker MVP** (§2).
3. **Generalize step grid**. Pull common code out of `DrumGrid` /
   `TrackerGrid` into a reusable component.
4. **CC Sequencer** (pending design — finalise spec just before
   this step). Uses the generalised step grid + CC observatory.
5. **Rhythm Sequencer genre expansion**. Round out to 21 genres.
6. **Tracker polish**. Copy/paste bars, transpose, paginator, live
   pass-through toggle.

### Phase 9 — Undo / Redo (≈ 0.5–1 sprint)

Last on purpose: the Command-stack abstraction (§4) wraps the REST
API surface, so we want every other feature's endpoints to be
finalised before we commit to wrapping them.

1. Client-side `Command` class + dual-stack history (cap 100).
2. Wrap every existing mutating call site (matrix toggle, mapping
   add/remove/edit, plugin add/remove, rename, paste).
3. Toolbar Undo/Redo buttons + Ctrl+Z / Ctrl+Shift+Z bindings.
4. Labelled toasts ("Undid: …").
5. SSE reconciliation: drop redo stack on any external change.

### What I'd start with right now

If you say "go" today: **Phase 1.1, Clock Divider**. Smallest, fully
spec'd, gives us the test bed for the new `tick` plumbing and the
`on_transport_continue` callback.

### Risk callouts

- **Phase 2 (`apply_edge_diff`)** is the riskiest. If you only have
  appetite for one phase to be paranoidly tested, it's that one.
- **Phase 4 (Controller MVP)** is the most UI-heavy. Plan for design
  iterations on the LayoutGrid edit experience.
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

  **Source data:** https://midi.guide is a community-maintained
  database of synth + drum-machine CC + NRPN + sysex maps. **License
  must be verified BEFORE any work** — find the upstream repo or
  authoritative source, confirm the licence (CC0 / CC-BY / GPL?),
  and decide accordingly:
  - **CC0 / public domain**: ship a snapshot in the deb under
    `/usr/share/raspimidihub/midiguide/`, refresh on update.
  - **CC-BY**: ship + display attribution prominently in the picker
    UI ("Mappings from midi.guide, CC-BY 4.0") and in the About box.
  - **GPL / share-alike**: probably can't ship in a permissively
    licensed deb; consider on-demand fetch instead, with cache, or
    drop the integration entirely.
  - **No clear licence**: open an issue with the upstream maintainer,
    don't proceed until clarified.

  **Data model sketch.** Two layers:
  1. **Library** (read-only, ships with the app or fetched on
     install): `instruments/<vendor>__<model>.json` with shape
     `{vendor, model, version, ccs: [{cc, name, channel?, range?,
     description?}], nrpns: [...], notes: [{note, name, ...}]}`.
     Indexed by a top-level `index.json` for fast picker rendering.
  2. **Per-device assignment** (user state, in `config.data`): each
     device (or each connection's destination) carries
     `instrument_profile: "vendor__model"`. Multiple devices may
     share a profile — only the assignment is per-device, not the
     data.

  **UX sketch.**
  - **Routing tab → device-detail panel**: a new "Instrument" row
    with a picker. Empty by default. Tapping opens a searchable list
    grouped by vendor; instant search by typing model name. Clearing
    removes the assignment.
  - **Controller cell config**: when a binding's destination has an
    instrument profile assigned, the **CC field becomes a combo box**
    — type-ahead by CC name (`"Cutoff"`, `"Resonance"`) OR by
    number; both resolve to the same numeric CC. Cell label
    pre-fills with the friendly name when a CC is picked from the
    library, but the user's typed override always wins.
  - **Tooltip on the CC number input**: if there's a profile, hover
    shows `"CC 74 — Cutoff (JX-08)"` so existing numeric bindings
    self-annotate without changing data.
  - **No profile assigned**: pickers degrade to plain numeric inputs
    — no regression for users who don't care about the library.
  - **User overrides**: a "+ Custom CC" entry in the picker lets the
    user add a name for a CC the library doesn't know (stored in
    `config.data.user_cc_names[device_id][cc] = "name"`). Future
    cell pickers see both library + user names.

  **Shipping form.** I'd lean on a snapshot at deb-build time rather
  than a live fetch — the Pi is often offline (AP mode), and the
  data churns slowly. Build step pulls from upstream into
  `data/midiguide/` (gitignored), Make deb copies into the
  package. Update card in Settings could show "Library: 2026-04-15,
  342 instruments — refresh?" with a manual refresh that requires
  client-mode WiFi (ties in with Phase 5.5 Transient WiFi).

  **Open questions:**
  - Can we contribute corrections back to midi.guide via PR? (good
    citizen / two-way street).
  - Does the data cover the user's specific instruments (Digitone II,
    LCXL3, S-1, Impact GX49)? Quick spot-check before committing.
  - NRPN + sysex coverage useful for §7 (CC Curve LFO) and a future
    sysex sender plugin, but probably out of scope for v1 — start
    with CC only.

- **TODO: `cc_lfo` per-cycle gate pattern** — `StepEditor`-style 1–32
  step pattern that mutes/un-mutes whole LFO cycles for ducking-style
  effects (e.g. `0111` = first cycle off, next three on). Behaviour
  during an off step (silent / hold-last / configurable rest value)
  TBD.
- **TODO: CC Sequencer** — step-based plugin emitting up to 4
  `(channel, cc, value)` per step, with arm-and-record from the CC
  observatory. Step grid UI shared with the Tracker.
- **TODO: CC Pickup / Relative plugin** — single virtual instrument
  with `mode = pickup | relative`, re-introducing the classic synth
  pickup/scale modes. Depends on the Phase-4 destination-keyed CC
  cache prereq above. Use case: user is editing a synth from the
  web-UI Controller (§5), then wants to grab a hardware controller
  and continue twisting *the same parameter* without value jumps.

  **Topology** (single IN, single OUT): `Physical Ctrl → Pickup IN`,
  `Pickup OUT → Synth`. The §5 Virtual Controller keeps its own
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

  **UI**: no engaged/armed indicator on the plugin itself. The §5
  Virtual Controller already shows live values, which gives the
  user the visual feedback they need.

  **Still open**: how the plugin discovers its destination
  `(client, port)` — iterate the plugin's OUT-port matrix wires at
  first-touch time and pick the unique destination; fall back to
  "no reference, suppress until external write" when ambiguous
  (multiple destinations) or disconnected.
- **TODO: Preset Trigger** plugin — `(channel, note) → preset_name`.
  Calls the matrix preset-load API on note-on. Behaviour around hung
  notes during the swap is now mostly handled by the Engine track's
  edge-diff work; the remaining question is whether a dedicated
  panic-before-load toggle is still needed.
- **TODO: SysEx-Sender** plugin — virtual instrument in `plugins/`
  that ships a `.syx` file (uploaded via the config panel; hex-string
  paste possibly also accepted) to its connected destination, with
  configurable throttling (bytes/sec or inter-message delay) for slow
  targets and a Button param to fire a one-shot send. Open: where the
  uploaded file lives (plugin config blob vs. separate filesystem
  path), whether send progress is streamed to the UI, and whether
  hex-string input is in scope for v1.
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

## Dropped

- **USB Network gadget** (formerly §9). Pi 3 routes USB through a
  LAN9514 hub that doesn't expose OTG / peripheral mode, so there's
  no way to make the Pi appear as a USB-Ethernet device on the
  current target hardware. Pi 4 / 5 / Zero would support it, but
  not the deploy target. Spec preserved in git history if we ever
  switch hardware.

## Not planned right now (but noted for later)

- Multi-pattern chains / song mode.
- MIDI file import/export of patterns.
- Per-track effects (delay, stutter) inside the rhythm sequencer — do
  that via the matrix by chaining the existing `MIDI Delay` plugin.
- Tracker: per-step CC automation column.
- Live-coded patterns (e.g. Tidal-style).
