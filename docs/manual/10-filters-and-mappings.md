# Filters and Mappings

Tapping a connected (lit) cell and picking **Edit** from the menu
opens the filter and mappings panel for that connection. This
chapter is the complete reference for the panel and for the four
mapping types it hosts. Per-mapping parameter tables live in
**Appendix C**; this chapter is the *behaviour* reference.

## The Panel Layout

The filter panel slides up from the bottom of the screen. It has
three sections, top to bottom:

1. **MIDI Channels** -- the 16-channel grid.
2. **Message Types** -- the seven message-type toggles.
3. **Mappings** -- the list of active mappings, plus the
   **+ Add Mapping** button.

Dismiss the panel with any of the four standard overlay dismiss
gestures (chapter 8.17): swipe down, tap the dark overlay, press
`ESC`, or tap the `X` button.

![The filter panel: 16 channel toggles, seven message-type toggles, and a list of active mappings.](../screenshots/05-filter-panel.png){width=42%}

## Channel Filtering

The MIDI Channels section is a 4×4 grid of channels 1--16. Each
channel has a red / green traffic-light dot:

- **Green** -- channel passes.
- **Red** -- channel blocked. Messages on this channel are dropped
  silently.

Tap a channel to toggle. Tap the **MIDI Channels** heading to
toggle every channel at once (useful for inverting the mask: tap
the heading to flip everything, then tap the one channel you
*want* through).

