# RaspiMIDIHub — Functional Specification Document

**Version:** 1.2  
**Date:** 2026-04-05  
**Status:** Reviewed by Expert Group + User Feedback incorporated

---

## 1. Overview

RaspiMIDIHub turns a Raspberry Pi into a dedicated, appliance-like USB MIDI hub. When powered on, it automatically routes MIDI data between all connected USB MIDI devices. The system runs on a read-only root filesystem to maximize SD card longevity and ensure reliability in live/studio environments where sudden power loss is expected.

### 1.1 Goals

- **Zero-configuration MIDI routing:** Plug in USB MIDI devices, power on, all devices talk to each other.
- **Appliance reliability:** Read-only filesystem, no SD card wear, survives power cuts.
- **Easy installation:** `.deb` packages transform a stock Raspberry Pi OS into a MIDI hub.
- **Phase 2 — Web UI:** Optional browser-based interface for custom MIDI routing, filtering, and mapping.

### 1.2 Non-Goals

- Not a DAW or audio interface.
- Not a general-purpose MIDI processor (no scripting/plugin system).
- Not a wireless MIDI bridge (USB only in Phase 1).

---

## 2. Target Hardware

| Component | Requirement |
|-----------|------------|
| Board | Raspberry Pi 3B/3B+/4B/5/Zero 2 W |
| OS | Raspberry Pi OS Lite (Bookworm or later, arm64 preferred) |
| Storage | microSD card (any size ≥ 4 GB) |
| USB | 1–4 USB MIDI devices via USB-A ports (or USB hub). Pi 4/5 recommended for 5+ devices. |
| Network | WiFi or Ethernet (Phase 2 only, for web UI) |

**Note:** Performance with more than 4 devices on Pi Zero 2 W (single USB 2.0 bus) is untested. Pi 4/5 with dedicated USB 3.0 bus is recommended for high device counts.

---

## 3. Phase 1 — Auto-Connect MIDI Hub

### 3.1 Functional Requirements

#### FR-1: Automatic MIDI Routing

- **FR-1.1:** On boot, a background service shall discover all connected USB MIDI devices via the ALSA sequencer library API (`libasound2` / `pyalsa`). The service MUST NOT shell out to `aconnect` or any CLI tool.
- **FR-1.2:** Every MIDI input port shall be connected to every MIDI output port of every *other* device.
- **FR-1.3:** Self-connections (same device input → same device output) shall be excluded to prevent MIDI feedback loops.
- **FR-1.4:** The ALSA "System" client (client 0) and "Midi Through" virtual port shall be excluded from routing.
- **FR-1.5:** When a USB MIDI device is hot-plugged or unplugged, the service shall detect the change and re-establish all connections within 2 seconds. Detection uses ALSA sequencer announce events (`SND_SEQ_EVENT_PORT_START/EXIT`, `SND_SEQ_EVENT_CLIENT_START/EXIT`) as primary mechanism, with udev rules as secondary fallback.
- **FR-1.6:** The routing engine shall discover and connect ALL MIDI ports on multi-port devices, not only port 0. Port enumeration uses `snd_seq_query_next_port()`.
- **FR-1.7:** A 500 ms debounce window after any hotplug event before re-scanning, to allow multi-port devices to finish enumeration.
- **FR-1.8:** On any trigger (hotplug, restart), the service shall clean up orphaned/stale connections before establishing new ones.

**Known Limitation (Phase 1):** All-to-all routing also routes MIDI Clock and Realtime messages. If multiple devices send MIDI Clock, all devices receive all clocks, causing tempo confusion. Users must disable soft-thru/local-echo on their devices to prevent cross-device feedback loops. Clock filtering is planned for Phase 2.1.

#### FR-2: Read-Only Root Filesystem

Delivered as a separate package (`raspimidihub-rosetup`) that can be installed independently:

