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
  - `name` (display only)
  - `channel` (1-16), `note` (0-127), `velocity` (default, 1-127)
  - `mute` toggle
  - `pattern`: list of booleans of length `steps`, optional per-step
    velocity/accent
  - `randomize` button
- **Per-pattern state**:
  - `genre` (Radio): Techno, House, Tech-House, Minimal, Trance, Acid,
    DnB, Jungle, Breakbeat, Dubstep, Trap, Hip-Hop, Lo-Fi, Boom-Bap,
    Reggaeton, Afrobeats, Amapiano, Funk, Disco, Garage, Footwork.
  - `template` (Radio): templates for the current genre (≥5 each).
  - `swing` (Wheel, 0-75%).
  - `rate` (Radio): same set as the arp (1/4 … 1/32 + triplets).
  - `sync_mode`: Free / Tempo / Transport (identical to Arpeggiator).
- **Sync**: MIDI clock (24 PPQ) via existing ClockBus, same sync modes
  as the Arpeggiator.
- **Output**: note on + matching note off (short gate ~30ms, configurable).
  Uses `send_note_on/off` — no aftertouch or CC yet.
- **Randomize**: replaces the pattern of a single instrument with a
  fresh pattern drawn from **that instrument's probability profile for
  the currently selected genre** (see below), so a "randomized kick in
  Techno" still feels like Techno. User-invoked only (no live
  auto-randomization).

### Template format

Templates are JSON files under `plugins/rhythm_sequencer/templates/<genre>/<name>.json`.
Plain data only — no code — so they're sandbox-safe and editable by hand.

```json
{
  "name": "4-on-the-floor + rumble",
  "genre": "techno",
  "bpm_hint": 128,
  "steps": 16,
  "tracks": [
    { "name": "Kick",     "ch": 10, "note": 36, "velocity": 120,
      "pattern": [1,0,0,0, 1,0,0,0, 1,0,0,0, 1,0,0,0] },
    { "name": "Sub",      "ch": 10, "note": 35, "velocity": 90,
      "pattern": [0,0,1,0, 0,0,1,0, 0,0,1,0, 0,0,1,0] },
    { "name": "Clap",     "ch": 10, "note": 39, "velocity": 110,
      "pattern": [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0] },
    { "name": "CH",       "ch": 10, "note": 42, "velocity": 80,
      "pattern": [0,0,1,0, 0,0,1,0, 0,0,1,0, 0,0,1,0] },
    { "name": "OH",       "ch": 10, "note": 46, "velocity": 90,
      "pattern": [0,0,0,0, 0,1,0,0, 0,0,0,0, 0,1,0,0] },
    { "name": "Perc",     "ch": 10, "note": 40, "velocity": 70,
      "pattern": [0,0,0,0, 0,0,0,1, 0,0,0,0, 0,0,0,1] }
  ]
}
```

Per-step velocity is optional — a step can be an object `{"on": 1, "v": 127}`
instead of a bare `0/1`, matching our StepEditor's existing shape. Default
velocity comes from the track.

### Genre probability profiles (for Randomize)

Each genre has, per drum role, a **per-step probability vector** (length
16). Randomize rolls `random() < p[step]` with a minimum density floor to
avoid totally empty tracks.

Stored in `plugins/rhythm_sequencer/templates/_profiles.json`:

```json
{
  "techno": {
    "kick":  [1.00, 0.05, 0.05, 0.05,  1.00, 0.05, 0.05, 0.05,
              1.00, 0.05, 0.05, 0.05,  1.00, 0.05, 0.05, 0.05],
    "ch":    [0.10, 0.10, 0.90, 0.10,  0.10, 0.10, 0.90, 0.10, ...],
    "clap":  [0.00, 0.00, 0.00, 0.00,  0.95, 0.00, 0.00, 0.00, ...]
  },
  ...
}
```

Rule: the template's **track name** determines which profile to use. If
no profile is defined for a given name, Randomize falls back to a bland
25%-per-step probability (flagged in the UI as "Generic").

### UI (new param types we'll need)

- **`DrumGrid` param** — 8 rows × N steps toggle grid with:
  - per-row label + (ch, note) mini-editor
  - per-cell click-to-toggle (with optional accent via long-press)
  - per-row Mute and Randomize buttons
- **`GenreTemplatePicker` param** — two-level Radio: genre → template.
  Selecting a template rewrites the whole `DrumGrid`.

These live in `src/raspimidihub/static/plugin-controls.js` next to
`PluginStepEditor`.

### Persistence

`serialize_instances` already dumps `_param_values`. As long as the full
`DrumGrid` state (tracks + patterns + per-track velocities) is a single
dict/list param, it round-trips with existing config save/load.

