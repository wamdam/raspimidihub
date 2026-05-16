# Plan: User-bindable MIDI CC for plugin controls

A planning doc for the 4.1.0 release. Replaces the class-level
`cc_inputs` static dict with per-instance, user-editable bindings
that any knob / wheel / fader / radio / button can carry. Discovery
moves into the UI — long-press a control to open its binding popup;
no more reading the help text to find which CC drives RATE.

Status: planning. No code yet. Branch: `feature/cc-binding`.

## Motivation

Today every plugin declares a class-level dict:

```python
class Arpeggiator(PluginBase):
    cc_inputs = {70: "pattern", 74: "rate", 75: "gate", ...}
```

Three problems with that shape:

1. **Class-level, not instance-level.** Two Arpeggiators on the same
   Pi take the *same* CC numbers. The only way to drive them
   independently is via the routing-level CC→CC mapping, which is a
   second layer the user has to reason about.
2. **Channel-blind.** The dispatch path looks up by CC number only;
   the incoming channel is ignored. If your hardware controller sits
   on channel 1 and you'd like its CC 74 to hit Arp 1 while channel 2
   CC 74 hits Arp 2, you can't say so directly.
3. **Discoverability is in the docs.** Users learn which CC drives
   which knob by reading chapter 11 or the per-plugin HELP — not by
   touching the knob.

The feature replaces all three with a per-instance, per-param,
channel-aware binding state, stored in the config and editable
through a long-press popup on the control itself.

## The end-state UX

### Long-press / right-click on any knob, wheel, fader, radio, button

Opens a small modal popup over the current panel. The popup shows:

- **What you're binding** — heading line: `Arp 1 → Rate`.
- **Current binding** — `Channel: Any | 1 .. 16` dropdown, `CC: 0 .. 127`
  numeric field.
- **MIDI Learn** button — listens for the next inbound CC on any
  routed source; fills the fields automatically. Cancel anytime.
- **Default** line: `Plugin default: Any · CC 74`.
- **Reset to default** button — re-applies the plugin author's
  `default_cc`, channel = Any.
- **Clear** button — removes the binding entirely. The param will
  no longer respond to any CC.
- **Other params on this CC** — informational. If `Ch=Any, CC=74` is
  already used by `Arp 2 → Rate`, the popup lists them:
  `Also drives: Arp 2 → Rate, CC LFO 1 → Freq` (truncated to "+N more"
  past three). Collisions are intentional, not blocked — the user may
  want one CC moving multiple controls simultaneously.
- **Save** / **Cancel**.

Triggers: long-press on mobile (~500 ms, same threshold the pattern
bank uses); right-click on desktop. Both fire the same popup.

### Settings sub-navigation

Settings becomes a sub-page-style hub. Top bar reads `< Settings /
Sys Info >`, with a back-arrow on the left and a section title
adjusted per sub-page — same pattern as the Play / Controller
surfaces.

Sub-pages, in order:

| Sub-page | Content |
|---|---|
| **Sys Info** | Version banner, **Reload** button, **Reboot** button, system info (uptime, IP, MAC, USB topology, BLE adapter, free disk) |
| **Network** | Wi-Fi mode (Station / AP / Hybrid), captive-portal info, BT pairing |
| **MIDI** | New-device default routing (All / None), MIDI activity bar setting |
| **Display** | The four browser-local toggles (activity bar, knob/wheel sounds, scroll-assist, density) |
| **Update** | Check for update, current version, install update |
| **Plugin Control Mappings** | New: flat table of every binding across all plugin instances; filterable; row-edit reopens the popup |

The Per-tab sub-state hook (the one that remembers your last Play
instance) extends to Settings — bouncing through Settings → Plugin
Control Mappings → Routing → Settings lands back on the Mappings
page, not the Sys Info default.

## Backend model

### Param dataclasses gain `default_cc`

Today the binding is declared centrally in a dict; we move it to
the param itself:

```python
# Before
class Arpeggiator(PluginBase):
    params = [Knob(name="rate", ...), Knob(name="gate", ...)]
    cc_inputs = {74: "rate", 75: "gate"}

# After
class Arpeggiator(PluginBase):
    params = [
        Knob(name="rate", default_cc=74, ...),
        Knob(name="gate", default_cc=75, ...),
    ]
```

`default_cc: int | None = None` on `Wheel`, `Knob`, `Fader`, `Radio`,
`Button`. `None` means "no default; user can still bind via popup".

