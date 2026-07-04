# FSD-02 — UMP support in the ctypes ALSA binding (`alsa_seq.py`)

**Step:** 1 · **Depends on:** FSD-01 (hardware verify only; code can be
written against mocks) · **Parallel with:** FSD-06, FSD-10

## Goal

Extend the hand-rolled ctypes binding so the hub can (a) run seq clients
at `midi_version` 0/1/2, (b) send/receive `snd_seq_ump_event` (16-byte
UMP payload), (c) enumerate UMP endpoints, function blocks and group
ports, and (d) pack/unpack the MIDI 2.0 channel-voice UMP words in pure
Python. All new API is additive; with `ump_capable=False` nothing changes.

## Non-goals

No engine/routing changes (FSD-03). No SysEx8/Mixed Data Set. No Flex
Data. No JR timestamps (D5: strip on input, never emit).

## Current state (`src/raspimidihub/alsa_seq.py`, 754 lines)

- `SndSeqEvent` L223 (12-byte data union), `SndSeqEventNote` L187
  (velocity `c_uint8`), `SndSeqEventCtrl` L196 (`value: c_int` — already
  32-bit-wide in the struct), `MidiEventType` L151 (no UMP/hi-res types),
  `AlsaSeq` L400, `scan_devices()` L474, `subscribe()` L603, send helpers
  L713–742, coalescing L673, mock fallback L28–37.

## Design

1. **Structs & calls (mirror alsa-lib ≥ 1.2.10 `seq.h`/`ump.h`):**
   - `SndSeqUmpEvent` — layout-compatible with `SndSeqEvent` but 16-byte
     `ump[4]` (`c_uint32 * 4`) payload; flag `SNDRV_SEQ_EVENT_UMP` in
     `flags`.
   - Bind: `snd_seq_ump_event_input`, `snd_seq_ump_event_output`,
     `snd_seq_client_set_midi_version`,
     `snd_seq_client_set_ump_conversion` (suppress kernel conversion —
     needed later for pass-through cases),
     `snd_seq_get_ump_endpoint_info`, `snd_seq_get_ump_block_info`, and
     the port-info `ump_group` accessor. All looked up defensively (like
     the existing mock fallback) so old libasound keeps working.
   - Read `sound/core/seq/seq_ump_convert.c` and
     `alsa-utils/seq/aseqdump/aseqdump.c` first — they are the reference
     for exact semantics (research annex 2 §8).
2. **Client versioning:** `AlsaSeq.__init__` gains
   `midi_version: int = 0`. The event pump gains a UMP read path: when
   the client is UMP, `snd_seq_ump_event_input` returns events whose
   payload is a UMP packet; non-UMP events (announce etc.) still arrive
   as classic events — both must be handled on one fd.
3. **Pure-Python UMP codec (`ump_codec` section or sibling module):**
   pack/unpack for MT 0x4 (MIDI 2.0 channel voice: note on/off w/ 16-bit
   velocity + attribute, CC 32-bit, RPN/NRPN atomic, per-note controllers
   & pitch bend, 32-bit bend/pressure, program+bank), MT 0x2 (MIDI 1.0 in
   UMP), MT 0x1 (system RT), MT 0x3 (SysEx7 reassembly per group), MT 0xF
   recognition (stream messages — decode Endpoint Info / FB Info /
   Device Identity for FSD-03/10; others skipped by size), MT 0x0
   (utility — recognized and dropped). Unknown MTs skipped by their fixed
   size table. This is ~300 lines of shifting/masking with golden-packet
   tests; UMP words arrive CPU-native via ALSA.
4. **Enumeration:** `scan_devices()`/`scan_one_client()` L474/541 learn
   to read per-client UMP info: endpoint name, protocol capability
   (MIDI 1.0/2.0), static flag, and per-port `ump_group` +
   `SNDRV_SEQ_PORT_CAP_INACTIVE`. Exposed as plain fields on the existing
   scan result objects — consumed by FSD-03; no behaviour change here.
5. **Send helpers:** UMP variants `send_ump()` (raw words) used by
   later FSDs; existing `send_note_on/send_cc` unchanged.
6. **Event-type surface:** add `MidiEventType.UMP` handling; also add the
   long-missing ALSA hi-res types (CONTROL14/NONREGPARAM/REGPARAM,
   ALSA types 14–16) to the enum so they at least stop being silently
   invisible (they appear when the kernel down-converts 2.0 RPNs to a
   1.0 client — today they'd be dropped by the unknown-type guard).

## Config / API / manual impact

None (internal). Manual `04-system-architecture.md` gets a paragraph when
Step 1 completes.

## Tests

- Golden UMP packets: spec worked examples from research annex 1 §2–3
  (e.g. 7→32 bit 70→0x8C30C30C via FSD-06; note-on velocity layouts;
  RPN atomic message round-trips). Encode→decode round-trip property
  tests.
- Mock-lib coverage: `midi_version` request on a mock without symbols →
  clean fallback to 0.
- SysEx7 reassembly across interleaved groups.
- Hardware (A6DC): scan shows endpoint/FB info for a reference UMP peer;
  pump receives UMP events with `midi_version=2` scratch client.

## UX verification

None user-visible on its own — verified through FSD-03's Step 1
checklist. Regression: full pytest suite green with mock lib; deploy to
A6DC and confirm 1.0 routing/hotplug/clock unchanged.
