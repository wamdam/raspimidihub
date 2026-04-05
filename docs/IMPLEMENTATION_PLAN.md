# RaspiMIDIHub — Implementation Plan

**Based on:** FSD v1.1  
**Date:** 2026-04-05

---

## Phase 1: Core MIDI Hub (Target: MVP in ~2 weeks)

### Step 1.1: Project Scaffolding
- Initialize git repo, `.gitignore`, `LICENSE`, `README.md`
- Create directory structure:
  ```
  raspimidihub/
  ├── src/
  │   └── raspimidihub/
  │       ├── __init__.py
  │       ├── __main__.py        # Entry point
  │       ├── midi_engine.py     # ALSA sequencer logic
  │       └── config.py          # Configuration management
  ├── debian/                    # Debian packaging
  ├── systemd/
  │   └── raspimidihub.service
  ├── udev/
  │   └── 90-raspimidihub.rules
  ├── tests/
  ├── docs/
  └── pyproject.toml
  ```
- Set up `pyproject.toml` with dependencies: `pyalsa`

### Step 1.2: MIDI Engine Core
**File:** `src/raspimidihub/midi_engine.py`

Implement:
1. `MidiEngine` class that opens an ALSA sequencer client
2. `scan_devices()` — enumerate all ALSA seq clients and their ports via `snd_seq_query_next_client/port`. Filter out client 0 (System), Midi Through, and own client. Return list of `MidiDevice(client_id, name, ports: [MidiPort(port_id, name, type)])`.
3. `connect_all()` — for each input port, connect to every output port on every *other* device. Uses `snd_seq_subscribe_port()`.
4. `disconnect_all()` — remove all subscriptions managed by this service.
5. `_is_self_connection(src_client, dst_client)` — prevent loops.
6. Event loop using `asyncio` + ALSA sequencer fd: block on `SND_SEQ_EVENT_PORT_START`, `PORT_EXIT`, `CLIENT_START`, `CLIENT_EXIT`. On event → debounce 500 ms → `disconnect_all()` + `connect_all()`.

**Test with:** `snd-virmidi` kernel module (`sudo modprobe snd-virmidi`), create 3 virtual MIDI devices, verify connection matrix.

### Step 1.3: Systemd Service + udev Rules
**Files:**
- `systemd/raspimidihub.service` — `Type=notify`, `Restart=always`, `RestartSec=2`, `WatchdogSec=30`, `User=root` (needed for ALSA seq), `ExecStart=/usr/bin/python3 -m raspimidihub`
- `udev/90-raspimidihub.rules` — match `SUBSYSTEM=="sound"`, `ACTION=="add|remove"`, `ATTR{id}!=""` → write to notification pipe or send SIGHUP as fallback trigger

### Step 1.4: Debian Packaging (`raspimidihub`)
**Directory:** `debian/`
- `control` — Package metadata, `Depends: python3 (>= 3.9), python3-pyalsa, alsa-utils, avahi-daemon`, `Recommends: raspimidihub-rosetup`
- `rules` — Standard debhelper build
- `raspimidihub.install` — file placement
- `raspimidihub.service` — systemd integration via dh_installsystemd
- `postinst` — enable and start service
- `postrm` — stop and disable service

### Step 1.5: Read-Only FS Package (`raspimidihub-rosetup`)
**Directory:** `rosetup/`
- `rosetup/debian/` — separate package source
- `rosetup/setup.sh` — main script, also callable as `raspimidihub-rosetup [--dry-run]`
- `rosetup/undo.sh` — reversal script for postrm

Script logic (idempotent, each step checks before acting):
1. Validate OS (`/etc/os-release` must contain `Raspberry Pi`)
2. Back up files to `/var/lib/raspimidihub-rosetup/backup/`
3. Append tmpfs entries to `/etc/fstab` (if not already present)
4. Append `fsck.mode=skip` to `cmdline.txt` (if not already present), backup to `.bak`
5. `systemctl mask dphys-swapfile` + `swapoff -a`
6. `systemctl disable systemd-timesyncd` + ensure `ntpsec` installed/enabled
7. Configure NTP drift file, `PrivateTmp=false` override
8. NetworkManager `rc-manager=file`, symlinks for resolv.conf/dhcp/NM state
9. Random seed → `/tmp` symlink + systemd override
10. Mask `systemd-rfkill`, `apt-daily.timer`, `apt-daily-upgrade.timer`, `man-db.timer`
11. Mask `fake-hwclock`
12. Set journald `SystemMaxUse=25M`
13. Add `rw`/`ro` aliases + prompt to `/etc/bash.bashrc`
14. Add auto-remount to `/etc/bash.bash_logout`
15. Add `ro` to root and boot mount options in `/etc/fstab`
16. Append `ro` to `cmdline.txt`

### Step 1.6: Testing on Real Hardware
- Flash Pi OS Lite on SD card
- `scp` the `.deb` files
- Install, reboot, connect 2-3 USB MIDI devices
- Verify: `aconnect -l` shows all connections
- Hot-plug test: add/remove device, verify reconnection < 2s
- Power-pull test: yank power, verify clean boot

