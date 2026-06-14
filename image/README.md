# RaspiMIDIHub bootstrap image

A pre-built Raspberry Pi OS Lite (64-bit) image that **auto-installs RaspiMIDIHub
on first boot** by running the same `install.sh` shipped with every release. The
image itself doesn't change between RaspiMIDIHub releases — only the underlying
RPi OS Lite version does, when we choose to refresh it.

End users flash it via **Raspberry Pi Imager** with the customization wizard
(WiFi credentials, keyboard layout, hostname, SSH).

## What's inside the image

Three files dropped onto a fresh RPi OS Lite image:

| File | Purpose |
|---|---|
| `/usr/local/sbin/firstboot-led` | LED state helper (green ACT LED only) |
| `/usr/local/sbin/raspimidihub-bootstrap-run` | First-boot runner — fetches install.sh, runs it, reboots |
| `/etc/systemd/system/raspimidihub-bootstrap.service` | Oneshot, enabled at multi-user.target |

The unit is gated by `ConditionPathExists=!/var/lib/raspimidihub/bootstrap-done`
so it can never re-run after a successful install.

The build also runs `systemctl enable ssh` so that sshd comes up on first
boot. Stock RPi OS / cloud-init does **not** reliably enable sshd, which left
a failed bootstrap undiagnosable — the fail-LED tells the user to "SSH in and
run `journalctl`", but there was nothing listening. With ssh enabled at build
time, the wizard's user (key or password) can actually get in.

## Build prerequisites (one-time)

On a Debian/Ubuntu host (x86_64 is fine — `virt-customize` handles ARM via
qemu-user):

```bash
sudo apt install libguestfs-tools qemu-user-static xz-utils curl
```

That's everything. No Docker, no VM, no pi-gen, no real Pi needed for the build.

The build prompts for `sudo` twice — once for `virt-customize` (drops our
firstboot scripts into `/etc` and `/usr/local/sbin`) and once for
`virt-sparsify` (zeros free blocks so xz can compress them away). Both are
libguestfs operations that need to read the host kernel to build their
internal appliance. Output files end up owned by you, not root.

We deliberately do **not** run `pishrink`. Pishrink wipes `/var/log/*` and
`/var/lib/cloud/`, which breaks cloud-init's first-boot customization on RPi
OS Trixie (where Pi Imager applies WiFi / keyboard / user via cloud-init).
`virt-sparsify` gets us most of the compression benefit without touching that
state.

## Building

```bash
cd image/
./build.sh
```

The script:

1. Resolves the current Raspberry Pi OS Lite (64-bit) URL via the official
   `raspios_lite_arm64_latest` redirect.
2. Downloads it into `cache/` **only if newer** than the local copy (curl
   `--time-cond`).
3. Decompresses to `work/`, runs `virt-customize` to drop in the three files
   above, enable the systemd unit, and `systemctl enable ssh` (so a failed
   first boot is diagnosable over SSH).
4. Runs `virt-sparsify` (needs sudo) to zero unused blocks.
5. Compresses with `xz -T0 -9`.
6. Emits `dist/raspimidihub-bootstrap-<date>.img.xz` and `dist/os-list.json`
   with hashes filled in.

Re-running is cheap: nothing is rebuilt unless the upstream image or any
`image/*` source file is newer than the last output.

## Releasing

1. Run `./build.sh` — get `dist/raspimidihub-bootstrap-YYYY-MM-DD.img.xz`.
2. Create a GitHub release tagged e.g. `image-YYYY-MM-DD` (separate from code
   releases — the image stays valid across many code releases).
3. Upload the `.img.xz` as an asset.
4. Re-emit the manifest with the real asset URL:
   ```bash
   RELEASE_URL=https://github.com/wamdam/raspimidihub/releases/download/image-YYYY-MM-DD/raspimidihub-bootstrap-YYYY-MM-DD.img.xz \
     ./build.sh
   ```
   (No actual rebuild happens — only `dist/os-list.json` is regenerated with
   the real URL.)
5. Copy `dist/os-list.json` over `image/os-list.json` and commit:
   ```bash
   cp dist/os-list.json image/os-list.json
   git add image/os-list.json && git commit -m "image: bump manifest to YYYY-MM-DD"
   ```

The user-facing URL stays stable:
`https://raw.githubusercontent.com/wamdam/raspimidihub/main/image/os-list.json`

## End-user instructions (for the main README)

1. Open Raspberry Pi Imager → ⚙ Settings → **Use custom repository** and paste:
   `https://raw.githubusercontent.com/wamdam/raspimidihub/main/image/os-list.json`
2. Pick **RaspiMIDIHub OS**.
3. Click **Customize** (or wait for the wizard prompt) — set WiFi credentials,
   keyboard layout, hostname, SSH if wanted.
4. Flash. Boot the Pi.
5. Watch the green ACT LED (next to the SD slot):

   | LED pattern | Meaning |
   |---|---|
   | Slow heartbeat | Starting up, waiting for network |
   | Medium blink (~2 Hz) | Downloading RaspiMIDIHub |
   | Fast blink (~5 Hz) | Installing — takes 1–3 minutes, don't unplug |
   | Solid on | Install complete, rebooting now |
   | One short flash per second (long gap) | Install failed — SSH in, run `journalctl -u raspimidihub-bootstrap` |

   After reboot the LED resumes normal appliance behavior (steady, flickers on
   MIDI activity).

6. Connect to `RaspiMIDIHub-XXXX` WiFi (password `midihub1`).

**Internet is required on first boot.** Either plug in ethernet, USB-tether a
phone, or pre-configure WiFi credentials in the Pi Imager wizard.

## Testing

There's no shortcut: the only honest test of the first-boot path is flashing
to a real SD card and booting a real Pi. The build itself doesn't need
hardware.
