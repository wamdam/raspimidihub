# RaspiMIDIHub — Functional Specification Document

**Version:** 2.0
**Date:** 2026-04-07
**Status:** All phases implemented

---

## 1. Overview

RaspiMIDIHub turns a Raspberry Pi into a dedicated, appliance-like USB MIDI hub. When powered on, it automatically routes MIDI data between all connected USB MIDI devices. The system runs on a read-only root filesystem to maximize SD card longevity and ensure reliability in live/studio environments where sudden power loss is expected.

### 1.1 Goals

- **Zero-configuration MIDI routing:** Plug in USB MIDI devices, power on, all devices talk to each other.
- **Appliance reliability:** Read-only filesystem, no SD card wear, survives power cuts.
- **Easy installation:** Single `.deb` package transforms a stock Raspberry Pi OS into a MIDI hub.
- **Web UI:** Browser-based interface for custom MIDI routing, filtering, mapping, and device management.

### 1.2 Non-Goals

- Not a DAW or audio interface.
- Not a general-purpose MIDI processor (no scripting/plugin system).
- Not a wireless MIDI bridge (USB only).

---

## 2. Target Hardware

| Component | Requirement |
|-----------|------------|
| Board | Raspberry Pi 3B/3B+/4B/5/Zero 2 W |
| OS | Raspberry Pi OS Lite (Trixie/Bookworm or later) |
| Storage | microSD card (any size >= 4 GB) |
| USB | 1-4+ USB MIDI devices via USB-A ports (or USB hub) |
| Network | WiFi (built-in AP) or Ethernet (for updates and web access) |

---

## 3. Core MIDI Hub

### 3.1 Automatic MIDI Routing

- All connected USB MIDI devices discovered via ALSA sequencer ctypes bindings to libasound2 (no CLI tools).
- Every MIDI input port connected to every output port of every other device (all-to-all).
- Self-connections excluded to prevent feedback loops.
- System client (0) and Midi Through excluded.
- Hotplug detection via ALSA sequencer announce events with 500ms debounce.
- Multi-port devices fully supported (all ports enumerated and connected).
- Configurable default routing: "all-to-all" (default) or "none" (manual) for new devices.

### 3.2 Read-Only Root Filesystem

Delivered as a separate package (`raspimidihub-rosetup`):

- Root filesystem and boot partition mounted read-only.
- tmpfs for `/tmp`, `/var/log`, `/var/tmp`, and other volatile paths.
- Swap disabled, fsck skipped, unnecessary services masked.
- NTP via `ntpsec`, NetworkManager configured for read-only operation.
- Shell aliases `rw`/`ro` for maintenance, with prompt indicator.
- Auto-remount to `ro` on shell logout.

### 3.3 Service Reliability

- Systemd service with `Restart=always`, `RestartSec=2`, `WatchdogSec=30`.
- Full state reconstruction on restart (re-scan devices, re-establish connections from saved config).
- LED status: green ACT steady = running, blinks on MIDI activity, red PWR on = config fallback.

---

## 4. Web-Based MIDI Router UI

### 4.1 Web Server

- Single Python process (asyncio) serves MIDI routing engine and web UI.
- Custom async HTTP server (stdlib `asyncio`, no framework dependencies).
- REST API for all MIDI routing operations.
- SPA frontend with Preact + htm (no build step, no npm).
- Real-time updates via Server-Sent Events (SSE).
- Accessible at `http://raspimidihub.local` (mDNS) on port 80.

### 4.2 Connection Matrix

- Mobile-first touch interface (390px+ width).
- Rows = MIDI sources (FROM), columns = destinations (TO).
- Tap to connect/disconnect, long-press or right-click for filter/mapping panel.
- Purple cells indicate connections with active filters or mappings.
- Offline devices shown grayed out with dimmed checkboxes for saved connections.
- Clock indicator: pulsing play icon on devices sending MIDI clock, orange warning for multiple sources.
- Device labels show custom names, tap for full name toast with original ALSA name.

### 4.3 MIDI Filtering (per-connection)

- 16-channel bitmask filtering with traffic light indicators.
- Message type filtering: notes, CC, program change, pitch bend, aftertouch, SysEx, clock/realtime.
- Instant apply — changes take effect immediately.
- Filtered connections route through userspace (~1-3ms latency) instead of kernel-level ALSA subscriptions.

### 4.4 MIDI Mapping (per-connection)

- Note to CC (momentary): note on/off sends configurable CC values.
- Note to CC (toggle): each press alternates between two CC values.
- CC to CC: remap CC numbers with input/output range scaling and inversion.
- Channel remap: route events from one channel to another.
- Pass-through option for forwarding original events alongside mapped output.
- MIDI Learn: auto-detect source note/CC from device.
- Mappings persisted via stable USB device identification.

### 4.5 Device Management

- Device renaming with persistence across reboots (stored by USB topology + VID:PID).
- Per-port renaming for multi-port devices.
- Device detail panel: info, MIDI monitor, MIDI test sender (piano keyboard + CC slider).
- Remove offline devices from saved configuration.

### 4.6 Presets

- Save/load named routing configurations.
- Export/import presets as JSON files.
- Presets include stable device IDs, filters, and mappings.

### 4.7 Configuration Persistence

