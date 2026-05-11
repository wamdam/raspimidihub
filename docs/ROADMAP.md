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

## 1. Matrix Undo / Redo

> **Deferred to the very end of the roadmap.** The Command-stack
> approach below needs to wrap whatever final shape the API ends up
> in, so we want the API to be settled first.

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

## 2. Drawable LFO (`CC Curve LFO`)

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

## Phased rollout

Features ship independently — these are proposed orderings, not
dependencies.

**Workflow track** (Undo/Redo is the only remaining piece)
1. ✓ Matrix Context Menu — Edit / Copy / Paste / Remove scaffolding.
2. ✓ Clipboard for connections — filter + mappings stack.
3. ✓ Clipboard for plugins — paste-as-new + paste-over-instance.
4. Undo / Redo — client-side `Command` stack, toolbar buttons,
   keyboard shortcuts, labelled toasts. (§1)

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

Each phase ends in a release.

### Phase 7 — Modulator (≈ 0.5–1 sprint)

Creative, niche, no other dependencies.

1. **CurveEditor extensions**: `wrap` flag, `shapes` pulldown
   replacing preset pills, Smooth button. `velocity_curve` benefits
   for free.
2. **Drawable LFO** (`CC Curve LFO`, §2).

### Phase 9 — Undo / Redo (≈ 0.5–1 sprint)

Last on purpose: the Command-stack abstraction (§1) wraps the REST
API surface, so we want every other feature's endpoints to be
finalised before we commit to wrapping them.

1. Client-side `Command` class + dual-stack history (cap 100).
2. Wrap every existing mutating call site (matrix toggle, mapping
   add/remove/edit, plugin add/remove, rename, paste).
3. Toolbar Undo/Redo buttons + Ctrl+Z / Ctrl+Shift+Z bindings.
4. Labelled toasts ("Undid: …").
5. SSE reconciliation: drop redo stack on any external change.

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
  useful for §2 (CC Curve LFO destinations) and a future SysEx
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

- MIDI file import/export of patterns.
