# PLAN-MIDI2.0 — MIDI 2.0 support for RaspiMIDIHub

Planning package, compiled 2026-07-04. **No code has been changed.** This
directory contains the research, the strategy, and one FSD (functional
specification document) per work package, written so that multiple agents
can implement packages in parallel where the dependency graph allows.

## Contents

| File | What it is |
|---|---|
| `README.md` | This file: strategy, step plan, dependency graph, decisions |
| `research/01-midi2-protocol.md` | UMP format, MIDI 2.0 messages, scaling algorithms, MIDI-CI, adoption reality |
| `research/02-linux-alsa-ump.md` | Kernel/ALSA/alsa-lib UMP support, Raspberry Pi OS gap, reference code |
| `research/03-codebase-impact-map.md` | Every file/line in this repo that MIDI 2.0 touches |
| `FSD-01 … FSD-11` | One spec per work package (see table below) |

Read the three research annexes before implementing any FSD. Line numbers
in the annexes and FSDs are as of commit `77a1ba8` — re-verify before
editing.

## Executive summary

MIDI 2.0 gives us: 32-bit controllers (CC/RPN/NRPN as atomic messages),
16-bit note velocity, 32-bit pitch bend/pressure, per-note controllers and
per-note pitch bend, groups (16×16 = 256 channels per endpoint), and a
discovery layer (UMP endpoint/function-block info + MIDI-CI over SysEx).

Three facts shape the whole plan:

1. **The Linux kernel already does the hard part.** ALSA's sequencer
   (kernel ≥ 6.5) speaks UMP natively and converts 1.0↔2.0 *per
   delivery, per client*. Our kernel-subscription routing keeps working
   against MIDI 2.0 hardware with zero changes; "native" support is an
   incremental upgrade (declare `midi_version=2`, handle 16-byte events),
   not a rewrite.
2. **But Raspberry Pi OS ships every MIDI 2.0 kernel config off**
   (verified through rpi-6.18.y: no `SND_UMP`, no
   `SND_USB_AUDIO_MIDI_V2`, no `USB_CONFIGFS_F_MIDI2`). Trixie userspace
   (alsa-lib 1.2.14) is ready. Kernel enablement is Step 0 and gates all
   on-hardware verification. Everything must degrade gracefully on
   kernels without UMP — that is also our safety net.
3. **Real-world MIDI 2.0 hardware is still scarce** (a dozen product
   lines; mostly controllers, few sound engines use the resolution). So
   the plan is sequenced to deliver visible value early (device
   detection, hi-res monitoring, hi-res plugin automation from a 2.0
   controller) and keep MIDI 1.0 behaviour byte-for-byte unchanged
   throughout.

Where resolution actually matters in *our* architecture: unfiltered edges
are kernel subscriptions — the kernel already routes 2.0→2.0 at full
resolution today, even with our legacy client. Python only sees events on
**filtered/mapped edges, plugin I/O, the monitor, and the network/BLE
bridges**. Those are exactly the surfaces the FSDs upgrade.

## The steps — each ends in a user-verifiable state

