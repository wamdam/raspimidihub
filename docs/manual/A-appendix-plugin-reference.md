```{=latex}
\appendix
```

# Plugin Reference

The complete per-plugin parameter reference. Each entry follows
the same structure: a one-paragraph summary, a parameter table
with ranges and defaults, the input and output behaviour, and the
clock semantics (if any).

The conceptual model of plugins -- how they fit into the routing
matrix, how they are added and removed, how clock sync and CC
automation work -- is in chapter 11.

**CC defaults.** Where a parameter shows a `(CC N default)` note,
that's the plugin author's factory binding -- the (Any channel,
CC N) the param ships with. Users override per-instance via
long-press → MIDI Learn (chapter 11.7); the default just tells
you what to expect before any rebinding.

## Arpeggiator

Detailed surface-and-workflow reference: chapter 13. Plugin-level
metadata:

| Trait | Value |
|-------|-------|
| Name | Arpeggiator |
| Description | Plays held notes as a pattern with a step sequencer |
| Surface | Play tab (`SURFACE_KIND = "play"`); add from **Add → Play** |
| Pattern modes | up / down / up-down / random / as-played / programmed / chord (7) |
| Rate range | 4/1 / 4/1T / 2/1 / ... / 1/16T / 1/32 (15 values) |
| Steps per pattern | 1..32 |
| Octaves | 1..4 |
| Patterns per instance | 8 numbered slots (see chapter 13) |

| Surface | Parameter | Type | Range | Default |
|---------|-----------|------|-------|---------|
| Play    | **Pattern** | Wheel (wide) | 7 modes (see above) | up |
| Play    | **Rate** | Wheel (wide) | 15 values | 1/8 |
| Play    | **Steps** | Wheel | 1--32 | 8 |
| Play    | **Accent Vel.** | Knob | 0--127 | 30 |
| Play    | **Gate %** | Wheel | 10--100 | 80 |
| Play    | **Octaves** | Wheel | 1--4 | 1 |
| Play    | **Step Pattern** | StepEditor | per-step on/off + offset + accent | all-on, offset 0 |
| Play    | **Patterns** | PatternStrip | end-of-surface P1--P8 bank | slot 1 active |
| Setup   | **Arp Ch** | ChannelSelect | 1--16 or any | any |
| Setup   | **Sync** | Radio | free / tempo / transport | transport |
| Setup   | **BPM** (visible when Sync = free) | Wheel | 40--300 | 120 |
| Setup   | **Ctrl Ch** | Wheel | Off / 1--16 | Off |
| Setup   | **P1..P8** (visible when Ctrl Ch is on) | NoteSelect ×8 | one learnable trigger note per slot | C2..G2 (36..43) |

CC automation (mirrors the Euclidean for shared params):

| CC | Parameter | CC | Parameter |
|----|-----------|----|-----------|
| 70 | Pattern   | 74 | Rate |
| 71 | Octaves   | 75 | Gate % |
| 73 | Steps     | 83 | Accent Vel. |

**Input.** Notes (held-note buffer), CC 64 (temporary Hold via
sustain pedal), CC 70..83 (parameter automation), Clock +
Transport, and the 8 learnable notes on Ctrl Ch when set.
**Output.** Notes (the arpeggiated stream). Aftertouch and Pitch
Bend pass through unchanged.
**Clock.** Consumes external clock when Sync is `tempo` or
`transport`; free-runs at BPM when Sync is `free`.

![Arpeggiator play surface.](../screenshots/arpeggiator-play.png){width=42%}

![Arpeggiator device-detail panel.](../screenshots/09-plugin-arpeggiator.png){width=35%}

## CC LFO

Generates a CC waveform on the output. Five wave shapes; free-run
or clock-synced rate up to 8 bars; live scope display.

