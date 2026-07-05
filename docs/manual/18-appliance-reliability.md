# Appliance Reliability

RaspiMIDIHub is designed to be treated like a guitar pedal: yank
the power, plug it back in next week, get the same state.

## Read-Only Filesystem

The SD-card root is mounted read-only during normal operation (the
`raspimidihub-rosetup` package adds the mount layer and the
`rw` / `ro` helper commands), so a power-cut cannot corrupt the
filesystem. Writable paths live on tmpfs (RAM):

- `/var/lib/raspimidihub/` -- runtime project state.
- `/var/lib/bluetooth/` -- BlueZ pairing state (chapter 14.3).
- `/var/log/` -- service logs.
- `/run/` and `/tmp/` -- standard ephemeral paths.

The boot partition (`/boot/firmware`) is read-only in steady state
too. Writers -- Save Config, the BlueZ snapshot, a downloaded
deb -- run a millisecond remount-rw / write / `sync` / remount-ro
cycle; between operations both filesystems are ro, so a power yank
cannot hit a half-written file. Root stays read-only throughout.

For maintenance windows that need root writes:

```bash
ssh user@raspimidihub-<id>.local
rw                # remount root read-write
# … do the thing …
ro                # remount root read-only
```

## Power-Safe Operation

The persistence model assumes the power *will* be yanked:

- **Save Config** (`config.json`) is written atomic-replace (temp
  file, fsync, rename) inside a brief remount-rw window on the
  boot partition.
- The live edited state is autosaved in the background; a hard cut
  resumes the last edit, not just the last manual Save (below).
- BlueZ bonds are snapshotted to the boot partition on every
  change and restored on boot before the routing service starts.

## Autosave and Resume

Boot resumes the newest valid autosave, falling back to
`config.json`, then its `.bak`, then defaults. Three properties
make this power-cut-safe:

- **Ping-pong, never overwrite-in-place.** The autosave alternates
  between two gzip-compressed slots (`autosave-0` / `autosave-1`);
  a cut can only corrupt the slot being written, and a torn write
  fails the gzip CRC on decompress, so boot uses the other slot.
- **No clock, so no dates.** With no real-time clock, the autosave
  (and the Backup list, chapter 16) records uptime + a per-boot
  id: "n ago" is shown only within the current boot; older items
  show only a sequence number.
- **Debounced and launch-free.** Autosave fires a few seconds
  after edits settle and on clean shutdown. Launching Tracker
  patterns or tapping pattern slots changes no saveable content --
  no autosave, no Routing dirty-asterisk; only real edits
  (recording, routing changes, parameter edits) count. **Load**,
  **Restore** (chapter 16), and **Import** force an immediate
  autosave so the just-loaded state is the resume point.

Pulling the power loses at most the few seconds of editing since
the last autosave settled.

## Reserved Cores

Two cores are isolated (`isolcpus=2,3 nohz_full=2,3
rcu_nocbs=2,3`, set by the rosetup package at boot):

- **Core 3** -- only the asyncio routing/MIDI loop.
- **Core 2** -- only the plugin threads (plugins emit notes on
  their own threads and need the same consistent latency).
- **Cores 0-1** -- everything else: kernel, IRQs, WiFi AP, mDNS,
  Bluetooth, the background config-save process.

No kernel ticks and no other userland run on cores 2 and 3 --
loop-lag and note-timing spikes from other system activity are
essentially impossible.

## Auto-Start

The routing service is a systemd unit: it starts after networking
and ALSA, routes MIDI within roughly 30 seconds of power-on,
restarts on crash (`Restart=always`), and brings up the AP via
hostapd / dnsmasq. It comes up in the last saved state with no
login or web access.

## LED Status

| Green ACT LED | Red PWR LED | Meaning |
|---------------|-------------|---------|
| Steady on     | Off         | Running normally |
| Flickering    | Off         | MIDI activity |
| Fast blink    | On          | Config fallback (error) |
| Off           | Default     | Service stopped |

The green ACT LED is repurposed from its OS default (SD-card
activity) to service health; the red PWR LED keeps its hardware
default (power present).

## Failure-Mode Catalogue

### WiFi client lost mid-update

The 180-second watchdog (chapter 17.7) restarts the routing
service, bringing the AP back; the deb cache (latest 3) survives,
so the retry can install offline.

### Plugin crash

Each plugin runs in its own thread. An unhandled exception is
logged and the thread restarts; parameters are kept, in-flight
events may be lost.

### ALSA hot-plug

On plug-in, the device is matched against saved routing by USB
topology and the routing re-applied silently. On unplug, the
row/column goes offline in the matrix; saved connections stay
visible and dimmed.

### AP wedged

If the AP is unreachable but the routing service is healthy (rare,
usually hostapd hanging), `sudo reset-wifi` from a console forces
AP mode with default credentials.

### Config file corrupt

If the boot config cannot be parsed, the service falls back to a
clean state and lights the "fast blink, PWR on" LED pattern. The
corrupt file is renamed with a `.bak` suffix so its contents can
be recovered over SSH.

## Maintenance Operations

### Updating

See chapter 17: pick an internet path (ethernet, USB tethering, or
temporary WiFi-client mode), tap **Check GitHub for newer
versions**, then **Install**.

### Uninstalling

```bash
ssh user@raspimidihub-<id>.local
rw
sudo apt purge raspimidihub raspimidihub-rosetup
sudo reboot
```

After the reboot the Pi is a plain Raspberry Pi OS Lite install
again (plus whatever else was installed on top).

### Resetting WiFi

```bash
sudo reset-wifi
```

Forces AP mode with default credentials -- the console alternative
to chasing a wedged AP through the UI.

### Re-flashing the SD card

The most thorough reset: re-image the SD card with Raspberry Pi OS
Lite and run the install one-liner. Loses all saved state (routing
config, BlueZ bonds, AP password); use **Export Config**
beforehand to keep the routing state recoverable.