- **FR-2.1:** Root filesystem (`/`) and boot partition (`/boot/firmware`) mounted as `ro`.
- **FR-2.2:** `/tmp`, `/var/tmp`, `/var/log`, `/var/spool/mail`, `/var/spool/rsyslog`, `/var/lib/logrotate`, `/var/lib/sudo` mounted as `tmpfs`.
- **FR-2.3:** `fsck.mode=skip` appended to kernel command line. Swap disabled via `systemctl mask dphys-swapfile` and `swapoff -a` (not the invalid `noswap` kernel parameter).
- **FR-2.4:** Time synchronization via `ntpsec` with drift file on tmpfs (`/var/tmp/ntp.drift`). `PrivateTmp=false` override for NTP service.
- **FR-2.5:** NetworkManager configured with `rc-manager=file`; `resolv.conf`, DHCP state, and NM state symlinked to `/var/run`.
- **FR-2.6:** Random seed symlinked to `/tmp` with pre-creation service override.
- **FR-2.7:** Unnecessary services disabled/masked: `systemd-rfkill`, `apt-daily.timer`, `apt-daily-upgrade.timer`, `man-db.timer`, `systemd-timesyncd`.
- **FR-2.8:** `fake-hwclock` masked entirely (NTP handles time sync). Eliminates periodic rw remount.
- **FR-2.9:** Shell aliases `rw` / `ro` added to `/etc/bash.bashrc` for maintenance access, with prompt indicator showing current mount mode `(ro)` / `(rw)`.
- **FR-2.10:** Auto-remount to `ro` on shell logout via `/etc/bash.bash_logout`.
- **FR-2.11:** journald limited to `SystemMaxUse=25M` to prevent tmpfs exhaustion.

#### FR-3: Installation & Packaging

Two Debian packages:

- **`raspimidihub-rosetup`** — Generic read-only filesystem hardening (FR-2.*). Useful standalone.
- **`raspimidihub`** — MIDI routing service + web UI + WiFi AP. `Depends: alsa-utils, python3-pyalsa, avahi-daemon, hostapd, dnsmasq`. `Recommends: raspimidihub-rosetup`.

Requirements:

- **FR-3.1:** Installable via `sudo apt install ./raspimidihub*.deb` or `sudo dpkg -i ... && sudo apt-get -f install`.
- **FR-3.2:** The `raspimidihub` package includes: systemd service, udev rules, Python MIDI routing daemon, all configuration files.
- **FR-3.3:** A reboot after installation completes the setup.
- **FR-3.4:** `dpkg --purge` fully reverses all changes. The postinst backs up every modified file to `/var/lib/raspimidihub-rosetup/backup/` before modification; postrm restores from backups.
- **FR-3.5:** The postinst script is idempotent — running it twice produces the same result. It checks before modifying (no duplicate fstab entries, no double-appends to cmdline.txt).
- **FR-3.6:** The postinst validates preconditions: checks `/etc/os-release` for Raspberry Pi OS, verifies expected files exist, aborts with clear error if preconditions fail.
- **FR-3.7:** `raspimidihub-rosetup --dry-run` prints what would be changed without modifying anything.
- **FR-3.8:** `cmdline.txt` is backed up to `cmdline.txt.bak` before any modification.
- **FR-3.9:** Package built for `arm64` (primary) with `armhf` variant for 32-bit Pi OS. If core is pure Python, architecture can be `all`.
- **FR-3.10:** `.deb` packages GPG-signed. SHA256 checksums published in a signed `SHA256SUMS.asc` alongside each release.

#### FR-4: Service Reliability

- **FR-4.1:** Systemd service uses `Restart=always`, `RestartSec=2`, `WatchdogSec=30`.
- **FR-4.2:** On restart, the service performs full state reconstruction (re-scan all devices, re-establish all connections). No persistent runtime state required.
- **FR-4.3:** Optional hardware watchdog (`/dev/watchdog`) support for full system reboot on hang.

#### FR-4A: LED Status Indication

On Pi models with an activity LED (`/sys/class/leds/ACT/`):

- **FR-4A.1:** Green steady = service running, custom config loaded successfully.
- **FR-4A.2:** **Red/fast blink = config could not be read, fallen back to all-to-all default routing.** This signals to the user that the saved configuration was corrupted or unreadable and the device is operating in safe fallback mode.
- **FR-4A.3:** After the user saves a valid configuration for the first time (via web UI), the LED returns to green/steady.
- **FR-4A.4:** Fast green blink = device hotplug detected, re-establishing connections.
- **FR-4A.5:** Off = service not running.