| Group | Parameter | Type | Range | Default |
|-------|-----------|------|-------|---------|
| Waveform | **Wave** | Radio | sine / triangle / square / saw / s&h | sine |
| Timing | **Sync to Clock** | Button | on / off | off |
| Timing | **Rate** | Radio | 8 / 4 / 2 / 1 / 1/2 / 1/4 / 1/8 / 1/16 bars | 1 |
| Timing | **Frequency** | Fader | 0.1--20.0 Hz (raw 1--200) | 0.5 Hz (CC 74 default) |
| Output | **Channel** | ChannelSelect | 1--16 | 1 |
| Output | **CC #** | Wheel | 0--127 | 1 |
| Output | **Depth** | Fader | 0--127 | 127 (CC 75 default) |
| Output | **Center** | Fader | 0--127 | 64 (CC 76 default) |

**Input.** Clock (when **Sync to Clock** is on).
**Output.** CC (the LFO stream).
**Clock.** Consumes external clock when sync is on; free-runs at
the **Frequency** when off.
**Display.** Scope of the output value.

![CC LFO config panel with live scope.](../screenshots/10-plugin-cc-lfo.png){width=35%}

## CC Smoother

Smooths jitter on a noisy CC input by interpolating between
incoming values over a configurable window. Dual scope -- input
and output side by side -- makes the smoothing visible.

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| **Input CC #** | Wheel | 0--127 | 1 |
| **Output CC #** | Wheel | 0--127 | 1 |
| **Smoothing** | Fader | 1--50 (interpolation window) | 10 (CC 76 default) |

**Input.** CC at **Input CC #**.
**Output.** CC at **Output CC #** with smoothed values.
**Clock.** None.
**Display.** Two scopes -- input and output.

![CC Smoother with input and output scopes.](../screenshots/11-plugin-cc-smoother.png){width=35%}

## Chord Generator

Each incoming Note On triggers a chord. Selectable chord type,
inversion, and an "added-note velocity scale" so the upper
voices can be softer than the played root.

| Group | Parameter | Type | Range | Default |
|-------|-----------|------|-------|---------|
| Chord | **Type** | Radio | major / minor / 7th / minor 7th / major 7th / sus2 / sus4 / custom intervals | major |
| Chord | **Inversion** | Radio | root / 1st / 2nd | root |
| Output | **Added Note Vel %** | Wheel | 10--100 % | 90 (CC 76 default) |

**Input.** Notes.
**Output.** Notes -- root + chord voices.
**Clock.** None.

![Chord Generator config panel.](../screenshots/12-plugin-chord-generator.png){width=35%}

## Clock Divider

Emits one MIDI Clock for every N received. Useful for driving a
slow second device from a fast master clock.

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| **Divide by** | Wheel | 2--32 | 2 (CC 74 default) |

**Input.** Clock.
**Output.** Clock at 1/N the input rate; passes Start / Stop /
Continue through.
**Clock.** Consumes and produces.

![Clock Divider config panel.](../screenshots/21-plugin-clock-divider.png){width=35%}

## Euclidean

Detailed surface-and-workflow reference: chapter 13. Plugin-level
metadata:

| Trait | Value |
|-------|-------|
| Name | Euclidean |
| Description | Held notes voiced through a Bjorklund-distributed step pattern |
| Surface | Play tab (`SURFACE_KIND = "play"`); add from **Add → Play** |
| Layers | Bjorklund + Window wave (sine threshold) + Manual override grid |
| Pattern modes | up / down / up-down / random / as-played / chord (6) |
| Rate range | 4/1 ... 1/32 (15 values, same as Arp) |
| Steps per pattern | 1..32 |
| Scales | major / minor / dorian / mixolydian / pentatonic / blues / harmonic m / whole tone / chromatic (9) |
| Patterns per instance | 8 numbered slots (see chapter 13) |

