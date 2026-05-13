# The Routing Matrix

The **Routing** tab is the central screen of RaspiMIDIHub. Every USB
MIDI device, every Bluetooth MIDI peripheral, every plugin instance,
and every controller instance appears here as a row, a column, or
both. Every potential connection between them is one cell in the
grid. This chapter is the complete reference for the matrix screen.

![The Routing matrix. Rows are sources, columns are destinations, cells are connections. The bottom-nav Routing icon carries the dirty-state asterisk.](../screenshots/01-routing.png){width=42%}

## Reading the Grid

Rows are **sources** (FROM). Columns are **destinations** (TO).
Headers along the top show the columns; headers along the left show
the rows. The intersection cell of a source row and a destination
column represents that one connection.

Cells are in one of four visual states:

| Appearance | Meaning |
|------------|---------|
| Empty (unlit) | No connection between this source and destination |
| Lit (red) | Connection active, no filter or mapping applied |
| Lit (purple) | Connection active, with an active filter or mapping |
| Dimmed | Connection saved but at least one side is offline |

A live **rate meter** ticks on every cell with traffic, showing
MIDI message throughput. The clock indicator (a pulsing play icon
next to a row header) marks devices currently sending MIDI Clock;
when more than one device sends clock the icon turns orange to
warn of a typical misconfiguration.

The diagonal -- a device's own row meeting its own column -- is
always blocked. Self-connections would feed a device into itself
and the loop-prevention logic disallows them.

## The Cell Context Menu

Tapping a cell opens its context menu. The entries depend on the
cell state:

**Empty cell.**

- **Add connection** -- enables the connection with the default
  empty filter (all channels, all message types pass).
- **Paste** -- pastes the cell clipboard contents (filter +
  mappings) and enables the connection. Visible only when the
  clipboard holds a cell payload.

**Connected cell.**

- **Edit** -- opens the filter and mappings panel (chapter 10).
- **Copy** -- copies the filter + mappings to the cell clipboard.
- **Paste** -- overwrites the cell's filter + mappings from the
  clipboard, keeping the connection enabled.
- **Remove** -- disables the connection. The filter and mappings
  are *not* discarded; re-enabling the cell restores them.

## Row and Column Header Menus

Tapping a row or column header opens a menu of device-level actions:

- **Edit** -- opens the device-detail panel. For USB devices, this
  is the rename + MIDI monitor + test-sender panel. For plugins,
  it is the plugin-config panel.
- **Copy / Paste** (controllers, plugins) -- copies the whole
  instance. Paste creates a new instance with all parameters
  cloned.
- **Reconnect / Disconnect / Forget** (Bluetooth devices) --
  chapter 14.
- **Rename** -- inline edit of the displayed name. The original
  ALSA name remains shown in grey alongside.

## Adding and Renaming Devices

USB devices appear as soon as they are plugged in. Custom names are
remembered by USB topology (the path through the hub tree), so
unplugging and re-plugging the same device into the same port
restores its name. Plugging it into a *different* port shows it
with its original ALSA name -- the rename does not follow the
device, it follows the port.

Multi-port devices (some interfaces expose multiple MIDI ports per
USB connection) appear as one row and one column *per port*.
Individual ports can be renamed; the **Octatrack** DIN output, for
example, can be named explicitly instead of appearing as
`<Device> Port 2`.

## Offline Devices

When a saved device is unplugged, it does not disappear from the
matrix. Its row and column stay visible, dimmed, with any saved
connections still shown as toggleable cells. This means you can
build up routing in advance and only physically connect the gear
when you are ready, or recover from a cable getting kicked out
without losing the routing state.

The dimmed cells can still be toggled on or off; the changes apply
the moment the device is plugged back in. Offline cells in the
purple state (filtered / mapped) keep their filter and mapping
state through the offline period.

## The Clipboard

The matrix supports three clipboards, each with its own scope:

| Clipboard | Holds | Pasted by |
|-----------|-------|-----------|
| **Cell clipboard** | One cell's filter + mappings | Pasting onto any cell |
| **Plugin clipboard** | One plugin instance with all parameters | Pasting from a plugin's header menu |
| **Mapping clipboard** | One mapping (Note → CC, CC → CC, ...) | Pasting from the **+ Paste Mapping** button in the filter panel |

The cell clipboard and the mapping clipboard interact with their
own paste-conflict resolution:

- **Cell paste** overwrites the destination cell's filter and
  mappings wholesale.
- **Mapping paste-with-bump** auto-resolves duplicate CC conflicts
  by bumping the pasted mapping onto the next free slot.

The plugin clipboard duplicates the *instance*: a Mixer 8 with all
its renamed cells, learned CCs, drop-button captures, and theme
choices can be cloned for a second venue by Copy on the original,
Paste on the matrix, and renaming the duplicate.

## The Add Menu

The **Add** button at the bottom of the matrix opens an overlay
with four sections, each grouping addable instances by what they
do:

1. **Plugins** -- routing-graph plugins that consume / transform /
   produce MIDI events: Arpeggiator, CC LFO, CC Smoother, Chord
   Generator, Clock Divider, Hold, Master Clock, MIDI Delay, Note
   Splitter, Note Transpose, Panic Button, Scale Remapper, SysEx
   Sender, Velocity Curve, Velocity Equalizer (chapter 11). Tapping
   an entry creates a new instance and adds it to the matrix.
2. **Controllers** -- the four play-surface templates (Mixer 8,
   FX 6, Performance 16, XY 4) that live on the **Controller** tab.
   See chapter 12.
3. **Play** -- step-sequencer surfaces that live on the **Play**
   tab. The Tracker (chapter 13) is the only built-in entry today.
4. **Bluetooth MIDI** -- a Scan button and a list of paired
   peripherals. See chapter 14 for the pairing flow.

User-supplied plugins discovered at startup appear in the
appropriate section based on their declared surface kind.

## The Bottom Bar -- Save, Load, Export, Import

Four buttons run across the bottom of the matrix:

- **Save Config** -- persists the current in-memory state to disk
  as the boot default. Clears the dirty-state asterisk.
- **Load Config** -- reloads the last saved state. Plugin instances
  that exist only in memory (unsaved) are stopped and discarded.
- **Export Config** -- downloads the current state as a JSON file.
  Useful for backing up before a risky experiment.
- **Import Config** -- uploads a JSON file and replaces the current
  state. The import is validated before commit; a partial / corrupt
  file is rejected with an error.

**Save Config** is the most-used button in the UI. The dirty-state
asterisk on the bottom-nav **Routing** icon is the persistent
reminder to use it.

## The Dirty-State Asterisk

A dark-red `*` next to the **Routing** icon in the bottom navigation
lights up whenever any of the following diverges from the saved
config:

- A connection added or removed
- A filter or mapping edited
- A plugin instance added, removed, or its parameters changed
- A controller instance added, removed, or its cells edited
- A device renamed
- A port renamed

The asterisk is *only* about persistence. The unit runs perfectly
fine with unsaved state; the next reboot is the only thing that
loses it.

## The Direct-Path vs Filter-Path Distinction

Connections without a filter and without mappings are wired
directly in the ALSA kernel sequencer -- effectively zero added
latency, no userspace involvement after setup. Connections with any
filter or mapping go through the userspace filter/mapper, adding
roughly 1--3 ms. Most of the time this distinction does not matter
in practice, but it is the reason the matrix differentiates red
(direct) from purple (filtered/mapped) cells: the colour also
hints at the latency profile.

See chapter 4 for the architectural details.