### 3.2 Non-Functional Requirements

- **NFR-1:** MIDI latency added by routing shall be < 1 ms (ALSA kernel-level connections add negligible latency).
- **NFR-2:** The service shall consume < 10 MB RAM.
- **NFR-3:** Boot to fully operational MIDI routing in < 30 seconds.
- **NFR-4:** SD card writes during normal operation: zero.

---

## 4. Phase 2 — Web-Based MIDI Router UI

### 4.1 Overview

A lightweight web application served from the Raspberry Pi that provides visual MIDI routing control The interface allows users to override the default "everything-to-everything" routing with custom configurations.

### 4.2 Functional Requirements

#### FR-5: Web Server

- **FR-5.1:** A single Python process (asyncio + Quart) serves both the MIDI routing engine and the web UI. One systemd unit, one process. The web module is disabled by default in Phase 1, enabled by configuration for Phase 2.
- **FR-5.2:** The server shall be accessible via `http://raspimidihub.local` (mDNS/Avahi) on port 80 (configurable).
- **FR-5.3:** The server shall expose a REST API for all MIDI routing operations. All mutating endpoints require `Content-Type: application/json`.
- **FR-5.4:** The web UI shall be a single-page application (SPA) with no external CDN dependencies — all assets bundled. Built with Preact (~3 KB gzipped).
- **FR-5.5:** Real-time updates via Server-Sent Events (SSE), not WebSocket. Events: `device-connected`, `device-disconnected`, `midi-activity`, `connection-changed`.

#### FR-6: MIDI Device Discovery UI

- **FR-6.1:** The UI shall display all connected USB MIDI devices with their names and port counts.
- **FR-6.2:** Devices listed with inputs on the left, outputs on the right (wiring diagram layout).
- **FR-6.3:** Device list updates in real-time via SSE.
- **FR-6.4:** Devices identified by stable USB topology path + VID:PID (not ALSA client number, which changes on reconnection).

#### FR-7: Visual Routing Interface

- **FR-7.1:** Users can click an input port to select it (highlighted in accent color).
- **FR-7.2:** When an input is selected, checkboxes appear on output ports to enable/disable connections.
- **FR-7.3:** Active connections drawn as SVG bezier curves between input and output ports. Color-coded per source device for disambiguation.
- **FR-7.4:** A "Connect All" button restores default everything-to-everything routing.
- **FR-7.5:** A "Disconnect All" button removes all connections.
- **FR-7.6:** Connections take effect immediately (< 100 ms).
- **FR-7.7:** For 6+ devices, an alternative **connection matrix view** (rows = inputs, columns = outputs, checkboxes at intersections) is available via a toggle. The wiring diagram view is default for ≤ 5 devices.

#### FR-8: MIDI Channel Filtering (Phase 2.1)

- **FR-8.1:** Per-connection MIDI channel filter: select which of the 16 MIDI channels pass through.
- **FR-8.2:** Per-connection MIDI message type filter: Note On/Off, CC, Program Change, Pitch Bend, Aftertouch, SysEx, Clock/Realtime.
- **FR-8.3:** Filter UI accessible by clicking a connection line or via a detail panel.

**Note:** Channel filtering requires userspace MIDI passthrough (read from one ALSA port, filter, write to another) instead of direct kernel-level ALSA subscriptions. This adds measurable but small latency (~1-3 ms).

#### FR-9: Configuration Persistence

