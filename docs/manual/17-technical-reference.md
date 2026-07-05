# Technical Reference

How the parts fit together, what the saved state contains, and the
numbers: performance envelopes, capacities, and the interfaces
RaspiMIDIHub speaks. Nothing here is required to operate the unit;
it pays off when diagnosing edge cases. Hardware requirements
(supported Pi models, SD card, power) are in chapter 2.

## The Top-Level Block Diagram

![System architecture block diagram](../screenshots/architecture-block-diagram.svg)

The MIDI path on the left is the *hot* path -- every MIDI event
goes through it. The web UI on the right is the *cold* path --
configuration changes flow through it but never sit in the
per-event critical path.

## How MIDI Flows

Every MIDI event takes one of two paths:

- **Direct path.** A connection without filter or mapping is wired
  at the kernel level; events pass through no RaspiMIDIHub code.
  Added latency is effectively zero (sub-microsecond). Shown as a
  *red* cell in the matrix.
- **Filtered path.** A connection with a channel filter, a
  message-type filter, or any mapping is received, transformed,
  and re-emitted in software. Added latency is roughly 1--3 ms.
  Shown as a *purple* cell.

Toggling a filter off can shave a couple of milliseconds on a
latency-critical chain.

**MIDI 2.0 (UMP).** On kernels with MIDI 2.0 support (see *MIDI 2.0
Kernel Requirements* below) the ALSA sequencer speaks the Universal
MIDI Packet format natively and converts between MIDI 1.0 and 2.0
clients per delivery: direct-path routing between two MIDI 2.0
devices preserves full resolution, and mixed 1.0/2.0 wiring needs
no special handling. The hub reads each device's UMP *endpoint*
description at scan time and models its ports from the function
blocks (chapter 5); discovery is automatic.

## Plugins Are Virtual Devices

Plugin instances appear in the matrix alongside USB devices and
Bluetooth peripherals -- one input port, one output port, the same
routing, filtering, and mapping behaviour. The play surfaces
(Tracker, Arpeggiator, Euclidean, Cartesian), the controllers
(Mixer 8, FX 6, Performance 16, XY 4), and every other plugin live
in the same routing graph; no plugin has a special-case path.

## The Bluetooth MIDI Bridge

The built-in BLE-MIDI bridge handles pairing, GATT subscription,
and BLE-MIDI framing, exposing each paired peripheral as a virtual
MIDI device indistinguishable from a USB device. Chapter 10 covers
pairing, reconnection, and persistence across power-off.

## The Network MIDI Bridge