| Surface | Parameter | Type | Range | Default |
|---------|-----------|------|-------|---------|
| Play    | **Pattern** | Wheel (wide) | 6 modes (see above) | up |
| Play    | **Rate** | Wheel (wide) | 15 values | 1/16 |
| Play    | **Pulses** | Wheel | 0--32 (capped by Steps) | 4 |
| Play    | **Steps** | Wheel | 1--32 | 16 |
| Play    | **Rotate** | Wheel | -16--+16 | 0 |
| Play    | **Octaves** | Wheel | 1--4 | 1 |
| Play    | **Phase** | Wheel | 0--31 | 0 |
| Play    | **Cycles** | Wheel | 0.5 / 1 / 2 / 3 / 4 | 1 |
| Play    | **Open** | Knob | 0--100 | 100 |
| Play    | **Gate %** | Wheel | 10--100 | 80 |
| Play    | **Accent Vel.** | Knob | 0--127 | 30 |
| Play    | **Fade In** | Wheel | 0--16 firing steps | 0 |
| Play    | **Fade Out** | Wheel | 0--16 firing steps | 0 |
| Play    | **Jitter %** | Knob | 0--100 | 0 |
| Play    | **Tune Spread** | Knob | 0--100 | 0 |
| Play    | **Snap** | Wheel | free / octaves / 5ths+oct. | octaves |
| Play    | **Scale** | Wheel | 9 scales (see above) | major |
| Play    | **Root** | Wheel | C ... B | C |
| Play    | **Step Pattern** | StepEditor (override mode) | per-step default / force-on / force-on+accent / force-off + offset | all default |
| Play    | **Patterns** | PatternStrip | end-of-surface P1--P8 bank | slot 1 active |
| Setup   | **Arp Ch** | ChannelSelect | 1--16 or any | any |
| Setup   | **Sync** | Radio | free / tempo / transport | transport |
| Setup   | **BPM** (visible when Sync = free) | Wheel | 40--300 | 120 |
| Setup   | **Retrig** | Button | reset cycle on first key of a phrase | on |
| Setup   | **Ctrl Ch** | Wheel | Off / 1--16 | Off |
| Setup   | **P1..P8** (visible when Ctrl Ch is on) | NoteSelect ×8 | one learnable trigger note per slot | C2..G2 (36..43) |

CC automation (full block CC 70..88, skipping CC 84 = GM
Portamento Control):

| CC | Parameter | CC | Parameter |
|----|-----------|----|-----------|
| 70 | Pattern    | 80 | Fade In |
| 71 | Octaves    | 81 | Fade Out |
| 72 | Pulses     | 82 | Jitter |
| 73 | Steps      | 83 | Accent Vel. |
| 74 | Rate       | 85 | Tune Spread |
| 75 | Gate %     | 86 | Snap |
| 76 | Open       | 87 | Scale |
| 77 | Phase      | 88 | Root |
| 78 | Cycles     |    |    |
| 79 | Rotate     |    |    |

**Input.** Notes (held buffer), CC 64 (sustain pedal), CC 70..83
/ CC 85..88 (parameter automation), 8 learnable notes on Ctrl Ch
when set (each picks a pattern slot; consumed, not arpeggiated),
Clock + Transport, Aftertouch, Pitch Bend.
**Output.** Notes (Bjorklund-voiced, scale-quantised). Aftertouch
and Pitch Bend pass through unchanged.
**Clock.** Consumes external clock when Sync is `tempo` or
`transport`; free-runs at BPM when Sync is `free`.

![Euclidean play surface.](../screenshots/euclidean-play.png){width=42%}

![Euclidean device-detail panel.](../screenshots/30-plugin-euclidean-config.png){width=35%}

## Hold

Latches incoming notes so they keep sounding after release.
Two latch modes, chosen with **Toggle notes**:

- **off (default) -- chord-latch.** While any key is physically
  down, further presses extend the held chord; once every key is
  released the chord stays sounding. Pressing the Release Note
  (default `C8`, high enough to be out of normal play range)
  silences the chord; pressing any other note after a full
  release replaces the held chord with a new one starting on
  that note.
- **on -- per-note toggle.** Each note latches independently.
  The first press of a note plays and holds it; the next press
  of the same note releases it. The keyboard's own note-off
  events are ignored. The Release Note still works as an
  "all off" trigger across every latched note.

Flipping Toggle notes mid-session releases everything currently
sounding so the new mode starts from a clean slate.

