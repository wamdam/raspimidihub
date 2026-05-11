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

The boot partition (`/boot/firmware`) is writable on a different
mount and is used for the BlueZ snapshot path (chapter 14.3).
The main root remains read-only.

For maintenance windows that need filesystem writes (manual
package installs, custom tweaks):

```bash
ssh user@raspimidihub.local
rw                # remount root read-write
# … do the thing …
ro                # remount root read-only
```

The `rw` / `ro` commands are part of the `raspimidihub-rosetup`
package.

## Power-Safe Operation

The persistence model assumes the user *will* yank the power. The
service explicitly:

- Writes the project state only when **Save Config** is tapped --
  no autosave that could be interrupted mid-write.
- Uses atomic-replace on every config write (write to temp file,
  fsync, rename).
- Snapshots BlueZ bonds to the writable boot partition on every
  change, not periodically.
- Restores BlueZ bonds from the snapshot on every boot before the
  routing service comes up.

Pulling the power between **Save Config** taps loses the unsaved
state and *only* the unsaved state. The boot config and the
BlueZ bonds are intact.

## CPU 3 Reservation

The asyncio main loop runs pinned to CPU 3, an isolated core. The
isolation is done at boot via the Linux kernel `isolcpus=3`
parameter (set by the rosetup package). Effects:

- No kernel timer ticks scheduled on CPU 3.
- No other userland processes scheduled on CPU 3.
- The routing service has CPU 3 to itself, which makes loop-lag
  spikes from other system activity essentially impossible.

The trade-off is one less general-purpose core for the rest of
the system, which is not a problem on Pi 4 / 5 (the remaining
three cores are sufficient) and is a tighter constraint on Pi
Zero 2 W (only four cores total).

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
ssh user@raspimidihub.local
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

