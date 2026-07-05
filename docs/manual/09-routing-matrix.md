# The Routing Matrix

The **Routing** tab is where every USB device, Bluetooth peripheral,
plugin and controller instance appears and every connection is made.
The **Matrix / Rack** toggle at the top switches two views of the
same routing: **Matrix** — a grid, rows sources, columns
destinations, cells connections — for overview; **Rack** — 19" rack
units with cables between IN/OUT jacks — for signal flow and touch.
Both share all connections, filters, mappings, clipboards, menus and
the bottom bar; the view choice is a per-browser preference, not
saved config.

![The Routing matrix. Rows are sources, columns are destinations, cells are connections. The bottom-nav Routing icon carries the dirty-state asterisk.](../screenshots/01-routing.png){width=42%}

## Reading the Grid

Cell states:

| Appearance | Meaning |
|------------|---------|
| Empty (unlit) | No connection between this source and destination |
| Lit (red) | Connection active, no filter or mapping applied |
| Lit (purple) | Connection active, with an active filter or mapping |
| Dimmed | Connection saved but at least one side is offline |

A live **rate meter** ticks on cells with traffic. A pulsing play
icon by a row header marks a device sending MIDI Clock — orange when
more than one does, a typical misconfiguration. The diagonal
(self-connection) is blocked.

Long header names middle-truncate
(`Velocity Equalizer 1 → Velo…ar 1`); the full name shows atop the
header menu. Header tint: teal plugins, blue Bluetooth, violet plus
a link icon for Network-MIDI mirrors.

**MIDI 2.0 devices.** On a MIDI 2.0-capable kernel (chapter 21), a
device's *function blocks* — its declared sections, e.g. "Keys" and
"Pads" — are its port rows (one for a single-block device); routing,
filters, mappings and replug identity work as for any port. Without
kernel support the device is plain MIDI 1.0. A **2.0 badge** by the
name (matrix and rack) marks a capable device; struck through means
forced to MIDI 1.0 via the device-detail toggle (below).

## Remote Hub Groups