The class-level `cc_inputs` dict goes away entirely — the manifest
that the frontend reads derives bindings from each instance's
runtime `cc_map`.

### Per-instance `cc_map`

The instance carries a dict:

```python
cc_map: dict[str, dict] = {
    "rate": {"ch": None, "cc": 74},     # Any channel
    "gate": {"ch": 0,    "cc": 75},     # Channel 1 only
}
```

At instance creation, `cc_map` is seeded from each param's
`default_cc` with `ch=None`. Config-restore overrides the seed
with whatever the user saved. Editing in the popup mutates
`cc_map` and broadcasts it via SSE.

`ch` field semantics: `None` = "any channel" (matches today's
channel-blind behaviour), `0..15` = MIDI channel 1..16 (the wire
value, 0-indexed).

### CC dispatch path

`src/raspimidihub/plugin_host/host.py` line 486 today reads:

```python
if cc_num in plugin.cc_inputs:
    param_name = plugin.cc_inputs[cc_num]
    self._cc_to_param(instance, param_name, cc_val)
```

After:

```python
for param_name, binding in plugin.cc_map.items():
    if binding["cc"] != cc_num:
        continue
    if binding["ch"] is not None and binding["ch"] != ev.data.control.channel:
        continue
    self._cc_to_param(instance, param_name, cc_val)
# fall through to on_cc only if no binding matched
```

Loop instead of dict lookup because collisions are allowed (multiple
params on the same CC). The dispatch list is small (≤ 20 params per
instance × ≤ 10 instances), so the linear scan is fine. If it shows
up in profiles, we add a reverse index `{(ch, cc): [param_names]}`
rebuilt on cc_map edit.

### Config schema

Each plugin instance dict in the JSON config gains an optional
`cc_map` field:

```json
{
  "plugin": "arpeggiator",
  "name": "Arpeggiator 1",
  "params": { "rate": 80, "gate": 50 },
  "cc_map": {
    "rate": { "ch": null, "cc": 74 },
    "gate": { "ch": 0,    "cc": 75 }
  }
}
```

Missing `cc_map` → defaults apply (every param with a `default_cc`
gets `{ch: None, cc: <default_cc>}`). Existing config files don't
need a migration — they just load with default bindings, same as a
fresh install.

When the user clears every binding on a param, that entry is *stored*
in `cc_map` as `{"ch": null, "cc": null}` (or absent — TBD), so the
"clear" is durable across boots and not re-seeded from the default.

### Plugin manifest