- **FR-9.1:** Config stored at `/boot/firmware/raspimidihub/config.json` (FAT32 boot partition).
- **FR-9.2:** At boot, config copied to `/run/raspimidihub/config.json` (tmpfs). Service operates from tmpfs copy.
- **FR-9.3:** On explicit user save: write to tmpfs temp file, validate JSON, remount `/boot/firmware` rw, copy, `sync`, remount ro. Keep `config.json.bak` as fallback.
- **FR-9.4:** If `config.json` fails to parse on boot, fall back to `config.json.bak`, then fall back to default all-to-all routing. **On fallback, the LED turns red/fast-blink (FR-4A.2) and the web UI shows a warning banner** indicating the config was unreadable and defaults are active. After the user saves a new valid config, the LED and UI return to normal.
- **FR-9.5:** Config references devices by stable USB path + VID:PID. Routes for disconnected devices stored as "pending" and applied when device appears.
- **FR-9.6:** Config JSON includes `"version": 1` field. Service runs migration functions on version mismatch.
- **FR-9.7:** Users can save/load named presets via the UI. Maximum 100 presets, 64 KB per preset.
- **FR-9.8:** Export/import presets as JSON files (download/upload via browser).

#### FR-10: System Status Panel

- **FR-10.1:** Display system info: hostname, IP address, uptime, CPU temperature, RAM usage, software version.
- **FR-10.2:** MIDI activity indicators: per-port blinking dot showing real-time traffic (throttled to 10 updates/sec via SSE).
- **FR-10.3:** Connected device list with USB port location.

#### FR-11: WiFi Access Point with Captive Portal

By default, the Pi creates its own WiFi network so users can configure MIDI routing from any phone/tablet without any network setup.

- **FR-11.1:** On boot, the Pi starts a WiFi access point (AP mode) using `hostapd` + `dnsmasq`. Default SSID: `RaspiMIDIHub-XXXX` (last 4 hex digits of MAC for uniqueness). Default WPA2 password: `midihub1` (printed on a sticker / shown in docs).
- **FR-11.2:** **Captive portal:** All DNS queries from AP clients are resolved to the Pi's IP (`192.168.4.1`). When a phone/laptop connects to the AP, the OS auto-opens a captive portal browser (like hotel WiFi) which lands directly on the RaspiMIDIHub configuration page. Implemented via `dnsmasq` DNS hijacking + an HTTP redirect from any requested host to `http://192.168.4.1/`.
- **FR-11.3:** The AP password can be changed via the web UI (Settings page). The new password is saved to the persistent config and applied on next reboot (or immediately via `hostapd` reload).
- **FR-11.4:** **Optional client mode:** Via the web UI Settings page, the user can switch from AP mode to client mode — connecting the Pi to an existing WiFi network (enter SSID + password). This is for users who want the Pi on their studio/venue network for access from any device on that network. The web UI remains accessible via `http://raspimidihub.local` (mDNS).
- **FR-11.5:** A toggle in Settings allows switching back to AP mode at any time.
- **FR-11.6:** If client mode WiFi connection fails (wrong password, network not found), the Pi automatically falls back to AP mode after 30 seconds so the user is never locked out of the web UI.
- **FR-11.7:** The captive portal only intercepts DNS for devices connected to the Pi's own AP. In client mode (connected to external WiFi), the Pi behaves as a normal network device with no DNS hijacking.

#### FR-12: Mobile-First Web UI

The web UI is designed **mobile-first** — the primary use case is a musician configuring routing from their phone while standing next to the Pi on stage or in the studio.

- **FR-12.1:** The UI shall be designed for touch interaction on phone screens (min 375px width) as the primary target, with desktop as secondary.
- **FR-12.2:** All tap targets minimum 48px (per Google Material guidelines for touch).
- **FR-12.3:** The routing interface shall use the connection matrix view as default on mobile (wiring diagram is secondary/desktop view). Matrix cells are large, touch-friendly checkboxes.
- **FR-12.4:** Swipeable tabs or bottom navigation for switching between Routing / Presets / Settings / Status views.
- **FR-12.5:** No pinch-to-zoom required — all content readable at default zoom level.
- **FR-12.6:** The captive portal landing page shall show a simplified routing overview with the most common actions (Connect All / Disconnect All / select a preset) immediately visible without scrolling.

### 4.3 Non-Functional Requirements

- **NFR-5:** Web UI mobile-first: designed and tested primarily on phone browsers (iOS Safari, Chrome Android). Desktop is a supported secondary target.
- **NFR-6:** Web UI works without internet connectivity (fully self-contained, no CDN).
- **NFR-7:** Total process memory footprint (MIDI engine + web server + hostapd + dnsmasq) < 50 MB.
- **NFR-8:** Web UI initial load time < 2 seconds over WiFi AP connection.

