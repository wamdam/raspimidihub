# Changelog

All notable changes to RaspiMIDIHub will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [2.0.6] - 2026-04-19

### Added
- **Arpeggiator**: slow rates plus their triplet variants. Full list, ordered
  by length: `4/1, 4/1T, 2/1, 2/1T, 1/1, 1/1T, 1/2, 1/2T, 1/4, 1/4T, 1/8,
  1/8T, 1/16, 1/16T, 1/32`. Lets the arp step at bar-scale for slow evolving
  patches. All three sync modes (Free, Tempo, Transport) honour the new rates.

### Fixed
- **Mapping fan-out rejected as "duplicate"**. Duplicate detection for CC→CC
  and Note→CC ignored `dst_channel`, so legit mappings like
  `ch9,cc1 → ch1,cc10` + `ch9,cc1 → ch2,cc10` got rejected. The pointless-check
  also rejected same-ch/same-CC mappings with non-identity scaling (a
  legitimate value-shaper use case). Rules are now:
  - REJECT only an exact all-fields-identical duplicate (including scaling
    ranges, pass-through flag, on/off velocities).
  - REJECT a CC→CC with same src+dst and identity `0..127 → 0..127` scaling.
  - REJECT a channel-map with `src_channel == dst_channel`.
  - ALLOW everything else, including fan-out to multiple destination channels
    and same-src-dst variants with different scaling curves.

  The validation logic was extracted into `validate_new_mapping` in
  `midi_filter.py` and is covered by a 30-row parametrized test matrix.

## [2.0.5] - 2026-04-19

### Added
- **Hold plugin**: latch notes without a sustain pedal. Press any combination of
  keys, lift your fingers, and the chord sustains. While at least one key is
  still held, new presses add to the chord. Once all keys are released, press
  the configured release-note to silence the chord (the note itself is never
  forwarded) or press any other note to release the previous chord and start
  a new one. Release-note can be disabled if you only want the
  new-note-replaces behaviour. Released on MIDI Stop.
- **Panic button** (red, bottom of the matrix page). Sends CC 123
  (All Notes Off) + CC 120 (All Sound Off) on every channel to every outbound
  destination in the live routing graph, and invokes `plugin.panic()` on every
  instance so stateful plugins release their internal note tracking. Transport
  is left alone so panic doesn't derail whatever's playing.
- **MIDI Learn button** under every `NoteSelect` wheel. Tap it and the next
  note you play on any connected source becomes the value. Applies to Hold's
  release-note, Note Splitter's split-point, etc. Opt out with
  `NoteSelect(..., learnable=False)`.
- **Channel-remap fan-out**: a single incoming channel can be layered to
  multiple destination channels (e.g. bass on ch 1 + strings on ch 6) by
  adding one channel-map mapping per target. Previously the second mapping
  was rejected as a duplicate, and even if accepted would have silently
  overwritten the first because the engine rewrote the event in-place. Each
  matching channel map now emits its own copy.
- **`panic()` hook** on `PluginBase` (default no-op). Override in plugins
  that hold note state to silence any sustaining output when the Panic
  button fires. Implemented on Hold, Arpeggiator, Chord Generator,
  MIDI Delay.
- Transport Start/Stop now reach every plugin, not just clock-tick
  subscribers (the tick queue is always created now).

### Fixed
- Saved config was not loaded at boot when running headless. `_scan_and_connect`
  always passed an empty live-state snapshot to `_apply_saved_config`, which
  treated `[]` as "nothing to apply" instead of falling back to
  `config.connections`. Devices were left unconnected until the user hit
  "Load config" in the web UI. Boot now restores saved routing correctly.
- Plugin-referencing connections (hw↔plugin, plugin↔plugin) were dropped at
  boot. `engine.start()` used to run the initial scan *before* plugins were
  restored, so their ALSA clients didn't exist yet when saved connections
  were applied. Initial scan now runs after plugin restore.
- Hold got wedged in a stuck state if you changed `release_note` (via wheel
  or Learn) to a note that was already tracked in `_physical`. The paired
  note-off was swallowed and the plugin could never reach LOCKED again, so
  every subsequent note stacked without replacement. `on_note_off` now
  always clears `_physical`, independent of the release-note guard.

## [2.0.4] - 2026-04-15

### Changed
- Removed global clock/transport bridge introduced in 2.0.1. Clock now flows
  only through explicit matrix connections (use the per-connection Clock/RT
  filter toggle to enable/disable). The bridge caused duplicate clock when
  devices were also connected in the matrix.

## [2.0.3] - 2026-04-13

### Fixed
- **rosetup**: install now works on fresh Pi OS Trixie (64-bit). Previously
  failed because `/etc/os-release` no longer contains "Raspberry Pi" (it's
  pure Debian now), and `/boot/firmware` is mounted ro by default.
  Detection now uses `/sys/firmware/devicetree/base/model`, and setup remounts
  boot rw as needed.

## [2.0.2] - 2026-04-12

### Fixed
- Swipe-dismiss no longer triggers when interacting with wheels/faders in panels.
  Dual protection: ignore list for interactive controls + horizontal movement check.
- Update checker crash on Pi (unused `packaging` module import removed).
- LED no longer flickers constantly on MIDI clock. Clock: gentle heartbeat per beat.
  Notes/CC: sharp blink as before.

