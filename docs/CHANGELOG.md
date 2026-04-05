# Changelog

All notable changes to RaspiMIDIHub will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

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
