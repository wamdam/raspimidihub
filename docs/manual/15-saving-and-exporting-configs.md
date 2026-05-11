# Saving, Loading, and Exporting Configurations

The routing matrix has four bottom-bar buttons that manage the
project state: **Save Config**, **Load Config**, **Export Config**,
and **Import Config**. This chapter is the full reference for each.

There is no separate "Presets" tab. The boot config (managed by
**Save Config**) is *one* state; JSON files captured with **Export
Config** are how you keep additional snapshots, share state between
units, or move state between machines.

## The Two States

At any moment, RaspiMIDIHub keeps two versions of the project state
in mind:

- **In-memory state** -- what is currently running. Reflects every
  edit you have made since the last load.
- **Boot config** -- what is on disk at
  `/boot/firmware/raspimidihub/config.json`. This is what loads on
  next boot.

The dark-red asterisk on the **Routing** bottom-nav icon (chapter
6.4) shows whenever these two diverge.

## Save Config

Tap **Save Config** at the bottom of the routing matrix. The
current in-memory state is written to the boot config with an
atomic-replace + remount-rw / remount-ro cycle (chapter 4.7). The
dirty-state asterisk clears. The next reboot will start in this
state.

Save Config writes the *entire* project state. Anything in chapter
15.5 is captured.

## Load Config

Tap **Load Config** at the bottom of the routing matrix. The
in-memory state is replaced with the boot config from disk. Any
unsaved edits since the last save are discarded; plugin instances
that exist only in memory are stopped.

Load Config is the "undo my unsaved edits" button. It is the
single-button equivalent of rebooting -- except faster and without
losing the AP connection.

## Export Config

Tap **Export Config** at the bottom of the routing matrix. The
current in-memory state is downloaded to the browser as a JSON
file named `raspimidihub-config.json`.

Export captures the *current* state, including unsaved edits. The
dirty-state asterisk does not affect what Export emits; the
in-memory state is what you get.

Use Export to:

- **Back up** before a risky experiment with new routing or plugin
  combinations.
- **Share** a setup with another musician who has a RaspiMIDIHub
  unit.
- **Archive** a finished rig before reusing the unit for a
  different project.
- **Snapshot** intermediate states during a long session, the way
  some applications save "versions" of a project.

The exported JSON is human-readable and version-controlled-
friendly. Diffing two exports tells you exactly what changed
between two saved states.

## Import Config

Tap **Import Config** at the bottom of the routing matrix. A file
picker opens; pick a previously exported JSON file. The in-memory
state is replaced with the file's contents:

- Plugin instances are stopped and recreated with the imported
  parameters.
- Controller instances are recreated.
- Connections are torn down and re-established.
- Device renames and port renames are applied.

The dirty-state asterisk lights up after the import -- the unit is
now running the imported state, but the *boot config* on disk is
still the previous one. To make the imported state the boot
default, tap **Save Config**.

The import validates the JSON before commit. A malformed file or
a file from an incompatible major version is rejected with an
explanatory error; the running state is left untouched.

## What the State Contains

The exported / saved state covers everything that affects how the
unit *runs*:

- Every connection in the matrix (cell state, enabled / disabled)
- Every per-cell filter (channel mask, message-type mask)
- Every per-cell mapping (Note → CC, Note → CC toggle, CC → CC,
  Channel Remap)
- Every plugin instance and its full parameter state
- Every controller instance, every cell rename, every learned CC,
  every captured drop-button snapshot, the chosen theme
- The Tracker's grid contents, page count, per-track channels, and
  cursor position (the Tracker is a plugin)
- Every device rename and every port rename
- The default routing for new devices (Connect all / None)
- The WiFi configuration: AP SSID and password, home WiFi
  credentials, and the WiFi mode preference

## What the State Does Not Contain

Some state is deliberately *not* part of the project config:

- **BlueZ bonds** -- live in their own snapshot path on
  `/boot/firmware/` (chapter 14.3). An import does not overwrite
  paired devices.
- **System logs and the deb cache** -- ephemeral.
- **Display preferences** (MIDI activity bar visibility, tick
  sounds) -- stored separately as per-browser preferences.

Exporting a config from one RaspiMIDIHub unit and importing it on
another moves the routing and plugin state across, but the second
unit keeps its own WiFi credentials, its own Bluetooth bonds, and
its own browser-side preferences.

::: warning
WiFi credentials *are* part of the exported state. If you intend
to share a config with someone, edit the WiFi section out of the
JSON first, or change the AP password on the receiving unit after
import.
:::

## The Save / Load / Export / Import Map

| Action | Source | Destination | When to use |
|--------|--------|-------------|-------------|
| **Save Config** | In-memory | Boot config (disk) | Commit current state as next-boot default |
| **Load Config** | Boot config (disk) | In-memory | Discard unsaved edits |
| **Export Config** | In-memory | JSON file (browser download) | Back up / share / archive |
| **Import Config** | JSON file (browser upload) | In-memory | Restore / receive |

A round-trip pattern in heavy use: **Export Config** before
experimenting, **Import Config** to restore if the experiment goes
sideways. This is the closest the appliance has to "undo" for
routing state.

## Practical Patterns

- **Per-gig backup.** Export the config before each gig. If the
  unit needs to be re-imaged in a hurry, the gig setup is one
  file away.
- **Per-song archive.** Export the config after each song's
  routing is finalised. The exports form a labelled archive that
  outlives any single setup.
- **Per-rig handoff.** Export → email → import. The receiving
  unit runs the sender's rig in seconds.
- **The "scratch" snapshot.** Save the current routing, Export it,
  then experiment freely. Tap **Load Config** to undo or **Import
  Config** of the snapshot if Load alone is not enough.