## [2.0.1] - 2026-04-11

### Changed
- **Hotplug preserves live state**: filters, mappings, and connection state survive
  device hotplug without needing to save config first. The engine snapshots all live
  state before teardown and restores it after rescan.
- **Plugins start unconnected**: new virtual instrument instances no longer auto-connect
  to all devices. Users route them manually for precise control.
- **Duplicate device handling**: two identical USB devices (same VID:PID) now get
  unique stable IDs, so renaming one no longer affects the other.

## [2.0.0] - 2026-04-11

Massive release introducing the virtual instrument / plugin system.

### Plugin System
- Complete plugin framework with 12 built-in plugins
- Each plugin runs in its own thread with ALSA IN/OUT ports
- Declarative UI: Wheel, Fader, Radio, Toggle, StepEditor, CurveEditor, Button, NoteSelect, ChannelSelect, Group, Display (scope/meter)
- CC automation: hardware CCs control plugin params, UI animates in real-time via SSE
- Clock bus with 24 PPQ, musical divisions, transport (Start/Stop/Continue)
- Plugin sandbox: import validation, callback watchdog (1s timeout)
- Plugin display outputs: oscilloscope and meter with SSE push
- Per-plugin rate limiting (1000 events/sec)
- Plugin icons (icon.svg per plugin, turquoise in UI)
- Plugin help text (? button)
- Rawmidi workaround for transport to DIN outputs

### 12 Built-in Plugins
- **Arpeggiator** -- pattern player with step sequencer, accents, gate control, and transport sync
- **CC LFO** -- waveform generator (sine, triangle, square, saw, S&H) with live oscilloscope
- **CC Smoother** -- jitter removal with configurable smoothing factor and dual scopes
- **Chord Generator** -- input note triggers full chords (major, minor, 7th, custom intervals)
- **Master Clock** -- internal BPM clock with start/stop/pause transport and beat meter
- **MIDI Delay** -- note delay with circular buffer, feedback repeats and velocity decay
- **Note Splitter** -- keyboard split at configurable note into two channels with per-zone transpose
- **Note Transpose** -- semitone shift up or down
- **Panic Button** -- All Notes Off + All Sound Off on all 16 channels
- **Scale Remapper** -- quantize notes to musical scales with labeled root-note wheel
- **Velocity Curve** -- drawable 128-point response curve
- **Velocity Equalizer** -- normalize velocity to fixed value or compressed range

### UI
- 3-tab navigation: Routing, Presets, Settings (Devices tab removed)
- Routing matrix: plugin icons, DIN icons, rate meters, Add button, tap-to-open device panels
- Device panel: editable title, plugin config, scrollable multitouch piano, mixer fader with value on thumb
- Mapping form: Wheel/Fader/Radio/Toggle controls replace dropdowns, MIDI Learn
- Presets include plugin instances, overwrite confirmation
- Settings: system info with load indicator, PWA install, reload button
- Haptic feedback (tick/thud sounds + vibration)
- CC coalescing for test sender
- SSE timeout prevents stuck connections

### Bug Fixes
- ALSA event type constants (Start=30, Stop=32, not 37/39)
- Filter engine per-connection write ports (no event leaking)
- Clock bus: auto-start, monitor-port-only counting, queue flush on Start
- Plugin clock timing: pipe wake-up, ALSA events before ticks
- MIDI Delay circular buffer (no thread explosion)
- Hanging notes fix (stable refs in piano touch handlers)
- Direct MIDI addressing (no broadcast from test sender)

## [1.3.6] - 2026-04-09

### Fixed
- Mapping duplicate detection for CC fan-out
- SSE drain timeout

## [1.3.5] - 2026-04-08

### Fixed
- Minor stability improvements

## [1.3.3] - 2026-04-07

### Fixed
- Gateway not applied for static IP: uses separate `gateway=` key in NetworkManager
  config and brings connection down/up to force reapplication.

## [1.3.2] - 2026-04-07

### Added
- **Offline connections**: saved connections for offline devices shown as grayed-out
  checkboxes in the matrix -- can be toggled on/off even while the device is unplugged.
- **Clock indicator**: pulsing play icon on FROM devices sending MIDI clock.
  Turns orange when multiple devices send clock simultaneously (common mistake).
- **MIDI bar auto-expire**: bottom bar entries vanish after 2 seconds of inactivity.
- **Toast shows original name**: tapping a renamed device in the matrix shows the
  custom name plus the original ALSA name in gray.

### Changed
- Clock events filtered from bottom MIDI bar (shown only as matrix indicator).
- Device detail panel: MIDI monitor uses direct DOM updates to prevent
  channel/port dropdown flickering from rapid MIDI events.
- Rename save button: small inline style, hidden after saving (device and port).
- Custom port names no longer truncated in matrix labels.

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
  devices in Settings > MIDI Routing.
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
  install with live progress (Downloading > Installing > Restarting).
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
- Devices sorted alphabetically in connection matrix and device list --
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
- Hotplug support with 500ms debounce -- add/remove devices at any time
- Loop prevention (no self-connections)
- Multi-port device support

**MIDI Filtering (per-connection)**
- Channel filtering with 16-channel bitmask
- Message type filtering (notes, CC, program change, pitch bend, aftertouch, SysEx, clock/realtime)
- Instant apply -- no confirmation needed
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
