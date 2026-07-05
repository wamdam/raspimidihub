# Configuration and Data Structure

How RaspiMIDIHub remembers what it is. This chapter is the
reference for the project state -- what lives where, what is part
of "the saved state", and what each button on the routing matrix
actually writes.

## The Two State Locations

The project state lives at these paths:

- **Working copy** -- `/run/raspimidihub/config.json` on tmpfs
  (RAM). This is what the running unit reads from and writes to.
- **Persistent copy** -- `/boot/firmware/raspimidihub/config.json`
  on the FAT32 boot partition, the deliberate **Save Config**
  checkpoint. A backup of the previous version is kept alongside
  it as `config.json.bak`.
- **Autosave slots** -- `autosave-0.json.gz` / `autosave-1.json.gz`
  in the same directory: a gzipped, double-buffered snapshot of
  the live edited state, written debounced while editing so a hard
  power cut resumes the last edit, not just the last Save.
- **Rolling backups** -- `backups/backup-NNNNN.json.gz` (+ an
  `index.json`): a compressed checkpoint dropped on every Save,
  last 50 kept, restorable from Settings -> Backup.

The runtime copy is the one the routing service reads and writes
during operation. **On boot the unit prefers the newest valid
autosave**, falling back to the persistent `config.json` (then
`.bak`, then defaults). **Save Config** writes the runtime copy
*and* copies it to the persistent location (chapter 4.7 describes
the crash-safe save flow). The autosave + backup mechanism is
covered in chapters 15.6 and 18.3.

Storing the persistent copy on the boot partition rather than the
main root is deliberate. Both filesystems are mounted **read-only**
in steady state (chapter 18.1); Save Config briefly remounts
`/boot/firmware` rw, writes via `mv` (atomic on FAT32 when source
and destination share a directory), syncs, and remounts it ro.
The window is milliseconds and self-contained; the main root is
never remounted. Putting the persistent copy on the boot partition
keeps the rw remount confined to a small filesystem with no service
state on it.

## The Top-Level Schema

The exported / saved JSON has the following top-level keys:

| Key | Type | Meaning |
|-----|------|---------|
| `version` | int | Schema version. Currently `1`. |
| `mode` | string | `"all-to-all"` -- routing mode. |
| `default_routing` | string | `"none"` (default) -- new devices arrive disconnected; `"all"` -- auto-connect every new device to every other. |
| `connections` | list | Every saved connection in the matrix. |
| `disconnected` | list | Connections explicitly toggled off but kept for re-enable. |
| `wifi` | object | WiFi configuration; see 5.4. |
| `network_midi` | object | Network MIDI (RTP-MIDI) sharing; see the *Network MIDI Configuration* section below. |
| `midi2` | object | MIDI 2.0 behaviour. Currently one key: `force_midi1`, a list of device stable-IDs the hub treats as MIDI 1.0 even when they advertise MIDI 2.0 — the escape hatch for devices that misbehave under the new protocol. Empty by default. |

Plugin instances, controller instances, device renames, port
renames, and per-cell filter/mapping state all live inside the
`connections` and supporting structures within this top-level
schema. The runtime serialisation handles the per-instance
parameter state as part of the matrix payload.

## Connections

Each entry in the `connections` list describes one matrix cell:

- The source -- ALSA client/port identifier or virtual-device
  reference (plugin instance ID, controller instance ID, BLE
  peripheral ID).
- The destination -- same form.
- The filter object: channel mask, message-type mask.
- The mappings list: zero or more mappings (Note → CC, Note →
  CC toggle, CC → CC, Channel Remap).
- The enable flag (toggling a connection off keeps the entry;
  removing it deletes the entry entirely).

The exact field names are an implementation detail; the JSON
emitted by **Export Config** is the authoritative schema if you
need to inspect it.

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

The `mode` field reflects the *current* mode (live state); the
`wifi_mode_pref` field is the user's *preference* set in
**Settings**. The service reconciles preference to mode as
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

Like `wifi`, this is an appliance setting: changes apply
immediately and are saved on the spot, outside the dirty-state
model. Devices mirrored *from* a peer hub get stable IDs with the
`net-` prefix (see chapter 21, "Device identity").

## Plugin Instances

Plugin instances are serialised as part of the project state.
Each instance carries:

- A unique instance ID (stable across save/load).
- The plugin type name (e.g. `"arpeggiator"`).
- An optional rename.
- A `params` dict mapping parameter names to current values.
- For plugins with sub-structured state (the Tracker's grid, the
  Velocity Curve's curve data, captured drop-button snapshots),
  the structured payload alongside `params`.

Cloning an instance from the **plugin clipboard** copies this
entire serialisation; the duplicate gets a fresh instance ID and
the rest unchanged.

## Controller Instances

Controller instances follow the same shape as plugin instances
and serialise the same way. The controller-specific payload adds:

- Per-cell rename, CC, channel, On/Off values, learned MIDI
  source.
- Per-axis configuration for XY pads (spring force, home).
- Drop-button captured snapshots (one per slot).
- Theme choice (`"default"`, `"navy"`, `"forest"`, ...).

## Device Topology and Renames

USB devices are identified by their **USB serial number** when the
hardware provides a usable one (`usb-<vid>:<pid>-<serial>`), and by
*USB topology* (the path through the hub tree to a given port,
`usb-<path>-<vid>:<pid>`) otherwise. Factory placeholder "serials"
(all zeros and the like) are treated as absent. The practical
consequences:

- A device with a real serial number keeps its custom name and
  saved connections on *any* port -- replug it wherever you like.
- A device without one is re-recognised when replugged into a
  different port as long as it is the only one of its model: the
  hub matches it by vendor/product ID, unambiguously, and carries
  its state over. The migrated identity is written on the next
  **Save Config**.
- Two identical serial-less devices plugged in at the same time
  are kept distinct by port -- they will not share state by
  accident, and the hub deliberately never *guesses* between them.
- Re-recognition never rewrites configs, backups, or exports by
  itself; old saved IDs keep loading and resolve live against the
  connected hardware.

Multi-port devices (an interface with multiple MIDI ports) have
each port identified by topology + port number; per-port renames
are persisted.

## What Is *Not* in the Project State

- **BlueZ bonds** -- live in their own snapshot path on
  `/boot/firmware/raspimidihub/bluetooth-state.tar` (chapter
  14.3). Not part of `config.json`; not included in **Export
  Config**.
- **Logs** -- ephemeral, on tmpfs at `/var/log/`.
- **The deb cache** -- on the boot partition under
  `/boot/firmware/raspimidihub/debs/` (or similar), not in
  `config.json`.
- **System-level OS settings** (timezone, locale, the OS kernel
  parameters) -- managed outside RaspiMIDIHub.
- **Browser-side display preferences** (MIDI activity bar
  visibility, knob tick sounds) -- stored as per-browser
  preferences, not on the Pi.

## Legacy Keys

The loader uses `_deep_merge(DEFAULT_CONFIG, on_disk_data)` so
that a config saved by an older release missing keys still loads
cleanly -- missing keys take their default values from
`DEFAULT_CONFIG`.

An explicit drop list handles keys that newer releases have
*removed* -- the loader strips them silently. The current drop
list contains `presets`, which was a previous-generation feature
replaced by the Save / Load / Export / Import flow described in
chapter 15.

## Schema Evolution and Major Versions

The `version` field starts at `1`. Patch releases of RaspiMIDIHub
do not change it. A future major version that breaks the schema
will bump it; the import validator (chapter 15.5) refuses
incompatible major versions outright rather than half-loading a
config it cannot fully interpret.