---

## 5. Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                    Raspberry Pi                       │
│                                                       │
│  ┌────────────────────────────────────────────────┐  │
│  │      raspimidihub (single Python process)      │  │
│  │                                                │  │
│  │  ┌─────────────────┐  ┌────────────────────┐  │  │
│  │  │  MIDI Engine     │  │  Web Server        │  │  │
│  │  │  (asyncio)       │  │  (Quart/SSE)       │  │  │
│  │  │                  │◄─┤                    │  │  │
│  │  │  - ALSA seq API  │  │  - REST API        │  │  │
│  │  │  - Event monitor │  │  - Static SPA      │  │  │
│  │  │  - Hotplug       │  │  - SSE stream      │  │  │
│  │  │  - LED control   │  │  - Captive portal  │  │  │
│  │  └─────────┬────────┘  └────────────────────┘  │  │
│  └────────────┼───────────────────────────────────┘  │
│               │ snd_seq_* API calls                   │
│  ┌────────────┴───────────────────────────────────┐  │
│  │        ALSA Sequencer (kernel)                 │  │
│  │        Source of truth for connections          │  │
│  └────────────────────────────────────────────────┘  │
│                                                       │
│  ┌────────────────────────────────────────────────┐  │
│  │  WiFi AP (hostapd + dnsmasq)                   │  │
│  │  - WPA2 access point (default mode)            │  │
│  │  - DNS hijack → captive portal                 │  │
│  │  - DHCP for AP clients (192.168.4.0/24)        │  │
│  └────────────────────────────────────────────────┘  │
│                                                       │
│  USB ←→ [Device A] [Device B] [Device C] ...         │
│  WiFi ←→ [Phone] [Tablet] [Laptop]                   │
└──────────────────────────────────────────────────────┘
```

### 5.1 Component Breakdown

| Component | Description | Technology |
|-----------|-------------|------------|
| MIDI Engine | ALSA sequencer event loop, connection management, LED control | Python 3 + `pyalsa` (libasound2 bindings) |
| Web Server | REST API + SSE + static file serving + captive portal (Phase 2) | Python 3 + Quart (async Flask) |
| Frontend SPA | Mobile-first visual routing interface (Phase 2) | Preact + SVG + `htm` (no build step) |
| WiFi AP | Access point + DHCP + DNS captive portal (Phase 2) | `hostapd` + `dnsmasq` |
| RO Setup | Post-install script for read-only FS | Bash (separate `raspimidihub-rosetup` package) |
| udev rules | Secondary hotplug fallback | udev `.rules` file |

### 5.2 State Management

**ALSA sequencer is the single source of truth for connection state.**

- **User action via UI:** REST API → `snd_seq_subscribe_port()` → read back ALSA state → return confirmed state → push SSE event.
- **Device hotplug:** ALSA event → apply saved config for matching device → push SSE event.
- **Boot:** Read config from tmpfs → apply to ALSA → read back to confirm. Missing devices stored as "pending" in memory.
- **UI load:** `GET /api/devices` and `GET /api/connections` query ALSA live. UI never caches state.

### 5.3 REST API (Phase 2)

```
GET    /api/devices                    # List all connected MIDI devices + ports
GET    /api/connections                # List all active connections
POST   /api/connections                # Create a connection {from, to}
DELETE /api/connections/{id}           # Remove a connection
PATCH  /api/connections/{id}           # Update filters on a connection
POST   /api/connections/connect-all    # Default all-to-all routing
DELETE /api/connections                # Disconnect all
GET    /api/presets                    # List saved presets
POST   /api/presets                    # Save current routing as preset
POST   /api/presets/{name}/activate    # Load and apply a preset
DELETE /api/presets/{name}             # Delete a preset
GET    /api/presets/{name}/export      # Download preset JSON
POST   /api/presets/import             # Upload preset JSON
GET    /api/system                     # System info (hostname, IP, temp, RAM, version)
GET    /api/events                     # SSE stream
```

### 5.4 Configuration Storage

Config on `/boot/firmware/raspimidihub/config.json`, operated from tmpfs copy at runtime:

1. Boot: `ExecStartPre` copies `/boot/firmware/raspimidihub/config.json` → `/run/raspimidihub/config.json`
2. Runtime: all reads/writes go to tmpfs copy
3. Explicit save: validate → write tmpfs temp → remount `/boot/firmware` rw → copy → sync → remount ro → backup old as `.bak`
4. Corruption recovery: parse failure → try `.bak` → fall back to all-to-all defaults

---

## 6. Security Considerations

### 6.1 Core Security (Phase 1)

- **SEC-1:** The core service MUST NOT invoke `aconnect`, `amidi`, or any ALSA CLI tool via shell execution. All ALSA sequencer operations use the `snd_seq_*` library API directly. This eliminates command injection as a vulnerability class.
- **SEC-2:** The read-only filesystem limits persistent attack surface.
- **SEC-3:** udev rules restrict managed devices to USB Audio Class only (class 01, subclass 03). Devices presenting additional interfaces (HID, mass storage) are logged and ignored by the MIDI service.
- **SEC-4:** The `.deb` package post-install script shall not download anything from the internet.
- **SEC-5:** `.deb` packages GPG-signed with SHA256 checksums.

### 6.2 Web UI Security (Phase 2)

**Security model:** The WiFi AP password is the primary security boundary (like a printer or pro audio mixer). Anyone who knows the AP password can access the web UI. No additional web authentication is required for the MIDI routing page — this is a deliberate usability choice for musicians who need quick access on stage.

- **SEC-6:** **AP mode (default):** WPA2 password protects access. The web UI is only reachable by devices connected to the Pi's own WiFi. No additional login required. Users who want stronger security can change the AP password via the Settings page.
- **SEC-7:** **Client mode (optional):** When connected to an external WiFi, the web UI is accessible to all devices on that network. Users choosing this mode accept the security posture of their network. An optional PIN/password for the web UI can be enabled in Settings for this scenario.
- **SEC-8:** Security headers on all responses: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'self'`.
- **SEC-9:** All USB device names and user-supplied strings HTML-escaped before rendering. Preact auto-escapes by default.
- **SEC-10:** REST API rate-limited: max 10 mutating requests/second. SSE connections capped at 5 concurrent.
- **SEC-11:** Config JSON validated against strict schema on read. No `eval()`, no YAML, JSON only.
- **SEC-12:** No sensitive data stored. Config files contain only MIDI routing rules and WiFi credentials (WPA password stored in hostapd config, same as any Linux AP setup).