`get_plugin_manifest` already returns `cc_inputs`. Replace with
`cc_map` (the live, per-instance dict) and `default_cc_map` (the
plugin author's defaults, for the "Reset to default" button). The
frontend reads both.

### REST + SSE

| Endpoint | Verb | Body | Effect |
|---|---|---|---|
| `/api/plugins/{id}/cc-map/{param}` | `PUT` | `{ch: int\|null, cc: int\|null}` | Set or clear binding |
| `/api/plugins/{id}/cc-map/{param}` | `DELETE` | — | Reset to plugin default |
| `/api/plugins/cc-mappings` | `GET` | — | Flat list for the Settings page |
| `/api/cc-learn/start` | `POST` | `{instance_id, param}` | Arm Learn; returns `learn_id` |
| `/api/cc-learn/cancel` | `POST` | `{learn_id}` | Cancel armed Learn |

SSE events:

- `cc_learn_result` `{learn_id, ch, cc}` — sent when the first
  inbound CC after `cc-learn/start` arrives on any source. Learn
  auto-cancels after 30 s with `cc_learn_timeout`.
- `cc_map_changed` `{instance_id, param, ch, cc}` — broadcast on
  every binding edit so all open panels stay in sync.

Learn mode is global, not per-source: any CC on any routed device
triggers it. The frontend pops a "Move the knob you want to bind"
banner while armed.

## Frontend pieces

### `static/components/ccbinding.js` — new

Popup component. Props:

- `instanceId`, `paramName`, `paramLabel`, `pluginName`
- `current` `{ch, cc}`
- `defaultCc` (int | null)
- `collisions` (computed in JS from the global manifest cache)
- `onSave(ch, cc)`, `onClear()`, `onResetDefault()`, `onClose()`

Renders the modal, owns the Learn flow (POST start, listen for SSE
`cc_learn_result`, prefill fields). Closes on outside-tap or Esc.

### Per-param renderers

Wheel / Knob / Fader / Radio / Button get a long-press handler
(reusing the same timer pattern as the pattern bank), and a
desktop `oncontextmenu` handler. Both open `<CcBinding />` for the
current param.

This means touching `static/components/renderparam.js` and the five
specific param renderers it dispatches to. Keep the handler logic
in renderparam (single source) so the renderers stay thin.

### `static/pages/settings.js` — restructure

Current Settings page becomes a sub-router. New components:

- `settings_sys_info.js` — version, Reload, Reboot, system info
- `settings_network.js` — Wi-Fi mode, captive portal
- `settings_midi.js` — routing default, activity bar setting
- `settings_display.js` — current Display section
- `settings_update.js` — update check + install
- `settings_cc_mappings.js` — the new flat-table sub-page

The top-level Settings page becomes a list of cards / links, each
opening the corresponding sub-page. Sub-page header is the
`< Settings / <title> >` bar.

Per-tab sub-state already remembers `settings` as a key; extend it
to remember the active sub-page (`settings:sysinfo`, `settings:network`,
…) so bouncing through tabs returns to the same sub-page.

### Plugin Control Mappings page

Table view, columns: **Plugin** | **Param** | **Ch** | **CC** | **Edit**.

Rows are pulled from `/api/plugins/cc-mappings` (a flattened walk
over every instance's `cc_map`). Click a row → opens the same
binding popup as long-press. Empty `ch` / `cc` cells indicate
cleared bindings; the popup's "Reset to default" reinstates them.

Sort options: by plugin name (default), by CC number, by channel.
Filter input scopes to plugin name or param substring.

Bulk actions (deferred — Phase 5 polish, not blocking ship):
"Reset all bindings on this plugin", "Clear all bindings on this
plugin". Cards across the top of the table; act on the current
filter scope.

## Routing-level CC→CC mapping — keep it

The user confirmed: keep it. Still useful for:

- Hardware controllers and synths where a CC needs renaming on the
  wire (e.g. a synth that expects CC 7 for volume but the controller
  sends CC 11).
- Bus-style flows where one CC fans out to multiple devices via the
  matrix, not via plugin bindings.

Documentation update: chapter 10 explains the matrix mapping is for
device-to-device CC rewriting; chapter 11 explains the per-plugin
binding popup. They serve different layers.

## Documentation impact

This is a non-trivial manual pass. The CC binding feature changes
how users discover *and* manage CC routing — the chapters that
currently teach the old model need rewriting.

| Chapter | Edit |
|---|---|
| **11 Plugins, §11.7 CC Automation** | Rewrite. Drop the "Arpeggiator takes CC 74 as RATE" sentence; explain the long-press popup instead. Reference the Mappings sub-page in Settings. |
| **11.8 Plugins, intro paragraphs** | Drop the "CC 70..88" mentions in the Arpeggiator / Euclidean one-liners. The defaults still exist; they're just an implementation detail visible in the popup. |
| **13 Play Surfaces** | Drop the CC-number callouts from the Arpeggiator and Euclidean sections. Add a short paragraph in the chapter intro pointing at the binding popup. |
| **16 Settings** | Heavy rewrite. Old: one page of cards. New: hub page + six sub-pages described individually. Add the Plugin Control Mappings sub-page. |
| **Appendix A** | Keep the "default CC" column. Add a footnote: "default — change via long-press on the control or in Settings → Plugin Control Mappings." |
| **Appendix E REST/SSE** | New rows for the cc-map endpoints + learn flow. |
| **README** | Marketing-style sweep — anywhere "CC 74" is named, replace with the binding-popup story. |
| **Plugin HELP text** (every `HELP = """..."""` block) | Strip CC numbers; add "Long-press any knob to bind it to a MIDI CC." |

Screenshots to regenerate:

- Long-press popup (Arp Rate, channel = Any, default and bound states)
- Settings hub page (the new card list)
- Settings → Plugin Control Mappings (populated table)
- Settings → Sys Info (Reload + Reboot moved here)

Add scenes in `scripts/screenshots/run.py` for each.

## Phasing

Five phases, each lands as its own commit (or small commit cluster).
Each phase passes its tests before the next starts.

### Phase 1 — Schema + backend, no UI

- Add `default_cc` to Wheel, Knob, Fader, Radio, Button in
  `plugin_api.py`. Default None.
- Add `cc_map` instance attribute to `PluginBase`. Seed from
  `default_cc` declarations.
- Migrate every plugin: delete its `cc_inputs` dict, add `default_cc`
  to the matching params. List of plugins to touch:
  - `arpeggiator` (6 entries)
  - `euclidean` (18 entries)
  - `cc_lfo` (2)
  - `panic` (1)
  - `note_transpose` (1)
  - `note_splitter` (1)
  - `midi_delay` (2)
- Update CC dispatch in `host.py` to iterate `cc_map`.
- Update manifest emission: replace `cc_inputs` with `cc_map` +
  `default_cc_map`.
- Add `cc_map` field to plugin save/restore.
- REST endpoints for set / clear / reset.
- Learn-mode armed-state on the host, SSE result event.
- Tests: a) defaults derived correctly from `default_cc`, b)
  config round-trip preserves user bindings, c) collision dispatch
  fires every matching param, d) channel filter respects the wire
  channel, e) clear is durable across restart.

