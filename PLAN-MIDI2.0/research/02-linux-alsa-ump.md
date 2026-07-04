# Research Annex 2 — MIDI 2.0 on Linux / ALSA / Raspberry Pi OS

Compiled 2026-07. Verified against kernel sources (rpi-6.12.y through
rpi-6.18.y defconfigs), alsa-lib release notes, Debian package archives,
and the upstream binding repositories.

> **Editor's note / correction:** parts of §4 were originally researched
> against the `alsa-midi` PyPI package. RaspiMIDIHub does **not** use it —
> the repo has a hand-rolled ctypes binding to libasound
> (`src/raspimidihub/alsa_seq.py`, see Annex 3 §1) and zero runtime pip
> dependencies. The conclusion is the same but simpler: we extend **our
> own** binding; there is no third-party library to wait for.

## 1. ALSA Sequencer UMP Support (kernel 6.5+)

The whole MIDI 2.0 stack landed in **kernel 6.5** (merged May–June 2023,
authored by Takashi Iwai) as one large series: UMP core, ALSA sequencer UMP
binding, and the USB MIDI 2.0 driver
([LWN: "ALSA: Add MIDI 2.0 support"](https://lwn.net/Articles/932437/),
[UMP 1.1 follow-up](https://lwn.net/Articles/934414/)). It was then refined
continuously through ~6.12 (Function Block handling, protocol switching,
legacy-rawmidi fixes). The canonical reference is the kernel doc
["MIDI 2.0 on Linux"](https://docs.kernel.org/sound/designs/midi-2.0.html)
— thorough, current, and the primary design document for this plan.

Key sequencer facts:

- **Event type.** A new `snd_seq_ump_event` is layout-compatible with
  `snd_seq_event` but carries a 16-byte payload (one full 128-bit UMP
  packet) instead of 12 bytes, flagged with `SNDRV_SEQ_EVENT_UMP` in the
  event flags. Same queues, same timestamping, same delivery machinery.
- **Client MIDI version.** Each seq client declares `midi_version` in
  `snd_seq_client_info`: 0 = legacy (what our clients are today), 1 = UMP
  MIDI 1.0, 2 = UMP MIDI 2.0. New configs: `CONFIG_SND_UMP`,
  `CONFIG_SND_UMP_LEGACY_RAWMIDI`, `CONFIG_SND_SEQ_UMP`,
  `CONFIG_SND_SEQ_UMP_CLIENT`, `CONFIG_SND_USB_AUDIO_MIDI_V2`.
- **Automatic conversion — the critical answer: yes, transparent.** The
  kernel converts events *per delivery* based on the receiving client's
  `midi_version`: legacy ↔ UMP MIDI 1.0 ↔ UMP MIDI 2.0, in every
  direction. A legacy MIDI 1.0 seq client (our hub) can subscribe to/from
  a UMP MIDI 2.0 endpoint's ports and everything works — the kernel
  down-converts MIDI 2.0 channel voice messages (16-bit velocity → 7-bit,
  32-bit CC → 7-bit, RPN/NRPN message pairs, etc.) and up-converts on the
  way in. Our existing kernel-side port-subscription routing therefore
  keeps working unchanged against MIDI 2.0 hardware. The conversion is
  lossy where MIDI 1.0 has no equivalent (per-note controllers, per-note
  pitch, attribute data; UMP-1.1-only messages get dropped or
  approximated). Pass-through clients that must not be converted set
  `SNDRV_SEQ_FILTER_NO_CONVERT`.
- **Group ports.** A UMP endpoint client exposes port 0 as a catch-all
  "MIDI 2.0" endpoint port (all 16 groups + groupless messages) and ports
  1–16 for individual UMP Groups (`ump_group` field in port info). Groups
  not backed by an active Function Block are flagged
  `SNDRV_SEQ_PORT_CAP_INACTIVE`. To a legacy client, the group ports look
  and behave like ordinary seq ports — in our routing matrix, a MIDI 2.0
  device simply shows up as up-to-17 ports instead of one-per-USB-cable.

## 2. USB MIDI 2.0: Host Driver and Gadget

**Host side** (`CONFIG_SND_USB_AUDIO_MIDI_V2`, kernel 6.5): when enabled,
snd-usb-audio probes the MIDI 2.0 interface (altsetting 1) first and falls
back to MIDI 1.0 (altsetting 0); the `midi2_enable=0` module option reverts
to MIDI 1.0 binding at runtime
([kernel doc](https://docs.kernel.org/sound/designs/midi-2.0.html)). Each
UMP Endpoint gets a **UMP rawmidi device** at `/dev/snd/umpC*D*`
(reads/writes are 32-bit-word aligned UMP packets, not byte streams),
distinct from legacy `/dev/snd/midiC*D*`. With
`CONFIG_SND_UMP_LEGACY_RAWMIDI`, an additional legacy rawmidi device with
16 substreams (one per group) is created for old apps. Important build
detail (verified in the Kconfig): `SND_USB_AUDIO_MIDI_V2` is a **bool
compiled into snd-usb-audio** (default off), which selects `SND_UMP`; it is
not a loadable add-on module — this matters for the Pi (§5).

**Gadget side** (Pi as a USB *device*): the `f_midi2` USB gadget function
was merged in **kernel 6.6**
([Phoronix](https://www.phoronix.com/news/Linux-6.6-USB),
[LWN patch series](https://lwn.net/Articles/939185/)), needing
`CONFIG_USB_GADGET` + `CONFIG_USB_CONFIGFS` + `CONFIG_USB_CONFIGFS_F_MIDI2`.
It emulates a USB MIDI 2.0 device **with automatic MIDI 1.0 fallback** for
old hosts, configured entirely via configfs
(`/sys/kernel/config/usb_gadget/...`): per-endpoint attributes (`ep_name`,
`iface_name`, `protocol`, `manufacturer`, `family`/`model`, ...) and
per-Function-Block attributes (`name`, `first_group`, `num_groups`,
`direction`, `ui_hint`, `is_midi1`, `midi1_first_group`/
`midi1_num_groups`), multiple endpoints and FBs supported
([gadget-testing doc](https://www.kernel.org/doc/html/latest/usb/gadget-testing.html)).
When bound it creates a local ALSA card with a UMP rawmidi (loop-back to
the USB host) plus a legacy rawmidi — hub-side software talks to it through
the normal ALSA seq/rawmidi path. This is the natural upgrade path for a
"Pi as USB MIDI device" feature and a much richer replacement for the old
`f_midi` gadget.

**Introspection:** endpoint/FB info is exposed via ioctls
(`SNDRV_UMP_IOCTL_ENDPOINT_INFO`, `SNDRV_UMP_IOCTL_BLOCK_INFO`, and
control-API variants `SNDRV_CTL_IOCTL_UMP_*` that work without opening the
device) and human-readably in `/proc/asound/card*/midi*` and
`/proc/asound/seq/clients` — verified in `sound/core/ump.c` (v6.12): it's
proc + ioctls, not sysfs attributes; the "/sys interface" people mention is
the gadget's configfs.

## 3. alsa-lib and alsa-utils

- **alsa-lib 1.2.10** (Sept 2023) is the minimum for UMP: new `ump.h` with
  the `snd_ump_*` rawmidi-UMP API, and seq-side `snd_seq_ump_event_t`,
  `snd_seq_ump_event_input()`/`snd_seq_ump_event_output()`,
  `snd_seq_client_set_midi_version()` (switch a client to UMP 1.0/2.0 on
  the fly), `snd_seq_client_set_ump_conversion()` (suppress
  auto-conversion), and `snd_seq_get_ump_endpoint_info()`/
  `snd_seq_get_ump_block_info()`
  ([release notes](https://web.alsa-project.org/wiki/Detailed_changes_v1.2.9_v1.2.10)).
  Refinements continued through
  [1.2.13](https://www.alsa-project.org/wiki/Detailed_changes_v1.2.12_v1.2.13)
  and
  [1.2.14](https://www.alsa-project.org/wiki/Detailed_changes_v1.2.13_v1.2.14).
- **alsa-utils 1.2.10**: `aseqdump -u {0|1|2}` (run as legacy/UMP1/UMP2
  client) and `-r` (raw, no conversion); `aconnect` and `aplaymidi` became
  UMP-aware
  ([aseqdump man page](https://manpages.debian.org/testing/alsa-utils/aseqdump.1.en.html)).
  alsa-utils 1.2.13 added `aplaymidi2`/`arecordmidi2` for the new MIDI Clip
  File format. `aseqdump -u 2` and the `aplaymidi2` source are the best
  small reference clients for the seq UMP API.

## 4. Python Bindings: Nothing Supports UMP Yet

Verified directly against the sources:

- **[python-alsa-midi](https://github.com/Jajcus/python-alsa-midi)**
  (`alsa-midi` on PyPI, cffi-based): latest release 1.0.4 (Jan 2026),
  actively maintained — but its cffi definitions contain **zero** "ump"
  hits and there is no MIDI 2.0 issue/PR. No UMP support.
- **[pyalsa / alsa-python](https://github.com/alsa-project/alsa-python)**
  (official ALSA project bindings): `pyalsa/alsaseq.c` has **zero** "ump"
  occurrences. No support.
- `alsaseq` (ppaez) is long dormant; `mido`/`python-rtmidi` are MIDI 1.0
  byte-stream only.

**For RaspiMIDIHub the question is moot** (see editor's note): the project
owns its ctypes binding, so the path is to extend `alsa_seq.py` with the
UMP structs/calls above. UMP packets are plain 32-bit words —
packing/unpacking MIDI 2.0 channel-voice messages in pure Python is
trivial and cheap (4×uint32). The raw `/dev/snd/umpC*D*` path (bypassing
the sequencer) would lose our routing/queue model entirely and is not
appropriate here.

## 5. Raspberry Pi OS Reality Check — the Headline Finding

- **Raspberry Pi OS Trixie** (Debian 13 based, released 2025-10-01) runs
  **kernel 6.12 LTS**
  ([raspberrypi.com](https://www.raspberrypi.com/news/trixie-the-new-version-of-raspberry-pi-os/));
  the final Bookworm update (May 2025) also moved to 6.12. So the kernel
  *version* is comfortably ≥ 6.5.
- **But the Raspberry Pi kernel does not enable any of the MIDI 2.0
  configs.** Checked `bcm2711_defconfig` and `bcm2712_defconfig` on
  `rpi-6.12.y`, and again on `rpi-6.15.y`/`rpi-6.17.y`/`rpi-6.18.y` in
  [raspberrypi/linux](https://github.com/raspberrypi/linux): **no**
  `SND_UMP`, **no** `SND_USB_AUDIO_MIDI_V2`, **no** `USB_CONFIGFS_F_MIDI2`
  in any branch (they do ship `USB_CONFIGFS_F_MIDI` — the old MIDI 1.0
  gadget). Since `SND_USB_AUDIO_MIDI_V2` is a bool with no default,
  absence = off, and `SND_UMP` is only pulled in by selects. No open
  issue/PR requests it.
- **Vanilla Debian doesn't enable it either** — checked shipped kernel
  configs for trixie (6.12.86-1) and sid (7.0.14-1) on sources.debian.org:
  no `SND_USB_AUDIO_MIDI_V2`. **Ubuntu does** (noble annotations:
  `SND_UMP=m`, `SND_USB_AUDIO_MIDI_V2=y`, `USB_CONFIGFS_F_MIDI2=y`), as do
  Fedora/Arch.
- Userspace on Trixie is ready: **alsa-lib 1.2.14**
  ([packages.debian.org](https://packages.debian.org/trixie/libasound2t64))
  and matching alsa-utils have full UMP support. Bookworm's alsa-lib 1.2.8
  predates UMP entirely.

**Net for a Pi 4/5 on current Raspberry Pi OS today: no kernel UMP
anywhere.** USB MIDI 2.0 devices still work — they enumerate via their
mandatory MIDI 1.0 altsetting 0 and behave as MIDI 1.0 devices. To get
real MIDI 2.0 we must either (a) file a config request with Raspberry Pi
(low-cost, worth doing early — precedent: Ubuntu ships it), (b) rebuild
the kernel/deb with the configs on (well-trodden on Pi, but conflicts with
the apt-upgradeable appliance story), or (c) rebuild just the affected
modules (snd-usb-audio with the bool on, plus snd-ump, snd-seq-ump-client,
usb_f_midi2) against Pi kernel headers as a DKMS-style package — feasible
but per-kernel-update fragile. **This is the gating item for the whole
roadmap; the Python-binding work is small by comparison.**

## 6. Endpoint Discovery and MIDI-CI

Split is clean: **the kernel owns UMP endpoint/topology discovery; MIDI-CI
is entirely userspace.**

- At probe, the USB driver sends UMP 1.1 **stream messages** (Endpoint
  Discovery, Function Block Discovery) to the device and builds ALSA's
  topology from the replies — endpoint name, product ID, protocol caps,
  and named Function Blocks; for devices that don't answer it falls back
  to USB **Group Terminal Block** descriptors (`midi2_ump_probe=0` forces
  the fallback). Seq group ports are named from FB names and are updated
  when the device sends FB-change notifications (unless the endpoint
  declares itself static). Our UI can show real function-block names per
  group for free, via `snd_seq_get_ump_block_info()`.
- **MIDI-CI** (discovery, profiles, property exchange) is explicitly *not*
  in the kernel: "MIDI-CI is supported in user-space over the standard
  SysEx." There is no standard Linux MIDI-CI daemon; if the hub wants
  profile/property support, that's application code (§8 for libraries).
  For a routing hub, note the classic hazard: MIDI-CI sessions are
  endpoint-to-endpoint SysEx conversations — a hub that fans SysEx out to
  multiple destinations can confuse them; we'd eventually want
  per-connection MIDI-CI awareness or at least a "don't fork CI SysEx"
  story.

## 7. Network and BLE Transports (relevant to Hub-Link and BT bridge)

- **Network MIDI 2.0 (UDP)**: a real, ratified standard — adopted by the
  MIDI Association and AMEI in **November 2024**
  ([midi.org overview](https://midi.org/network-midi-2-0-udp-overview)).
  It carries UMP (both MIDI 1.0 and 2.0 protocol) over UDP with its own
  session/discovery layer (mDNS-based, `_midi2._udp`), FEC-style
  retransmit — and it is **not** RTP-MIDI/AppleMIDI-compatible; it's a
  separate protocol. RTP-MIDI itself remains a MIDI 1.0 byte-stream
  transport with no UMP payload standard. For Hub-Link (AppleMIDI) this
  means: no incremental upgrade path — MIDI 2.0 over the network would be
  a *second* transport implemented in userspace (no kernel involvement; a
  Python or C implementation is entirely feasible —
  [Zephyr ships a sample](https://docs.zephyrproject.org/latest/samples/net/midi2/README.html),
  and Windows MIDI Services has it on its roadmap). Our existing mDNS
  plumbing is a head start.
- **BLE-MIDI**: still MIDI 1.0 only. A **BLE MIDI 2.0 transport is in
  development but not finalized** as of the MIDI Association's
  [February 2026 update](https://midi.org/the-state-of-midi-2-0-high-resolution-performance-and-the-rise-of-profiles-update-feb-2026).
  Nothing to implement yet; the BlueZ bridge stays as-is.
- Ecosystem context: PipeWire 1.2+/1.4 moved its internal MIDI plumbing to
  UMP with conversion at node boundaries; as of mid-2026 Bitwig 6 is about
  the only Linux DAW with meaningful native MIDI 2.0; most "MIDI 2.0
  ready" controllers still ship MIDI 1.0 firmware
  ([Linux DJ overview, 2026](https://www.linuxdj.com/notes/midi-2-0-on-linux-2026-pipewire-ump-kernel-support-and-safe-fallbacks/)).
  Real UMP hardware today: Roland A-88MK2, NI Kontrol S MK3, newer Akai
  MPKs, CME WIDI.

## 8. Reference Implementations to Study

- **[AM_MIDI2.0Lib](https://github.com/midi2-dev/AM_MIDI2.0Lib)** (Andrew
  Mee, MIT, C++): small, portable UMP + MIDI-CI processing library; the
  de-facto reference for UMP translation logic. Hub:
  [midi2-dev on GitHub](https://github.com/midi2-dev) /
  [midi2.dev](https://midi2.dev/) — also hosts
  **[MIDI2.0Workbench](https://github.com/midi2-dev/MIDI2.0Workbench)**,
  the testing/validation tool (invaluable once real UMP is flowing), plus
  USB descriptor helpers. There's also the Rust **midi2 crate** (100% of
  UMP + MIDI-CI).
- **[libremidi](https://github.com/celtera/libremidi)** (C++): modern
  cross-platform MIDI 1 + MIDI 2 real-time I/O with a native ALSA seq UMP
  backend — the best example of *exactly* our integration problem (seq
  client with `midi_version=2`, group ports, conversion flags) in library
  form.
- **[Windows MIDI Services](https://github.com/microsoft/MIDI)**
  (Microsoft + AMEI, open source): the largest MIDI 2.0 codebase; its
  transport plugins and UMP↔MIDI1 translation logic are
  cross-platform-readable.
- **In-tree ALSA code**: `alsa-utils/seq/aseqdump/aseqdump.c` (UMP seq
  client in ~hundreds of lines) and kernel
  `sound/core/seq/seq_ump_convert.c` (the exact conversion rules our hub
  inherits when bridging MIDI 1.0 clients to UMP endpoints) are the two
  files most worth reading before writing the Python layer.

## Bottom line for planning

1. The ALSA architecture is ideal for us: kernel-side conversion means
   MIDI 2.0 devices already interoperate with our legacy seq client, and
   "native" support is an *incremental* upgrade (declare `midi_version=2`,
   handle 16-byte events, model group ports), not a rewrite.
2. The blocker is not software design — it's that **Raspberry Pi OS
   kernels ship with every MIDI 2.0 config off** (verified through
   rpi-6.18.y). File the config request first; everything else can proceed
   against a self-built kernel on the test Pi.
3. Python bindings don't exist anywhere; extending our own ctypes binding
   in `alsa_seq.py` is the sane path and a modest amount of work.
4. Network/BLE MIDI 2.0: the UDP standard exists (Nov 2024,
   userspace-implementable, not AppleMIDI-compatible); BLE is still
   unratified as of Feb 2026 — no action needed there yet.
