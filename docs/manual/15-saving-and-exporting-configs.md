# Saving, Loading, and Exporting Configurations

Four bottom-bar buttons on the routing matrix manage the project
state: **Save Config**, **Load Config**, **Export Config**, and
**Import Config**. There is no "Presets" tab — the boot config is
*one* state; **Export Config** JSON files hold additional
snapshots and move state between units.

## The Two States

- **In-memory state** — what is currently running, including every
  edit since the last load.
- **Boot config** — on disk at
  `/boot/firmware/raspimidihub/config.json`; what loads on next
  boot.

The dark-red asterisk on the **Routing** bottom-nav icon (chapter
6.4) shows whenever the two diverge.

## Save Config

Tap **Save Config**. The in-memory state is written to the boot
config (chapter 4.7) and the asterisk clears. The button shows
**Saving…** until the write has completed, then **Configuration
saved**; a failed write is reported, never claimed as success. The
save does not disturb live MIDI — safe mid-set.

Save writes the *entire* project state (chapter 15.7) and drops a
**rolling backup checkpoint** — a compressed copy tagged with a
short change summary ("+1 instrument · −18 mappings"); the last 50
can be restored or downloaded from **Settings → Backup**
(chapter 16). Separate from the automatic **autosave** below.

## Load Config

Tap **Load Config**. The in-memory state is replaced with the
**boot config** — the last deliberate Save, *not* the autosave.
Unsaved edits are discarded; memory-only plugin instances are
stopped. Load is the "undo my unsaved edits" button: it throws away
the work-in-progress the autosave has been keeping. The loaded
state is autosaved immediately, making it the next resume point.

## Export Config

Tap **Export Config**. The in-memory state — including unsaved
edits — downloads as `raspimidihub-config.json`. Use it to back up
before a risky experiment, share a setup with another RaspiMIDIHub
owner, archive a finished rig, or snapshot mid-session. The JSON is
human-readable; diffing two exports shows exactly what changed.

## Import Config

Tap **Import Config** and pick an exported JSON file. The in-memory
state is replaced: plugin and controller instances stopped and
recreated, connections re-established, device and port renames
applied.

The asterisk lights — the boot config is still the previous one;
tap **Save Config** to make the import the boot default. The
imported state is autosaved immediately, so it survives a power cut
even before you Save. The file is validated first: a malformed file
or one from an incompatible major version is rejected with an error
and the running state is untouched.

## Autosave and Resume

The unit continuously **autosaves the live edited state** in the
background, so a hard power cut resumes the last thing you were
doing — not just the last Save. On boot it prefers the newest valid
autosave, falling back to `config.json` (then its `.bak`, then
defaults).

- No need to Save before pulling the power — the autosave has your
  edits. Save still sets the *committed* checkpoint that **Load
  Config** reverts to, and drops a backup checkpoint.
- The autosave is **debounced**: a few seconds after edits settle,
  and on clean shutdown / reboot.
- Purely *performing* does not autosave. Launching Tracker patterns
  or tapping pattern slots changes no saveable content — no
  autosave, no asterisk; the active pattern is still written by a
  deliberate **Save**.
- After **Load**, a backup **Restore** (chapter 16), or **Import**,
  the new state is autosaved at once, making it the resume point.

The autosave is double-buffered and integrity-checked, so a cut
mid-write never leaves the unit without a good snapshot to resume
from (chapter 18.3).

## What the State Contains

Everything that affects how the unit *runs*:

- Every connection in the matrix (cell state, enabled / disabled)
- Every per-cell filter (channel mask, message-type mask)
- Every per-cell mapping (Note → CC, Note → CC toggle, CC → CC,
  Channel Remap)
- Every plugin instance and its full parameter state
- Every controller instance, cell rename, learned CC, captured
  drop-button snapshot, and the chosen theme
- The Tracker's grid contents, page count, per-track channels, and
  cursor position (the Tracker is a plugin)
- The 8-slot pattern bank on every play-surface plugin (Tracker,
  Arpeggiator, Euclidean, Cartesian), including the active slot and
  per-slot trigger notes
- Every device rename and port rename
- The default routing for new devices (Connect all / None)
- The WiFi configuration: AP SSID and password, home WiFi
  credentials, WiFi mode preference

## What the State Does Not Contain

- **BlueZ bonds** — stored separately on `/boot/firmware/`
  (chapter 14.3); an import does not overwrite paired devices.
- **System logs and the deb cache** — ephemeral.
- **Display preferences** (activity bar, tick sounds, scroll-assist
  buttons, layout density) — per-browser.
- **Per-tab last-viewed sub-state** (which play surface or
  controller instance each tab left open) — also browser-local.

Importing on another unit moves routing and plugin state across;
the second unit keeps its own WiFi credentials, Bluetooth bonds,
and browser-side preferences.

::: warning
WiFi credentials *are* part of the exported state. Before sharing a
config, edit the WiFi section out of the JSON, or change the AP
password on the receiving unit after import.
:::

## The Save / Load / Export / Import Map

| Action | Source | Destination | When to use |
|--------|--------|-------------|-------------|
| **Save Config** | In-memory | Boot config (disk) | Commit current state as next-boot default |
| **Load Config** | Boot config (disk) | In-memory | Discard unsaved edits |
| **Export Config** | In-memory | JSON file (browser download) | Back up / share / archive |
| **Import Config** | JSON file (browser upload) | In-memory | Restore / receive |

**Export Config** before experimenting, **Import Config** to
restore if the experiment goes sideways — the closest the appliance
has to "undo" for routing state.

## Practical Patterns

- **Per-gig backup.** Export before each gig; a hurried re-image
  is one file away from the gig setup.
- **Per-song archive.** Export after each song's routing is final.
- **Per-rig handoff.** Export → email → import; the receiving unit
  runs the sender's rig in seconds.
- **The "scratch" snapshot.** Save, Export, then experiment freely.
  **Load Config** to undo, or **Import Config** the snapshot if
  Load alone is not enough.