### Phase 2 — Popup + per-param handlers

- `ccbinding.js` component (popup, fields, learn integration).
- Long-press + right-click handlers on Wheel / Knob / Fader / Radio /
  Button.
- Collision computation client-side from the manifest cache.
- Validate end-to-end against the Pi: bind Arp 1 → Rate to a
  hardware knob via Learn, verify the param moves.

### Phase 3 — Settings sub-nav

- Restructure Settings page into hub + sub-pages.
- Move Reload / Reboot into Sys Info.
- Extend per-tab sub-state to remember the active Settings
  sub-page.

### Phase 4 — Plugin Control Mappings page

- Flat-table sub-page, row → popup edit, sort + filter.
- Bulk Reset / Clear deferred unless time allows.

### Phase 5 — Docs + screenshots + changelog

- All the manual edits in the table above.
- New screenshots in `scripts/screenshots/run.py`.
- CHANGELOG headline for the 4.1.0 release.

## Decisions settled

- **Channel default**: new bindings default to `Any`. Matches
  today's channel-blind behaviour; the user opts into channel-
  specific via the popup.
- **Collisions**: allowed and informational. The popup lists
  other params on the same CC for awareness; it doesn't block.
- **Cleared bindings**: durable. A param the user has cleared
  stays cleared across reboots — it doesn't get re-seeded from
  `default_cc`. (Implementation TBD: stored as
  `{"ch": null, "cc": null}` or as a `_cleared: [...]` list.
  Phase 1 picks one and writes the migration test.)
- **Bindable param types**: Wheel, Knob, Fader, Radio, Button.
  StepEditor, PatternStrip, Group, Display, ChannelSelect,
  NoteSelect are not bindable (too complex / not a 0..127 value).
  NoteSelect *could* be bindable to a CC-as-pitch flow in a future
  release; out of scope here.
- **Multi-CC per param**: no. One CC per param. Same CC may drive
  multiple params (collision case above).
- **Learn scope**: any CC on any routed source. The popup doesn't
  filter by what's routed to *this* plugin — the user is binding
  the control, not the routing.
- **Routing-level CC→CC mapping**: stays. Different layer, still
  earns its keep for device-to-device flows.

## Open questions

- **Cleared-binding storage shape.** `{"ch": null, "cc": null}` is
  the JSON-natural representation; a `_cleared: ["rate", "gate"]`
  sidecar list is shorter on the wire. Pick one in Phase 1.
- **Learn timeout**: 30 s feels right. Tweak if testing shows it's
  too short to walk over to the controller.
- **Button binding semantics**: today a Button has no value; CC
  ≥ 64 fires it. Could also do "on rising edge" only (any value
  64..127 fires, then re-armed at < 64). Phase 2 settles this with
  a hardware test.

## CHANGELOG headline (draft)

```
Added: User-bindable MIDI CC for every plugin control. Long-press
any knob, wheel, fader, radio, or trigger button to open the
binding popup — pick a channel (Any / 1..16) and CC (0..127)
manually or with MIDI Learn. Defaults come from the plugin author
and are shown in the popup. Per-instance bindings persist in the
config; same CC may drive multiple controls.

Changed: Settings page split into sub-pages (Sys Info, Network,
MIDI, Display, Update, Plugin Control Mappings). Reload and
Reboot moved to Sys Info. New Plugin Control Mappings sub-page is
a flat editable table of every CC binding across all plugins.

Removed: Per-plugin `cc_inputs` static dict. The default-CC
declarations now live on each param dataclass (Wheel / Knob /
Fader / Radio / Button) via a new `default_cc` field.
```
