# RaspiMIDIHub — Implementation Notes

**Status:** All phases complete (v1.3.3)

---

## Project Structure

```
raspimidihub/
+-- src/raspimidihub/
|   +-- __init__.py          # Version
|   +-- __main__.py          # Entry point, SSE event wiring, startup
|   +-- midi_engine.py       # ALSA sequencer: connections, hotplug, monitor
|   +-- midi_filter.py       # Userspace MIDI filtering and mapping engine
|   +-- device_id.py         # Stable USB device identification (topology + VID:PID)
|   +-- config.py            # Config persistence (boot partition, tmpfs copy)
|   +-- web.py               # Async HTTP server (stdlib asyncio, SSE)
|   +-- api.py               # REST API routes
|   +-- wifi.py              # WiFi AP/client mode, network interface config
|   +-- led.py               # LED status control
|   +-- alsa_seq.py          # ctypes bindings to libasound2
|   +-- static/
|       +-- index.html        # SPA entry point
|       +-- app.js            # Preact + htm frontend (single file, no build step)
|       +-- style.css         # Mobile-first CSS
|       +-- lib/              # Preact + htm modules
+-- debian/                   # Package control files
+-- systemd/                  # Service unit
+-- udev/                     # Hotplug rules
+-- scripts/                  # update.sh, reset-wifi.sh, install.sh
+-- Makefile                  # Build, deploy, release
+-- docs/
```

## Key Design Decisions

- **No framework dependencies:** Web server uses Python stdlib `asyncio` (not Flask/Quart). Frontend uses Preact + htm via ES modules (no npm, no build step).
- **ctypes ALSA bindings:** Direct ctypes calls to `libasound2` instead of `pyalsa` or `python-rtmidi`. Eliminates a package dependency.
- **Single process:** MIDI engine + web server + SSE in one asyncio event loop. One systemd unit, one process.
- **Dual routing paths:** Direct ALSA kernel subscriptions for unfiltered connections (zero latency). Userspace passthrough via filter engine for filtered/mapped connections (~1-3ms).
- **Stable device IDs:** `usb-{bus}-{port_path}-{vid}:{pid}` derived from sysfs USB topology. Survives reboots unlike ALSA client numbers.
- **Read-only filesystem:** Config saved to `/boot/firmware` (FAT32) via rw/ro remount cycle. Runtime copy on tmpfs.

## Build & Deploy

```bash
make deb              # Build .deb package
make deploy           # Build + scp + install on Pi (10.1.1.2)
make clean            # Remove build artifacts
```

## Release Checklist

1. Bump version in `src/raspimidihub/__init__.py` and `Makefile`
2. `git commit && git push`
3. `git tag vX.Y.Z && git push origin vX.Y.Z`
4. `make clean && make deb`
5. `gh release create vX.Y.Z dist/*.deb scripts/install.sh --title "vX.Y.Z" --notes "..."`

**Important:** Always include `scripts/install.sh` in every release — the one-line installer downloads it from the latest release.