### Open questions

1. **Accents**: boolean accent flag per step + flat accent-velocity
   (like the Arp), OR per-step 0-127 velocity (richer but more UI)?
2. **Shuffle/swing implementation**: delay every odd 16th by X ticks, or
   only odd 8ths?
3. **Fill / break**: should "break each 16 steps" be a template, or a
   mode flag on top of any template? Simpler: ship both shapes as
   separate templates.
4. **Gate length**: fixed ~30ms, or per-track configurable? Default
   fixed, promote to param later if needed.

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

**Edit** on a connection cell is today's long-press behaviour (opens
the filter/mapping panel). **Edit** on a plugin header opens the
plugin config panel (same as tap).

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

- **Soft panic** (default tap on the Panic button)
  - For each edge: emit `note_off` for tracked active notes.
  - `CC 123` (All Notes Off) on each used channel.
  - Plugins still get `panic()` so internal state (Hold, Arp) clears.
  - **Does not send `CC 120`** (All Sound Off) — delay / reverb tails
    keep ringing.
- **Hard panic** (long-press the button — or a separate "Sound Off"
  control)
  - Soft panic + `CC 120` on every channel of every destination.
  - For when the rig is genuinely stuck and you don't care about
    tails.

### Where this plugs in

- `MidiEngine.apply_edge_diff(target_edges)` — the new core operation.
- `MidiEngine.panic(hard=False)` — replaces the current `panic()`,
  gains the `hard` flag.
- `api.api_load_config` and the (future) Preset Trigger plugin call
  `apply_edge_diff` instead of disconnecting first.
- `api.api_panic` POST body gains `{"hard": bool}` (default False).

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

1. **Soft vs hard panic surface**. Long-press for hard, or two
   buttons? I'd default to long-press to keep the matrix toolbar
   tidy, with a tooltip on the existing button explaining both
   behaviours.
2. **Delay/reverb tail responsibility**. Soft panic relies on the
   downstream FX device honouring CC 123 (note-off-style behaviour)
   and not interpreting it as CC 120. Most synths do the right
   thing; document the exception list as we encounter it.
3. **Preset Trigger plugin interaction**. With smooth presets,
   panic-before-load becomes unnecessary in normal cases. The
   Preset Trigger plugin can default to "no panic, smooth diff" and
   leave hard panic as a manual user action.

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
  - Rhythm Sequencer: parametrized tests over every genre template (JSON
    schema validation, pattern length == `steps`, notes/channels in
    range). Randomize: test that probability profiles cover the
    instrument names used in their genre's templates; snapshot a seeded
    randomize result.
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
   5 genres × 5 templates (Techno, House, DnB, Hip-Hop, Trap),
   profiles for Randomize on those 5.
2. Rhythm Sequencer genre expansion — full 21 genres × ≥5 templates.
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

---

## Pending design — sketched, not yet specified

These have been discussed at idea-level but need another design pass
before implementation.

- **LFO improvements** on the existing `cc_lfo` plugin:
  - `min` / `max` value bounds (replacing or supplementing
    `depth/offset`).
  - **Per-cycle gate pattern** (e.g. `0111` mutes one cycle in four —
    ducking-style). Pattern length 1–32, default empty (always on).
- **Drawable LFO** — new plugin or mode that walks a 128-point curve
  from the existing `CurveEditor` param at the configured rate.
- **CC Sequencer** — step-based plugin emitting up to 4
  `(channel, cc, value)` per step, with arm-and-record from the CC
  observatory. Step grid UI shared with the Tracker.
- **Clock Divider** plugin — forward every Nth Clock tick, pass
  Start/Stop/Continue intact. ~30 lines.
- **Preset Trigger** plugin — `(channel, note) → preset_name`. Calls
  the matrix preset-load API on note-on. Behaviour around hung notes
  during the swap is now mostly handled by the Engine track's
  edge-diff work; the remaining question is whether a dedicated
  panic-before-load toggle is still needed.
- **USB Network gadget** (lives in `raspimidihub-rosetup`, not the
  app) — Pi exposes a USB ethernet interface via `dwc2` + `g_ether`,
  serves DHCP on `10.55.0.0/24`. Runs in parallel with the AP.
  Settings → Network toggle.

## Not planned right now (but noted for later)

- Multi-pattern chains / song mode.
- MIDI file import/export of patterns.
- Per-track effects (delay, stutter) inside the rhythm sequencer — do
  that via the matrix by chaining the existing `MIDI Delay` plugin.
- Tracker: per-step CC automation column.
- Live-coded patterns (e.g. Tidal-style).
