# Technical Information

Hardware requirements, software stack, performance envelopes, and
the interfaces RaspiMIDIHub speaks. The right place to look when
deciding whether RaspiMIDIHub fits a particular setup.

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
read-only filesystem and the isolated-core reservation assume a
multi-core ARMv8 system.

### SD card

- **Capacity** -- 4 GB minimum, 8 GB or 16 GB recommended.
- **Class** -- A1 or better. A2 (high endurance) is not required;
  the read-only root means the card is rarely written.

### USB topology

- USB-A ports double as MIDI device inputs and as tethered-phone
  internet inputs.
- Hot-plug supported.
- USB hubs supported on any USB-A port; powered hubs recommended
  if the attached devices are bus-powered.

### Device identity

- Devices with a usable USB serial number are identified by it
  (`usb-<vid>:<pid>-<serial>`) -- port-independent.
- Devices without one (or with a factory placeholder) are
  identified by hub-tree path (`usb-<path>-<vid>:<pid>`); a single
  such device replugged elsewhere is re-matched by vendor/product
  ID when unambiguous. Details in chapter 5, "Device Topology and
  Renames".
- Bluetooth devices are identified by MAC address (`bt-<mac>`),
  plugin instruments by instance ID (`plugin-<id>`).
- Devices mirrored from a peer hub over Network MIDI are
  identified by the peer's hub ID plus the device's stable ID on
  that hub (`net-<hub>-<remote-id>`) -- stable across reboots and
  IP changes on both ends.

### Bluetooth

- On-board BLE used for BLE-MIDI peripherals.
- External Bluetooth USB dongles are **not** supported.
- **WiFi/BT coexistence (Pi 3-class).** Pi 3B / 3B+ / Zero 2 W
  share one 2.4 GHz radio between hostapd (the AP) and BLE. With
  the AP up, BLE *central* connects may be aborted locally
  (`le-connection-abort-by-local`), surfacing as **Connection
  failed**; confirmed by the connect succeeding once
  `raspimidihub-hostapd` is stopped. Unit/chip-dependent -- a
  controller that booted on a generic fallback BD address (`dmesg`:
  "Using default device address") has even less margin. Pi 4 / 5
  use separate radios and are unaffected. Chapter 14, *Limits*.

### Audio

- Audio I/O is not used by RaspiMIDIHub. The appliance is MIDI-
  only.

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

No external Python packages are required at runtime; the routing
service uses the standard library exclusively. The optional
`python3-dbus-next` package is recommended (and pulled by the
`raspimidihub` deb's Recommends) for Bluetooth support.

The web UI is **Preact + HTM**, served as static assets. No build
step. No npm.

## Performance Envelope

| Path | Typical latency | Note |
|------|-----------------|------|
| **Direct ALSA connection** | Sub-microsecond | Kernel-only; effectively zero |
| **Filtered / mapped connection** | 1--3 ms | Userspace filter + mapper round-trip |
| **Plugin (event-driven)** | Sub-millisecond | Plugin threads on isolated CPU 2 |
| **Plugin (clocked)** | Sub-millisecond jitter | Sample-accurate ALSA queue scheduling |
| **BLE-MIDI** | 7.5--15 ms | Bound by BLE connection interval, not the bridge |
| **Web UI → MIDI out** | 2--6 ms (Stats card readout) | HTTP POST + routing |

The Stats card in **Settings** is the live readout of loop lag,
MIDI in→out latency, and Control in→MIDI out latency. Values
significantly above the typical range almost always indicate one
of: USB bus contention from a bus-powered device, an underpowered
PSU, or a plugin doing more work than expected in a callback.

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
| mDNS hostname | `raspimidihub-<id>.local` (unique per hub; `<id>` = title-bar/WiFi code). Single hub also answers `raspimidihub.local` |
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

Both `/` and `/boot/firmware` are mounted read-only in steady
state. Save Config (and the BlueZ snapshot, and the update
downloader) briefly remounts `/boot/firmware` rw, writes the
file, syncs, and remounts it ro -- the main root never gets
remounted. Volatile state lives on tmpfs. See chapter 18 for
the rationale and the `rw` / `ro` helpers.

## Power Budget

- The Pi itself draws around 3--7 W under typical load
  (model-dependent).
- Bus-powered MIDI devices add ~50--200 mA each; large keyboards
  and class-compliant interfaces add more.
- Use the manufacturer's official PSU (5V/3A on Pi 4, 5V/5A on Pi
  5) to avoid undervolt warnings. Phone chargers and laptop USB-C
  ports are sometimes inadequate, particularly when bus-powered
  MIDI devices are present.
- A powered USB hub is recommended for any setup with three or
  more bus-powered MIDI devices.

## Compliance and Licences

- **Application licence** -- LGPL.
- **Bundled third-party** -- Preact (MIT), HTM (Apache 2.0).
- **OS underneath** -- Raspberry Pi OS Lite, which has its own
  licence terms. Out of scope here; consult the OS documentation.

## Project Repository

The project lives on GitHub at
`https://github.com/wamdam/raspimidihub`. Releases are tagged
`vX.Y.Z` and attached as GitHub releases with the matching `.deb`
files (chapter 17).

