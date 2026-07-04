# Research Annex 3 — Codebase Impact Map (MIDI 1.0 assumptions)

Compiled 2026-07 from a full read of the repository. Line numbers are as of
commit `77a1ba8`; re-verify before editing (they will drift).

## 0. Repo shape, LOC, packaging

**Python package layout** (`src/raspimidihub/`): `alsa_seq.py`,
`midi_engine.py`, `midi_filter.py`, `midi_codec.py`, `plugin_api.py`,
`controller_base.py`, `plugin_host/` (`host.py`, `alsa_client.py`,
`clock_bus.py`, `instance.py`), `runtime/` (`loops.py`, `coalesce.py`),
`api.py`, `web.py`, `config.py`, `device_id.py`, `network_midi.py`,
`apple_midi.py`, `ble_midi_bridge.py`, `bluetooth.py`, `rawmidi.py`,
`clock_gen.py`, `scales.py`, `slot_bank.py`, `spectator.py`,
`perf_stats.py`, `cpu_affinity.py`, `led.py`, `wifi.py`, `usb_tether.py`,
`update_flow.py`, `__main__.py`. Built-in plugins live in top-level
`plugins/` (26 dirs).

**LOC**: backend core ≈ **18,800** (`src/raspimidihub/**/*.py`), plugins ≈
**7,700**, frontend static (JS+CSS+HTML) ≈ **17,700** (JS alone ≈ 13,700),
tests ≈ **9,700**.

**No third-party MIDI library.** The repo has no `pyproject.toml` runtime
deps and no pip runtime dependencies at all (`debian/control` supplies
`libasound2`, `python3-zeroconf`, optional `python3-dbus-next`). ALSA is
accessed via a **hand-rolled ctypes binding to libasound** in
`src/raspimidihub/alsa_seq.py`. This is the single most important fact for
MIDI 2.0: there is no third-party MIDI library to upgrade — the project
owns its own ALSA sequencer binding, and it binds the **classic MIDI-1.0
`snd_seq_event_t` API only** (no UMP: no `snd_seq_ump_event_t`, no
`snd_seq_client_info_set_midi_version`). UMP support means extending this
ctypes layer by hand (and requires alsa-lib ≥ 1.2.10 / kernel UMP configs
on the Pi image).

## 1. ALSA integration layer

- **`src/raspimidihub/alsa_seq.py`** (754 lines) — the ctypes binding.
  - Structs: `SndSeqEvent` (L223), `SndSeqEventNote` (L187:
    `channel/note/velocity/off_velocity` as `c_uint8` — velocity is
    byte-width in the struct itself), `SndSeqEventCtrl` (L196: `param:
    c_uint`, `value: c_int` — CC value is 32-bit-capable *in the struct*
    but 7-bit everywhere in use), `SndSeqEventExt` (L204, SysEx
    var-length).
  - `MidiEventType` IntEnum (L151):
    NOTEON/NOTEOFF/KEYPRESS/CONTROLLER/PGMCHANGE/CHANPRESS/PITCHBEND/SYSEX
    + realtime. **No enum members for ALSA's high-res event types**
    (CONTROL14/NONREGPARAM/REGPARAM = ALSA types 14–16 are absent), and no
    UMP types.
  - `MSG_FILTER_GROUPS` (L173) — the 7 filter categories the whole filter
    UI is built on.
  - `AlsaSeq` class (L400): opens the seq client, creates an
    announce-listener port subscribed to
    `SND_SEQ_CLIENT_SYSTEM:SND_SEQ_PORT_SYSTEM_ANNOUNCE` (L423–453) —
    **hotplug** arrives as `PORT_START/PORT_EXIT/CLIENT_START/CLIENT_EXIT`
    events (L68–71). Device enumeration: `scan_devices()` L474,
    `scan_one_client()` L541. **Routing = kernel port subscriptions**:
    `subscribe()`/`unsubscribe()` L603/618 (`snd_seq_subscribe_port`).
    Send helpers `send_note_on/off`, `send_cc` L713–742, CC coalescing
    `send_event_coalesced` L673. Mock-lib fallback (L28–37) so tests run
    without libasound.
- **`src/raspimidihub/midi_engine.py`** — `MidiEngine` (L69): owns
  `AlsaSeq`, the `FilterEngine`, a `monitor` port (created in `start()`
  L213–218 to receive copies of all traffic for the UI), `DeviceRegistry`
  glue, `_scan_and_connect` L754, hotplug rescan scheduling
  `_schedule_rescan` L1374, plugin client add/remove L459/507, the async
  pump `run_event_loop()` L809 (single persistent `loop.add_reader` on the
  seq fd, L825), `panic()` L957, per-edge diff apply `apply_edge_diff`
  L1014, active-note tracking `_track_note_event` L1214 and
  CC-destination cache `_track_cc_to_destinations` L1303 (feeds the
  "Observatory" endpoint — stores 0–127 CC values). Config snapshot shape:
  `_snapshot_live_state` L419.
