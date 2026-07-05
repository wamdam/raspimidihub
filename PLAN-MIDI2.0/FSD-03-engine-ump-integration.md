# FSD-03 — Engine + device registry UMP integration

**Step:** 1 · **Depends on:** FSD-02 · **Parallel with:** FSD-06, FSD-10

## Status (2026-07-05): implemented (backend)

- Capability fields live on `MidiDevice` (filled by `_fill_ump_info`
  during both scans); `GET /api/devices` carries `midi2 = {protocol,
  capable, forced_midi1, endpoint_name, product_id, function_blocks}`.
- Port policy implemented as pure `apply_ump_port_policy` (unit
  tested): ≥2 FBs → named group ports, catch-all hidden; ≤1 FB →
  endpoint port only; inactive group ports dropped via
  `SND_SEQ_PORT_CAP_INACTIVE`.
- **Design deviation from §2:** no stable-ID `#g` suffix — UMP group
  ports have stable kernel port numbers (group N = port N), so the
  existing stable_id + port-number config resolution works unchanged.
- `midi2.force_midi1` config block + `POST
  /api/devices/{id}/force-midi1` action (persisted, masks `protocol`
  in the API payload). Verified live on A6DC (round-trip into config).
- Endpoint/FB reading verified live against a fake 2-FB UMP peer
  ("Keys"/"Pads" blocks read back correctly by a second client).
- **Open (needs a real UMP *kernel* client, i.e. gadget or hardware):**
  matrix rows from FB ports end-to-end — the fake peer is a *user*
  client, which the device scan intentionally skips; FB-change
  hotplug behaviour on live hardware.

## Goal

Teach `MidiEngine` and the device registry that UMP endpoints exist:
correct device/port modelling (endpoint + named function-block group
ports), capability fields on every device record, and hotplug that
understands FB-change notifications. Routing behaviour is unchanged —
kernel subscriptions keep doing the work.

## Non-goals

No high-resolution value handling (FSD-05/07/08). No UI (FSD-04). No
protocol switching of our own clients yet (that starts with the monitor
in FSD-05).

## Current state

- `midi_engine.py`: `MidiEngine` L69, `_scan_and_connect` L754, hotplug
  `_schedule_rescan` L1374 (announce events PORT_START/EXIT etc. from
  `alsa_seq.py` L68–71), monitor port L213–218, snapshot shape
  `_snapshot_live_state` L419.
- `device_id.py`: stable IDs from USB sysfs (`iSerialNumber`, VID:PID,
  port path; `_identity_serial` L76).
- To a legacy client, a UMP endpoint already appears as up to 17 ports
  (port 0 = whole endpoint, 1–16 = groups; inactive groups flagged
  `PORT_CAP_INACTIVE`) — today they'd show as an anonymous port list.

## Design

1. **Device model gains capability fields** (flow into the registry and
   `_snapshot_live_state`): `is_ump: bool`, `midi2_protocol: bool`
   (endpoint protocol capability), `endpoint_name`,
   `product_instance_id`, `function_blocks: [{name, direction,
   first_group, num_groups, ui_hint, active}]`, `static_blocks: bool`.
   Populated from FSD-02's scan fields; absent/None on non-UMP kernels.
2. **Port presentation policy:** show port 0 (endpoint catch-all) *or*
   the FB group ports, not both, to avoid a 17-row matrix per device.
   Recommendation: list one row per **active function block** (named),
   collapse to the endpoint port when the device has 0/1 FBs — mirrors
   what users see of the physical device. Inactive group ports hidden.
   The chosen policy must keep `stable_id`-based config resolution
   working: extend `device_id.py` stable IDs with the group number for
   FB ports (e.g. `…#g5`), so saved connections survive
   replug/renumber exactly like today.
3. **Hotplug:** FB info/name change notifications arrive as (a) port
   change announces (kernel updates port names) — already triggers
   `_schedule_rescan`; verify rescan re-reads UMP info; (b) devices with
   `static_blocks=False` may activate/deactivate groups at runtime →
   rescan must diff FB activity and emit the existing
   `device-connected/-disconnected` SSE semantics per FB row.
4. **Per-device protocol pin (backend half of D4):** registry honours a
   persisted `force_midi1` set (config key, written by FSD-04's toggle).
   Implementation: when set, the hub treats the device as 1.0
   (capability fields masked) — and, where the kernel binding allows,
   re-binds via `midi2_enable`-style sysfs/module toggling is *not*
   attempted at runtime; instead we simply never upgrade our interaction
   with that device (no CI, no hi-res edges). Document the distinction:
   kernel-level rebinding stays a boot-time module option noted in the
   manual.
5. **No pass-through breakage:** the engine's own clients stay
   `midi_version=0` in this FSD; kernel converts as today.

## Config / API / manual impact

- Config: new optional top-level key `midi2: {force_midi1: [stable_id…]}`
  (empty default — no migration). Documented in `05-configuration…`.
- API: `GET /api/devices` entries gain the capability fields (additive).
  Route summaries already self-document.
- Manual: `09-routing-matrix.md` (FB rows), `04-system-architecture.md`
  (UMP endpoint modelling) — written with FSD-04 in the same step-2
  commit if preferred, but the FB-row behaviour lands here (Step 1) and
  must be documented in the Step 1 commit.

## Tests

- Registry unit tests with faked scan results: FB naming, collapse
  policy, stable-ID extension, force_midi1 masking.
- Hotplug diff tests: FB activation toggles produce connect/disconnect
  events; `test_edge_diff.py` extended for group-port endpoints.
- Regression: `test_device_id.py` untouched semantics for non-UMP
  devices.

## UX verification (Step 1 gate, on A6DC)

1. Plug a UMP peer (f_midi2 gadget from a laptop or real device): matrix
   and rack show the endpoint with named FB rows; names match the
   device's self-description.
2. Save a config with a connection to an FB row; replug the device;
   connection resolves.
3. Full 1.0 regression sweep: existing devices enumerate identically
   (names, stable IDs, saved configs load), filters/mappings/plugins/
   clock/panic unchanged, hotplug of 1.0 devices unchanged.
4. On the stock-kernel reference Pi: zero visible change anywhere.
