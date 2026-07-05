# Filters and Mappings

Tap a connected (lit) cell and pick **Edit** to open the filter and
mappings panel for that connection. Per-mapping parameter tables
live in **Appendix C**.

## The Panel Layout

The panel slides up from the bottom, with three sections top to
bottom: **MIDI Channels** (the 16-channel grid), **Message Types**
(the toggles), and **Mappings** (the active list plus **+ Add
Mapping**). Dismiss with any of the four standard overlay gestures
(chapter 8.17).

![The filter panel: channel toggles, message-type toggles, and the list of active mappings.](../screenshots/05-filter-panel.png){width=42%}

## Channel Filtering

A 4×4 grid of channels 1--16, each with a red / green dot: **green**
passes, **red** silently drops that channel. Tap a channel to
toggle; tap the **MIDI Channels** heading to toggle all sixteen —
flip all, then re-enable one, to invert the mask.

Channel filtering runs *before* mappings: a **Channel Remap**
targeting channel 3 still needs channel 3 enabled here, or the
source event never reaches the mapper. Destination-channel filtering
belongs to the destination side's own filter.

## Message-Type Filtering

Toggles control which categories of MIDI events pass:

| Toggle | Default | Covers |
|--------|---------|--------|
| **Notes** | On | Note On, Note Off, polyphonic pressure |
| **CCs** | On | Control Change (incl. MIDI 2.0 atomic RPN/NRPN) |
| **PC** | On | Program Change |
| **Pitch Bend** | On | Pitch Bend |
| **Aftertouch** | On | Channel pressure |
| **SysEx** | On | System Exclusive |
| **Clock** | On | MIDI Clock, Start, Stop, Continue, Song Position |
| **MIDI 2.0** | On | MIDI 2.0-only per-note messages (Per-Note CC / Pitch Bend / Management) — only ever carried between MIDI 2.0 devices |

Toggles apply instantly; there is no per-cell Save. **Save Config**
on the routing matrix persists filter state, and the dirty-state
asterisk fires as soon as a toggle flips.

**MIDI 2.0 resolution.** On a capable hub (chapter 21), a filtered
or mapped connection between two MIDI 2.0 devices carries full
32-bit resolution end to end; MIDI 1.0 devices see exactly the
values they always did. Mapping value fields accept fractionals like
`63.5` — rounded for MIDI 1.0 destinations.

## Mappings

Mappings transform individual events passing through the connection:
a **source** (channel + note or CC) becomes a **destination**
(channel + CC, with optional value scaling). Multiple mappings apply
in declaration order.

**Tap** a mapping row to edit; **long-press** (right-click on
desktop) for the Edit / Copy / Remove submenu. **+ Add Mapping**
adds one; **+ Paste Mapping** appears next to it when the clipboard
holds a mapping.

## The Mapping Types

One form serves every type; the type radio at the top switches the
visible fields.

### Note → CC

Each Note On sends the CC at the **On value**, each Note Off at the
**Off value** — a footswitch that sends notes drives CC 64
(sustain). The **Src Note** wheel's **Any** position at the top
triggers on every incoming note, not just one pitch.

**Value Source**: **Fixed** (default) sends the literal On value;
**Velocity** sends the live key velocity (0--127), the Off value
still sent on release for a defined idle state. Velocity plus
**Any** turns the whole keyboard into a velocity-to-CC pedal.

Fields: source channel, note number (or Any), output channel, CC#,
value source (Fixed / Velocity), on value (Fixed only), off value.

### Note → CC (toggle)

Each Note On alternates between **Toggle A** and **Toggle B**; Note
Off does nothing — a momentary button becomes a latching mute
(127, 0, 127, ...).

Fields: source channel, note number, output channel, CC#, toggle A,
toggle B.

### Note → Note

Notes pass through with the note number rewritten and the channel
remapped; velocity unchanged. Eight pads sharing one channel become
eight per-voice triggers on a sampler that wants the same note on a
different channel per voice — one mapping per pad; two mappings with
the same source but different destination channels layer one pad
onto two voices. **Any** folds every note on the source channel onto
one destination note — trigger a sample slot from any key.

Fields: source channel, source note (or Any), destination channel,
destination note.

### CC → CC

Each source CC produces a destination CC, with optional number remap
and range scaling — a knob sending CC 16 at 0--127 feeds a synth
expecting CC 1 at 0--63. Swap **Out Min** and **Out Max** to invert
the range.

Fields: source channel, source CC#, output channel, output CC#,
In Min / In Max, Out Min / Out Max.

![Note → CC mapping form.](../screenshots/07-mapping-note-to-cc.png){width=42%}

![CC → CC mapping form with range scaling.](../screenshots/08-mapping-cc-to-cc.png){width=42%}

### Channel Remap

Every event on the source channel is forwarded to the destination
channel(s), regardless of message type. Fan-out: one source to
several destinations in a single mapping — a keyboard on channel 1
layered onto channels 5, 6 and 7.

Fields: source channel, destination channels (multi-select).

## MIDI Learn

Every source field has a **Learn** button. Tap it, then play a note
or move a knob; the first recognised event fills the source fields
and a pulsing border confirms. Learn times out after ten seconds
if nothing arrives. It works when creating and when editing
— follow a changed hardware channel or CC# without retyping.

## Pass Through the Original Event

Each mapping's **Pass through original event** toggle, on, forwards
the source event *alongside* the mapped output; off, only the mapped
output is sent — augment instead of replace, e.g. the original note
plus a sustain CC on every key press.

## Toggling a Connection Without Losing Filters

**Remove** on a connected cell disables the connection but keeps its
filter and mappings; re-enabling the cell (Add connection, or a cell
paste) restores them exactly — safe to "mute" a connection during a
performance.

## Clipboards Revisited

From chapter 9: cell-menu **Copy** takes the whole filter + mappings
set; mapping-row **Copy** takes one mapping; **+ Paste Mapping**
pastes it, bumping a duplicate CC onto the next free slot. The
plugin clipboard lives at the row/column header level (chapter 9.6).