- **`src/raspimidihub/plugin_host/alsa_client.py`** — `PluginAlsaClient`
  (L28): one ALSA client per plugin instance with IN/OUT ports and a
  **per-client named ALSA queue** (L79–90) for kernel-timed scheduled
  sends. `send_event()` L118 (direct, rate-limited to 1000 ev/s "DIN MIDI
  limit"), `send_event_at()` L152 (queue-scheduled at monotonic time),
  `send_sysex()` L210 (chunked/paced), `cancel_tag()` L253 (queue event
  removal by tag). All event construction here fills the MIDI-1.0 union
  fields.
- **`src/raspimidihub/plugin_host/clock_bus.py`** — `ClockBus` (L38):
  24-PPQN tick fan-out to plugins, `tick_to_monotonic()` for pre-queuing.
- **`src/raspimidihub/rawmidi.py`** — raw byte escape hatch for transport
  Start/Stop/Continue that some USB drivers won't convert from seq events;
  sends raw `0xFA/0xFC/0xFB` via `snd_rawmidi`.

## 2. MIDI event representation

**There is no Python-level message class.** The raw ctypes `SndSeqEvent`
*is* the event object end-to-end: engine → filter engine → plugins →
codec. The only bytes↔event translation layer is:

- **`src/raspimidihub/midi_codec.py`** (158 lines) — `event_to_midi()`
  L32 / `midi_to_event()` L84, shared by the network-MIDI bridge.
  Wall-to-wall 7-bit: every field masked `& 0x7F`; pitch bend
  packed/unpacked as 14-bit (`(msg[2] << 7) | msg[1]`, L142). Note: it
  treats pitch bend as **unsigned 0–16383**, while ALSA kernel devices
  deliver **signed −8192..+8191** in `data.control.value` — no offset
  conversion is applied in either direction (same in the BLE bridge).
  **Pre-existing bug candidate — verify during FSD work on pitch bend.**
- **`src/raspimidihub/ble_midi_bridge.py`** — carries **its own
  duplicate** channel-voice encode/decode subset (`_event_to_midi`, event
  build around L565/661), acknowledged as a copy in midi_codec's
  docstring.

**7-bit hardcode census (backend)** — hits of
`127|0x7f|16383|8192|<<7|>>7` per module, characterized:

| Subsystem | Files (hits) | Nature |
|---|---|---|
| Wire codecs | `midi_codec.py` (14), `ble_midi_bridge.py` (13), `apple_midi.py` (1) | `& 0x7F` masks, 14-bit pitch-bend packing |
| Controller templates | `controller_base.py` (19) | cell-value→CC clamps `max(0, min(127, …))` (L243–296, 630, 684, 839–896) |
| Plugin param schema | `plugin_api.py` (12) | `min=0, max=127` defaults on Wheel/Knob/Fader |
| Mappings | `midi_filter.py` (10) | mapping defaults (`cc_on_value=127`, ranges 0–127) + `_scale_value` clamp L129 |
| CC→param binding | `plugin_host/host.py` (4) | `_cc_to_param` L567: `value = pmin + (cc_value / 127) * (pmax - pmin)` |
| Plugins | `tracker/tracker_base.py` (13), `cc_lfo` (10), `velocity_equalizer` (8), `arpeggiator` (7), `pitch_cc` (5), `euclidean` (5), `cc_smoother` (5), controller_* templates, etc. | velocity/CC output ranges, LFO amplitude 0–127, velocity curve maths |

There are **zero** hits of `16383`/`8192` anywhere in the backend — pitch
bend values are passed through opaquely; nothing computes with the center
value.

## 3. Filters and mappings

All in **`src/raspimidihub/midi_filter.py`**:

- `MappingType` (L29) — exactly 5: `note_to_cc`, `note_to_cc_toggle`,
  `note_to_note`, `cc_to_cc`, `channel_map`.
- `MidiMapping` dataclass (L38): `cc_on_value: int = 127`, `cc_off_value:
  int = 0`, `in_range_min/max = 0/127`, `out_range_min/max = 0/127`;
  `cc_value_source="velocity"` forwards note-on velocity (0–127) as CC
  value. `_scale_value()` L122 clamps output to `max(0, min(127, …))`.
  Serialization `to_dict`/`from_dict` L69/96 → these field names land
  verbatim in `config.json`.
- `MidiFilter` (L241): `channel_mask` (16-bit, `ALL_CHANNELS = 0xFFFF`) +
  `msg_types` set from `ALL_MSG_TYPES` (L24: note/cc/pc/pitchbend/
  aftertouch/sysex/clock). MIDI 2.0's group/16-channels-per-group model
  collides with this 16-channel mask.
- `FilterEngine` (L321): unfiltered edges stay **kernel subscriptions**; a
  filter/mapping converts the edge to userspace — per-edge read/write
  ports, `process_event()` L471, `_apply_mappings()` L528 (velocity
  comparisons like `velocity > 0` for note-on-as-off), `_forward_cc()`
  L518. Mapping validation/dedup: `validate_new_mapping` L132.
- Tests: `tests/test_midi_filter.py`, `test_filter_pipeline.py`,
  `test_mapping_validation.py`.

## 4. Plugins

- **Param declaration** — `src/raspimidihub/plugin_api.py`: `Param` base
  (L39) + `Wheel`/`Knob`/`Fader` (all `min=0, max=127, default=0` class
  defaults, L74–141), `Radio`, `StepEditor`, `CurveEditor` (128-point
  0–127 curve), `NoteSelect`, `CCSelect`, `ChannelSelect`, `Button`,
  `Display`, `PatternStrip`, `DropButtonRow`, `XYPad`, `CartesianGrid`,
  `LayoutGrid`/`StructuralParam`. `default_cc: int | None` is a kw-only
  field on every bindable type (Wheel L86, Knob L116, Fader L141, Radio
  L161, NoteSelect L217, Button L277) — seeds the instance `cc_map`.
  `PluginBase` (L701): `params`, `cc_outputs: list[int]` (documentary
  outgoing CC list), `cc_map` per instance.
- **MIDI I/O** — `plugin_host/host.py` `_start_instance()` L225–330
  injects `_send_note_on/off/cc/pitchbend/aftertouch/program_change/clock/
  sysex` (+ `_send_*_at` scheduled variants) as lambdas over
  `PluginAlsaClient.send_event(_at)`. Inbound dispatch `_dispatch_event()`
  L507: `on_note_on(ch, note, velocity)`, `on_note_off`, and the
  **CC-binding walk** (L524–540): incoming CONTROLLER events are matched
  against each instance's `cc_map` `{param: {ch, cc}}`, then
  `_cc_to_param()` L567 linearly maps **cc_value/127** onto the param's
  min–max (or Radio option index). This is the exact spot 32-bit CC
  resolution would land.
- **Binding persistence**: `get_default_cc_map` / `_diff_cc_map` (host.py
  L18/L30) — only user-overridden bindings are saved as `cc_map` in
  config. REST: `PUT /api/plugins/instances/…/cc-map/…` (api.py L2709),
  `GET /api/plugins/cc-mappings` (L2442), MIDI Learn `POST
  /api/cc-learn/start|cancel` (L2398/2430) with the armed-learn observer
  `_cc_learn_observe` at api.py L410 (emits SSE `cc_learn_result` /
  `cc_learn_timeout`).
- **Note/CC generators**: `tracker` (notes+CC lanes, `tracker_base.py`),
  `arpeggiator`, `euclidean`, `chord_generator`, `cartesian` (note
  sequencers), `cc_lfo`, `cc_smoother` (CC), `pitch_cc` (note→pitch-CC,
  passes `on_pitchbend` through), `velocity_curve`/`velocity_equalizer`
  (velocity transforms — pure 7-bit math), `note_transpose`,
  `note_splitter`, `scale_remapper`, `hold`, `midi_delay`,
  `channel_selector`, `clock_divider`, `master_clock`, `panic`,
  `sysex_sender`, `latency`, and 4 controller templates
  (`controller_mixer_8`, `controller_fx_6`, `controller_performance_16`,
  `controller_xy_4`) built on **`src/raspimidihub/controller_base.py`**
  `ControllerBase` (L30): `_cell_value_to_cc()` L243 clamps to 0–127;
  `_store_cc_into_cell()` L253; xypad emit L281; bidirectional `on_cc`
  sync L296; drop-scheduling via `send_cc_at` L684.

## 5. Web UI

Vanilla Preact+htm ES modules under `src/raspimidihub/static/`, no build
step. Wholly 7-bit; **no 14/16/32-bit constant exists anywhere in the
frontend**.

- **Widgets** (`static/components/`): `knob.js`, `wheel.js`, `fader.js`
  take `min`/`max` from the server param schema (generic), but: `wheel.js`
  renders **one tick per integer value** (L225 — unusable at 32-bit
  ranges), `xypad.js` hardcodes `lo=0/hi=127` fallbacks (L31–32),
  `noteselect.js` `MAX=127` (L24), `ccselect.js` `MAX=127` (L19),
  `ccbinding.js` CC wheel hardcoded 0–127 (L296), `cellbinding.js` (L314),
  `display.js` meter/scope fallback `hi=127`, `curveeditor.js` fully
  hardcoded 128-point/`/127` math, `layoutgrid.js` cell editor hardcodes
  0–127 On/Off CC values.
- **Param rendering**: `components/renderparam.js` (dispatcher; range
  comes entirely from `param.min/max` in the manifest) +
  `ui/plugin-params.js` (`usePluginParams`, rAF-coalesced `PATCH
  /api/plugins/instances/{id}`).
- **Routing matrix**: `pages/routing.js`, `pages/matrix.js` — per-endpoint
  `extra` object at matrix.js **L125** (`client_id, dev_name, port_name,
  online, stable_id, is_plugin, is_bluetooth, is_network, remote_hub`) is
  *the* place a device-capability flag (MIDI-CI / UMP) would surface, fed
  from `GET /api/devices`. Rack view: `pages/rack.js` +
  `ui/rack-engine.js`, shared `ui/connections.js`.
- **Filter/mapping editor**: `panels/filterpanel.js` (channel mask
  `0xFFFF`, 16-ch grid) and `panels/mappingform.js` — the densest frontend
  hardcode hotspot: every range wheel `min=0 max=127` (L187–246), defaults
  127/0.
- **MIDI monitor**: `panels/devicedetail.js` — `formatEvent()` L355
  (`vel={velocity}`, `cc{cc}={value}`), test sender wheels 0–127, piano
  guard `>127`; header midi-bar formatter in `app.js` L303–305. CC binding
  popups orchestrated from `app.js` `openCcBinding` L454.
- **SSE plumbing**: `ui/sse-subscriptions.js` (per-view subscribe via
  `POST /api/sse/subscribe`); ~6 independent consumers parse
  `midi-activity`'s 7-bit `note/velocity/cc/value` fields (`app.js`,
  `devicedetail.js`, `mappingform.js`, `ccselect.js`, `noteselect.js`,
  cell/cc binding learn).

