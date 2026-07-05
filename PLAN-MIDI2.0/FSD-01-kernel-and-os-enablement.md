# FSD-01 — Kernel & OS enablement + runtime capability detection

**Step:** 0 · **Depends on:** nothing · **Blocks:** all on-hardware
verification (software FSDs can proceed against mocks/laptop)

## Status (2026-07-05): DONE — Step 0 gate passed

- Work item 1 — upstream request **filed**:
  https://github.com/raspberrypi/linux/issues/7474 (watch per release).
- Work item 2 — UMP modules built + installed on the A6DC test Pi
  (Pi 3B+, 6.12.75+rpt-rpi-v8) via `build-ump-modules.sh`; vermagic
  verified, survives in `/lib/modules/…/updates/`. See
  `kernel-build-notes.md` for the four traps hit on the way
  (version-exact source, cross-M= symvers, LOCALVERSION/vermagic,
  no-RTC clock vs apt signatures).
- Work item 3 — runtime probe shipped
  (`alsa_seq.probe_ump_support()`, logged at engine start, `midi2`
  field in GET /api/system) + 5 unit tests. Verified both ways on the
  same hardware: `kernel=no` pre-modules, `kernel=yes` post-reboot;
  `aseqdump -u 2` runs as a UMP client.
- Work items 4/5 — log line ships with the probe; decision memo waits
  on the upstream issue's outcome.
- USB MIDI 1.0 regression vs the rebuilt snd-usb-audio: **passed**
  (Keystation Mini 32). Probe fell back per design ("Quirk or no
  altset; falling back to MIDI 1.0"), enumeration + hub registry +
  real hotplug + simulated replug (sysfs unbind/rebind) + TX
  (note_on/off via /api/devices/{id}/send) + RX (41 captured
  note-ons, correct velocities) all clean; zero errors in the boot
  journal. Optional cross-check on the stock-kernel 5A5D reference
  Pi remains available but the same deb was already verified
  pre-modules on A6DC itself (kernel=no path).

## Goal

Get a UMP-capable kernel onto the A6DC test Pi, start the upstream
process to make Raspberry Pi OS ship the configs, and give the hub a
single runtime capability probe that every later FSD gates on. On
kernels without UMP the hub must behave byte-for-byte as today.

## Non-goals

No UMP code in the hub beyond the capability probe. No change to the
shipped image yet (that lands when upstream/packaging is resolved).

## Current state

- Target OS: Raspberry Pi OS **Trixie**, kernel 6.12 LTS. alsa-lib
  1.2.14 (UMP-complete). See research annex 2 §5.
- Pi kernels have `SND_UMP`, `SND_USB_AUDIO_MIDI_V2`,
  `USB_CONFIGFS_F_MIDI2` **absent/off** in all branches through
  rpi-6.18.y. `SND_USB_AUDIO_MIDI_V2` is a *bool inside snd-usb-audio*,
  so enabling it means rebuilding that module, not adding one.
- Appliance constraints: read-only FS, apt-based update path
  (`17-connectivity-and-updates.md`), watchdog/reliability story
  (`18-appliance-reliability.md`).

## Work items

1. **Upstream config request (do first, it's free).** File an issue/PR
   against `raspberrypi/linux` requesting `SND_UMP=m`,
   `SND_SEQ_UMP_CLIENT=m`, `SND_UMP_LEGACY_RAWMIDI=y`,
   `SND_USB_AUDIO_MIDI_V2=y`, `USB_CONFIGFS_F_MIDI2=m` in
   bcm2711/bcm2712 defconfigs. Cite Ubuntu noble shipping the same
   (precedent), zero cost when unused (bool defaults to probing alt-set 1
   only when a device offers it; `midi2_enable=0` module option exists).
2. **Test-Pi kernel.** Build the Pi kernel (rpi-6.12.y, bcm2711_defconfig
   + the configs above) and install on A6DC only. Document the build
   recipe in this directory (`kernel-build-notes.md`, added when done) so
   it is reproducible after `rpi-update`-style bumps.
3. **Runtime capability probe** in the hub (small, ships immediately):
   - `alsa_seq.py`: probe once at startup — (a) alsa-lib exports
     `snd_seq_client_info_get_midi_version` (ctypes `hasattr`-style
     lookup, same pattern as the existing mock fallback L28–37); (b) the
     kernel accepts setting `midi_version=1` on a scratch client (kernels
     without `CONFIG_SND_SEQ_UMP` reject/ignore it); expose
     `AlsaSeq.ump_capable: bool`.
   - Surface it read-only in `GET /api/status` (or the existing settings
     info endpoint — check `api.py` for the current system-info route and
     extend it) so the UI and support flows can see why 2.0 features are
     absent.
4. **Fleet guard:** the probe result is logged once at startup
   (`ump: kernel=yes/no alsa-lib=yes/no`) for support bundles.
5. **Decision memo** (short section appended to this FSD when known):
   upstream accepted → ship configs with which RPi OS kernel version;
   upstream declined → evaluate (a) module-rebuild deb built per kernel
   version in CI, (b) full self-built kernel in our image (`image/`
   pipeline), (c) feature stays "advanced users only". Each option's
   interaction with the apt-update path and read-only FS must be written
   down before choosing.

## Config / API / manual impact

- No config keys. One new read-only field in the status/info API
  (self-documenting route summary per project rules).
- Manual: `21-technical-information.md` gains a "MIDI 2.0 kernel
  requirements" subsection; `18-appliance-reliability.md` notes graceful
  degradation. (Written in Step 2 when the feature becomes visible;
  Step 0 itself is invisible.)

## Tests

- Unit: capability probe against the mock lib (reports False), and a
  fake lib exposing the symbols (reports True).
- Hardware: on A6DC with the new kernel, `cat /proc/asound/seq/clients`
  shows UMP fields; `aseqdump -u 2 -l` lists a plugged 2.0 device (or the
  f_midi2 gadget from another machine).

## UX verification (gate to Step 1)

1. Hub deb installed on A6DC with UMP kernel: boots clean, all existing
   behaviour unchanged (routing, plugins, autosave, watchdog).
2. Same deb on the 5A5D reference Pi (stock kernel): identical behaviour,
   probe reports `ump_capable=false`, no errors logged.
3. `aseqdump -u 2` on A6DC decodes UMP from a reference peer.

## Risks

- Upstream request stalls → the whole 2.0 story ships dark (code present,
  enabled only on capable kernels). That is acceptable: every later FSD
  is written to degrade gracefully, so upstream timing never blocks
  merging code.
- `SND_USB_AUDIO_MIDI_V2=y` changes probing order for *all* USB MIDI
  devices (alt-set 1 first). Mitigation: soak the current device park
  against the new kernel early in Step 0; `midi2_ump_probe=0` /
  `midi2_enable=0` are the escape hatches, and FSD-04's per-device
  Force-1.0 toggle builds on them.