| Group | Parameter | Type | Range | Default |
|-------|-----------|------|-------|---------|
| -- | **Toggle notes** | Button | on / off | off |
| Release Note | **Enabled** | Button | on / off | on |
| Release Note | **Note** | NoteSelect | 0--127 | C8 (108) |

**Input.** Notes.
**Output.** Notes -- with sustained Note Ons. The configured
release note acts as the off trigger for all held notes.
**Clock.** None.

![Hold config panel.](../screenshots/22-plugin-hold.png){width=35%}

## Latency

Adds a fixed millisecond delay to every MIDI event before forwarding,
via the ALSA kernel queue (sub-millisecond jitter under load).
Compensates synths whose own MIDI-in processing lands the sound a few
milliseconds after the message arrives -- route a tight source (the
Arpeggiator, the Tracker, a hardware controller) through Latency
before that synth so the audio lines up with the synth's internal
sequencer.

Clock and transport (Start / Stop / Continue) pass through
immediately. Delaying them would shift the downstream synth's own
sequencer and defeat the point of the plugin.

The note-on / note-off pair is bookkept so a live fader move
mid-note cannot reorder it -- the off reuses the offset captured at
the matching on.

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| **Delay (ms)** | Fader | 1--100 ms | 10 (CC 74 default) |

**Input.** All events.
**Output.** All events (delayed) plus clock + transport (immediate).
**Clock.** Pass-through (not delayed).

*Screenshots needed:* `screenshots/XX-plugin-latency.png` showing the
config panel with the single Delay (ms) fader.

## Master Clock

Generates MIDI Clock from an internal BPM. Includes a transport
button, a beat meter showing the position within the bar, and a
bar counter.

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| **BPM** | Wheel | 20--300 | 120 (CC 74 default) |
| **Play** | Button | on / off | off |

**Input.** None (generator).
**Output.** Clock, Start, Stop, Continue.
**Clock.** Produces.
**Display.** Beat meter, bar counter.

![Master Clock with BPM, transport, beat meter.](../screenshots/13-plugin-master-clock.png){width=35%}

## MIDI Delay

Pre-scheduled echoes through the ALSA queue. Sub-millisecond
jitter under load. Supports clock-synced delay times or
free-running milliseconds; per-repeat velocity decay.

| Group | Parameter | Type | Range | Default |
|-------|-----------|------|-------|---------|
| Timing | **Sync to Clock** | Button | on / off | on |
| Timing | **Delay (ms)** | Fader | 10--2000 ms | 250 (CC 74 default) |
| Timing | **Rate** | Radio | 1/4 / 1/4T / 1/8 / 1/8T / 1/16 / 1/16T | 1/8 |
| Controls | **Repeats** | Wheel | 0--10 | 3 (CC 75 default) |
| Controls | **Vel Decay %** | Fader | 0--100 % | 20 (CC 76 default) |

**Input.** Notes.
**Output.** Notes -- the original plus the scheduled echoes.
**Clock.** Consumes external clock when **Sync to Clock** is on.

![MIDI Delay config panel.](../screenshots/14-plugin-midi-delay.png){width=35%}

## Note Splitter

Splits the keyboard at a configurable note into two channels with
independent per-zone transpose.

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| **Split Point** | NoteSelect | 0--127 | C4 (60) (CC 74 default) |
| Lower Zone -- **Channel** | ChannelSelect | 1--16 | 1 |
| Lower Zone -- **Transpose** | Wheel | -48..+48 semitones | 0 (CC 75 default) |
| Upper Zone -- **Channel** | ChannelSelect | 1--16 | 2 |
| Upper Zone -- **Transpose** | Wheel | -48..+48 semitones | 0 (CC 76 default) |

**Input.** Notes.
**Output.** Notes routed to the lower or upper zone channel based
on the split point.
**Clock.** None.

![Note Splitter config panel.](../screenshots/15-plugin-note-splitter.png){width=35%}

## Note Transpose

Shifts all incoming notes up or down by a fixed number of
semitones.

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| **Semitones** | Wheel | -48..+48 | 0 (CC 74 default) |

