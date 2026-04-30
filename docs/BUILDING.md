# Building from Source

RaspiMIDIHub is packaged as two `.deb` files built with `dpkg-deb` and `fakeroot`. No Debian packaging toolchain (debhelper, pbuilder, etc.) is required.

## Prerequisites

Install build tools on your development machine (Debian/Ubuntu):

```bash
sudo apt install fakeroot dpkg-dev make
```

No cross-compilation needed — the packages are `Architecture: all` (pure Python + static web assets).

## Building

```bash
# Clone the repository
git clone git@github.com:wamdam/raspimidihub.git
cd raspimidihub

# Build both .deb packages
make all

# Or build individually:
make deb           # builds dist/raspimidihub_<VERSION>-1_all.deb
make deb-rosetup   # builds dist/raspimidihub-rosetup_<ROSETUP_VERSION>-1_all.deb
```

Output files land in `dist/`.

## What the packages contain

### raspimidihub

| Path | Contents |
|------|----------|
| `/usr/lib/python3/dist-packages/raspimidihub/` | Python source + static web assets |
| `/lib/systemd/system/raspimidihub.service` | Systemd service unit |
| `/lib/udev/rules.d/90-raspimidihub.rules` | Udev rules for MIDI device events |
| `/usr/local/bin/raspimidihub-system-prepare` | Trim services + reserve CPU 3 (see below) |
| `/usr/local/bin/raspimidihub-system-revert` | Undo the prepare changes |
| `/usr/local/bin/reset-wifi` | Wipe stored WiFi credentials |
| `/DEBIAN/postinst` | Sets hostname, unmasks hostapd, enables service, runs `system-prepare` |
| `/DEBIAN/postrm` | Disables and removes service on purge |

**Dependencies:** `python3 (>= 3.9)`, `libasound2t64 | libasound2`, `alsa-utils`, `avahi-daemon`, `hostapd`, `dnsmasq`

#### System prepare: service trim + CPU isolation

`raspimidihub-system-prepare` runs from postinst on every install / upgrade
(idempotent). It encodes the assumption "this Pi only does MIDI" — anything
else uses the **rosetup** package instead, which is generic.

**Pass 1 — disable services + timers:** `bluealsa`, `bluealsa-aplay`,
`bluetooth`, `ModemManager`, `cloud-init` (×4 units), `udisks2`, `cron`,
`sshswitch`, `e2scrub_reap`, plus the `e2scrub_all`, `fstrim`,
`dpkg-db-backup`, `logrotate`, `rpi-zram-writeback` timers. Each is silently
skipped if the unit isn't installed on the running Pi-OS variant.

**Pass 2a — kernel cmdline:** appends `isolcpus=3 nohz_full=3 rcu_nocbs=3`
to `/boot/firmware/cmdline.txt` (auto-remounts `/boot/firmware` rw, edits,
restores ro). Removes CPU 3 from the general scheduler, suppresses its
periodic timer tick, offloads RCU callbacks. Takes effect on **next reboot**.

**Pass 2b — systemd drop-in:** writes `/etc/systemd/system/raspimidihub.service.d/cpu-affinity.conf`
with `AllowedCPUs=3` and `Nice=-5`. Pins the asyncio Python process to the
isolated core. Takes effect on **next service restart** (postinst already
restarts the service).

**Goal:** the asyncio main loop sits on a quiet core that no kernel timer,
no RCU callback, and no other userland process can preempt — latency spikes
from external influence stop being possible by construction. Cost: a Pi 4
loses ~1 / 4 of its compute budget; the asyncio loop never used more than
one core anyway, so this is a free win for MIDI latency.

**Backups:** every system file edited is copied to
`/var/lib/raspimidihub-prepare/backup/` first.

**Revert:** `sudo raspimidihub-system-revert` re-enables the services and
strips the kernel cmdline params and the drop-in. Reboot to release CPU 3
back to the general scheduler.

### raspimidihub-rosetup

| Path | Contents |
|------|----------|
| `/usr/sbin/raspimidihub-rosetup` | Setup script (makes filesystem read-only) |
| `/usr/sbin/raspimidihub-rosetup-undo` | Undo script (restores read-write) |
| `/DEBIAN/postinst` | Runs setup on install |
| `/DEBIAN/prerm` | Runs undo on removal |

**Dependencies:** `bash`. **Recommends:** `ntpsec`

## Deploying to a Pi for development

The Makefile includes shortcuts for iterating on a Pi connected at `10.1.1.2`:

```bash
# Deploy source files only (fast, no .deb rebuild)
make deploy-src

# Then on the Pi, restart the service:
make restart

# Or deploy + install the .deb:
make deploy

# View logs:
make logs

# Check service status:
make status
```

To change the Pi address, override `PI_HOST`:

```bash
make deploy-src PI_HOST=user@192.168.4.1
```

## Versioning

Version numbers are defined in two places:

1. `Makefile` — `VERSION = 1.3.0` (used for .deb filename and control file)
2. `src/raspimidihub/__init__.py` — `__version__ = "1.3.0"` (reported in web UI)

When releasing a new version:

1. Update both version numbers
2. Rename the `Unreleased` section in `CHANGELOG.txt` to the new
   version + date. New entries are written there continuously
   during development, so a release just stamps the date.
3. Build: `make clean all`
4. Test on a Pi
5. Tag: `git tag -a v1.x.x -m "v1.x.x — description"`
6. Push: `git push --tags`
7. Create GitHub release: `gh release create v1.x.x dist/*.deb --title "v1.x.x" --notes "..."`

## Project structure

```
raspimidihub/
├── src/raspimidihub/        # Python source
│   ├── __init__.py          # Version
│   ├── __main__.py          # Entry point
│   ├── alsa_seq.py          # ALSA sequencer ctypes bindings
│   ├── api.py               # REST API routes
│   ├── config.py            # Configuration persistence
│   ├── device_id.py         # Stable USB device identification
│   ├── led.py               # Pi LED control
│   ├── midi_engine.py       # MIDI routing engine
│   ├── midi_filter.py       # Filtering + mapping engine
│   ├── web.py               # Async HTTP server (stdlib only)
│   ├── wifi.py              # WiFi AP/client management
│   └── static/              # Web UI (Preact SPA, no build step)
│       ├── index.html
│       ├── app.js
│       ├── style.css
│       └── lib/             # Preact + htm (bundled, ES modules)
├── debian/                  # Debian packaging scripts
├── rosetup/                 # Read-only filesystem package
├── systemd/                 # Service unit
├── udev/                    # Udev rules
├── docs/                    # Documentation + screenshots
├── Makefile                 # Build, deploy, dev shortcuts
└── LICENSE
```
