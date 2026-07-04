# Research Annex 1 — The MIDI 2.0 Protocol

Compiled 2026-07 from the primary specs (M2-104-UM UMP v1.1.2, M2-115-U
v1.0.2 — read in full), the Linux kernel docs, Microsoft's Windows MIDI
Services documentation, and current adoption reporting. Target context:
Raspberry Pi, ALSA sequencer, Python, 1.0↔2.0 translation both directions.

---

## 1. Universal MIDI Packet (UMP) Format

UMP is the container format for *both* MIDI 1.0 protocol and MIDI 2.0
protocol messages. Spec: M2-104-UM "Universal MIDI Packet (UMP) Format and
MIDI 2.0 Protocol", current v1.1.2 (2023-10-27)
([PDF](https://amei-music.github.io/midi2.0-docs/amei-pdf/M2-104-UM_v1-1-2_UMP_and_MIDI_2-0_Protocol_Specification.pdf)).

Packets are 1–4 **32-bit words** (32/64/96/128 bits). The top 4 bits of the
first word are the **Message Type (MT)**; all messages of one MT have the
same size. The MT allocation (from Table 4 of the spec):

| MT | Size | Content |
|----|------|---------|
| 0x0 | 32 | Utility (NOOP, JR Clock, JR Timestamp, DCTPQ, Delta Clockstamp) — **groupless since v1.1** |
| 0x1 | 32 | System Real Time + System Common (except SysEx) |
| 0x2 | 32 | **MIDI 1.0 channel voice in UMP** (status+2 data bytes, unchanged 7-bit semantics) |
| 0x3 | 64 | Data: **SysEx7** (complete/start/continue/end, ≤6 data bytes per packet) |
| 0x4 | 64 | **MIDI 2.0 channel voice** |
| 0x5 | 128 | Data: **SysEx8** (8-bit data, 13 bytes/packet, stream ID) + Mixed Data Set |
| 0x6–0xC, 0xE | 32–128 | Reserved (sizes pre-assigned so unknown packets can be skipped) |
| 0xD | 128 | **Flex Data** (v1.1: tempo, time/key signature, metronome, chord name, lyrics/text — the SMF-meta-event replacements) |
| 0xF | 128 | **UMP Stream messages** (endpoint/function-block discovery & configuration — groupless) |

**Groups:** after MT, the next 4 bits are the **Group** (0–15). Each group
carries an independent 16-channel MIDI stream ⇒ 16×16 = **256 channels per
UMP endpoint**. A group corresponds roughly to one virtual cable in USB
MIDI 1.0 terms. Each group can independently run MIDI 1.0-in-UMP (MT 0x2)
or MIDI 2.0 (MT 0x4) messages — but under UMP v1.1 stream configuration the
*whole endpoint* declares one protocol; you don't mix per-group anymore
(see §4). Utility (MT 0x0) and Stream (MT 0xF) messages are **groupless** —
they address the endpoint itself. This groupless change landed at spec v1.1
and broke earlier implementations (see §8).

Words are in CPU-native endianness in ALSA's API; the transport driver
handles wire byte order
([kernel docs](https://docs.kernel.org/sound/designs/midi-2.0.html)).

**SysEx7 vs SysEx8:** SysEx7 (MT 0x3) is byte-identical in payload to MIDI
1.0 SysEx with F0/F7 stripped, chunked 6 bytes per 64-bit packet with a
start/continue/end state machine. SysEx8 (MT 0x5) carries full 8-bit bytes
plus a Stream ID allowing interleaving; **SysEx8 and Mixed Data Set cannot
be translated to a MIDI 1.0 byte-stream at all** (spec Appendix D.2.9) — a
router must drop or reject them at a 1.0 boundary.

---

## 2. MIDI 2.0 Channel Voice Messages (MT 0x4, 64-bit)

Layout: word 1 = `MT(4) | group(4) | opcode(4) | channel(4) | index
bytes(16)`; word 2 = 32-bit data. Opcodes:

- **0x8 Note Off / 0x9 Note On**: note number (7-bit), **16-bit velocity**,
  plus an 8-bit **Attribute Type** and 16-bit **Attribute Data**. Defined
  attribute types (spec Table 8): `0x00` none, `0x01`
  manufacturer-specific/unknown, `0x02` profile-specific, `0x03` **Pitch
  7.9** (fixed-point note pitch: 7 bits note + 9 fractional bits —
  microtonal note-on pitch). Critically: **Note On velocity 0 is a valid
  Note On in 2.0**, *not* a Note Off (spec §7.4).
- **0xA Poly Pressure**: 32-bit value.
- **0xB Control Change**: controller index 0–127, **32-bit value**. Same CC
  numbers as 1.0, but CC 6/38/98/99/100/101 (RPN/NRPN machinery) and CC
  0/32 (bank select) **have no CC function in 2.0** — they're replaced by
  dedicated messages below.
- **0x2 Registered Controller (RPN) / 0x3 Assignable Controller (NRPN)**:
  single atomic message: bank (7-bit, = old RPN/NRPN MSB), index (7-bit, =
  LSB), **32-bit data**. 16,384 of each. Replaces the 4-message CC
  101/100/6/38 dance entirely.
- **0x4/0x5 Relative Registered/Assignable Controller**: signed 32-bit
  two's-complement *delta*. **No MIDI 1.0 equivalent — untranslatable**
  (Appendix D.2.8).
- **0x0 Registered Per-Note Controller / 0x1 Assignable Per-Note
  Controller**: note number + 8-bit controller index (256 each) + 32-bit
  value. Registered per-note controllers include #3 Pitch 7.25, #7 volume,
  #10 pan, #74 brightness, etc. (spec Appendix A). This is the "MPE done
  properly" mechanism. **Untranslatable to 1.0** by default translation.
- **0x6 Per-Note Pitch Bend**: note number + 32-bit bend, per sounding
  note. Sensitivity set by a dedicated Registered Controller (§7.4.13).
  **Untranslatable to 1.0.**
- **0xE (Channel) Pitch Bend**: **32-bit**, center 0x80000000.
- **0xD Channel Pressure**: 32-bit.
- **0xC Program Change**: option-flag byte with a **Bank Valid (B) bit**;
  program (7-bit) + bank MSB + bank LSB in one atomic message. B=0 ⇒ ignore
  bank fields.
- **0xF Per-Note Management**: note number + option flags **D** (detach
  per-note controllers from previously received notes of that number) and
  **S** (set/reset per-note controllers to default) — manages controller
  state when note numbers are reused polyphonically (spec §7.4.5, Appendix
  C). **Untranslatable to 1.0.**

Hub design consequence: RPN/NRPN, bank+program, and (via CC 88 high-res
velocity) velocity all become **stateless single messages** in 2.0; the
*stateful* parsing burden lives entirely on the 1.0→2.0 translation side.

---

## 3. Resolution Scaling / Translation Rules (M2-115-U + M2-104 Appendix D)

Primary sources:
[M2-115-U v1.0.2 "MIDI 2.0 Bit Scaling and Resolution"](https://amei-music.github.io/midi2.0-docs/amei-pdf/M2-115-U_v1-0-2_MIDI%202.0%20Bit%20Scaling%20and%20Resolution.pdf)
and Appendix D of M2-104-UM. Where they disagree, **M2-115-U is
authoritative**. The exact pseudocode is short enough to port to Python
verbatim.

### 3.1 Min-Center-Max scaling (the default)

Used for: velocity, poly/channel pressure, pitch bend, CC values, NRPN
data, and **RPN data where RPN LSB is 32–127**. Core rules: min→min,
max→max (7-bit 127 → 16-bit 0xFFFF), center→center (center =
`(highest+1)/2`, e.g. 64 → 0x8000 → 0x80000000), and **down(up(x)) == x**
round-trip losslessness.

**Upscaling** (srcBits ≥ 2): below/at center = plain left shift; above
center = left shift with the low bits filled by an **expanded bit-repeat**
of the source's lower (srcBits−1) bits, so values ramp smoothly to all-ones
at max:

```c
uint32_t scaleUp(uint32_t srcVal, uint8_t srcBits, uint8_t dstBits) {
    uint8_t  scaleBits = dstBits - srcBits;
    uint32_t srcCenter = 1u << (srcBits - 1);
    uint32_t bitShifted = srcVal << scaleBits;
    if (srcVal <= srcCenter) return bitShifted;
    uint8_t  repeatBits = srcBits - 1;
    uint32_t repeatValue = srcVal & ((1u << repeatBits) - 1);
    if (scaleBits > repeatBits) repeatValue <<= (scaleBits - repeatBits);
    else                        repeatValue >>= (repeatBits - scaleBits);
    while (repeatValue) { bitShifted |= repeatValue; repeatValue >>= repeatBits; }
    return bitShifted;
}
```

Worked values (7→16): 0→0x0000, 32→0x4000, 64→0x8000, 70→0x8C30, 96→0xC104,
120→0xF1C7, 127→0xFFFF. (7→32): 70→0x8C30C30C, 127→0xFFFFFFFF. 1-bit
values: 0→0, 1→max.

**Downscaling** is just truncation: `srcVal >> (srcBits - dstBits)`. That
plus the bit-repeat guarantees round-trip stability.

### 3.2 Zero-Extension scaling with rounding

Used for **Registered Controllers (RPN) with index LSB 0–31** — the classic
MIDI 1.0 RPNs (pitch bend sensitivity, fine/coarse tune, MPE Configuration,
etc.), which are fixed-point/unit-valued, not 0–100%. Min-Center-Max would
inject noise (spec example: pitch 7.9 value 127.0 becomes 127.00385 — ⅓
cent off). Rules: **upscale = plain left shift, zero-filled** (7-bit 127 →
16-bit 0xFE00, *not* 0xFFFF); **downscale = round-half-up then clamp**:

```c
uint scaleDownRounding(uint srcVal, uint srcBits, uint dstBits) {
    uint scaleBits = srcBits - dstBits;
    uint shifted = (srcVal + (1u << (scaleBits - 1))) >> scaleBits;
    uint maxValue = (1u << dstBits) - 1;
    return shifted > maxValue ? maxValue : shifted;
}
```

### 3.3 Message-level translation rules (M2-104 Appendix D — mandatory "Default Translation Mode")

Both directions a hub must implement:

**2.0 → 1.0:**

- Note On: scale velocity 16→7; **if result is 0, send 1** (velocity-0
  note-on would mean note-off).
- RPN/NRPN message → **four** CCs: 101,100 (or 99,98), 6, 38 (data 32→14,
  method per §3.1/3.2 above).
- Program Change: B=0 → bare PC; B=1 → CC0, CC32, PC in that order.
- SysEx7 packets reassembled between F0…F7.
- **Drop silently-untranslatable messages**: relative controllers, per-note
  controllers, per-note pitch bend, per-note management (D.2.8); SysEx8,
  Mixed Data Set, Utility messages never reach byte-stream 1.0 (D.2.9).

**1.0 → 2.0 (the stateful direction):**

- Note On vel 0 → **MIDI 2.0 Note Off with velocity 0x8000**. Vel 1–127
  min-center-max upscaled (vel 1 → 0x0200).
- Attribute type/data = 0 unless an active Profile says otherwise.
- **RPN/NRPN state machine**: individually received CC 6/38/98/99/100/101
  do *not* pass through; the translator holds latest values and emits one
  MIDI 2.0 Registered/Assignable Controller message when CC38 arrives, a
  subsequent CC6 arrives, or a new CC98–101 begins a new parameter. Null
  RPN (127/127) is not translated. Spec notes some 1.0 devices never send
  CC38 — a short timeout after CC6 is suggested to avoid losing RPNs.
- **Bank Select buffering**: lone CC0/CC32 are swallowed; latest values
  attach to the next Program Change (Bank Valid=1), otherwise B=0.
- 14-bit CC pairs (MSB 1–31 / LSB 33–63) are **not** merged — they stay two
  independent 32-bit CC messages.
- CC 96/97 (increment/decrement) translate as plain CCs, explicitly *not*
  to relative controllers.
- Pitch bend: 14-bit (LSB-first!) → 32-bit min-center-max.

"Alternate Translation Modes" (e.g., per-note-controllers↔MPE) are allowed
but must be user-visible and optional (D.4). This is exactly what Linux
DAWs see today: PipeWire/ALSA downconvert per-note controllers, and Ardour
receives them as MPE-ish data
([linuxdj.com overview](https://www.linuxdj.com/notes/midi-2-0-on-linux-2026-pipewire-ump-kernel-support-and-safe-fallbacks/)).

---

## 4. Discovery: MIDI-CI and UMP Stream Messages

Two layers, and the split matters:

### UMP Stream messages (MT 0xF, UMP spec v1.1) — transport-level, in-band

128-bit groupless messages: **Endpoint Discovery** (0x00) → **Endpoint Info
Notification** (0x01: UMP version, number of function blocks, MIDI 1.0/2.0
protocol capability, JR timestamp capability), **Device Identity** (0x02:
sysex-ID/family/model/version), **Endpoint Name** (0x03), **Product
Instance ID** (0x04, = serial), **Stream Configuration
Request/Notification** (0x05/0x06 — *this* is protocol negotiation now: the
host asks the endpoint to switch the whole endpoint to MIDI 1.0 or 2.0
protocol ± JR timestamps), **Function Block Discovery/Info/Name**
(0x10/0x11/0x12), Start/End of Clip (0x20/0x21).

**Function Blocks** describe which groups belong together (direction, first
group + span, UI hint, MIDI 1.0-bandwidth flag, CI support level). They
replace/augment the USB **Group Terminal Block** descriptors; a host
queries FBs via stream messages and falls back to GTBs for devices that
don't answer (this is exactly what the Linux USB driver does —
[kernel docs](https://docs.kernel.org/sound/designs/midi-2.0.html)).

### MIDI-CI (M2-101-UM, current v1.2) — SysEx-based, transport-agnostic

Universal SysEx (sub-ID 0x0D), works over any bidirectional MIDI 1.0 or 2.0
connection, including 5-pin DIN. Each device generates a random **28-bit
MUID** per power-cycle; **Discovery Inquiry** (broadcast MUID 0xFFFFFFF)
returns device identity, supported categories (Profiles / Property Exchange
/ Process Inquiry), and max SysEx size
([MIDI.org overview](https://midi.org/details-about-midi-2-0-midi-ci-profiles-and-property-exchange-updated-june-2023)).

- **Protocol Negotiation: deprecated in MIDI-CI 1.2**, replaced by the UMP
  Stream Configuration messages above
  ([atsushieno's MIDI-CI tools writeup](https://atsushieno.github.io/2024/01/26/midi-ci-tools.html)).
  Windows MIDI Services implements *only* UMP-based endpoint
  discovery/protocol negotiation and deliberately does not do the
  deprecated CI version
  ([Microsoft implementation details](https://microsoft.github.io/MIDI/kb/midi2-implementation-details/)).
- **Profile Configuration**: query/enable/disable named behavior bundles
  (MPE Profile M2-120, Piano, Drawbar Organ, Default Drum Note Map M2-125,
  Orchestral Articulation M2-123) per channel/group/function block.
  Profiles are the part the MIDI Association is currently pushing hardest
  ([State of MIDI 2.0, Feb 2026](https://midi.org/the-state-of-midi-2-0-high-resolution-performance-and-the-rise-of-profiles-update-feb-2026)).
- **Property Exchange (PE)**: chunked JSON request/reply over SysEx
  (M2-103-UM Common Rules). `ResourceList` enumerates resources;
  foundational ones are `DeviceInfo`, `ChannelList`, `JSONSchema`; others
  include `ProgramList` (patch names!), `ChCtrlList`/controller resources
  (which also declare **significant bits** of controllers — relevant to
  scaling, per M2-115-U §2.3), `State` (snapshot save/restore). Headers +
  data are Mcoded7-packed JSON.
- **Process Inquiry** (new in CI 1.2): "MIDI Message Report" — ask a device
  to dump its current controller/note state.

**How a hub detects a MIDI 2.0-capable synth:** on USB, the presence of an
alt-setting-1 MIDI 2.0 interface (§6) is the first signal; then send UMP
Endpoint Discovery and read the Endpoint Info protocol-capability bits;
then Stream Configuration Request to pick MIDI 2.0 protocol. MIDI-CI
Discovery over SysEx is the *only* option on DIN or via 1.0 transports, and
per Microsoft's stance the OS won't do it for you — the hub application
layer would own that. On Linux, the kernel already performs the UMP
endpoint/FB inquiry at probe time and exposes the result via ALSA.

---

## 5. Jitter Reduction Timestamps & Delta Clockstamps

- **JR Clock** (utility 0x1): sender broadcasts its 16-bit internal clock
  (units of 1/31250 s ≈ 32 µs, wraps ~2 s) periodically. **JR Timestamp**
  (utility 0x2): prepended to any message, giving the send time in the same
  units; receiver uses the pair to de-jitter by scheduling against the
  recovered sender clock (UMP spec §4.1). A translator receiving
  JR-timestamped traffic destined for a non-JR link "shall schedule the
  MIDI 1.0 messages according to the received JR Timestamps" (spec §4.1.1).
- **DCTPQ** (utility 0x3) + **Delta Clockstamp** (utility 0x4), added in
  UMP v1.1: tick-based *musical* time (ticks-per-quarter-note + delta
  ticks) — designed for the **MIDI Clip File (SMF2)** container, not for
  live streams.
- **Real-world usage: effectively none.** Microsoft states flatly that
  "hardware manufacturers, AMEI, and the MIDI Association agreed that JR
  Timestamp handling in the operating systems is not needed at this time
  (and may not be needed for many years)" and tells apps not to send them
  ([Microsoft](https://microsoft.github.io/MIDI/kb/midi2-implementation-details/)).
  JR is per-hop link-level, poorly matched to multi-hop routing, and USB
  polling already bounds jitter. **Recommendation for the hub: negotiate JR
  off in Stream Configuration, accept and strip JR packets on input, never
  emit them.** Delta Clockstamps only matter if you ever read/write SMF2
  clip files.

---

## 6. Backward Compatibility & Transports

- **Negotiation-down is structural, not optional.** Every MIDI 2.0 device
  must function as a 1.0 device: USB devices must expose a MIDI 1.0
  interface, and the default protocol on a fresh UMP connection is
  effectively 1.0-in-UMP until stream configuration upgrades it.
- **USB MIDI Class 2.0**
  ([usb.org spec PDF](https://www.usb.org/sites/default/files/USB%20MIDI%20v2_0.pdf)):
  one MIDIStreaming interface with **alt setting 0 = USB MIDI 1.0**
  (`bcdMSC=0x0100`, 4-byte event packets, virtual cables) and **alt setting
  1 = MIDI 2.0** (`bcdMSC=0x0200`, raw UMP words over bulk endpoints). Old
  hosts never see alt 1; UMP-aware hosts select it. **Group Terminal
  Block** descriptors (spec §5.4) declare group topology/direction and pair
  in/out groups for bidirectional MIDI-CI. Good implementer series:
  [Building a USB MIDI 2.0 Device, MIDI.org](https://midi.org/building-a-usb-midi-2-0-device-part-1).
- **5-pin DIN**: remains a **MIDI 1.0 31.25 kbaud byte stream, period**.
  There is no UMP-over-DIN. But **MIDI-CI runs fine over DIN** (it's just
  SysEx), so Profiles and Property Exchange are usable there;
  32-bit-resolution channel voice traffic is not. A hub port on DIN is
  permanently a translation boundary.
- **Network MIDI 2.0 (UDP)**: ratified by MMA/AMEI **November 2024**,
  introduced at NAMM 2025 — native UMP over UDP with session management,
  mDNS discovery, sub-ms LAN latency
  ([MIDI.org overview](https://midi.org/network-midi-2-0-udp-overview),
  [Synthtopia](https://www.synthtopia.com/content/2025/01/26/midi-association-intros-network-midi-2-0-at-2025-namm-show/)).
  This is the successor-track to RTP-MIDI and directly relevant to this
  appliance's Hub-Link feature. Device support is only starting to appear.
- **BLE-MIDI 2.0**: transport spec still in development as of Feb 2026
  ([MIDI.org state-of update](https://midi.org/the-state-of-midi-2-0-high-resolution-performance-and-the-rise-of-profiles-update-feb-2026));
  BLE today is MIDI 1.0-only.

---

## 7. Real-World Adoption (honest assessment, mid-2026)

**Operating systems** (real, shipping):

- **Linux**: the most quietly complete story. ALSA UMP landed in **kernel
  6.5** (Aug 2023), refined through 6.12+: `CONFIG_SND_UMP`,
  `CONFIG_SND_USB_AUDIO_MIDI_V2`, UMP rawmidi devices (`/dev/snd/umpC*D*`),
  sequencer clients declaring `midi_version` 0/1/2, per-group ports plus a
  catch-all endpoint port, **automatic bidirectional 1.0↔2.0 conversion
  between clients of different versions** (a 1.0 CC arrives at a 2.0 client
  already upscaled), endpoint/function-block ioctls, a legacy rawmidi
  bridge (`CONFIG_SND_UMP_LEGACY_RAWMIDI`) exposing each group as a 1.0
  substream, and a **USB MIDI 2.0 gadget driver** (configfs) — the Pi
  itself could enumerate as a USB MIDI 2.0 device
  ([kernel docs](https://docs.kernel.org/sound/designs/midi-2.0.html)).
  `aseqdump -u 2` etc. in alsa-utils ≥1.2.10. PipeWire ≥1.2 carries UMP
  natively in its graph with automatic down-conversion
  ([linuxdj.com](https://www.linuxdj.com/notes/midi-2-0-on-linux-2026-pipewire-ump-kernel-support-and-safe-fallbacks/)).
  ALSA-sequencer-based code gets 1.0↔2.0 conversion "for free" but only
  sees 2.0 resolution if the client opens as `midi_version=2`. Python
  bindings: alsa-lib's UMP API is new; `mido`/`python-rtmidi` are 1.0-only
  today.
- **macOS/iOS**: CoreMIDI has had UMP APIs (`MIDIEventList`/
  `MIDIEventPacket`) since macOS 11/iOS 14, USB MIDI 2.0 class driver since
  **Monterey (Oct 2021)** — first shipping OS; fuller native UMP
  endpoint/MIDI 2.0-protocol API in Sonoma+ and iOS 18 (`MIDIUMPEndpoint`,
  `MIDIUMPMutableEndpoint`)
  ([Apple docs](https://developer.apple.com/documentation/coremidi/incorporating-midi-2-into-your-apps)).
- **Android**: USB MIDI 2.0 host support since **Android 13** (2022);
  virtual UMP apps via `MidiUmpDeviceService` since Android 15
  ([atsushieno](https://atsushieno.github.io/2024/04/12/midi2-on-android.html)).
- **Windows**: the long pole, finally moving. **Windows MIDI Services**
  (open source, [github.com/microsoft/MIDI](https://github.com/microsoft/MIDI))
  is UMP-native internally with translation for 1.0 apps/devices. But as of
  Windows 11 **25H2 it is only partially shipped** — the in-box
  service/multi-client routing bits are still Insider-Canary-only; retail
  GA has repeatedly slipped into 2026
  ([Sweetwater status article](https://www.sweetwater.com/sweetcare/articles/windows-11-midi-2-0/)).

**Hardware** — the honest list is short. Devices with genuinely shipping
MIDI 2.0/UMP-over-USB features: **Roland A-88MKII** (via 2024 firmware),
**Korg Keystage** (first with working Property Exchange), **Yamaha Montage
M / MODX8+** (USB MIDI 2.0 via firmware), **Native Instruments Kontrol
S-series MK3**, **Studiologic SL MK2** series, **Waldorf Iridium/Quantum**,
some 2025+ **Akai MPK** models
([Sound On Sound overview](https://www.soundonsound.com/music-business/introducing-midi-20),
[MIDI.org Feb 2026](https://midi.org/the-state-of-midi-2-0-high-resolution-performance-and-the-rise-of-profiles-update-feb-2026)).
That's on the order of **a dozen product lines after six years** — many
"MIDI 2.0 ready" devices still run 1.0 firmware with promised updates, and
virtually no synth *sound engines* respond to 32-bit resolution
meaningfully yet; the current wave is controllers. DAWs: Cubase/Nuendo and
Logic have UMP paths; on Linux only **Bitwig Studio 6** has meaningful
native UMP support; REAPER still consumes converted 1.0. The MIDI
Association's own Feb 2026 positioning has visibly shifted from "high
resolution" to **Profiles** (Piano profile, Drum maps, Orchestral
Articulation, DAW-control profiles targeted Q2 2026) as the adoption
driver. Plan the hub so MIDI 1.0 remains the lingua franca for years; 2.0
support is future-proofing plus a translation feature, not a user-base
today.

---

## 8. Common Implementer Pitfalls

1. **Spec-version churn**: the v1.0→v1.1 change making Utility/Stream
   messages groupless broke libraries (cmidi2 had to break its API for it —
   [cmidi2](https://github.com/atsushieno/cmidi2)). Target UMP v1.1.x +
   MIDI-CI v1.2 only; ignore v1.0-era protocol negotiation entirely.
2. **The RPN/NRPN + bank-select state machine** in 1.0→2.0 translation is
   the classic bug farm: devices that omit CC38, interleaved RPN/NRPN,
   null-RPN, running status. The spec's own "maybe add a timeout after CC6"
   hedge tells you how ragged real traffic is.
3. **Velocity edge cases both directions**: 2.0→1.0 velocity scaling to 0
   must become 1; 1.0 vel-0 note-on must become a 2.0 Note *Off* (velocity
   0x8000), never a vel-0 Note On.
4. **Wrong scaling method per field**: min-center-max for
   CC/velocity/pressure/bend/NRPN, but **zero-extension for RPN 0–31** —
   mixing them injects audible detune noise into
   pitch-bend-sensitivity/tuning RPNs (spec's own ⅓-cent example).
5. **Untranslatable messages**: per-note anything, relative controllers,
   SysEx8/MDS. A router must have an explicit drop/flag policy at every
   2.0→1.0 edge, or notes get stuck expressive state.
6. **Buggy devices choke on discovery**: some USB devices misbehave when
   sent UMP v1.1 endpoint inquiries — Linux grew `snd-usb-audio
   midi2_ump_probe=0` and `midi2_enable=0` module options as escape hatches
   ([kernel docs](https://docs.kernel.org/sound/designs/midi-2.0.html)). A
   hub needs the same per-device "force MIDI 1.0" toggle.
7. **USB descriptors are easy to get wrong** (GTB/alt-setting layout), and
   per Microsoft, devices without a unique `iSerialNumber` lose their
   identity/metadata when re-plugged into a different port — relevant if
   the Pi ever runs the UMP gadget driver.
8. **Don't emit JR timestamps** (§5) — OSes have agreed not to handle them.
9. **MUIDs are per-power-cycle random** — never persist device identity by
   MUID; use Device Identity/Product Instance ID (serial) instead.
10. **SysEx7 fragmentation across UMPs** (6 bytes/packet, interleavable
    across groups) means MIDI-CI parsing needs a per-group reassembly
    buffer; naive byte-stream SysEx parsers break.

---

## Key takeaways for RaspiMIDIHub

The ALSA sequencer already implements the two hardest parts of this
briefing — UMP transport and spec-compliant bidirectional translation —
in-kernel: existing `midi_version=0/1` sequencer clients keep working
against MIDI 2.0 hardware unchanged. Incremental adoption path: (a) verify
the Pi kernel has `SND_UMP`/`SND_USB_AUDIO_MIDI_V2`; (b) surface UMP
endpoint/function-block names in device listings; (c) open the hub's
sequencer client as `midi_version=2` only when routing/filter code is ready
for 32-bit values and new event types; (d) treat MIDI-CI (discovery/PE
patch names) as an application-layer feature the hub could own, since no OS
does it for you; (e) watch Network MIDI 2.0 (UDP) as the successor to the
existing RTP-MIDI Hub-Link work.

**Primary sources:**
[M2-104-UM UMP & MIDI 2.0 Protocol v1.1.2 (PDF)](https://amei-music.github.io/midi2.0-docs/amei-pdf/M2-104-UM_v1-1-2_UMP_and_MIDI_2-0_Protocol_Specification.pdf) ·
[M2-115-U Bit Scaling v1.0.2 (PDF)](https://amei-music.github.io/midi2.0-docs/amei-pdf/M2-115-U_v1-0-2_MIDI%202.0%20Bit%20Scaling%20and%20Resolution.pdf) ·
[USB MIDI Class 2.0 (PDF)](https://www.usb.org/sites/default/files/USB%20MIDI%20v2_0.pdf) ·
[Linux kernel MIDI 2.0 docs](https://docs.kernel.org/sound/designs/midi-2.0.html) ·
[Microsoft MIDI 2.0 implementation details](https://microsoft.github.io/MIDI/kb/midi2-implementation-details/) ·
[MIDI.org State of MIDI 2.0 (Feb 2026)](https://midi.org/the-state-of-midi-2-0-high-resolution-performance-and-the-rise-of-profiles-update-feb-2026) ·
[MIDI.org MIDI-CI details](https://midi.org/details-about-midi-2-0-midi-ci-profiles-and-property-exchange-updated-june-2023) ·
[Network MIDI 2.0 UDP overview](https://midi.org/network-midi-2-0-udp-overview) ·
[atsushieno on MIDI-CI tooling](https://atsushieno.github.io/2024/01/26/midi-ci-tools.html) ·
[linuxdj.com Linux 2026 status](https://www.linuxdj.com/notes/midi-2-0-on-linux-2026-pipewire-ump-kernel-support-and-safe-fallbacks/)