## 6. Config schema

**`src/raspimidihub/config.py`** — `DEFAULT_CONFIG` L143: top-level keys
`version`, `mode`, `default_routing`, `connections`, `disconnected`,
`wifi`, `network_midi`, plus `plugins` (instances), `device_names`.
Connection entries (shape built in `midi_engine._snapshot_live_state`
L419) carry `src/dst_client`, `src/dst_port`, `src/dst_stable_id`,
optional `filter` (`MidiFilter.to_dict`) and `mappings` (list of
`MidiMapping.to_dict` — raw CC numbers and 0–127 values: `cc_on_value`,
`in_range_*`, `out_range_*`). Plugin instance entries store `params` (raw
int values in 0–127-scaled param units) and diffed `cc_map` (`{param:
{ch, cc}}`). Any resolution change is a **config-migration surface**
(documented in `docs/manual/05-configuration-and-data-structure.md`).

## 7. REST/SSE API

**`src/raspimidihub/api.py`** (routes registered via `@server.route`,
self-documented at `/docs`). MIDI-value-carrying endpoints:

- `GET /api/observatory` (L658) — live CC values per destination + held
  notes (from engine's 0–127 CC cache).
- `POST /api/devices/` action `test` (L843, body `cc` default 1 at L968) —
  test-message sender.
- `GET/POST/PATCH /api/connections*` (L987–1264) — filter dicts;
  `GET/POST/DELETE /api/mappings/` (L1266–1329) — mapping dicts with raw
  values.
- Plugin params: `GET/POST/PATCH /api/plugins/instances*` (L2589–2745),
  CC binding `PUT …/cc-map/…` (L2709), `GET /api/plugins/cc-mappings`
  (L2442), MIDI Learn `POST /api/cc-learn/start|cancel` (L2398/2430).

**SSE** — registry `SSE_EVENTS` in `web.py` L52. Value-carrying events:
`midi-activity` (emitted from `__main__.py` `on_midi_event` L174–252;
payload `channel`, `note`, `velocity`, `cc`, `value`, `dst_clients` —
throttled 10/s/port), `plugin-param`, `plugin-display`, `cc`, plus learn
results `cc_learn_result`/`cc_learn_timeout` (emitted api.py L423).
Non-value: `clock-quarter`, `transport-start`,
`device-connected/-disconnected`, `connection-changed`, `plugin-changed`,
`panic`, spectator events.

## 8. Already >7-bit aware? Essentially nothing.

- **Pitch bend** is the only 14-bit path: packed/unpacked in
  `midi_codec.py` (L65–67, 139–142) and the BLE bridge; carried opaquely
  in `data.control.value` otherwise; `plugins/pitch_cc` passes it through
  untouched. (Signed-vs-unsigned conversion gap noted in §2.)
- **No NRPN/RPN handling anywhere** (grep for NRPN/MSB/LSB/14-bit across
  backend+plugins yields only an unrelated apple_midi comment). ALSA's
  CONTROL14/NONREGPARAM/REGPARAM event types are not in the
  `MidiEventType` enum and would be silently ignored by `on_midi_event`
  (unknown types return early).
- **No MIDI-CI / Identity Request**: `device_id.py` builds stable IDs
  purely from USB sysfs (`iSerialNumber`, VID:PID, port path — L1–30,
  `_identity_serial` L76); no SysEx-based device inquiry exists. MIDI-CI
  discovery would be a net-new subsystem (though the `sysex_sender`
  plugin and `alsa_client.send_sysex` prove the SysEx TX path, and SYSEX
  RX events flow through the monitor).
- **Transports are MIDI 1.0 byte-stream by definition**: RTP-MIDI
  (`network_midi.py`/`apple_midi.py` via `midi_codec`), BLE-MIDI
  (`ble_midi_bridge.py`), rawmidi — none can carry UMP; MIDI 2.0 traffic
  must down-translate at these boundaries.

## 9. Docs (chapters describing value ranges / protocol behaviour)

`docs/manual/`: **08-ui-controls.md** (control ranges),
**10-filters-and-mappings.md** + **C-appendix-midi-mapping-reference.md**
(mapping value semantics, 0–127 tables), **11-plugins.md** (CC Automation
/ `default_cc`), **A-appendix-plugin-reference.md** (per-plugin param
range tables — written from plugin `__init__.py` declarations),
**12-controllers.md** + **B-appendix-controller-reference.md** (cell CC
values), **13-play-surfaces.md**, **E-appendix-rest-and-sse-api.md** (SSE
payloads), **05-configuration-and-data-structure.md** (config schema),
**04-system-architecture.md**, **21-technical-information.md**
(ALSA/kernel specifics), **03-hardware-and-connectors.md**.

## 10. Tests

`tests/` (~9,700 LOC, pytest + pytest-asyncio; `plugins/*/test_plugin.py`
per plugin, shared `plugins/conftest.py`). Most relevant:
`test_midi_codec.py` (bytes↔event), `test_midi_filter.py`,
`test_filter_pipeline.py`, `test_mapping_validation.py` (mappings),
`test_cc_binding.py` (CC→param), `test_edge_diff.py` (routing),
`test_clock_bus.py`/`test_clock_feedback.py`, `test_tracker_base.py`,
`test_ble_midi.py`, `test_apple_midi.py`, `test_network_midi.py`,
`test_panic.py`, `test_device_id.py`, `test_drop_buttons.py`,
`test_xypad_spring.py`, `test_tidy_param_values.py`, plus
`tests/e2e/network_midi_loopback.py`.

---

## Headline conclusions

1. **The ALSA binding is bespoke and MIDI-1.0-only** — UMP support =
   hand-extending `alsa_seq.py` ctypes (new event struct, client
   MIDI-version negotiation, UMP endpoint/port enumeration), plus an
   OS-image dependency (kernel UMP configs / alsa-lib ≥ 1.2.10).
2. **There is no message abstraction to widen** — the raw `SndSeqEvent` is
   the currency everywhere; introducing resolution means either a
   translation shim at the engine boundary or touching every consumer
   (filter engine, plugin dispatch, codec, monitor, SSE payloads).
3. **7-bit assumptions are concentrated, not diffuse**: mapping
   defaults/clamps (`midi_filter.py`), CC→param scaling
   (`host.py:_cc_to_param`), controller cell clamps
   (`controller_base.py`), param schema defaults (`plugin_api.py`), the
   two wire codecs, and ~10 frontend files (worst: `mappingform.js`,
   `ccbinding.js`/`cellbinding.js`, `curveeditor.js`, `wheel.js`'s
   per-integer ticks).
4. **MIDI-CI is greenfield**; the device-capability surface would flow
   `device_id.py`/`midi_engine` → `GET /api/devices` → `pages/matrix.js`
   L125 `extra` object.
5. **All three network/BLE transports are MIDI 1.0 byte-stream** and
   become down-translation boundaries.
