# Configuration and Data Structure

The reference for the project state: what lives where and what the
saved state contains.

## The Two State Locations

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
  restorable from Settings -> Backup.

Boot prefers the newest valid autosave, then `config.json`, `.bak`,
defaults -- a hard power cut resumes the last edit, not just the
last Save. **Save Config** writes both the runtime and persistent
copies (chapter 4.7; 15.6 and 18.3 for autosave + backups).

Both filesystems are read-only in steady state; Save Config
remounts `/boot/firmware` rw for milliseconds, writes via `mv`
(atomic on FAT32 within one directory), syncs, and remounts it ro.
The root is never remounted (chapter 18.1).

## The Top-Level Schema

Top-level keys of the exported / saved JSON:

| Key | Type | Meaning |
|-----|------|---------|
| `version` | int | Schema version. Currently `1`. |
| `mode` | string | `"all-to-all"` -- routing mode. |
| `default_routing` | string | `"none"` (default) -- new devices arrive disconnected; `"all"` -- auto-connect every new device to every other. |
| `connections` | list | Every saved connection in the matrix. |
| `disconnected` | list | Connections explicitly toggled off but kept for re-enable. |
| `wifi` | object | WiFi configuration; see 5.4. |
| `network_midi` | object | Network MIDI (RTP-MIDI) sharing; see the *Network MIDI Configuration* section below. |
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

The `network_midi` object (Settings → Network MIDI; chapter 17's
*Network MIDI* section for the concept):

| Key | Type | Meaning |
|-----|------|---------|
| `enabled` | bool | Master switch for advertising / discovery. |
| `exported` | list | Stable IDs of local devices shared as RTP-MIDI sessions. |
| `mirror_disabled` | list | Peer-hub sessions excluded from auto-mirroring. |
| `mirrored_foreign` | list | Manually mirrored non-hub sessions (by mDNS service name). |
| `manual_peers` | list | IPs/hostnames invited directly when mDNS discovery cannot reach them. |

Like `wifi`, an appliance setting: changes apply and save
immediately, outside the dirty-state model. Devices mirrored *from*
a peer hub get stable IDs prefixed `net-` (chapter 21, "Device
identity").

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

## Device Topology and Renames

USB devices are identified by **USB serial number** when the
hardware provides a usable one (`usb-<vid>:<pid>-<serial>`),
otherwise by *USB topology* (`usb-<path>-<vid>:<pid>`). Factory
placeholder "serials" (all zeros and the like) count as absent.
Consequences:

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

Multi-port devices have each port identified by topology + port
number; per-port renames persist.

## What Is *Not* in the Project State

- **BlueZ bonds** -- snapshotted to
  `/boot/firmware/raspimidihub/bluetooth-state.tar` (chapter 14.3);
  not in `config.json` or **Export Config**.
- **Logs** -- ephemeral, on tmpfs at `/var/log/`.
- **The deb cache** -- `/boot/firmware/raspimidihub/debs/`.
- **System-level OS settings** (timezone, locale, kernel
  parameters).
- **Browser-side display preferences** (MIDI activity bar
  visibility, knob tick sounds) -- stored per browser, not on the
  Pi.

## Legacy Keys

The loader deep-merges the on-disk data over the defaults, so a
config saved by an older release loads cleanly with missing keys
taking their defaults. An explicit drop list strips keys removed by
newer releases; currently `presets`, replaced by the Save / Load /
Export / Import flow (chapter 15).

## Schema Evolution and Major Versions

The `version` field starts at `1`; patch releases do not change it.
A schema-breaking major version will bump it, and the import
validator (chapter 15.5) refuses incompatible major versions
outright rather than half-loading a config.
