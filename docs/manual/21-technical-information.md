# Technical Information

Hardware requirements, software stack, performance envelopes, and
the interfaces RaspiMIDIHub speaks.

## Hardware

### Supported Raspberry Pi models

+-------------+------------------+-------+----------------------------------------------+
| Model       | Ports            | Max   | Best for                                     |
+:============+:=================+:=====:+:=============================================+
| Pi Zero 2 W | 1 (OTG + hub)    | 3--4  | Entry-level / portable                       |
+-------------+------------------+-------+----------------------------------------------+
| Pi 3B+      | 4                | 4     | Budget option                                |
+-------------+------------------+-------+----------------------------------------------+
| Pi 4B       | 4 (2 × USB 3.0)  | 8+    | **Recommended**                              |
+-------------+------------------+-------+----------------------------------------------+
| Pi 5        | 4 (2 × USB 3.0)  | 8+    | Plugin-heavy / BLE-critical                  |
+-------------+------------------+-------+----------------------------------------------+

Pi 1, Pi 2, and the original Pi Zero are **not** supported -- the
read-only filesystem and isolated-core reservation assume a
multi-core ARMv8 system.

### SD card

- **Capacity** -- 4 GB minimum, 8 or 16 GB recommended.
- **Class** -- A1 or better; A2 (high endurance) is unnecessary on
  the read-only root.

### USB topology

- USB-A ports double as MIDI inputs and tethered-phone internet
  inputs; hot-plug supported.
- USB hubs work on any USB-A port; powered hubs recommended for
  bus-powered devices.

### Device identity

- A usable USB serial number → `usb-<vid>:<pid>-<serial>`,
  port-independent.
- No serial (or a factory placeholder) → hub-tree path
  (`usb-<path>-<vid>:<pid>`); a single such device replugged
  elsewhere is re-matched by vendor/product ID when unambiguous
  (chapter 5, "Device Topology and Renames").
- Bluetooth devices: MAC address (`bt-<mac>`); plugin instruments:
  instance ID (`plugin-<id>`).
- Network MIDI mirrors: peer hub ID + the device's stable ID there
  (`net-<hub>-<remote-id>`) -- stable across reboots and IP changes
  on both ends.

### Bluetooth