Channel filtering happens *before* mappings see the event. A
**Channel Remap** mapping that targets channel 3 still requires
channel 3 to be enabled in the filter -- otherwise the source event
never reaches the mapper. (Filtering on the *destination* channel
is the **destination** side's filter, not this one.)

## Message-Type Filtering

A row of seven toggles controls which categories of MIDI events
pass through the connection:

| Toggle | Default | Covers |
|--------|---------|--------|
| **Notes** | On | Note On, Note Off |
| **CCs** | On | Control Change |
| **PC** | On | Program Change |
| **Pitch Bend** | On | Pitch Bend |
| **Aftertouch** | On | Channel pressure and polyphonic pressure |
| **SysEx** | On | System Exclusive |
| **Clock** | On | MIDI Clock, Start, Stop, Continue, Song Position |

Toggles apply instantly. There is no "Save" button for the per-cell
filter state -- changes take effect the moment the toggle flips.
The **Save Config** at the bottom of the routing matrix persists
the filter state across reboots; the dirty-state asterisk fires as
soon as a toggle flips.

## Mappings

Mappings transform individual events as they pass through the
connection. A mapping has a **source** (a channel + note or CC) and
a **destination** (a channel + CC, with optional value scaling).
Multiple mappings can be active on the same connection; they are
applied in declaration order.

The mappings list shows each mapping as a tappable row:

- **Tap** -- open the mapping form for editing.
- **Long-press** (or right-click on desktop) -- open the
  Edit / Copy / Remove submenu.

**+ Add Mapping** at the bottom adds a new mapping. When the
clipboard holds a mapping, a **+ Paste Mapping** button appears
next to it.

## The Mapping Types

The mapping form is the same form for every type; the type radio
at the top toggles which fields are visible.

### Note → CC

Each Note On on the source produces one CC event at the
**On value**, and each Note Off produces a CC event at the
**Off value**. Use case: a footswitch sends notes; you want it to
send CC 64 (sustain) instead.

The **Src Note** wheel has an **Any** position at the top: pick
it and every incoming note triggers the mapping, not just one
specific pitch.

The **Value Source** selector chooses how the On value is
computed. With **Fixed** the literal On value is sent on every
Note On (the default, useful for switch-style controllers). With
**Velocity** the live key velocity (0--127) is sent as the CC
value, giving you continuous expression from a velocity-sensitive
key -- the **Off value** is still sent on key release so the CC
has a defined idle state. Combined with **Src Note = Any** this
turns the whole keyboard into a one-shot velocity-to-CC pedal.

Fields: source channel, note number (or Any), output channel,
CC#, value source (Fixed / Velocity), on value (Fixed only),
off value.

### Note → CC (toggle)

Each Note On alternates between two CC values, **Toggle A** and
**Toggle B**. Note Off does nothing. Use case: a momentary button
on a hardware controller behaves like a latching mute -- first
press sends CC value 127 (muted), second press sends CC value 0
(unmuted), third press goes back to 127.

Fields: source channel, note number, output channel, CC#, toggle
A, toggle B.

### Note → Note

Each Note On / Note Off on the source produces the same kind of
event on the destination, with the note number rewritten and the
channel routed to a different MIDI channel. Velocity is passed
through unchanged.

Use case: a pad controller has eight pads, all on the same MIDI
channel, each emitting a different note number. The receiving
sampler expects every voice to be triggered with the same note
(typically C-3 = note 60) but on a different channel per voice.
Add one Note → Note mapping per pad: source channel + pad's note
→ destination channel for that voice + note 60. Eight pads become
eight per-voice triggers without leaving the original controller
or the sampler.

Fan-out works the same way as on the other types: two Note → Note
mappings with the same source but different destination channels
layer one pad onto two voices.

The **Src Note** wheel also exposes an **Any** position at the top.
When selected, every incoming note on the source channel is folded
onto the same destination note. Handy for triggering a single
sample slot from any key on the keyboard, or for collapsing a
multi-pad drum controller down to a single trigger lane.

Fields: source channel, source note (or Any), destination channel,
destination note.

### CC → CC

Each CC on the source produces a CC on the destination, with
optional number remap and range scaling. Use case: a knob sends
CC 16 with a 0--127 range, but the destination synth expects CC 1
with a 0--63 range; map CC 16 → CC 1 and 0..127 → 0..63.

Range inversion: swap the **Out Min** and **Out Max** values --
the source's high end maps to the destination's low end.

Fields: source channel, source CC#, output channel, output CC#,
In Min / In Max, Out Min / Out Max.

![Note → CC mapping form.](../screenshots/07-mapping-note-to-cc.png){width=42%}

![CC → CC mapping form with range scaling.](../screenshots/08-mapping-cc-to-cc.png){width=42%}

### Channel Remap

Every event on the source channel is forwarded to a different
destination channel, regardless of message type. Fan-out is
supported: one source channel can be routed to multiple
destination channels in one mapping (the same event lands on each
of the listed destinations).

Use case: the controller keyboard sends on channel 1, but the
target synth listens on channels 5, 6, and 7 for layered sound.
One Channel Remap mapping fans out 1 → 5, 6, 7.

Fields: source channel, destination channels (multi-select).

## MIDI Learn

Every mapping field that takes a *source* (the source channel +
note for Note mappings, the source channel + CC for CC mappings)
has a **Learn** button next to it. Tap Learn, then play a note or
move a knob on the hardware. The first recognised event fills in
the source fields.

The Learn timeout is around five seconds; if nothing is captured
within that window, the button reverts on its own. A pulsing
border on the field confirms which value just captured.

Learn is available both when creating a new mapping and when
editing an existing one -- handy when a hardware control's
channel or CC# changes and an existing mapping needs to follow
without retyping all the other fields.

## Pass Through the Original Event

Every mapping has a **Pass through original event** toggle. When
on, the source event is forwarded *in addition to* the mapped
output. When off, only the mapped output is sent.

Pass-through is the most common edit when a mapping should
*augment* rather than *replace* a signal -- for example, sending
both the original note and a sustain CC on every key press.

## Toggling a Connection Without Losing Filters

Tapping a connected cell and picking **Remove** disables the
connection but does not delete its filter or mappings. Re-enabling
the cell later (Add connection on the same cell, or paste from the
cell clipboard) brings the configuration back exactly as it was.

This makes it safe to "mute" a connection during a performance
without redoing the filter setup.

## Clipboards Revisited

From chapter 9: the filter panel exposes the **cell** and the
**mapping** clipboards.

- **Copy** at the cell-menu level copies the whole filter +
  mappings set.
- **Copy** at the mapping row level copies one mapping.
- **+ Paste Mapping** in the filter panel pastes the single
  mapping with conflict-bumping on duplicate CCs.

The plugin clipboard lives at the row/column header level and is
documented in chapter 9.6.

