# FSD-10 — MIDI-CI subsystem (discovery, identity, Property Exchange)

**Step:** 6 · **Depends on:** FSD-03 (device-registry fields to hang
results on); otherwise independent

## Status (2026-07-05): implemented (commit 72f0fd6)

- midi_ci.py: CI v1.2 codec (Discovery, PE caps, PE Get w/ chunk
  assembly; parser never raises) + CiSession (dedicated seq client,
  point-to-point subscriptions, select-based, worker-threaded, single
  retry, per-boot dedup). PE data is plain-ASCII JSON (default
  encoding); Mcoded7 not implemented yet — revisit if a device
  negotiates it.
- Engine probes new bidirectional devices on connect (plugins /
  network mirrors / opted-out skipped); results in GET /api/devices
  midi_ci + device-detail card + Identify action; config
  midi2.ci_enabled / ci_disabled.
- Live-verified on A6DC against the fake synth's new CI responder:
  Discovery + PE caps + PE DeviceInfo end to end, through the
  kernel's classic<->SysEx7 conversion (hub CI client legacy, synth
  midi_version=2).
- Registry addition: card-less UMP-declared user clients get
  ump-<name> stable ids (virtual devices are first-class).
- Found + fixed a pre-existing bug: SND_SEQ_EVENT_LENGTH_VARIABLE
  was 0x01 (TIME_STAMP_REAL) instead of 1<<2 — all SysEx TX
  (sysex_sender plugin included) failed with EINVAL since ever.
- Open: real-hardware CI check (Korg Keystage class) over USB + DIN;
  ProgramList fetch (manual button) deliberately not implemented;
  suggested-rename from DeviceInfo.model parked.

## Goal

The hub actively *identifies* what's connected: send MIDI-CI Discovery,
collect device identity/capabilities, optionally fetch Property-Exchange
`DeviceInfo` (and later `ProgramList` = patch names), and show it in the
device detail panel. This is the "detect synths with 2.0" feature —
including synths on DIN or behind 1.0 links, which UMP endpoint info
can't see.

## Non-goals

Profiles (enable/disable) — display-only if reported; acting on profiles
is a later feature. Process Inquiry. PE `State` snapshots. Acting as a
MIDI-CI *responder* (the hub only initiates; responding is FSD-11
territory alongside the gadget).

## Current state

Greenfield (annex 3 §8): no SysEx-based inquiry exists. Building blocks
present: SysEx TX path (`alsa_client.send_sysex` L210, `sysex_sender`
plugin), SysEx RX flows through the monitor, `device_id.py` stable IDs
(USB serial — stays the identity anchor), device detail panel from
FSD-04.

## Design

1. **New module `midi_ci.py`:** MIDI-CI v1.2 initiator implementing
   Discovery (Universal SysEx sub-ID 0x0D), Reply parsing (identity:
   manufacturer/family/model/version; category support bits: Profiles /
   PE / Process Inquiry; max SysEx size), and PE GET (`ResourceList`,
   `DeviceInfo`) with Mcoded7 + chunking. Pure protocol logic (bytes in
   → dataclasses out), fully unit-testable without hardware; port test
   vectors from AM_MIDI2.0Lib / MIDI2.0Workbench captures.
2. **MUID handling (D7):** hub generates a random MUID per boot; device
   MUIDs are session-scoped only — persisted metadata (shown name,
   identity) keys off `stable_id`. Cache CI results per boot; re-inquire
   on device connect.
3. **Session/routing hazard (annex 2 §6):** CI is a point-to-point SysEx
   conversation. The initiator must use a **dedicated seq client/port
   pair connected only to the target device's in/out**, never the
   routed graph, so (a) CI traffic doesn't leak to user destinations and
   (b) replies aren't forked. Inquiry runs briefly on device
   connect (and on manual "Identify" action), with timeout + single
   retry; devices that answer garbage get a per-device CI-disable flag
   (mirrors D4's toggle, same config block `midi2:`).
4. **Where results surface:** registry fields (`ci_identity`,
   `ci_categories`, `ci_device_info`) → `GET /api/devices` → device
   detail panel section "MIDI-CI" (FSD-04's panel). Optional nicety:
   PE `DeviceInfo.model` offered as a suggested device rename (existing
   `device_names` mechanism) — suggestion only, never automatic.
5. **Bidirectionality requirement:** CI needs a return path. Only run
   inquiry when the device has both in and out ports (the registry
   knows); DIN devices wired one-way simply never get CI data.
6. **SysEx budget:** PE JSON can be large; respect the device's declared
   max SysEx size, pace via the existing chunked `send_sysex`, and cap
   total PE fetch (e.g. DeviceInfo only by default; `ProgramList`
   behind a manual button in device detail — it can be thousands of
   entries).

## Config / API / manual impact

- Config: `midi2.ci_disabled: [stable_id…]` (with the FSD-03 block).
- API: device fields additive; manual "Identify" device action; optional
  `GET /api/devices/{id}/ci/programs` for ProgramList (self-documented).
- SSE: reuse device refresh events; if a `ci-updated` event is needed,
  register in `SSE_EVENTS`.
- Manual: device-detail chapter section (where FSD-04 documented the
  panel), `16-settings.md` if any global CI on/off lands (recommend:
  global off-switch in Settings for paranoid setups),
  `21-technical-information.md` (what CI is, what the hub sends),
  `E-appendix…` registry lines.

## Tests

- Protocol unit tests: discovery/reply/PE parsing golden vectors,
  Mcoded7 round-trip, chunk reassembly, malformed-reply robustness
  (fuzz the parser — CI replies come from arbitrary firmware).
- Integration: fake responder over the mock seq (scripted replies);
  timeout/retry/disable-flag paths.
- Hardware: against a real CI device (Korg Keystage class) over USB and
  over a DIN interface.

## UX verification (Step 6 gate)

1. Connect a CI-capable synth → device detail shows manufacturer/model/
   version and capability chips within ~2 s of connect; "Identify"
   re-runs on demand.
2. The same synth behind a plain 1.0 DIN interface (bidirectional):
   identity still appears — demonstrating detection without UMP.
3. Non-CI devices: no CI section, no SysEx storms (verify with monitor
   that inquiry is single-shot + timeout).
4. A device on the CI-disable list is never probed.
5. Live-set safety: CI inquiry on hotplug does not audibly disturb
   ongoing routing (SysEx pacing respected).
