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
make deb           # builds dist/raspimidihub_1.3.0-1_all.deb
make deb-rosetup   # builds dist/raspimidihub-rosetup_1.0.0-1_all.deb
```

Output files land in `dist/`.

## What the packages contain

### raspimidihub

| Path | Contents |
|------|----------|
| `/usr/lib/python3/dist-packages/raspimidihub/` | Python source + static web assets |
| `/lib/systemd/system/raspimidihub.service` | Systemd service unit |
| `/lib/udev/rules.d/90-raspimidihub.rules` | Udev rules for MIDI device events |
| `/DEBIAN/postinst` | Sets hostname, unmasks hostapd, enables service |
| `/DEBIAN/postrm` | Disables and removes service on purge |

**Dependencies:** `python3 (>= 3.9)`, `libasound2t64 | libasound2`, `alsa-utils`, `avahi-daemon`, `hostapd`, `dnsmasq`

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