- Config stored at `/boot/firmware/raspimidihub/config.json` (FAT32).
- Runtime copy on tmpfs at `/run/raspimidihub/config.json`.
- Explicit save: write tmpfs temp -> validate -> remount rw -> copy -> sync -> remount ro -> backup.
- Fallback chain: runtime copy -> persistent config -> .bak -> defaults.
- Full config export/import as JSON.
- Disconnected connection states saved with filter/mapping data.

### 4.8 MIDI Activity Bar

- Persistent bar showing latest MIDI events from two sources.
- Clock events filtered out (shown as matrix indicator instead).
- Auto-expire: entries vanish after 2 seconds of inactivity.
- Toggleable in Settings.

---

## 5. WiFi & Network

### 5.1 WiFi Access Point

- Built-in WPA2 access point using `hostapd` + `dnsmasq`.
- Default SSID: `RaspiMIDIHub-XXXX` (MAC-derived), default password: `midihub1`.
- Captive portal: DNS hijack resolves all queries to Pi IP, success responses for OS probe endpoints.
- AP password changeable via Settings.

### 5.2 WiFi Client Mode

- Join existing WiFi network via Settings (network scanner dropdown).
- Writes `.nmconnection` file directly (works on read-only filesystem).
- Auto-fallback to AP mode if connection lost (~90 seconds).
- `sudo reset-wifi` command for recovery.

### 5.3 Ethernet Configuration

- Configure eth0 as DHCP or static IP with address, netmask, gateway, and DNS.
- Connection brought down/up to apply gateway changes.
- Ethernet works alongside WiFi AP (recommended for updates).

---

## 6. Software Updates

- In-app update check against GitHub releases API.
- One-click install with live progress (external script survives service restart).
- Auto-reload after upgrade to pick up new JS/CSS.
- One-line installer: `curl -sL .../install.sh | bash`.

---

## 7. Security

- WiFi AP password is the primary security boundary (no web authentication).
- All ALSA operations via library API (no CLI shell-outs, no command injection).
- Read-only filesystem limits persistent attack surface.
- Security headers on all responses.
- Preact auto-escapes user-supplied strings.
- Config JSON validated on read (no eval, no YAML).

---

## 8. Architecture

```
+----------------------------------------------------+
|                    Raspberry Pi                     |
|                                                     |
|  +----------------------------------------------+  |
|  |      raspimidihub (single Python process)     |  |
|  |                                                |  |
|  |  +-----------------+  +--------------------+  |  |
|  |  |  MIDI Engine    |  |  Web Server        |  |  |
|  |  |  (asyncio)      |  |  (stdlib asyncio)  |  |  |
|  |  |                 |<-|                    |  |  |
|  |  |  - ALSA ctypes  |  |  - REST API        |  |  |
|  |  |  - Filter engine|  |  - Static SPA      |  |  |
|  |  |  - Hotplug      |  |  - SSE stream      |  |  |
|  |  |  - LED control  |  |                    |  |  |
|  |  +---------+-------+  +--------------------+  |  |
|  +------------+----------------------------------+  |
|               | snd_seq_* ctypes calls              |
|  +------------+----------------------------------+  |
|  |        ALSA Sequencer (kernel)                |  |
|  +-----------------------------------------------+  |
|                                                     |
|  +-----------------------------------------------+  |
|  |  WiFi AP (hostapd + dnsmasq)                  |  |
|  +-----------------------------------------------+  |
|                                                     |
|  USB <-> [Device A] [Device B] [Device C] ...       |
|  WiFi <-> [Phone] [Tablet] [Laptop]                 |
+----------------------------------------------------+
```

### REST API

```
GET    /api/devices                    # List connected + offline MIDI devices
GET    /api/connections                # List active + offline connections
POST   /api/connections                # Create connection (online or offline)
DELETE /api/connections/{id}           # Remove connection
PATCH  /api/connections/{id}           # Update filters
POST   /api/connections/connect-all    # Restore all-to-all routing
DELETE /api/connections                # Disconnect all
GET    /api/presets                    # List presets
POST   /api/presets                    # Save preset
POST   /api/presets/{name}/activate    # Load and apply preset
DELETE /api/presets/{name}             # Delete preset
GET    /api/presets/{name}/export      # Export preset JSON
POST   /api/presets/import             # Import preset JSON
GET    /api/config/export              # Export full config
POST   /api/config/import              # Import full config
GET    /api/system                     # System info
PATCH  /api/system                     # Update system settings
GET    /api/system/update-check        # Check for updates
POST   /api/system/update              # Start update
GET    /api/system/update-status       # Poll update progress
GET    /api/network                    # List network interfaces
POST   /api/network/configure          # Configure interface
GET    /api/wifi                       # WiFi status
POST   /api/wifi/ap                    # Switch to AP mode
POST   /api/wifi/client               # Switch to client mode
GET    /api/wifi/scan                  # Scan WiFi networks
POST   /api/system/reboot             # Reboot
GET    /api/events                     # SSE stream
```

---

## 9. Installation

Two Debian packages:

| Package | Purpose |
|---------|---------|
| `raspimidihub` | MIDI routing service + web UI + WiFi AP |
| `raspimidihub-rosetup` | Read-only filesystem hardening (optional but recommended) |

Dependencies: `libasound2`, `hostapd`, `dnsmasq`, `avahi-daemon`, `ntpsec`.

Install: `curl -sL .../install.sh | bash && sudo reboot`

Uninstall: `sudo apt purge raspimidihub raspimidihub-rosetup && sudo reboot`
