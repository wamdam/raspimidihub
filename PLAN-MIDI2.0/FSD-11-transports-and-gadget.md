# FSD-11 — Transports & gadget: 1.0-boundary policy, f_midi2, Network MIDI 2.0

**Step:** 7 (parked — go/no-go per feature when Steps 1–6 are done)
**Depends on:** FSD-02 (gadget), FSD-06 (codec scaling)

This FSD is three loosely-coupled packages; each gets its own go/no-go.

## A. Explicit 1.0-boundary policy for existing transports (small, real)

**Goal:** RTP-MIDI (Hub-Link), BLE-MIDI and rawmidi are permanent MIDI
1.0 byte-stream boundaries (annex 2 §7). Once internal traffic can be
hi-res (Steps 3–5), the *userspace* codecs must down-convert correctly
and account for what they drop (decision D6).

**Current state:** `midi_codec.py` `event_to_midi` L32 /`midi_to_event`
L84 (shared by network MIDI), duplicate subset in `ble_midi_bridge.py`
(~L565/661), pitch-bend signed/unsigned gap at L139–142 (annex 3 §2 —
**fix here regardless of MIDI 2.0**, with FSD-06's bend helpers; write
the failing test first to confirm the bug on hardware).

**Design:** the bridges' seq clients stay `midi_version=0` — the kernel
down-converts routed traffic before the codec sees it, so most of this
package is *verification*, plus: (a) the pitch-bend fix; (b) drop
counters for untranslatable messages if any userspace path ever receives
them (assert-they-don't first); (c) de-duplicate the BLE codec onto
`midi_codec.py` while touching both (the docstring already admits the
copy — small refactor-first win, per the user-level rule 3).

**UX verify:** Hub-Link two-Pi session and BLE session with 2.0 traffic
upstream: notes/CC arrive correctly 7-bit, bend centered correctly; no
stuck notes when per-note traffic is dropped upstream.

## B. Pi as USB MIDI 2.0 device (`f_midi2` gadget)

**Goal:** replace/augment the USB-gadget story: the Pi presents itself
to a computer as a USB MIDI 2.0 device (with automatic 1.0 fallback for
old hosts), exposing hub traffic at full resolution to a DAW.

**Current state:** kernel `f_midi2` (6.6+, configfs; annex 2 §2) is not
in Pi kernels (FSD-01 config request includes it). The repo's USB
device-mode story today is `usb_tether.py` (networking) — check whether
any `f_midi` gadget use exists before designing (none found in the
impact map).

**Design sketch (full FSD when un-parked):** configfs setup unit
(endpoint name = hub name, FBs mirroring exported devices or a single
"RaspiMIDIHub" FB), integration with the device registry (gadget appears
as a local ALSA card → routed like any device), settings toggle, and the
identity caveat: set a unique `iSerialNumber` or hosts lose metadata on
re-plug (annex 1 §8).

**UX verify:** plug Pi into macOS/Windows-MIDI-Services/Bitwig-Linux
host → appears as named MIDI 2.0 device; hi-res values arrive; old
hosts see a working 1.0 device.

## C. Network MIDI 2.0 (UDP)

**Goal (watch item):** the ratified (Nov 2024) UMP-over-UDP standard
with mDNS discovery (`_midi2._udp`) — the successor track to RTP-MIDI.
Not AppleMIDI-compatible: a second transport beside Hub-Link, not an
upgrade of it.

**Position:** parked until peers exist (OS/DAW support is only starting;
annex 2 §7). Our zeroconf/mDNS plumbing (`network_midi.py`, hub-stats
suite, per-device export model) is a strong head start; the
avahi/link-local constraints from the Hub-Link work (see project
memories) apply identically. Re-evaluate when a mainstream DAW or a
second hub implementation ships it; then write a dedicated FSD modeled
on the Hub-Link design decisions.

## Manual impact (when un-parked)

`14-bluetooth-midi.md` (boundary note), `17-connectivity-and-updates.md`
/ Hub-Link chapter (network transport), new gadget section in
`03-hardware-and-connectors.md` + `16-settings.md`, `21-technical…`.

## Tests

- A: codec golden tests incl. signed-bend fix (`test_midi_codec.py`,
  `test_ble_midi.py`, `test_apple_midi.py`, `test_network_midi.py`),
  e2e loopback (`tests/e2e/network_midi_loopback.py`).
- B/C: specified when un-parked.
