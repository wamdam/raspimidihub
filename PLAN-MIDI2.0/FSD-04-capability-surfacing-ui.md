# FSD-04 — Capability surfacing: API, matrix badge, Force-MIDI-1.0 toggle

**Step:** 2 · **Depends on:** FSD-03 · **Parallel with:** FSD-05 (disjoint
files — two agents can run these concurrently)

## Goal

Make MIDI 2.0 *visible and controllable*: a "2.0" badge on capable
devices in matrix/rack, endpoint details (protocol, endpoint name,
product instance ID, function blocks) in the device detail panel, and a
per-device **Force MIDI 1.0** toggle (decision D4) that persists and
survives replug.

## Non-goals

No value/resolution changes (FSD-05). No MIDI-CI data (FSD-10 extends
the same panel later). Per the config-UI rule: the badge reflects
*capability*, never live protocol state or traffic.

## Current state

- `pages/matrix.js` L125 — per-endpoint `extra` object (`is_plugin`,
  `is_bluetooth`, `is_network`, `remote_hub`, …) already drives per-type
  header markers; the natural place for `is_ump`/`midi2_protocol`.
- `pages/rack.js` + `ui/rack-engine.js` render the same device set;
  `ui/connections.js` is the shared fold.
- `panels/devicedetail.js` — device detail panel (also hosts the
  monitor, which FSD-05 touches — coordinate on section boundaries; this
  FSD owns the info header area only).
- `GET /api/devices` gains capability fields in FSD-03; config key
  `midi2.force_midi1` exists from FSD-03.

## Design

1. **Badge:** small "2.0" chip on matrix headers and rack device cards
   when `midi2_protocol` is true (capability, from endpoint info — shown
   even while forced to 1.0, then rendered struck-through/dimmed with the
   forced state). Reuse the existing marker styling for
   bluetooth/network devices.
2. **Device detail info block:** endpoint name, product instance ID,
   protocol capability, function-block list (name, direction, groups,
   active) — read-only rows in the existing detail layout.
3. **Force MIDI 1.0 toggle** in device detail: writes
   `POST /api/devices/{id}` action (extend the existing device action
   route at `api.py` L843 rather than adding a new route — check the
   action dispatch there) → engine masks capability (FSD-03 §4), config
   dirties, SSE `device-connected`-style refresh updates all views.
   Include the one-line explanation in the UI ("for devices that
   misbehave with MIDI 2.0"). Toggle is a plain setting — instant, no
   confirmation dialog.
4. **Settings page note:** no new settings sub-page in this FSD; the
   toggle lives on the device. (MIDI-CI gets its surface in FSD-10.)
5. **SSE:** no new event types; capability changes ride the existing
   device refresh events. If a new event proves necessary, register it in
   `SSE_EVENTS` (`web.py` L52) per project rules.

## Config / API / manual impact

- Config: uses `midi2.force_midi1` from FSD-03.
- API: device action `force_midi1` (body: bool) — summary string on the
  route per self-documenting-API rule.
- Manual (same commit): `09-routing-matrix.md` (badge), a new short
  section in `16-settings.md` or the device-detail part of
  `06-interacting-with-the-web-ui.md` (wherever device detail is
  documented — verify) for the toggle, `03-hardware-and-connectors.md`
  ("MIDI 2.0 devices" subsection: what works, what requires the UMP
  kernel), `21-technical-information.md` cross-ref to FSD-01 kernel
  requirements. Screenshot: matrix with a 2.0 badge — add a
  `Screenshots needed` entry (needs real 2.0 hardware).

## Tests

- API: force toggle round-trip, persistence across simulated replug
  (stable-ID resolution), capability fields in `GET /api/devices`.
- Frontend is exercised via the screenshot scene walk (add a scene once
  hardware exists) — no JS unit-test infra exists; keep it that way.

## UX verification (Step 2 gate, together with FSD-05)

1. 2.0 peer plugged in → badge appears in matrix and rack; detail shows
   endpoint info and FBs.
2. Toggle Force MIDI 1.0 → badge dims, capability fields mask, setting
   survives replug and reboot (autosave), un-toggle restores.
3. 1.0-only devices: no badge, no new UI elements, detail unchanged.
4. Non-UMP kernel: no badges anywhere, toggle hidden (capability field
   absent), zero layout drift in matrix/rack/detail.