### 6.3 Future Security Enhancements

- **SEC-F1:** Optional HTTPS with self-signed certificate.
- **SEC-F2:** MAC address allowlist for AP clients.

---

## 7. Installation Flow

```
User downloads raspimidihub_1.0_arm64.deb + raspimidihub-rosetup_1.0_all.deb
         │
         ▼
sudo apt install ./raspimidihub*.deb
  (resolves deps: ntpsec, alsa-utils, python3-pyalsa, avahi-daemon)
         │
         ▼
raspimidihub postinst:
  1. Install systemd service for MIDI routing
  2. Install udev rules (USB Audio Class devices)
  3. Configure hostapd (AP mode, SSID=RaspiMIDIHub-XXXX, WPA2)
  4. Configure dnsmasq (DHCP + DNS captive portal)
  5. Enable + start raspimidihub.service, hostapd, dnsmasq

raspimidihub-rosetup postinst:
  1. [debconf] "Make root filesystem read-only? [Y/n]"
  2. Back up all files to /var/lib/raspimidihub-rosetup/backup/
  3. Configure fstab (tmpfs mounts, ro flags)
  4. Configure cmdline.txt (fsck.mode=skip)
  5. Disable swap (mask dphys-swapfile)
  6. Disable unnecessary services
  7. Configure NTP, NetworkManager, random-seed
  8. Add shell helpers (rw/ro aliases)
         │
         ▼
sudo reboot
         │
         ▼
System boots read-only, MIDI routing active
```