Devices mirrored from a peer hub (chapter 17, *Network MIDI*) sit at
the bottom under a violet group row per hub — `@hub2 · 3 devices`.
Tap to collapse (hides that hub's rows **and columns**) or expand; a
per-browser preference. Rows show the bare device name, the
context-menu title the full `TX-7 @hub2` — twin names across hubs
stay unambiguous. An offline peer's devices act like unplugged
hardware: dimmed, intact, reconnecting automatically when the peer
returns.

## The Rack View

Each device is a rack unit: name and icon top-left, ports as rows —
**IN** jack (receive) left, **OUT** jack (send) right. Hardware
first, then plugins and controllers, then one collapsible sub-rack
per peer hub (shares the matrix's collapse state). Connections are
**cables**, one colour per source port; a **funnel badge** marks a
filtered or mapped cable. Jacks glow on MIDI activity; a
clock-sending jack gets a green ring.

**Patching.** Tap a jack, then its counterpart (either order) — the
chosen jack pulses, valid targets pulse with it. Or **drag** jack to
jack: the edges auto-scroll, the target shows an "insert here" ring,
and a second finger scrolls the rack while a cable is in hand.

**Inspecting and editing.** Hover (desktop), press-and-hold (touch)
or tap a jack to spotlight its cables: others dim, highlighted ones
fan apart; a jack with no connections dims *all* cables; the
highlight stays until you pick another jack or tap the same one
again. Tap a cable or its funnel badge for the connection menu (same
Edit / Copy / Paste / Remove as a matrix cell). Press-and-hold or
right-click a faceplate for the device menu — identical to the
header menu, renaming included. **+ Add Device** at the foot opens
the Add menu.

![The Rack view: devices as 19" rack units, patch cables hanging between their IN and OUT jacks; each cable's colour follows its source port.](../screenshots/01-routing-rack.png){width=42%}

## The Cell Context Menu

Tapping a cell opens a state-dependent menu:

**Empty cell.**

- **Add connection** — enables the connection with the default
  empty filter (everything passes).
- **Paste** — pastes the cell clipboard (filter + mappings) and
  enables the connection; shown only with a cell payload on the
  clipboard.

**Connected cell.**

- **Edit** — opens the filter and mappings panel (chapter 10).
- **Copy** — copies the filter + mappings to the cell clipboard.
- **Paste** — overwrites the cell's filter + mappings from the
  clipboard.
- **Remove** — disables the connection; filter and mappings are
  kept and restored on re-enable.

## Row and Column Header Menus

Tapping a row or column header opens device-level actions:

- **Edit** — the device-detail panel: USB devices get **rename**
  for the device and each port (the original ALSA name shows in
  grey; there is no separate Rename entry), a MIDI monitor and a
  test-sender; plugins get their config panel.
  The monitor shows MIDI 2.0 sources at real resolution —
  fractional values (`vel=100.53`, `cc74=63.99`) and 2.0-only
  messages (atomic RPN/NRPN, Per-Note CC, Per-Note Bend) as typed
  rows; MIDI 1.0 devices show whole numbers as before.
  Capable devices add a **MIDI 2.0 card** (endpoint name, product
  ID, function blocks) and a **Use MIDI 2.0** toggle — off forces
  MIDI 1.0, the escape hatch for misbehaving devices, persisting
  across replug and reboot.
  A **MIDI-CI card** appears when the device answered the hub's
  Capability Inquiry, sent automatically on connect to any
  bidirectional device (MIDI 2.0 not required — plain MIDI 1.0 and
  DIN work too): manufacturer / model / version, capability
  categories, and with Property Exchange the self-reported friendly
  name and serial number. **Identify** re-asks a device without an
  identity yet. Disable probing globally (`midi2.ci_enabled`) or
  per device (`midi2.ci_disabled`) for firmware that chokes on
  universal SysEx.
- **Copy / Paste** (controllers, plugins) — Paste creates a new
  instance with all parameters cloned.
- **Reconnect / Disconnect / Forget** (Bluetooth devices) —
  chapter 14.
- **Unmirror** (network devices) — drops the mirrored device from
  this hub's matrix; the peer's export is untouched. Re-add from
  the Add menu or Settings → Network MIDI.

## Adding and Renaming Devices

USB devices appear as soon as they are plugged in. Custom names
follow the device — a USB serial is recognised on any port, and a
serial-less device is matched by vendor/product ID while it is the
only one of its model — so name and routing survive replugging into
a different port. Only *identical serial-less* devices used side by
side stay bound to their ports (chapter 5, "Device Topology and
Renames"). Multi-port devices get one row and column per port, each
renamable — name the **Octatrack** DIN output instead of
`<Device> Port 2`.

## Offline Devices

An unplugged saved device keeps its row and column, dimmed, with
saved connections shown — build routing in advance or survive a
kicked-out cable. Dimmed cells still toggle; changes apply the
moment the device returns. Purple cells keep their filter and
mapping state while offline.

## The Clipboard

Three clipboards, each with its own scope:

| Clipboard | Holds | Pasted by |
|-----------|-------|-----------|
| **Cell clipboard** | One cell's filter + mappings | Pasting onto any cell |
| **Plugin clipboard** | One plugin instance with all parameters | Pasting from a plugin's header menu |
| **Mapping clipboard** | One mapping (Note → CC, CC → CC, ...) | Pasting from the **+ Paste Mapping** button in the filter panel |

**Cell paste** overwrites the destination's filter and mappings
wholesale; **mapping paste** bumps a duplicate CC onto the next free
slot. The plugin clipboard duplicates the whole *instance*,
including renamed cells, learned CCs, drop-button captures and
theme: Copy a configured Mixer 8, Paste, rename.

## The Add Menu

The **Add** button at the bottom of the matrix opens an overlay:

1. **Plugins** (chapter 11) — CC LFO, CC Smoother, Chord Generator,
   Clock Divider, Hold, Master Clock, MIDI Delay, Note Splitter,
   Note Transpose, Panic Button, Pitch CC, Scale Remapper, SysEx
   Sender, Velocity Curve, Velocity Equalizer; tapping an entry
   creates a new instance.
2. **Controllers** — the four play-surface templates (Mixer 8,
   FX 6, Performance 16, XY 4) on the **Controller** tab
   (chapter 12).
3. **Play** — fullscreen play surfaces on the **Play** tab:
   Tracker, Arpeggiator, Euclidean, Cartesian (chapter 13;
   parameter tables in Appendix A).
4. **Bluetooth MIDI** — Scan plus the paired-peripheral list
   (chapter 14).
5. **Network MIDI** (when enabled in Settings) — discovered,
   unmirrored RTP-MIDI sessions: peer-hub exports plus foreign
   sessions from Macs / iPads / DAWs, which never mirror
   automatically; **Add** mirrors one into the matrix (chapter 17).

User-supplied plugins appear in the section matching their declared
surface kind.

## The Bottom Bar -- Save, Load, Export, Import

- **Save Config** — persists the current state as the boot default
  and drops a rolling backup checkpoint (Settings → Backup,
  chapter 16). Clears the dirty-state asterisk.
- **Load Config** — reloads the last deliberate Save (not the
  autosave); unsaved plugin instances are stopped and discarded.
- **Export Config** — downloads the current state as JSON.
- **Import Config** — uploads a JSON file and replaces the current
  state; invalid or partial files are rejected.

## The Dirty-State Asterisk

A dark-red `*` next to the **Routing** icon lights whenever anything
diverges from the saved config:

- A connection added or removed
- A filter or mapping edited
- A plugin instance added, removed, or a saveable parameter changed
- A controller instance added, removed, or its cells renamed /
  rebound (labels, bindings, theme, drop-button settings)
- A device renamed
- A port renamed

**Performing does not light it.** Fader / knob / XY moves, Tracker
pattern launches or switches, and firing or cancelling a drop button
change no saveable content — no asterisk, no autosave; capturing a
drop snapshot *is* an edit and counts. Unsaved state runs fine —
even a hard power cut resumes your last edit from the background
autosave (chapter 15.6).

## The Direct-Path vs Filter-Path Distinction

Unfiltered connections are wired directly in the kernel sequencer —
effectively zero added latency; a filter or mapping routes the
connection through the hub, adding roughly 1--3 ms. Red = direct,
purple = filtered / mapped. See chapter 4.


Screenshots needed:

- `09-matrix-remote-hub-group.png` -- the matrix with a second
  hub's devices mirrored: the violet `@hub2` group row, one capture
  expanded, one collapsed. Needs two real hubs on one network; not
  coverable by the scripted scenes.
- `01-routing-rack.png` -- the Routing tab on the **Rack** toggle.
  Wired as the `_open_rack_view` scene in `scripts/screenshots/run.py`,
  so `make screenshots` regenerates it; the committed shot came from
  a live rig.
- `09-midi2-badge.png` -- a matrix row header with the 2.0 badge,
  plus the same device's rack faceplate. Coverable with
  `scripts/fake_midi2_synth.py` on a UMP-enabled hub (no 2.0
  hardware needed); add a scripted scene at the next regeneration.
