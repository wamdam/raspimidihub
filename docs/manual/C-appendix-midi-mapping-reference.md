# MIDI Mapping Reference

A flat reference for every mapping type, every parameter on the
mapping form, and the underlying behaviour. The walkthrough is in
chapter 10; this appendix is the lookup.

Value fields are **MIDI units**: the familiar 0--127 scale, with
fractional values (e.g. `63.5`) accepted since MIDI 2.0 support.
Whole numbers behave exactly as they always did; fractions carry
extra precision to MIDI 2.0 destinations and round for MIDI 1.0
ones. On a MIDI 2.0 connection the mapping engine computes in full
resolution — a hi-res controller swept through a CC → CC range
remap stays stepless.

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

**Src note = Any** (Note → CC, Note → CC toggle, Note → Note):
turns the note match into a wildcard. Every incoming note on the
selected source channel triggers the mapping; the destination
note (for Note → Note) or CC (for Note → CC variants) stays
fixed. Combined with **Value Source = Velocity** on Note → CC,
this makes the whole keyboard act as a velocity-to-CC pedal.

**Value Source = Velocity** (Note → CC only): the live note-on
velocity (0--127) is sent as the CC value, replacing the
**On value**. The **Off value** is still emitted on Note Off so
the CC has a defined release state.

## Channel filter mask

A 16-bit mask, one bit per MIDI channel, attached to every
connection. Defaults to all-on (`0xFFFF`).

- All-on -- every channel passes.
- All-off -- the connection is silent without being removed.
- Tap the **MIDI Channels** heading on the filter panel to flip
  every bit at once.

Channel filtering happens **before** mappings see the event. A
Channel Remap mapping that targets channel 3 still requires
channel 3 to be enabled in the source filter -- otherwise the
event never reaches the mapper.

## Message-type filter flags

Per-connection on/off, with defaults all on:

| Flag | Covers |
|------|--------|
| Notes | Note On, Note Off |
| CCs | Control Change |
| PC | Program Change |
| Pitch Bend | Pitch Bend |
| Aftertouch | Channel pressure, polyphonic pressure |
| SysEx | System Exclusive |
| Clock | MIDI Clock, Start, Stop, Continue, Song Position |

Disabling a flag at the cell level applies instantly. The change
is persisted to disk by **Save Config**.

## Loop prevention

- A device's own row meeting its own column on the diagonal is
  always blocked.
- Multi-hop loops (A → B → C → A) are detected at routing time
  and the would-be loop-closing connection is rejected.

## MIDI Learn

| Trait | Behaviour |
|-------|-----------|
| Trigger | Tap the **Learn** button next to a source field |
| Listening state | Button label changes to **Listening...** |
| First event wins | Note On for note fields; CC for CC fields |
| Timeout | None -- stays armed until an event arrives or Learn is tapped again |
| Cancel | Tap Learn a second time |

## The clipboards

Three clipboards interact with mappings:

| Clipboard | Scope | Paste action |
|-----------|-------|--------------|
| **Cell** | One cell's filter + mappings | Overwrites destination cell wholesale |
| **Mapping** | One mapping | Paste-with-bump; auto-resolves duplicate CC conflicts |
| **Plugin** | One plugin instance | Paste-as-new; clones with fresh instance ID |

The cell and mapping clipboards are surfaced as **Copy / Paste**
on the routing matrix and as **+ Paste Mapping** on the filter
panel respectively. The plugin clipboard is surfaced in the
row/column header menu.

## Latency

| Connection type | Latency |
|-----------------|---------|
| No filter, no mappings | Effectively zero (kernel-only ALSA subscribe) |
| Any filter or mapping | 1--3 ms (userspace path) |

Adding even one channel exclusion or one mapping pushes the
connection from the *direct* path to the *filtered* path. The
matrix renders this as the cell colour: red is direct, purple
is filtered.

## Bidirectional pairs

A mapping is one-directional. To map both directions of a
bidirectional pair (for example, a footswitch on a controller
that should map to CC 64 on the destination *and* the destination
should send any CC 64 changes back to a different controller),
two cells need mappings -- one per direction. The matrix is a
directed graph; each cell carries its own filter and mapping
set.

## Pass-through and original-event preservation

The **Pass through original event** toggle on each mapping is
*additive*: when on, the source event is forwarded *in addition
to* the mapped output. When off, only the mapped output is
sent.

The pass-through and the mapped event are emitted from the same
cell, so message ordering at the destination is preserved
(original event first, then the mapped event in the same MIDI
tick window).