**Input.** Notes.
**Output.** Notes -- shifted.
**Clock.** None.

![Note Transpose config panel.](../screenshots/16-plugin-note-transpose.png){width=35%}

## Panic Button

Sends *All Notes Off* and *All Sound Off* on every MIDI channel
on each press. Kills stuck notes everywhere downstream.

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| **Panic!** | Button (momentary, red) | trigger | -- |
| **Trigger CC #** | Wheel | 0--127 | 64 |

The **Trigger CC #** lets a hardware CC fire the panic button
remotely -- any incoming CC value of 64 or higher on that CC#
triggers a panic.

**Input.** CC (for the trigger).
**Output.** All Sound Off (CC 120 = 0) and All Notes Off
(CC 123 = 0) on every MIDI channel, on every press.
**Clock.** None.

![Panic Button config panel.](../screenshots/17-plugin-panic.png){width=35%}

## Pitch CC

Turns a keyboard into a chromatic player for synths that pitch
via a CC rather than the MIDI note number (Korg Volca Sample,
CC 49 = sample playback rate). Each Note On emits a pitch CC --
value `Base CC Value + (played_note - Base Note)`, clamped to
0--127 -- *before* forwarding the Note On. Note Off forwards
without a CC.

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| **Base Note** | NoteSelect (learnable) | 0--127 | 60 (C-3) |
| **Out CC#** | Wheel | 0--127 | 49 (Volca Sample pitch) |
| **Base Val** | Wheel | 0--127 | 64 |

**Input.** Notes, CC / Pitchbend / Aftertouch (pass-through).
**Output.** CC (pitch) + Notes on the same channel; other events
pass through.
**Clock.** None.

![Pitch CC config panel.](../screenshots/29-plugin-pitch-cc.png){width=35%}

## Scale Remapper

Quantises incoming notes to a musical scale. Labelled wheels for
the root pitch and a radio for the scale type.

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| **Scale** | Radio | major / minor / harmonic minor / melodic minor / pentatonic major / pentatonic minor / blues / chromatic / ... | major |
| **Root** | Wheel | 0--11 (note names) | C (CC 74 default) |

**Input.** Notes.
**Output.** Notes snapped to the nearest in-scale pitch.
**Clock.** None.

![Scale Remapper config panel.](../screenshots/18-plugin-scale-remapper.png){width=35%}

## SysEx Sender

Upload a `.syx` file in the configuration panel; the bytes are
streamed to the destination in 256-byte chunks with ~5 ms gaps
between chunks (some legacy synths' input buffers cannot handle
back-to-back SysEx without gaps).

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| **File picker** | File upload | -- | -- |

The uploaded file is not saved. Once the SysEx is sent, removing
the plugin instance is safe; the destination has the new state.

**Input.** None.
**Output.** SysEx -- the file's bytes.
**Clock.** None.

![SysEx Sender config panel with file picker.](../screenshots/27-plugin-sysex-sender.png){width=35%}

## Tracker

Detailed surface-and-workflow reference: chapter 13. Plugin-level
metadata:

| Trait | Value |
|-------|-------|
| Name | Tracker |
| Description | 8-voice step sequencer, single channel, paged |
| Voices | 8 (T1..T8) |
| Rows per page | 16 (hex 0..F) |
| Pages per pattern | up to 16, chained linearly, loops back to page 0 |
| Patterns per instance | 8 numbered slots; see chapter 13 |

Configuration parameters (from the device-detail panel):

- **Per-track channel** (T1..T8) -- 8 × ChannelSelect, default 1
  each. Doubles as the input matcher for direct channel routing
  during live recording.
- **Auto Ch.** -- Wheel, range `Off` / 1..16, default `Off`.
  Incoming notes/CCs on this channel use the historic
  cursor-relative recording (chord-spread from `cursor_track`
  across consecutive tracks). All other channels route by matching
  the per-track channel; unmatched channels are silently dropped.