---

## Phase 2: Web UI (Target: ~3–4 weeks after Phase 1)

### Step 2.0: WiFi Access Point + Captive Portal
**Files:** `config/hostapd.conf`, `config/dnsmasq-ap.conf`, `src/raspimidihub/wifi.py`

1. `hostapd.conf` template — WPA2, SSID=`RaspiMIDIHub-XXXX` (MAC-derived), channel auto, `wlan0`
2. `dnsmasq-ap.conf` — DHCP range `192.168.4.10-192.168.4.100`, lease 12h, DNS: resolve ALL queries to `192.168.4.1` (captive portal)
3. `wifi.py` — `WifiManager` class:
   - `start_ap()` — configure `wlan0` static IP `192.168.4.1`, start hostapd + dnsmasq
   - `start_client(ssid, password)` — stop AP, connect via NetworkManager, fallback to AP after 30s timeout
   - `get_mode()` — returns "ap" or "client"
   - `set_ap_password(new_password)` — update hostapd.conf, save to persistent config, reload
4. Captive portal handler in Quart: any HTTP request to a non-`192.168.4.1` host returns `302` redirect to `http://192.168.4.1/`. This triggers the OS captive portal popup on iOS/Android/macOS/Windows.
5. Special handling for Apple CNA (`/hotspot-detect.html`), Android (`/generate_204`), Windows (`/connecttest.txt`) captive portal detection endpoints.

### Step 2.1: Web Server Foundation
**File:** `src/raspimidihub/web.py`

1. Add Quart as dependency
2. Create async Quart app within the same process as the MIDI engine
3. Serve static files from `src/raspimidihub/static/`
4. Implement SSE endpoint (`GET /api/events`) — yields events from MIDI engine's event queue
5. Implement `GET /api/system` — hostname, IP, uptime, CPU temp, RAM, version, wifi mode
6. Add rate limiting (10 mutating req/s, 5 SSE connections)
7. Security headers middleware
8. Captive portal redirect for non-API requests from AP clients

### Step 2.2: Device & Connection API
Implement REST endpoints:
- `GET /api/devices` — calls `midi_engine.scan_devices()`, returns JSON with stable USB identifiers
- `GET /api/connections` — queries ALSA seq for active subscriptions, returns as JSON
- `POST /api/connections` — validate input (strict integer device/port IDs), call `snd_seq_subscribe_port()`
- `DELETE /api/connections/{id}` — call `snd_seq_unsubscribe_port()`
- `POST /api/connections/connect-all` — delegate to `midi_engine.connect_all()`
- `DELETE /api/connections` — delegate to `midi_engine.disconnect_all()`

### Step 2.3: Configuration Persistence
**File:** `src/raspimidihub/config.py`

1. `Config` class: load/save/validate JSON, versioning
2. Boot-time copy from `/boot/firmware/raspimidihub/config.json` → `/run/raspimidihub/config.json` (in `ExecStartPre`)
3. Save flow: write tmpfs temp → validate → remount rw → copy → sync → remount ro → backup
4. Preset CRUD: save/load/delete/export/import named presets
5. Device matching by USB path + VID:PID for persistent routing

### Step 2.4: Preset API
- `GET /api/presets` — list presets from config
- `POST /api/presets` — save current routing as named preset
- `POST /api/presets/{name}/activate` — load and apply
- `DELETE /api/presets/{name}` — delete
- `GET /api/presets/{name}/export` — download JSON
- `POST /api/presets/import` — upload and validate JSON

### Step 2.5: Frontend SPA — Mobile-First Design
**Directory:** `src/raspimidihub/static/`

No build step — use Preact + `htm` via ES modules:
```
static/
├── index.html
├── app.js              # Main Preact app, bottom-tab navigation
├── components/
│   ├── ConnectionMatrix.js  # Primary view: touch-friendly matrix grid
│   ├── RoutingDiagram.js    # Secondary: SVG wiring view (desktop)
│   ├── PresetManager.js     # Preset select/save/load
│   ├── StatusPanel.js       # System info + MIDI activity
│   ├── SettingsPanel.js     # WiFi mode, AP password, preferences
│   └── LandingPage.js      # Captive portal first-screen
├── lib/
│   ├── preact.module.js
│   └── htm.module.js
└── style.css            # Mobile-first CSS (min-width breakpoints)
```

1. **LandingPage** (captive portal first screen) — simplified overview: device count, "Connect All" / "Disconnect All" / preset dropdown. Immediately useful without scrolling. Links to full UI.
2. **ConnectionMatrix** (primary on mobile) — table grid with large (48px+) touch-friendly checkboxes at row/column intersections. Inputs as rows, outputs as columns. Swipe to scroll if many devices.
3. **RoutingDiagram** (desktop/tablet) — SVG bezier wiring view, color-coded per source device. Click input → checkboxes on outputs.
4. **StatusPanel** — system info from `GET /api/system`, MIDI activity blinking dots from SSE.
5. **PresetManager** — dropdown, save/rename/delete, export/import JSON.
6. **SettingsPanel** — WiFi mode toggle (AP/Client), AP password change, SSID change, client WiFi credentials input. System reboot button.

