# Step 0 — UMP kernel modules for the test Pi (FSD-01 work item 2)

Target: A6DC test Pi, Raspberry Pi 3B+, RPi OS Trixie, kernel
`6.12.75+rpt-rpi-v8` (Debian-packaged, `CONFIG_MODVERSIONS=y`, modules
xz-compressed). Strategy: **module-set rebuild**, not a full kernel —
rebuild `snd-seq` (gains `CONFIG_SND_SEQ_UMP`), `snd-usb-audio` (gains
`CONFIG_SND_USB_AUDIO_MIDI_V2`, a bool inside the module), plus the new
`snd-ump` and `snd-seq-ump-client`, from the exact apt source with the
running config + the headers' `Module.symvers` (CRC match), installed
to `/lib/modules/$KVER/updates/` (wins over `kernel/` in depmod order).

Runbook: `build-ump-modules.sh` (in this directory) — copied to the Pi
and run there. Takes ~20–40 min on the 3B+. Requires internet on the
Pi. **Lesson learned:** the NAT route (`nat.sh` + default route via
169.254.1.1) proved fragile twice — the hub's connectivity stack
rewrites `/var/run/resolv.conf` (fixed by pinning repo IPs in
`/etc/hosts`), and the dev machine's firewall silently re-flushed the
forward rules mid-download. The robust setup is a **reverse SOCKS
tunnel** over the existing ssh session instead:

    dev$ ssh -f -N -o ExitOnForwardFailure=yes -R 1080 user@<pi>
    pi$  echo 'Acquire::http::Proxy "socks5h://localhost:1080";' \
           | sudo tee /etc/apt/apt.conf.d/99midi2proxy

Remove `/etc/apt/apt.conf.d/99midi2proxy` after the build (apt fails
closed while it exists without the tunnel).

Persistent changes to the test Pi (acceptable, documented):
- `/etc/apt/sources.list.d/rpt-src.sources` (deb-src for the kernel)
- build packages (dpkg-dev, bison, flex, bc, libssl-dev)
- `~user/midi2-kernel/` build tree (~2 GB)
- `/lib/modules/$KVER/updates/*.ko` + depmod

Runtime-only (gone on reboot): default route, resolv.conf override,
NAT rules on the dev machine.

Verification after reboot:
1. `modinfo snd-usb-audio | grep -i midi2` / `modprobe snd-ump` loads.
2. Hub log line flips to `UMP (MIDI 2.0) support: kernel=yes`.
3. `aseqdump -u 2 -l` runs as a UMP client;
   `/proc/asound/seq/clients` shows the midi_version field.
4. Full 1.0 regression: existing USB devices enumerate + route
   unchanged (the rebuilt snd-usb-audio probes alt-set 1 first — watch
   for device quirks; escape hatch `snd_usb_audio.midi2_enable=0`).

Fragility: the `updates/` modules are built for exactly
`6.12.75+rpt-rpi-v8`. Any kernel upgrade orphans them (new kernel
simply lacks UMP again until rebuilt — fails safe, probe reports
kernel=no). Re-run the script after kernel bumps.

Rejected alternatives: full kernel rebuild (hours on a 3B+, breaks the
apt kernel-update story); cross-compile (no aarch64 toolchain on the
dev machine, not installing one globally per project rules); DKMS
packaging (premature until the upstream config request is answered).
