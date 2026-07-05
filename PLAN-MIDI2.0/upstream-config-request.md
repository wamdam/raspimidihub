# Upstream kernel config request (FSD-01 work item 1)

**Status: FILED 2026-07-04 — https://github.com/raspberrypi/linux/issues/7474**
Check back per release cycle; on accept, note the first RPi OS kernel
version that ships the configs in FSD-01's decision memo.

---

**Title:** Enable MIDI 2.0 / UMP support (SND_UMP, SND_USB_AUDIO_MIDI_V2,
USB_CONFIGFS_F_MIDI2) in the Pi kernel configs

**Body:**

Raspberry Pi OS kernels currently ship with all ALSA MIDI 2.0 / UMP
options disabled. The support has been upstream since kernel 6.5
(refined through 6.12, which the Pi kernels are based on), and Trixie's
userspace is already fully UMP-capable (alsa-lib 1.2.14, alsa-utils
with `aseqdump -u 2` / `aplaymidi2`), so the kernel configs are the
only missing piece for MIDI 2.0 hardware support on the Pi.

Request: enable in `bcm2711_defconfig` / `bcm2712_defconfig` (and the
32-bit configs if practical):

```
CONFIG_SND_UMP=m                  # (selected by the below)
CONFIG_SND_UMP_LEGACY_RAWMIDI=y   # legacy rawmidi bridge per UMP group
CONFIG_SND_SEQ_UMP=y              # sequencer UMP event support
CONFIG_SND_SEQ_UMP_CLIENT=m
CONFIG_SND_USB_AUDIO_MIDI_V2=y    # USB MIDI 2.0 (bool inside snd-usb-audio)
CONFIG_USB_CONFIGFS_F_MIDI2=m     # USB MIDI 2.0 gadget (f_midi2)
```

Rationale / precedent:

- Ubuntu enables exactly these (noble: `SND_UMP=m`,
  `SND_USB_AUDIO_MIDI_V2=y`, `USB_CONFIGFS_F_MIDI2=y`), as do
  Fedora and Arch.
- Cost when unused is negligible: `SND_USB_AUDIO_MIDI_V2` only changes
  probing for devices that actually expose a MIDI 2.0 altsetting
  (MIDI 1.0 devices are handled exactly as before), and module options
  `midi2_enable=0` / `midi2_ump_probe=0` exist as escape hatches.
- The Pi is a popular platform for MIDI hubs/routers and synth
  projects; MIDI 2.0 controllers (Roland A-88MKII, Korg Keystage,
  NI Kontrol S MK3, newer Akai MPKs) are shipping now, and the
  `f_midi2` gadget would let Pi-based devices present themselves as
  USB MIDI 2.0 peripherals with automatic 1.0 fallback.
- `USB_CONFIGFS_F_MIDI` (the MIDI 1.0 gadget) is already enabled, so
  `f_midi2` is the natural counterpart.

Happy to test on Pi 3B+/4/5 hardware — we maintain a Pi-based MIDI
appliance (RaspiMIDIHub) and have verified the equivalent module set
builds and runs on 6.12.75+rpt.

---

**Post-filing:** record the issue URL here and check back per release
cycle. If declined/stalled, decide between shipping a module-rebuild
package or documenting self-build (see FSD-01 §risks + decision memo).