- On-board BLE used for BLE-MIDI peripherals.
- External Bluetooth USB dongles are **not** supported.
- **WiFi/BT coexistence (Pi 3-class).** Pi 3B / 3B+ / Zero 2 W
  share one 2.4 GHz radio between hostapd (the AP) and BLE. With
  the AP up, BLE *central* connects may be aborted locally
  (`le-connection-abort-by-local`), surfacing as **Connection
  failed**; confirmed if the connect succeeds once
  `raspimidihub-hostapd` is stopped. Unit/chip-dependent -- a
  controller on a generic fallback BD address (`dmesg`: "Using
  default device address") has even less margin. Pi 4 / 5 use
  separate radios and are unaffected. Chapter 14, *Limits*.

### Audio

- Audio I/O is not used. The appliance is MIDI-only.

## Software Stack

| Component | Role |
|-----------|------|
| **Raspberry Pi OS Lite** (Bookworm or Trixie or later) | Base OS |
| **Linux kernel 6.x** | Kernel; `isolcpus=2,3` set by `raspimidihub-rosetup` (core 3 = loop, core 2 = plugins) |
| **Python 3.11+** (stdlib only) | Routing service runtime |
| **ALSA seq** (via `libasound2` + `ctypes`) | MIDI routing core |
| **BlueZ** | Bluetooth stack; `midi` plugin disabled in favour of the in-tree bridge |
| **hostapd + dnsmasq** | WiFi access point |
| **wpa_supplicant** | WiFi client mode |
| **avahi-daemon** | mDNS (`raspimidihub-<id>.local`) |
| **systemd** | Service supervision |

The routing service uses the Python standard library exclusively;
the optional `python3-dbus-next` package (deb Recommends) enables
Bluetooth. The web UI is **Preact + HTM**, served as static
assets -- no build step, no npm.

## MIDI 2.0 Kernel Requirements

The hub detects at startup whether the system can speak MIDI 2.0
(UMP) and reports the result in `GET /api/system` under `midi2`.
Both must be present:

- **alsa-lib ≥ 1.2.10** — shipped by Raspberry Pi OS Trixie
  (1.2.14). Bookworm's 1.2.8 predates UMP entirely.
- **A kernel with the UMP options enabled** (`CONFIG_SND_SEQ_UMP`,
  `CONFIG_SND_USB_AUDIO_MIDI_V2`, `CONFIG_SND_UMP`). Stock
  Raspberry Pi OS kernels currently ship with these **off**;
  enabling them is tracked upstream (raspberrypi/linux#7474).

When the kernel side is missing, the startup log shows
`UMP (MIDI 2.0) support: kernel=no` and all MIDI 2.0 features stay
dormant: devices fall back to their mandatory MIDI 1.0 mode at
classic resolution, and nothing needs configuring.

## Performance Envelope

| Path | Typical latency | Note |
|------|-----------------|------|
| **Direct ALSA connection** | Sub-microsecond | Kernel-only; effectively zero |
| **Filtered / mapped connection** | 1--3 ms | Userspace filter + mapper round-trip |
| **Plugin (event-driven)** | Sub-millisecond | Plugin threads on isolated CPU 2 |
| **Plugin (clocked)** | Sub-millisecond jitter | Sample-accurate ALSA queue scheduling |
| **BLE-MIDI** | 7.5--15 ms | Bound by BLE connection interval, not the bridge |
| **Web UI → MIDI out** | 2--6 ms (Stats card readout) | HTTP POST + routing |

The Stats card in **Settings** shows live loop lag, MIDI in→out
latency, and Control in→MIDI out latency. Values well above typical
usually mean USB bus contention from a bus-powered device, an
underpowered PSU, or a plugin overworking a callback.

## Capacities

| Capacity | Value | Note |
|----------|-------|------|
| Plugins | 16 built-in | User-supplied plugins also supported |
| Controllers | 4 templates | Multiple instances per template |
| Tracker pages | 16 per instance | Looping back to page 0 after last |
| Tracker voices | 8 per instance | T1..T8, each with own MIDI channel |
| MIDI devices | Bounded by USB ports / hub | See model table |
| BLE peripherals | Tested: one at a time | Two-at-once should work, not tested |
| Saved deb files | 3 latest | Automatic retention; older debs deleted |
| Connections in matrix | Unbounded in practice | Limited by USB and CPU |

## Network

| Parameter | Value |
|-----------|-------|
| AP SSID format | `RaspiMIDIHub-XXXX` (last four chars derived from MAC) |
| AP default password | `midihub1` (change immediately) |
| AP IP range | DHCP from the captive-portal subnet (typically `172.24.1.0/24`) |
| AP gateway | `172.24.1.1` (typical) |
| mDNS hostname | `raspimidihub-<id>.local` (unique per hub; `<id>` = title-bar/WiFi code). Bare `raspimidihub.local` does not resolve |
| HTTP server port | 80 |
| HTTPS | Not used (LAN-only; trust model is the AP password) |
| SSE endpoint | `/api/events` (long-lived `text/event-stream`) |
| BLE-MIDI service UUID | `03B80E5A-EDE8-4B33-A751-6CE34EC4C700` |
| BLE-MIDI characteristic UUID | `7772E5DB-3868-4112-A1A9-F2669D106BF3` |
| RTP-MIDI (Network MIDI) ports | UDP, one even/odd pair per exported device, allocated upward from 5004 |
| RTP-MIDI discovery | mDNS `_apple-midi._udp` via `python3-zeroconf` (coexists with avahi on port 5353) |

## Filesystem Layout

| Path | Mount | Role |
|------|-------|------|
| `/` | ext4, read-only | OS root |
| `/run/` | tmpfs | Runtime state (config working copy, sockets) |
| `/var/log/` | tmpfs | Logs (cleared on reboot) |
| `/var/lib/bluetooth/` | tmpfs | BlueZ pairing state (snapshotted to boot partition) |
| `/tmp/` | tmpfs | Standard ephemeral |
| `/boot/firmware/` | vfat, read-only (rw on demand) | Boot partition; persistent state lives here |

Save Config, the BlueZ snapshot, and the update downloader briefly
remount `/boot/firmware` rw, write, sync, and remount it ro; the
root is never remounted (chapter 18).

## Power Budget

- Pi draw: ~3--7 W under typical load, model-dependent.
- Bus-powered MIDI devices add ~50--200 mA each; large keyboards
  and class-compliant interfaces more.
- Use the official PSU (5V/3A on Pi 4, 5V/5A on Pi 5); phone
  chargers and laptop USB-C ports can be inadequate with
  bus-powered devices attached.
- A powered USB hub is recommended for three or more bus-powered
  MIDI devices.

## Compliance and Licences

- **Application licence** -- GPL.
- **Bundled third-party** -- Preact (MIT), HTM (Apache 2.0).
- **OS underneath** -- Raspberry Pi OS Lite, under its own licence
  terms.

## Project Repository

The project lives at `https://github.com/wamdam/raspimidihub`.
Releases are tagged `vX.Y.Z` with the matching `.deb` files
attached (chapter 17).