Each step is a shippable increment; UX is verified before the next starts.
"Verify" lists the acceptance walk-through for that step (details in each
FSD's checklist).

| Step | FSDs | What the user gets | UX verification |
|---|---|---|---|
| **0. Enablement** | FSD-01 | Nothing visible; test Pi gains a UMP-capable kernel; hub detects capability at runtime | `aseqdump -u 2` sees a UMP device on the test Pi; hub boots and behaves exactly as today on both UMP and non-UMP kernels |
| **1. UMP-aware core** | FSD-02, FSD-03 | MIDI 2.0 devices appear correctly in the matrix: endpoint name + one named port per function block (instead of anonymous ports) | Plug in a 2.0 device → matrix/rack show proper FB port names; full 1.0 regression pass (routing, filters, plugins, clock, hotplug) |
| **2. See MIDI 2.0** | FSD-04, FSD-05 | "2.0" badge on capable devices; device detail shows protocol/endpoint info + per-device **Force MIDI 1.0** toggle; MIDI monitor displays high-resolution values | Badge appears; toggle downgrades and survives replug; monitor shows 16-bit velocity / 32-bit CC from a 2.0 controller, still shows 0–127 for 1.0 devices |
| **3. Route MIDI 2.0** | FSD-06, FSD-07 | Filtered/mapped connections preserve full resolution end-to-end; mapping editor understands fractional values | cc_to_cc mapping between two 2.0 endpoints is stepless (verified in monitor); every existing 1.0 mapping behaves identically |
| **4. Hi-res plugin control** | FSD-08 | Plugin parameter CC automation uses full controller resolution; web knobs/wheels handle fine ranges | Bind a 2.0 controller knob to a plugin param → visibly smooth, stepless sweep; UI widgets remain usable |
| **5. Hi-res generation** | FSD-09 | CC LFO / smoother / velocity plugins and controller templates emit high resolution toward 2.0 destinations | Slow CC LFO into a 2.0 synth is stepless (audibly / in monitor); same patch into a 1.0 synth unchanged |
| **6. Know your synths** | FSD-10 | MIDI-CI discovery: device identity, capabilities, (optionally) Property-Exchange device info shown in device detail | Device detail shows CI identity for a CI-capable synth over USB *and* over DIN; non-CI devices show nothing new |
| **7. Outward-facing 2.0** (parked) | FSD-11 | Pi as USB MIDI 2.0 gadget; Network MIDI 2.0 (UDP); explicit 1.0-boundary policy for BLE/RTP | Separate go/no-go per feature when we get here |

Steps 0–2 contain **no behaviour change** for existing users — they are
pure additive visibility. The first behaviour-adjacent change is Step 3,
and it is gated per-edge (only edges where both endpoints are 2.0-capable
carry hi-res).

## FSD index and dependency graph

| FSD | Title | Step | Depends on | Parallel with |
|---|---|---|---|---|
| FSD-01 | Kernel & OS enablement, runtime capability detection | 0 | — | everything (gates only on-hardware testing) |
| FSD-02 | UMP support in the ctypes ALSA binding (`alsa_seq.py`) | 1 | FSD-01 (for hw verify only) | FSD-06, FSD-10 |
| FSD-03 | Engine + device registry UMP integration | 1 | FSD-02 | FSD-06, FSD-10 |
| FSD-04 | Capability surfacing: API, matrix badge, Force-1.0 toggle | 2 | FSD-03 | FSD-05, FSD-06, FSD-10 |
| FSD-05 | High-resolution monitor & SSE | 2 | FSD-03 | FSD-04, FSD-06, FSD-10 |
| FSD-06 | Bit-scaling library (`midi_scale.py`) — pure code, spec-mandated algorithms | 3 | — (fully independent) | all |
| FSD-07 | Filter/mapping engine at high resolution | 3 | FSD-03, FSD-06 | FSD-08 prep, FSD-10 |
| FSD-08 | Plugin param binding & UI controls at high resolution | 4 | FSD-03, FSD-06 | FSD-07, FSD-10 |
| FSD-09 | Hi-res generation: plugins & controller templates | 5 | FSD-08 | FSD-10 |
| FSD-10 | MIDI-CI subsystem (discovery, identity, PE) | 6 | FSD-03 (device registry hooks); usable without hi-res steps | FSD-04…09 |
| FSD-11 | Transports & gadget: BLE/RTP policy, f_midi2, Network MIDI 2.0 | 7 | FSD-02 (gadget), FSD-06 (codec scaling) | parked |

**Parallel lanes for multi-agent work:**

- **Lane A (critical path):** FSD-02 → FSD-03 → FSD-04/05 → FSD-07 →
  FSD-08 → FSD-09.
- **Lane B (immediately startable, no dependencies):** FSD-06 (scaling
  library + exhaustive tests — pure Python, spec pseudocode is in
  research annex 1 §3) and FSD-01 (kernel build + upstream config
  request).
- **Lane C (independent subsystem):** FSD-10 MIDI-CI — SysEx-based,
  works over plain MIDI 1.0, can be developed and UX-verified against a
  CI-capable synth even before any UMP code exists.
- FSD-04 and FSD-05 are disjoint (UI/registry vs monitor/SSE) and can run
  as two agents once FSD-03 lands.

## Core design decisions (recommended — confirm before Step 3)

These are recommendations with rationale; they need sign-off because they
set the architecture. Flagged per the "object and discuss" project rule.

**D1 — Internal event currency: flip our seq clients to `midi_version=2`
and make MIDI 2.0 widths the internal native format.** The kernel then
up-converts all 1.0 traffic on the way in and down-converts on delivery
to 1.0 receivers — Python handles ONE format instead of two, and we
inherit the spec-compliant translation in `seq_ump_convert.c` instead of
writing our own. Clients flip one at a time (monitor in Step 2, filter
engine edges in Step 3, plugin host in Step 4), each behind the runtime
capability check from FSD-01. On non-UMP kernels everything stays
`midi_version=0` and code paths fall back to 7-bit — same binaries, no
feature flag in config.

**D2 — User-facing value scale: fractional 0–127 ("MIDI units"),
not raw 32-bit, not percent.** UI, mappings, config, API keep the 0–127
scale users know; extra resolution appears as decimals (e.g. velocity
`100.53`, CC `64.002`). Rationale: (a) zero config migration — every
existing integer is a valid fractional value; (b) mapping semantics
("cc_on_value 127") stay meaningful across 1.0 and 2.0 edges; (c) raw
32-bit numbers (0–4294967295) are user-hostile. Internally values are
32-bit ints at ALSA boundaries and converted via FSD-06 exactly once per
crossing. SSE/API payloads keep existing integer fields for compatibility
and add fractional fields (FSD-05).

**D3 — Plugin API stays 0–127-compatible; hi-res is opt-in per plugin.**
`on_note_on(ch, note, velocity)` keeps 0–127 ints forever (26 plugins +
third-party expectations). Hi-res arrives as new optional callbacks /
float-valued params (FSD-08/09). No flag day for plugin authors.

**D4 — Per-device "Force MIDI 1.0" escape hatch is mandatory** (Step 2).
Real devices misbehave under UMP probing (kernel grew `midi2_ump_probe=0`
/ `midi2_enable=0` for this reason). We expose the same downgrade
per-device in the UI and persist it.

**D5 — JR timestamps: never emit, strip on input, negotiate off.** The
industry (MS/AMEI/MMA) agreed OSes don't handle them. Delta Clockstamps
only matter for SMF2 files — out of scope.

**D6 — Untranslatable messages get an explicit per-edge policy, not
silent behaviour.** Per-note controllers / per-note pitch bend / relative
controllers / SysEx8 cannot cross a 1.0 boundary (spec Appendix D). The
kernel drops them on down-conversion; wherever *we* down-convert (BLE/RTP
codecs, FSD-11), we drop-and-count and surface the count in the device
stats rather than corrupting data.

**D7 — MIDI-CI is application-layer and ours** (FSD-10). No OS does it
for us. MUIDs are per-power-cycle random — never persisted; stable
identity stays `device_id.py` (USB serial) + CI Device Identity as
display metadata.

## Open questions (parked, answers not needed before Step 3)

1. Upstream kernel config request timeline — if Raspberry Pi declines or
   stalls, choose between shipping a module-rebuild package (DKMS-style,
   per-kernel fragile) or documenting "bring your own kernel" for 2.0
   (FSD-01 §risks).
2. Per-note controllers / MPE-style routing through *mappings* (beyond
   pass-through) — new mapping types? Deliberately out of scope for all
   FSDs here; revisit after Step 5 with real hardware experience. (Per
   the plugin-vs-mapping rule, anything stateful here would be a plugin.)
3. Whether the tracker should record/play 16-bit velocity natively
   (pattern data format change) — out of scope; FSD-09 covers only live
   pass-through and generator plugins.
4. Network MIDI 2.0 (UDP) — ratified Nov 2024, not AppleMIDI-compatible,
   would be a second network transport next to Hub-Link. Parked in
   FSD-11 until devices exist to talk to.

## Testing & hardware strategy

- All backend FSDs must keep the libasound mock path
  (`alsa_seq.py` L28–37) working so the suite runs off-Pi; UMP structs
  get mock coverage plus golden-packet fixtures (known UMP words ↔
  expected decoded events).
- FSD-06 tests are pure and exhaustive (spec worked values are in
  research annex 1 §3 — 70→0x8C30C30C etc., round-trip property tests).
- On-hardware verification uses the **A6DC test Pi** (10.1.156.213) with
  the FSD-01 kernel; the LIVE Pi (735C) is off-limits per standing rules.
  A second Pi running the f_midi2 gadget (FSD-11, or a laptop with
  Ubuntu's UMP-enabled kernel + `aseqdump`/MIDI2.0Workbench) serves as
  the reference MIDI 2.0 peer until real 2.0 hardware is acquired —
  candidate purchase: used Korg Keystage (CI Property Exchange) or
  Roland A-88MKII.
- Each step's UX checklist lives at the bottom of its FSDs; per the
  test-pacing rule, hardware steps that need user action are coordinated,
  never timed.

## Manual impact (per project CLAUDE.md, same-commit rule)

Every FSD lists its chapters. The recurring set: `03-hardware…` (2.0
device support matrix), `05-configuration…` (new config keys),
`06-interacting…`/`08-ui-controls` (badge, fractional values),
`09-routing-matrix` (FB ports), `10-filters-and-mappings` + appendix C
(fractional mapping values), `11-plugins` + appendix A (hi-res params),
`12-controllers` + appendix B, `16-settings` (Force-1.0, CI page),
`18-appliance-reliability` (graceful degradation), `21-technical…`
(kernel requirements), `E-appendix-rest-and-sse-api` (SSE_EVENTS
registry entries only — route docs self-generate).
