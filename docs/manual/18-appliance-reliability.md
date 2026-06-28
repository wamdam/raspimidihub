# Appliance Reliability

RaspiMIDIHub is designed to be treated like a guitar pedal: yank the
power, throw it in a bag, plug it back in next week, get the same
state. This chapter documents the mechanisms that make that
behaviour safe and the failure modes the appliance plans for.

## Read-Only Filesystem

The SD card root is mounted read-only during normal operation.
The `raspimidihub-rosetup` Debian package adds the read-only mount
layer and the `rw` / `ro` helper commands. The result: the SD
card is never written during a typical session, so an unexpected
power-cut cannot corrupt the filesystem.

A handful of paths *are* writable, on tmpfs (RAM) instead of SD:

- `/var/lib/raspimidihub/` -- runtime project state.
- `/var/lib/bluetooth/` -- BlueZ pairing state (chapter 14.3).
- `/var/log/` -- service logs.
- `/run/` and `/tmp/` -- standard ephemeral paths.

The boot partition (`/boot/firmware`) is also mounted **read-only**
in steady state. Anything that needs to land there -- Save Config,
the BlueZ snapshot (chapter 14.3), a downloaded update deb -- runs
the rw / write / sync / ro cycle itself: `mount -o remount,rw
/boot/firmware`, write the file, `sync`, `mount -o remount,ro
/boot/firmware`. The window is milliseconds and self-contained;
between operations both filesystems are ro and a power yank can't
hit a half-written file. The main root remains read-only throughout
-- the remount cycle is on the boot partition only.

For maintenance windows that need filesystem writes (manual
package installs, custom tweaks):

```bash
ssh user@raspimidihub-<id>.local
rw                # remount root read-write
# … do the thing …
ro                # remount root read-only
```

The `rw` / `ro` commands are part of the `raspimidihub-rosetup`
package.

## Power-Safe Operation

The persistence model assumes the user *will* yank the power. The
service explicitly:

- Keeps the deliberate **Save Config** checkpoint
  (`config.json`) as the committed state, written with
  atomic-replace (write to temp file, fsync, rename) inside a
  brief remount-rw / remount-ro window on the boot partition.
- **Autosaves the live edited state in the background** so a hard
  power cut resumes the last thing you were doing, not just the
  last manual Save (see *Autosave and Resume* below).
- Snapshots BlueZ bonds to the boot partition on every change,
  not periodically (using the same rw / write / ro cycle as
  Save Config).
- Restores BlueZ bonds from the snapshot on every boot before the
  routing service comes up.

## Autosave and Resume

Because the appliance is switched off at the wall with no clean
shutdown, it keeps a rolling **autosave** of the live edited state
in addition to the manual **Save Config** checkpoint. On the next
boot the unit resumes the newest valid autosave, falling back to
`config.json` (then its `.bak`, then defaults) if no autosave is
usable.

Three properties make this power-cut-safe and unobtrusive:

- **Ping-pong, never overwrite-in-place.** The autosave alternates
  between two slots (`autosave-0` / `autosave-1`). A cut can only
  corrupt the slot being written; the other still holds the
  previous good snapshot. Each slot is gzip-compressed, and gzip's
  built-in CRC *is* the validity check — a torn write fails to
  decompress, so boot simply uses the other slot.
- **No clock, so no dates.** The appliance has no real-time clock,
  so the autosave (and the Backup list, chapter 16) never stores a
  wall-clock time. It records uptime + a per-boot id and shows a
  relative "n ago" that is only honest within the current boot;
  anything from before the last reboot shows only its sequence
  number.
- **Debounced and launch-free.** The autosave fires a few seconds
  after edits settle (and on a clean shutdown / reboot), not on
  every keystroke. Purely *performing* — launching Tracker
  patterns, tapping pattern slots — moves the live playhead but
  changes no saveable content, so it triggers **no** autosave and
  leaves the Routing dirty-asterisk clear. Only real edits
  (recording, routing changes, parameter edits) do. After a
  **Load**, a **Restore** (chapter 16), or an **Import**, an
  autosave is forced immediately so the just-loaded state is the
  resume point.