- **Internal BPM** -- used when no external clock is routed in.
- **Send Clock + Transport** -- Button toggle; when on, forwards
  incoming CLOCK / START / STOP / CONTINUE to OUT.
- **Rcv Trnsp.** -- Button toggle, default **on**. When on,
  external transport (START / STOP / CONTINUE off the global
  clock bus) drives the playhead. When off, the Tracker ignores
  foreign transport and is started only by its own Play / Stop
  buttons and the launch trigger modes; it still follows the
  shared clock for tempo. The Play / Stop buttons bypass this
  gate and always work.
- **Ctrl Ch** -- Wheel, range `Off` / 1..16, default
  `Off`. When set, the channel is reserved end-to-end (no
  recording, no pass-through, CCs dropped too) and incoming notes
  trigger the matching pattern slot.
- **Trigger Mode** -- Wheel, `Switch` / `One-shot` / `Hold` /
  `Toggle`, default `Switch`. Only visible when **Ctrl Ch** is
  not Off. Governs what a control-channel trigger does:
  *Switch* selects the pattern via the queue-on-wrap path an
  on-screen Tap uses (the historic behaviour; pre-existing
  configs load as Switch). *One-shot* / *Hold* / *Toggle* launch
  the pattern from row 0 on the next clock step without a
  transport Start -- One-shot plays once through then stops, Hold
  loops while the key is held, Toggle starts on press and stops
  on re-press. Launching is monophonic (a new trigger replaces
  the one in flight) and applies to MIDI triggers only; on-screen
  slot taps always behave as Switch.
- **Pattern Notes (P1..P8)** -- 8 × NoteSelect, learnable,
  defaults 36..43 (C1..G1). Only visible when **Ctrl Ch**
  is not Off. Each entry is the note that triggers that
  pattern slot. A note that doesn't match any slot is dropped on
  the control channel anyway.

The grid data is part of the plugin instance state and is
captured by **Save Config** and **Export Config** along with the
parameters above.

**Input.** Notes, CC (live recording, channel-routed -- see
chapter 13 §Routing), Clock, Start, Stop, Continue.
**Output.** Notes, CC (from the grid), optionally Clock /
Start / Stop / Continue (when **Send Clock + Transport** is on).
**Clock.** Consumes and optionally re-emits.

![Tracker play surface.](../screenshots/tracker.png){width=35%}

![Tracker config panel with per-track channel mapping.](../screenshots/28-plugin-tracker-config.png){width=35%}

## Velocity Curve

Remaps velocity through a drawable 128-point curve. Shape presets
(linear, ease-in, ease-out, S-curve) are available along the
canvas edge.

| Parameter | Type | Range | Default |
|-----------|------|-------|---------|
| **Velocity Curve** | CurveEditor | 128 points × 0..127 each | linear |

**Input.** Notes.
**Output.** Notes -- velocity remapped through the curve.
**Clock.** None.

![Velocity Curve with drawable canvas.](../screenshots/19-plugin-velocity-curve.png){width=35%}

## Velocity Equalizer

Normalises incoming velocity, either to a fixed value or by
compressing / expanding the range.

| Group | Parameter | Type | Range | Default |
|-------|-----------|------|-------|---------|
|  | **Mode** | Radio | fixed / compress / expand | fixed |
| Fixed | **Velocity** | Wheel | 1--127 | 100 (CC 74 default) |
| Range | **Min** | Wheel | 1--127 | 60 (CC 75 default) |
| Range | **Max** | Wheel | 1--127 | 120 (CC 76 default) |

**Input.** Notes.
**Output.** Notes -- velocity adjusted.
**Clock.** None.

![Velocity Equalizer config panel.](../screenshots/20-plugin-velocity-equalizer.png){width=35%}

## User-Supplied Plugins

If you have written your own plugin and dropped it into the
project's plugin directory, it appears in the **Add → Plugin**
overlay alongside the built-ins. User-supplied plugins are
subject to the same lifecycle, the same sandbox, and the same
persistence model as the built-ins.

The plugin developer guide in the project repository covers the
API in detail. This manual is not the place for that material.