The RTP-MIDI (AppleMIDI) counterpart to the BLE bridge. *Export*:
each shared local device is advertised over mDNS as its own
RTP-MIDI session; any standard participant (a second hub, macOS,
iOS, `rtpmidid`) can connect. *Mirror*: sessions exported by a peer
hub appear as virtual MIDI devices in the matrix. The
implementation is in-process and journal-free (RFC 6295's recovery
journal targets lossy open-internet paths; on a wired LAN the
engine's panic / note-release machinery covers the residual risk).
Discovery uses `python3-zeroconf` alongside the avahi daemon.
Chapter 13's *Network MIDI* section covers the user-facing side.

## The Web UI Connection

The configuration UI is a single-page web application served by the
Pi and rendered on your phone or tablet; the Pi needs no display.
The browser talks to the Pi over two channels: **HTTP** for actions
(Save Config, filter changes, plugin parameter edits) and
**Server-Sent Events** for live state (matrix changes, monitored
MIDI events, plugin scope values) pushed over a long-lived stream.
Themes are covered in chapter 3, spectator mirroring in chapter 12;
implementation notes for both live in `docs/UI-INTERNALS.md` in the
repository.

## The Reserved CPU

The routing service's main loop runs on a CPU core isolated from
the rest of the OS -- no other userland process or kernel timer is
scheduled there, so unrelated system activity cannot disturb the
MIDI path. This is why the Stats card in **Settings** reads
sub-millisecond loop lag even on a busy unit.

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

## Configuration Persistence

Project state lives in four places:

- **Working copy** -- `/run/raspimidihub/config.json` on tmpfs
  (RAM); what the running unit reads and writes.
- **Persistent copy** -- `/boot/firmware/raspimidihub/config.json`
  on the FAT32 boot partition; the **Save Config** checkpoint,
  previous version kept as `config.json.bak`.
- **Autosave slots** -- `autosave-0.json.gz` / `autosave-1.json.gz`
  alongside: a gzipped, double-buffered snapshot of the live edited
  state, written debounced while editing.
- **Rolling backups** -- `backups/backup-NNNNN.json.gz` (+ an
  `index.json`): one compressed checkpoint per Save, last 50 kept,
  restorable from Settings → Backup.

Boot prefers the newest valid autosave, then `config.json`, `.bak`,
defaults -- a hard power cut resumes the last edit, not just the
last Save. **Save Config** writes atomically (temp file, flush,
rename -- atomic on FAT32 within one directory), and the autosave
is double-buffered and gzip-CRC validated, so a cut mid-write
cannot corrupt state. Both filesystems are read-only in steady
state; save flows briefly remount `/boot/firmware` rw, write,
sync, and remount it ro, while the root is never remounted
(chapter 14; chapter 11 for the user-facing flows).

## The Top-Level Schema

Top-level keys of the exported / saved JSON:

| Key | Type | Meaning |
|-----|------|---------|
| `version` | int | Schema version. Currently `1`. |
| `mode` | string | `"all-to-all"` -- routing mode. |
| `default_routing` | string | `"none"` (default) -- new devices arrive disconnected; `"all"` -- auto-connect every new device to every other. |
| `connections` | list | Every saved connection in the matrix. |
| `disconnected` | list | Connections explicitly toggled off but kept for re-enable. |
| `wifi` | object | WiFi configuration; see *WiFi Configuration* below. |
| `network_midi` | object | Network MIDI (RTP-MIDI) sharing; see *Network MIDI Configuration* below. |
| `midi2` | object | MIDI 2.0 behaviour: `force_midi1` (list of device stable-IDs to treat as MIDI 1.0 — escape hatch for misbehaving devices), `ci_enabled` (bool, default true — send MIDI-CI Capability Inquiry to bidirectional devices on connect), `ci_disabled` (list of stable-IDs to never probe). |

Plugin instances, controller instances, device and port renames,
and per-cell filter/mapping state live inside `connections` and its
supporting structures.

## Connections

Each entry describes one matrix cell: source and destination (each
an ALSA client/port identifier or a virtual-device reference --
plugin instance ID, controller instance ID, BLE peripheral ID), the
filter object (channel mask, message-type mask), the mappings list
(Note → CC, Note → CC toggle, CC → CC, Channel Remap), and the
enable flag (toggling off keeps the entry; removing deletes it).
The JSON emitted by **Export Config** is the authoritative schema.

## WiFi Configuration

The `wifi` object:

| Key | Type | Meaning |
|-----|------|---------|
| `mode` | string | Current mode -- `"ap"` or `"client"`. |
| `ap_ssid` | string | AP SSID (auto-generated when empty). |
| `ap_password` | string | AP password (default `"midihub1"`). |
| `ap_band` | string | AP radio band -- `"2.4"` (default) or `"5"`. 5 GHz auto-falls back to 2.4 on a 2.4-only radio or a failed bring-up. |
| `ap_country` | string | Regulatory country (ISO alpha-2, e.g. `"DE"`). Empty = auto-detect from the kernel regdomain. Required for 5 GHz. |
| `client_ssid` | string | Home WiFi SSID. |
| `client_password` | string | Home WiFi password. |
| `wifi_mode_pref` | string | Mode preference -- `"ap_only"`, `"wifi_for_updates"`, or `"wifi_always"`. |

`mode` is the *current* live mode; `wifi_mode_pref` the preference
set in **Settings**. The service reconciles preference to mode as
conditions change.

## Network MIDI Configuration

The `network_midi` object (Settings → Network MIDI; chapter 13's
*Network MIDI* section for the concept):

| Key | Type | Meaning |
|-----|------|---------|
| `enabled` | bool | Master switch for advertising / discovery. |
| `exported` | list | Stable IDs of local devices shared as RTP-MIDI sessions. |
| `mirror_disabled` | list | Peer-hub sessions excluded from auto-mirroring. |
| `mirrored_foreign` | list | Manually mirrored non-hub sessions (by mDNS service name). |
| `manual_peers` | list | IPs/hostnames invited directly when mDNS discovery cannot reach them. |

Like `wifi`, an appliance setting: changes apply and save
immediately, outside the dirty-state model.

## Plugin Instances

Each serialised instance carries a unique instance ID (stable
across save/load), the plugin type name (e.g. `"arpeggiator"`), an
optional rename, a `params` dict of current values, and any
sub-structured payload (Tracker grid, Velocity Curve data,
drop-button snapshots). The **plugin clipboard** clones the entire
serialisation under a fresh instance ID.

## Controller Instances

Same shape as plugin instances, plus:

- Per-cell rename, CC, channel, On/Off values, learned MIDI source.
- Per-axis XY-pad configuration (spring force, home).
- Drop-button captured snapshots (one per slot).
- Theme choice (`"default"`, `"navy"`, `"forest"`, ...).

## Device Identity

Every device gets a stable ID; configs, backups, and exports key on
it. The formats:

- A usable USB serial number → `usb-<vid>:<pid>-<serial>`,
  port-independent. Factory placeholder "serials" (all zeros and
  the like) count as absent.
- No serial → *USB topology* (`usb-<path>-<vid>:<pid>`), identified
  by hub-tree path; multi-port devices add a port number, and
  per-port renames persist.
- Bluetooth peripherals: MAC address (`bt-<mac>`).
- Plugin instruments: instance ID (`plugin-<id>`).
- Network MIDI mirrors: peer hub ID + the device's stable ID there
  (`net-<hub>-<remote-id>`) -- stable across reboots and IP changes
  on both ends.

Consequences of the USB scheme:

- A device with a real serial keeps its name and connections on
  *any* port.
- A serial-less device replugged into a different port is
  re-recognised by vendor/product ID when it is the only one of its
  model; the migrated identity is written on the next **Save
  Config**.
- Two identical serial-less devices stay distinct by port; the hub
  never *guesses* between them.
- Re-recognition never rewrites configs, backups, or exports; old
  saved IDs keep loading and resolve live against the connected
  hardware.

## What Is *Not* in the Project State

- **BlueZ bonds** -- snapshotted to
  `/boot/firmware/raspimidihub/bluetooth-state.tar` (chapter 10.3);
  not in `config.json` or **Export Config**.
- **Logs** -- ephemeral, on tmpfs at `/var/log/`.
- **The deb cache** -- `/boot/firmware/raspimidihub/debs/`.
- **System-level OS settings** (timezone, locale, kernel
  parameters).
- **Browser-side display preferences** (MIDI activity bar
  visibility, knob tick sounds) -- stored per browser, not on the
  Pi.

## Legacy Keys and Schema Evolution

The loader deep-merges the on-disk data over the defaults, so a
config saved by an older release loads cleanly with missing keys
taking their defaults. An explicit drop list strips keys removed by
newer releases; currently `presets`, replaced by the Save / Load /
Export / Import flow (chapter 11).

The `version` field starts at `1`; patch releases do not change it.
A schema-breaking major version will bump it, and the import
validator (chapter 11.5) refuses incompatible major versions
outright rather than half-loading a config.

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
| MIDI devices | Bounded by USB ports / hub | See chapter 2 |
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

## The Two Packages

| Package | Role |
|---------|------|
| `raspimidihub` | The routing service, the plugin host, the web UI, the access point |
| `raspimidihub-rosetup` | Read-only filesystem hardening and CPU isolation |

`raspimidihub-rosetup` is technically optional -- the service runs
on a normal writable root -- but the read-only setup is what makes
the appliance power-safe, so the install one-liner installs both.

## Compliance and Licences

- **Application licence** -- GPL.
- **Bundled third-party** -- Preact (MIT), HTM (Apache 2.0).
- **OS underneath** -- Raspberry Pi OS Lite, under its own licence
  terms.