Pulling the power loses at most the few seconds of editing since
the last autosave settled. The boot config, the rolling backups,
and the BlueZ bonds are all intact.

## Reserved Cores

Two cores are isolated so the two latency-critical workloads each get a
quiet, contention-free core:

- **Core 3** runs only the asyncio routing/MIDI loop.
- **Core 2** runs only the plugin threads. Plugins emit their notes
  immediately on their own thread, so they need the same low, consistent
  scheduling latency as the loop.
- **Cores 0-1** run everything else — kernel, IRQs, the WiFi AP, mDNS,
  Bluetooth and the background config-save process.

The isolation is done at boot via the Linux kernel `isolcpus=2,3`
(plus `nohz_full=2,3 rcu_nocbs=2,3`), set by the rosetup package.
Effects:

- No kernel timer ticks scheduled on cores 2 and 3.
- No other userland processes scheduled on cores 2 and 3.
- The routing loop has core 3 to itself and the plugins have core 2 to
  themselves, which makes loop-lag and note-timing spikes from other
  system activity essentially impossible.

The trade-off is two general-purpose cores for the rest of the system,
which is comfortable on a quad-core Pi for this single-purpose
appliance.

## Auto-Start

The routing service is a systemd unit that:

- Starts on boot, after networking and ALSA.
- Runs MIDI routing within roughly 30 seconds of power-on.
- Restarts automatically on crash (`Restart=always`).
- Brings up the AP via hostapd / dnsmasq alongside the routing
  service.

No login or web access is required for the appliance to come up
in its last saved state.

## LED Status

| Green ACT LED | Red PWR LED | Meaning |
|---------------|-------------|---------|
| Steady on     | Off         | Running normally |
| Flickering    | Off         | MIDI activity |
| Fast blink    | On          | Config fallback (error) |
| Off           | Default     | Service stopped |

The green ACT LED is repurposed from its default Raspberry Pi OS
behaviour (SD card activity) to indicate service health. The red
PWR LED retains its hardware default (power present).

## Failure-Mode Catalogue

A short tour of what the appliance does when things go wrong.

### WiFi client lost mid-update

The 180-second service watchdog (chapter 17.7) forces the routing
service to restart, which brings the AP back. The user
reconnects to the AP and retries. The deb cache (latest 3) is
preserved, so the retry can install offline.

### Plugin crash

Each plugin runs in its own thread inside the routing service.
A plugin that raises an unhandled exception is logged and the
plugin's thread restarts. The plugin's parameters are kept; in-
flight events for that plugin may be lost.

### ALSA hot-plug

USB MIDI devices that come and go fire ALSA hotplug events. The
service catches them and:

- On plug-in: matches the device against saved routing by USB
  topology; if a match is found, the routing is re-applied
  silently.
- On unplug: marks the device's row/column as offline in the
  matrix; saved connections stay visible and dimmed.

### AP wedged

If the AP becomes unreachable but the routing service is healthy
(rare, usually caused by hostapd hanging), `sudo reset-wifi` from
a console forces AP mode with default credentials.

### Config file corrupt

If the routing service cannot parse the boot config on startup,
it falls back to a clean state and lights the LED in the "fast
blink, PWR on" pattern. The corrupt file is renamed with a
`.bak` suffix so the user can recover its contents over SSH.

## Maintenance Operations

### Updating

See chapter 17. The TL;DR: pick an internet path (ethernet, USB
tethering, or temporary WiFi-client mode), tap **Check GitHub for
newer versions**, then **Install**.

### Uninstalling

```bash
ssh user@raspimidihub-<id>.local
rw
sudo apt purge raspimidihub raspimidihub-rosetup
sudo reboot
```

After the reboot, the Pi is back to a plain Raspberry Pi OS Lite
install (subject to whatever else has been installed on top).

### Resetting WiFi

```bash
sudo reset-wifi
```

Forces AP mode with default credentials. The console alternative
to chasing a wedged AP through the UI.

### Re-flashing the SD card

The most thorough reset: re-image the SD card with Raspberry Pi
OS Lite and run the install one-liner. Loses all saved state
(routing config, BlueZ bonds, AP password). Useful when the SD
card itself is suspect. Use **Export Config** beforehand to keep
the routing state recoverable.