---

## 8. Upgrade Path

1. SSH into the Pi
2. `rw` (remount read-write)
3. `sudo apt install ./raspimidihub_1.1_arm64.deb` (or `sudo apt upgrade` if APT repo configured)
4. `ro` (remount read-only)
5. `sudo reboot`

**Future (Phase 2+):** Upload `.deb` via web UI system panel → server handles rw/install/ro/restart automatically.

---

## 9. Testing Strategy

- **Unit tests:** Mock ALSA sequencer clients, verify correct connection matrix generation for N devices with M ports each.
- **Integration tests:** Use `snd-virmidi` kernel module to create virtual MIDI devices. Install `.deb` on clean Pi OS image, verify all-to-all connectivity.
- **postinst/postrm tests:** Install on clean image, verify fstab/cmdline/services. Purge, verify full restoration.
- **Hot-plug stress test:** Rapidly connect/disconnect USB MIDI devices 50 times. Verify no leaked connections, no crash, correct final state.
- **Power-loss test:** Pull power during operation, verify clean boot and no filesystem corruption.
- **Security tests:** CSRF attempts, XSS via crafted USB device names, API fuzzing, rate limit verification.

---

## 10. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|-------------|-----------|
| US-1 | Musician | Plug in my MIDI keyboard and synth and have them connected | I can play without a computer |
| US-2 | Live performer | Power on the Pi and have MIDI routing ready in < 30s | I can set up quickly at a gig |
| US-3 | Studio owner | Add/remove MIDI devices without restarting | My workflow isn't interrupted |
| US-4 | Tinkerer | Install with a single command | Setup is painless |
| US-5 | Power user | Use a web UI to create custom routes | I can filter/route specific devices to specific destinations |
| US-6 | Musician | Save routing presets | I can switch between setups for different songs/shows |
| US-7 | Sysadmin | Uninstall cleanly | I can repurpose the Pi |
| US-8 | Live performer | Trust the Pi won't corrupt its SD card on power loss | My gear is reliable |

---

## 11. Resolved Questions (from Expert Review)

| # | Question | Resolution |
|---|----------|-----------|
| Q1 | Web UI technology? | Python (Quart) — single process with MIDI engine, pre-installed on Pi OS, large contributor pool. |
| Q2 | MIDI channel remapping? | Phase 2.1 scope. Routing + filtering first, remapping later. |
| Q3 | ALSA vs JACK vs PipeWire? | ALSA sequencer. Rock-solid, 20+ years, kernel-level routing, zero overhead. JACK/PipeWire add unnecessary complexity. |
| Q4 | Scenes via MIDI program change? | Phase 2.1 feature. Requires preset system (FR-9) first. |
| Q5 | Minimum Pi models? | Pi 3B+ and newer. Pi Zero 2 W supported but with USB bus caveat noted in Section 2. |
| Q6 | Web UI network access? | **WiFi AP mode is the default.** Pi creates its own WPA2 network with captive portal. AP password is the security boundary — no web auth needed. Optional: switch to client mode (join existing WiFi) via Settings. |

---

## 12. Glossary

| Term | Definition |
|------|-----------|
| ALSA | Advanced Linux Sound Architecture — Linux kernel sound subsystem |
| aconnect | ALSA utility to manage MIDI sequencer port connections (used for debugging only, not by the service) |
| MIDI | Musical Instrument Digital Interface — protocol for musical devices |
| SysEx | System Exclusive — MIDI messages specific to a device manufacturer |
| tmpfs | Temporary filesystem stored in RAM, lost on reboot |
| udev | Linux device manager — can trigger scripts on hardware events |
| SPA | Single-Page Application — web app that loads once and updates dynamically |
| mDNS | Multicast DNS — enables `.local` hostnames on local networks (Avahi) |
| SSE | Server-Sent Events — HTTP-based one-way server-to-client push |
| pyalsa | Python bindings for the ALSA library |
| Quart | Async Python web framework (async-compatible Flask API) |
| Preact | Lightweight (3 KB) React-compatible UI library |
