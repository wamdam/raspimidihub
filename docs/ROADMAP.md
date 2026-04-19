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

1. **Phase 1 — Rhythm Sequencer MVP**
   - Python plugin + `DrumGrid` + `GenreTemplatePicker` params.
   - 5 genres × 5 templates to start (Techno, House, DnB, Hip-Hop, Trap).
   - Genre profiles for Randomize on those 5.
2. **Phase 2 — Rhythm Sequencer genre expansion**
   - Round out to the full 21 genres and their ≥5 templates.
3. **Phase 3 — Tracker MVP**
   - Python plugin + `TrackerGrid` param.
   - Steps, play, record, overdub, clear.
4. **Phase 4 — Tracker polish**
   - Copy/paste bars, transpose, paginator, live pass-through toggle.

Each phase ships independently behind its own plugin; no flag days.

---

## Not planned right now (but noted for later)

- Multi-pattern chains / song mode.
- MIDI file import/export of patterns.
- Per-track effects (delay, stutter) inside the rhythm sequencer — do
  that via the matrix by chaining the existing `MIDI Delay` plugin.
- Tracker: per-step CC automation column.
- Live-coded patterns (e.g. Tidal-style).
