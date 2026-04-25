# RaspiMIDIHub Roadmap

Living doc for upcoming work — discuss + adjust before any implementation.
Items listed are **proposals**, not commitments.

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
  list. Cell types in v1: **Knob**, **Fader**, **Toggle**, **XY pad**.
  Each cell stores a name, color, and one or two `(channel, cc)`
  bindings (XY pad has two — one per axis).
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

### Phase 1 — Foundation + small win (≈ 1 sprint)

Small, mostly-mechanical work that delivers a couple of visible
things and de-risks the bigger Engine changes in Phase 2.

1. **Clock Divider plugin** (§8). Smallest fully-spec'd plugin.
   Forces us to land:
   - new `"tick": 1` entry in `DIVISION_TICKS`,
   - new `on_transport_continue` plugin callback + ClockBus
     `_notify_transport("_continue")`.
2. **Per-edge note refcount table** (§6). Pure data, no behaviour
   change yet. Engine starts tracking `(edge_id, channel, note) →
   count` so we know exactly which notes are sounding on which edges.
3. **Soft / hard panic with the double-tap state machine** (§6).
   Uses 1.2's table. Existing Panic button gains the Elektron-style
   double-press to upgrade to hard.

### Phase 2 — Engine smoothness (≈ 1 sprint)

The big invasive Engine change. **Highest test coverage of any
phase** — it touches the live MIDI hot path.

1. `MidiEngine.apply_edge_diff(target_edges)`. Replace the
   `disconnect_all() + _apply_saved_config()` pair in
   `api_load_config` with the diff-and-apply algorithm from §6.
2. Synthetic edge-diff tests covering all permutations
   (removed-only, added-only, both, changed-filter, changed-mappings,
   untouched).
3. End-to-end Pi test: load a preset while a synthesised note is
   sounding on a soon-to-be-removed edge → assert clean note-off,
   assert untouched edges receive nothing extra.

After this, Preset Trigger is essentially a 30-line plugin —
stays in pending until requested.

### Phase 3 — Foundation for Controllers (≈ 0.5 sprint)

Foundation work the Controller MVP depends on. Nothing user-visible
ships in this phase alone, but everything in 4 builds on it.

1. **UI controls refactor** (§11). Split `plugin-controls.js` into
   `components/*.js`. Acceptance: every existing plugin renders
   identically.
2. **UI sizing rules** (§9) baked into `plugin_api.py` param
   dataclasses (`size_w`, `size_h` defaults per type) + the
   renderer reads them.
3. **UI Demo plugin** (§10). Lands now so subsequent Knob / Fader /
   XY pad work has a live target to render into.
4. **CC observatory** (§5 engine plumbing). Cache last-seen value
   per `(client, port, ch, cc)`; broadcast on change via SSE
   `cc-snapshot`. Useful side-benefit: matrix can later show live
   CC values on cells.

### Phase 4 — Controller MVP (≈ 1 sprint)

Biggest user-visible win for performance.

1. `LayoutGrid` + `PluginXYPad` UI param types (§5).
2. Controller plugin: Knob / Fader / Toggle / XY pad cells, OUT port
   emit, IN port for MIDI Learn + bidirectional sync. Drop pad with
   short-press fire / long-press capture **only** — autodrop and
   preview deferred to 5.
3. Top-nav "Controller" entry, fullscreen mode, `localStorage`
   last-viewed persistence.

### Phase 5 — Controller polish (≈ 0.5 sprint)

1. **Autodrop**. Bar-quantized fire scheduling via the existing
   ClockBus. Free now that 1.1 added the new tick infrastructure.
2. **Preview mode**. Ghost indicators on cells.
3. Whatever the MVP usage in Phase 4 surfaced.

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
5. **Undo / Redo**. Client-side `Command` stack, labelled toasts,
   Ctrl+Z + toolbar buttons.

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

- **`cc_lfo` per-cycle gate pattern** — `StepEditor`-style 1–32 step
  pattern that mutes/un-mutes whole LFO cycles for ducking-style
  effects (e.g. `0111` = first cycle off, next three on). Behaviour
  during an off step (silent / hold-last / configurable rest value)
  TBD.
- **CC Sequencer** — step-based plugin emitting up to 4
  `(channel, cc, value)` per step, with arm-and-record from the CC
  observatory. Step grid UI shared with the Tracker.
- **Preset Trigger** plugin — `(channel, note) → preset_name`. Calls
  the matrix preset-load API on note-on. Behaviour around hung notes
  during the swap is now mostly handled by the Engine track's
  edge-diff work; the remaining question is whether a dedicated
  panic-before-load toggle is still needed.
- **SysEx-Sender** plugin — virtual instrument in `plugins/` that
  ships a `.syx` file (uploaded via the config panel; hex-string
  paste possibly also accepted) to its connected destination, with
  configurable throttling (bytes/sec or inter-message delay) for slow
  targets and a Button param to fire a one-shot send. Open: where the
  uploaded file lives (plugin config blob vs. separate filesystem
  path), whether send progress is streamed to the UI, and whether
  hex-string input is in scope for v1.
- **Per-version changelog in the Settings update card** — the
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