Navigation: bottom tab bar (Routing / Presets / Status / Settings) — swipeable on mobile.

### Step 2.6: WiFi Settings API
- `GET /api/wifi` — returns current mode (ap/client), SSID, IP
- `POST /api/wifi/ap` — switch to AP mode, body: `{ssid, password}`
- `POST /api/wifi/client` — switch to client mode, body: `{ssid, password}`
- `GET /api/wifi/scan` — scan for available networks (when in AP mode, briefly scan then return)

### Step 2.7: Update Debian Package
- Add `Depends: python3-quart, hostapd, dnsmasq` (or bundle Quart)
- Add config init to postinst (create `/boot/firmware/raspimidihub/` dir, generate AP config)
- Configure hostapd + dnsmasq in postinst
- Update systemd service `ExecStartPre` for config copy
- Disable default NetworkManager WiFi management for `wlan0` when in AP mode

---

## Phase 2.1: MIDI Filtering (Target: ~2 weeks after Phase 2)

### Step 2.1.1: Userspace MIDI Passthrough
For connections with filters, replace direct ALSA subscription with:
- Create virtual ALSA seq ports (one per filtered connection)
- Read MIDI events from source via userspace
- Apply channel/message-type filters
- Forward to destination

### Step 2.1.2: Filter Configuration
- `PATCH /api/connections/{id}` — set channel mask (bitmask of 16 channels) and message type mask
- Store in config JSON per-connection
- Filter UI component: 4x4 channel grid + message type checkboxes (designed for quick access)

### Step 2.1.3: MIDI Clock Filtering
- Priority feature: ability to block MIDI Clock/Realtime per-connection
- Resolves the "multiple clock sources" known limitation from Phase 1

---

## Build & Release

### Debian Package Build
```bash
# In raspimidihub/
dpkg-buildpackage -us -uc -b    # unsigned build for testing
# Or with signing:
dpkg-buildpackage -b

# In rosetup/
dpkg-buildpackage -us -uc -b
```

### Release Checklist
1. Tag version in git
2. Build `.deb` packages (arm64 + optionally armhf)
3. GPG-sign packages
4. Generate `SHA256SUMS.asc`
5. Upload to GitHub Releases
6. Update README with download links

### CI (GitHub Actions)
- Lint + unit tests on every push
- Build `.deb` on every tag
- Integration test with `snd-virmidi` in Docker/QEMU (stretch goal)

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| `pyalsa` not packaged for arm64 Pi OS | Blocks Phase 1 | Fallback: use `python-rtmidi` or ctypes bindings to libasound2 |
| Multi-port device enumeration edge cases | Wrong connections | Extensive testing with `snd-virmidi` multi-port configs |
| FAT32 config corruption on power loss during save | Lost config | Always keep `.bak`, minimize rw window, `sync` before remount |
| postinst bricks a non-standard Pi OS install | User locked out | Validate preconditions, backup everything, `--dry-run` support |
| MIDI feedback loops across devices | Audio chaos | Document limitation, add device exclusion in Phase 2, loop detection in Phase 2.1 |
| Quart not available in Pi OS apt | Packaging pain | Bundle via pip install to `/usr/lib/raspimidihub/` or use vendored copy |
| Captive portal not triggering on some OS versions | Users can't find web UI | Implement all known detection endpoints (Apple CNA, Android /generate_204, Windows /connecttest.txt). Fallback: print IP on landing page / README |
| Pi Zero 2 W WiFi chip limitations for AP mode | AP may be flaky | Test on all target Pi models. Pi Zero 2 W uses same BCM43436 as Pi 3B — AP mode well supported |
| hostapd conflicts with NetworkManager | WiFi doesn't start | Use `nmcli device set wlan0 managed no` in AP mode, restore in client mode |

---

## Milestone Summary

| Milestone | Deliverable | Dependencies |
|-----------|-------------|-------------|
| **M1** | MIDI engine with all-to-all routing + hotplug | pyalsa, ALSA headers |
| **M2** | Systemd service, working on real Pi | M1 |
| **M3** | `raspimidihub.deb` package | M2 |
| **M4** | `raspimidihub-rosetup.deb` package | None (independent) |
| **M5** | Phase 1 complete: install .deb → reboot → MIDI hub working | M3 + M4 |
| **M6** | WiFi AP + captive portal working on Pi | None (can parallel with M5) |
| **M7** | Web server + REST API + SSE | M2 |
| **M8** | Mobile-first frontend SPA with matrix routing | M7 |
| **M9** | Config persistence + presets | M7 |
| **M10** | WiFi settings UI (AP/client mode switch) | M6 + M8 |
| **M11** | Phase 2 complete: AP → phone connects → captive portal → MIDI routing UI | M6–M10 |
| **M12** | MIDI channel/message filtering | M11 |
