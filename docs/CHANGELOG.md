# Changelog

All notable changes to RaspiMIDIHub will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [1.3.1] - 2026-04-06

### Fixed
- Network settings: nmcli reload/activate timeout no longer fails the operation.
- Static IP now includes DNS servers (8.8.8.8, 8.8.4.4) automatically.

## [1.3.0] - 2026-04-06

### Added
- **Persistent connection states**: deliberately disconnected connections are saved
  and survive device reconnect/reboot. No more reset to all-to-all on hotplug.
- **Config restore on reconnect**: toggling a connection back on restores its
  previous filters and mappings automatically.
- **Default routing setting**: choose "all-to-all" or "none (manual)" for new
  devices in Settings → MIDI Routing.
- **Offline devices**: unplugged devices with saved config shown grayed out in
  the connection matrix.

### Fixed
- Filter engine cleanup when disconnecting a filtered connection.

## [1.2.1] - 2026-04-06

### Added
- `sudo reset-wifi` command to recover AP mode when Pi is unreachable.
- One-line installer: `curl -sL .../install.sh | bash`.

## [1.2.0] - 2026-04-06

### Added
- **In-app software updates**: check for new releases, view changelog, one-click
  install with live progress (Downloading → Installing → Restarting).
  Uses an external update script that survives the service restart.
- Version number displayed in header bar.
- Page auto-reloads after upgrade to pick up new JS/CSS.

### Changed
- Redesigned WiFi settings: single card with clear AP/client mode indicator.
- WiFi client mode: writes .nmconnection file directly (works on read-only fs).
- Sorted devices alphabetically in connection matrix and device list.

### Fixed
- Channel filtering: direct ALSA subscription now properly removed when
  switching to userspace filter engine.
- Captive portal: returns success responses so mobile OS stays connected.
- MIDI activity bar: no longer shows ALSA system events.

## [1.1.7] - 2026-04-06

### Changed
- Update mechanism uses external script that survives service restart.
- UI polls status file and detects new version after restart.

## [1.1.6] - 2026-04-06

### Fixed
- Update button text no longer duplicated; progress shown below button only.

## [1.1.5] - 2026-04-06

### Fixed
- Update button now shows progress (was broken: setUpdateStep prop not passed).
- Status text shown below button in visible color during update.

## [1.1.4] - 2026-04-06

### Fixed
- Update progress now visible: SSE events sent before dpkg install
  (postinst restarts the service, killing the process before events could be sent).

## [1.1.3] - 2026-04-06

### Improved
- Update button shows live progress: Downloading / Installing / Restarting.
- All action buttons disable during operations with dimmed styling.
- Immediate feedback after confirming update.

## [1.1.1] - 2026-04-06

### Fixed
- Channel filtering now actually blocks MIDI: direct ALSA subscription was not
  removed when switching to userspace filter on startup.
- WiFi client mode: write .nmconnection file directly instead of relying on
  nmcli (which fails on read-only filesystem).
- MIDI activity bar no longer shows ALSA system events (e.g. "0 type 66").

### Added
- Software update UI: check for new releases, view changelog, one-click install.
- Redesigned WiFi settings: single card with clear mode indicator and contextual actions.
- Offline-friendly update check (shows "no internet" instead of raw error).

## [1.1.0] - 2026-04-06

### Fixed
- Captive portal: mobile devices no longer disconnect from AP WiFi. Probe
  endpoints now return proper success responses instead of redirects.

### Added
- Devices sorted alphabetically in connection matrix and device list —
  rename with `1_...`, `2_...` prefixes for consistent ordering.
- Network settings page for configuring eth0 (DHCP or static IP).
- Enhanced MIDI activity bar with split left/right showing device names.

### Removed
- Unused captive portal redirect/catch-all code from web server.

## [1.0.0] - 2026-04-05

First stable release.

### Added

**Core MIDI Hub**
- Automatic all-to-all MIDI routing between USB devices via ALSA sequencer
- Hotplug support with 500ms debounce — add/remove devices at any time
- Loop prevention (no self-connections)
- Multi-port device support

**MIDI Filtering (per-connection)**
- Channel filtering with 16-channel bitmask
- Message type filtering (notes, CC, program change, pitch bend, aftertouch, SysEx, clock/realtime)
- Instant apply — no confirmation needed
- Colorblind-friendly traffic light indicators

**MIDI Mapping (per-connection)**
- Note to CC (momentary: on/off values on note press/release)
- Note to CC toggle (alternates between two values on each press)
- CC to CC with input/output range scaling and inversion
- Channel remapping
- Pass-through option (forward original event alongside mapped output)
- MIDI Learn (auto-detect source note/CC from device)
- Duplicate and conflict detection

**Web UI (mobile-first SPA)**
- Connection matrix with tap to connect, long-press for filters/mappings
- FROM/TO labels on matrix
- Slide-up panels with swipe-down dismiss, X button, ESC key support
- Device detail panel with rename, MIDI monitor, and test sender
- Piano keyboard (one octave, adjustable) for sending test notes
- CC slider for sending test CC values
- Persistent MIDI activity bar (toggleable in Settings)
- Real-time sync across multiple browsers via SSE
- Connection lost indicator in header
- Preact + htm frontend, no build step

**Presets**
- Save/load named routing configurations
- Export/import as JSON files

**WiFi**
- Built-in WiFi access point (RaspiMIDIHub-XXXX, WPA2)
- Captive portal for iOS/Android/Windows/macOS
- Client mode with WiFi network scanner dropdown
- Auto-fallback to AP mode if client connection lost (~90 seconds)
- mDNS: reachable at http://raspimidihub.local

**Configuration Persistence**
- Save/load config to boot partition (FAT32)
- Stable device identification via USB topology path + VID:PID
- Config restored on boot including connections, filters, and mappings
- Hotplug rescan respects saved config

**Appliance Features**
- Read-only root filesystem (via raspimidihub-rosetup package)
- Power-safe: pull the power at any time
- Systemd service with watchdog
- LED status: green ACT steady = running, blinks on MIDI activity, red PWR off = healthy
- Automatic hostname set to `raspimidihub`
- Reboot from web UI

**Packaging**
- `raspimidihub` .deb package (all arch, depends on libasound2, hostapd, dnsmasq)
- `raspimidihub-rosetup` .deb package (read-only filesystem hardening)
- postinst sets hostname, updates /etc/hosts, unmasks hostapd

**Documentation**
- README with installation instructions, usage examples, hardware compatibility
- UI Guide with mobile screenshots
- Functional Specification (FSD)
- Implementation Plan
