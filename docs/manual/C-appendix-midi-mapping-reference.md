# MIDI Mapping Reference

A flat reference for every mapping type and form parameter; the
walkthrough is in chapter 6.

Value fields are **MIDI units**: 0--127, fractional values (`63.5`)
accepted — full-resolution on MIDI 2.0 connections, rounded for
MIDI 1.0 destinations (chapter 6, *MIDI 2.0 resolution*).

## Mapping types

| Type | Source event | Output event(s) |
|------|--------------|-----------------|
| **Note → CC** | Note On / Note Off | One of two CC values |
| **Note → CC (toggle)** | Note On (alternating presses) | Two CC values, alternating each press |
| **Note → Note** | Note On / Note Off | Same event with rewritten note number and channel; velocity preserved |
| **CC → CC** | Control Change | Control Change (number / range remap, optional inversion) |
| **Channel Remap** | Any event | Same event on different channel(s); fan-out supported |

## Form parameters per mapping type

| Parameter | Range | Note → CC | Note → CC (toggle) | Note → Note | CC → CC | Channel Remap |
|-----------|-------|-----------|--------------------|-------------|---------|---------------|
| Src Ch | 1--16 or any | yes | yes | yes | yes | yes |
| Dst Ch | 1--16 | yes | yes | yes | yes | yes (multi-select) |
| Src note | 0--127 or Any | yes | yes | yes | --- | --- |
| Dst note | 0--127 | --- | --- | yes | --- | --- |
| CC# (source) | 0--127 | --- | --- | --- | yes | --- |
| CC# (output) | 0--127 | yes | yes | --- | yes | --- |
| Value Source | Fixed / Velocity | yes | --- | --- | --- | --- |
| On value | 0--127 | yes (Fixed only) | --- | --- | --- | --- |
| Off value | 0--127 | yes | --- | --- | --- | --- |
| Toggle A | 0--127 | --- | yes | --- | --- | --- |
| Toggle B | 0--127 | --- | yes | --- | --- | --- |
| In Min | 0--127 | --- | --- | --- | yes | --- |
| In Max | 0--127 | --- | --- | --- | yes | --- |
| Out Min | 0--127 | --- | --- | --- | yes | --- |
| Out Max | 0--127 | --- | --- | --- | yes | --- |
| Pass through original event | bool | yes | yes | yes | yes | yes |

**Src note = Any** (the three note types): every incoming note on
the source channel triggers the mapping; the destination note or CC
stays fixed. Combined with **Value Source = Velocity**, the whole
keyboard acts as a velocity-to-CC pedal.

**Value Source = Velocity** (Note → CC only): the note-on velocity
is sent as the CC value instead of **On value**; **Off value** is
still emitted on Note Off, so the CC has a defined release state.

## Channel filter mask

A 16-bit mask, one bit per MIDI channel, on every connection;
default all-on (`0xFFFF`). All-off silences the connection without
removing it. Tap the **MIDI Channels** heading on the filter panel
to flip every bit at once. Filtering happens **before** mappings --
a Channel Remap targeting channel 3 still needs channel 3 enabled
in the source filter.

## Message-type filter flags

Per-connection on/off, all on by default:

| Flag | Covers |
|------|--------|
| Notes | Note On, Note Off |
| CCs | Control Change |
| PC | Program Change |
| Pitch Bend | Pitch Bend |
| Aftertouch | Channel pressure, polyphonic pressure |
| SysEx | System Exclusive |
| Clock | MIDI Clock, Start, Stop, Continue, Song Position |

Changes apply instantly; **Save Config** persists them.

## Loop prevention

- The diagonal (a device's own row meeting its own column) is always
  blocked.
- Multi-hop loops (A → B → C → A) are detected at routing time; the
  loop-closing connection is rejected.

## MIDI Learn

| Trait | Behaviour |
|-------|-----------|
| Trigger | Tap the **Learn** button next to a source field |
| Listening state | Button label changes to **Listening...** |
| First event wins | Note On for note fields; CC for CC fields |
| Timeout | None -- stays armed until an event arrives or Learn is tapped again |
| Cancel | Tap Learn a second time |

## The clipboards

| Clipboard | Scope | Paste action |
|-----------|-------|--------------|
| **Cell** | One cell's filter + mappings | Overwrites destination cell wholesale |
| **Mapping** | One mapping | Paste-with-bump; auto-resolves duplicate CC conflicts |
| **Plugin** | One plugin instance | Paste-as-new; clones with fresh instance ID |

Cell and mapping clipboards surface as **Copy / Paste** on the
matrix and **+ Paste Mapping** on the filter panel; the plugin
clipboard is in the row/column header menu.

## Latency

| Connection type | Latency |
|-----------------|---------|
| No filter, no mappings | Effectively zero (kernel-only ALSA subscribe) |
| Any filter or mapping | 1--3 ms (userspace path) |

Even one channel exclusion or one mapping moves the connection from
the *direct* to the *filtered* path; cell colour shows it -- red
direct, purple filtered.

## Bidirectional pairs

A mapping is one-directional. To map both directions of a pair (a
footswitch to CC 64 one way, the destination's CC 64 back to another
controller), put a mapping in each of the two cells -- each carries
its own filter and mapping set.

## Pass-through and original-event preservation

**Pass through original event** is *additive*: on, the source event
is forwarded in addition to the mapped output; off, only the mapped
output is sent. The destination sees the original first, then the
mapped event in the same MIDI tick window.
