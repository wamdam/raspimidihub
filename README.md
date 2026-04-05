# RaspiMIDIHub

**Turn your Raspberry Pi into a plug-and-play USB MIDI hub.**

RaspiMIDIHub automatically connects all USB MIDI devices to each other. Plug in your keyboards, synths, drum machines, and controllers — they all talk to each other instantly. No computer needed, no configuration required.

The Raspberry Pi runs on a **read-only filesystem**, so you can pull the power at any time without risk of SD card corruption. Your last saved MIDI routing configuration is preserved across reboots and power cycles.

For custom routing, open the web interface from your phone — the Pi creates its own WiFi network with a captive portal that opens the configuration page automatically, just like hotel WiFi.

![License](https://img.shields.io/badge/license-MIT-blue.svg)

---

## Features

### Zero-Configuration MIDI Routing
- **Automatic all-to-all:** Every connected MIDI device can send to every other device
- **Loop prevention:** Self-connections are excluded automatically
- **Hot-plug support:** Add or remove devices at any time — routing updates within 2 seconds
- **Multi-port devices:** Devices with multiple MIDI ports (e.g., MOTU, iConnectivity) are fully supported

### Appliance Reliability
- **Read-only filesystem:** The SD card is never written to during normal operation, preventing corruption
- **Power-safe:** Pull the power cord at any time. The Pi boots back up with your last saved configuration intact
- **Auto-start:** MIDI routing is active within 30 seconds of power-on
- **Watchdog:** The service automatically restarts if anything goes wrong

### WiFi Configuration Interface (Phase 2)
- **Built-in WiFi access point:** The Pi creates its own WiFi network (`RaspiMIDIHub-XXXX`)
- **Captive portal:** Connect from your phone and the config page opens automatically
- **Mobile-first design:** Touch-friendly interface designed for phones on stage
- **Visual routing:** Drag-and-connect interface inspired by hardware patchbays
- **Presets:** Save and recall routing configurations for different songs or shows
- **MIDI activity monitor:** See real-time MIDI traffic on every port

### Easy Installation
- **Single package install:** Download one `.deb` file, install, reboot — done
- **Clean uninstall:** `dpkg --purge` fully restores the original system

---

## Quick Start

### Requirements

- Raspberry Pi 3B+, 4B, 5, or Zero 2 W
- Raspberry Pi OS Lite (Bookworm or later)
- microSD card (4 GB+)
- USB MIDI devices

### Installation

```bash
# Download the latest release
wget https://github.com/YOURUSERNAME/raspimidihub/releases/latest/download/raspimidihub_1.0_arm64.deb
wget https://github.com/YOURUSERNAME/raspimidihub/releases/latest/download/raspimidihub-rosetup_1.0_all.deb

# Install both packages
sudo apt install ./raspimidihub*.deb

# Reboot to activate
sudo reboot
```

After reboot, the Pi runs with a read-only filesystem and all connected MIDI devices are automatically routed to each other.

### Connecting to the Web Interface (Phase 2)

1. On your phone, go to WiFi settings
2. Connect to `RaspiMIDIHub-XXXX` (password: `midihub1`)
3. The configuration page opens automatically
4. Change routes, save presets, adjust settings

---

## Example Usages

### Example 1: Simple Keyboard-to-Synth Setup

**Scenario:** You have a MIDI keyboard and a synthesizer. You want to play the synth from the keyboard.

```
[MIDI Keyboard] --USB--> [Raspberry Pi] --USB--> [Synthesizer]
```

**Steps:**
1. Connect both USB MIDI cables to the Pi
2. Power on the Pi
3. Play — the keyboard controls the synth immediately

No configuration needed. The Pi routes the keyboard's MIDI output to the synth's MIDI input (and vice versa, if the synth sends data back).

---

### Example 2: Live Performance with Multiple Instruments

**Scenario:** A live performer has a controller keyboard, a drum machine, a bass synth, and a sampler. Everything should be connected to everything.

```
[Controller Keyboard]  ──┐
[Drum Machine]         ──┤
[Bass Synth]           ──┼── [Raspberry Pi] ── all-to-all
[Sampler]              ──┘
```

**Steps:**
1. Connect all four devices via USB (use a USB hub if needed)
2. Power on the Pi
3. All devices can send MIDI to all other devices:
   - Keyboard triggers bass synth AND sampler
   - Drum machine syncs with sampler via MIDI clock
   - Any device can control any other

**Power-safe:** Pull the power after the gig. Next time you plug it in, everything works exactly the same way.

---

### Example 3: Custom Routing via Web UI (Phase 2)

**Scenario:** A studio owner wants the controller keyboard to go to the synth only, while the sequencer goes to both the synth and the drum machine. The drum machine should NOT receive keyboard input.

```
[Controller] ───────────────> [Synth]
[Sequencer]  ───────────────> [Synth]
             └──────────────> [Drum Machine]
```

**Steps:**
1. Connect your phone to the Pi's WiFi (`RaspiMIDIHub-XXXX`)
2. The routing page opens automatically
3. Tap "Disconnect All" to start fresh
4. Tap "Controller MIDI Out" → check "Synth MIDI In"
5. Tap "Sequencer MIDI Out" → check "Synth MIDI In" and "Drum Machine MIDI In"
6. Tap "Save" → name it "Studio Setup"
7. Done — this configuration persists across power cycles

---

### Example 4: Song-Based Preset Switching (Phase 2)

**Scenario:** A band uses different MIDI routings for different songs.

**Steps:**
1. Configure routing for Song 1, save as preset "Song 1 - Ballad"
2. Configure routing for Song 2, save as preset "Song 2 - Rock"
3. During the show, open phone → select preset → routing changes instantly
4. Export presets as JSON backup files for safety

---

### Example 5: MIDI Channel Filtering (Phase 2.1)

**Scenario:** A keyboard sends on all 16 channels, but the synth should only receive channels 1-4, and the drum machine only channel 10.

**Steps:**
1. Open the routing page on your phone
2. Tap the connection line from Keyboard to Synth
3. In the filter panel, enable only channels 1, 2, 3, 4
4. Tap the connection line from Keyboard to Drum Machine
5. Enable only channel 10
6. Save

---

## Architecture

RaspiMIDIHub consists of two Debian packages:

| Package | Purpose |
|---------|---------|
| `raspimidihub` | MIDI routing service + web UI + WiFi AP |
| `raspimidihub-rosetup` | Read-only filesystem hardening (optional but recommended) |

The MIDI routing uses the Linux ALSA sequencer at the kernel level, adding virtually zero latency. The web UI runs as part of the same lightweight Python process.

See [docs/FSD.md](docs/FSD.md) for the full functional specification and [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for the development roadmap.

---

## Important Notes

### Power Safety

**You can power off the Raspberry Pi at any time.** The read-only filesystem ensures that sudden power loss will never corrupt the SD card or the operating system. This is critical for live performance and studio environments where equipment may be powered off via a power strip or breaker.

Your MIDI routing configuration is stored on a separate area of the SD card and is written only when you explicitly save. The last saved configuration is automatically loaded on every boot.

If the saved configuration cannot be read (e.g., SD card sector error), the Pi falls back to default all-to-all routing and the LED blinks red to indicate fallback mode. Save a new configuration from the web UI to return to normal operation.

### Network & Security

The Pi creates its own WiFi network by default. The WPA2 password is the only security gate — anyone with the password can access the configuration page. This is intentional: the devices are meant for trusted environments (your studio, your stage).

If you need tighter security:
- Change the default AP password via the web UI Settings page
- Switch to client mode and connect the Pi to your own secured network

### SD Card Lifetime

With the read-only filesystem enabled, the SD card receives zero writes during normal operation. An inexpensive SD card should last for many years of continuous use. Without read-only mode, Raspberry Pi SD cards typically fail after 1-2 years of 24/7 operation.

---

## Maintenance

### Updating the Software

```bash
# SSH into the Pi
ssh pi@raspimidihub.local

# Remount filesystem read-write (alias provided by raspimidihub-rosetup)
rw
# Or manually: sudo mount -o remount,rw / && sudo mount -o remount,rw /boot/firmware

# Install the new version
sudo apt install ./raspimidihub_1.1_arm64.deb

# Remount read-only and reboot
ro
# Or manually: sudo mount -o remount,ro /boot/firmware && sudo mount -o remount,ro /
sudo reboot
```

### Uninstalling

```bash
ssh pi@raspimidihub.local
rw
sudo apt purge raspimidihub raspimidihub-rosetup
sudo reboot
```

This fully restores the Pi to a normal read-write Raspberry Pi OS installation.

---

## Supported Hardware

| Raspberry Pi Model | USB Ports | Recommended Max MIDI Devices | Notes |
|--------------------|-----------|------------------------------|-------|
| Pi Zero 2 W | 1 (via OTG + hub) | 3-4 | Single USB bus, limited bandwidth |
| Pi 3B+ | 4 | 4 | Shared USB/Ethernet bus |
| Pi 4B | 4 (2x USB 3.0) | 8+ | Dedicated USB 3.0 bus, recommended |
| Pi 5 | 4 (2x USB 3.0) | 8+ | Best performance |

---

## Documentation

- [Functional Specification](docs/FSD.md) — Complete feature specification
- [Implementation Plan](docs/IMPLEMENTATION_PLAN.md) — Development roadmap and milestones
- [Contributing](docs/CONTRIBUTING.md) — How to contribute to the project
- [Changelog](docs/CHANGELOG.md) — Release history

---

## License

MIT License — see [LICENSE](LICENSE) for details.
