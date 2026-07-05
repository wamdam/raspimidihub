# The RaspiMIDIHub

What the appliance does on its own and why it has the shape it has.

## What It Is

Plug a Raspberry Pi running RaspiMIDIHub into power, plug USB MIDI
devices into its ports, and they are talking to each other -- no
computer, no driver install, no app to configure. Everything else is
layered on top of this default.

## The Three Pillars

### Routing matrix

A tap-to-edit grid of connections between MIDI devices. Per-cell
channel filters, message-type filters, and four mapping types
(Note → CC, Note → CC toggle, CC → CC, Channel Remap) reshape the
flow without code.

### Virtual instruments and play surfaces

Plugins -- LFOs, chord generators, delays, scale remappers, velocity
curves, a dozen others -- appear in the matrix as virtual MIDI
devices; the Tracker, Arpeggiator, and Euclidean also render
fullscreen play surfaces on the **Play** tab. Controllers (Mixer 8,
FX 6, Performance 16, XY 4) turn a phone or tablet into a tap-to-play
surface the matrix routes like any other device.

### Appliance reliability

Read-only filesystem, captive-portal access point, power-pull-safe
config writes, an isolated CPU core for the MIDI path. Treat the Pi
like a guitar pedal: yank the power, plug it back in next week, it
boots to the same state.

## Design Goals

- **Explicit routing by default.** New devices arrive disconnected
  and never inject MIDI until routed. One tap connects a pair; flip
  *Default routing* to **Connect all** (Settings → MIDI) for
  all-to-all plug-and-play.
- **Mobile-first UI.** A touch-first web UI from any phone; no
  desktop app. Wheels, faders, radios, and toggles replace dropdowns.
- **Sub-millisecond routing on direct connections.** Unfiltered,
  unmapped connections are wired in the ALSA kernel sequencer;
  latency is effectively zero.
- **Power-pull-safe.** The SD card is read-only in normal operation,
  config writes are atomic, BlueZ bonds are snapshotted on every
  change. Yanking the power loses unsaved edits and nothing else.
- **Open, inspectable, extensible.** Open source under the GPL, with
  a documented plugin API for user plugins in Python.

## What It Is Not

- **Not a DAW.** No recording, audio editing, or timeline automation.
- **Not an audio interface.** MIDI events only; audio comes from the
  connected gear. The Pi's analog and HDMI audio are unused.
- **Not a general-purpose Linux box.** The read-only root and
  isolated-core reservation make it a worse host for other software.
  Install on a fresh Raspberry Pi OS Lite image only.

## The Project's Story in Brief

Started as a routing-only utility -- ALSA `aconnect` wrapped in a
kiosk UI -- and grew into a plugin host and controller platform.
Major shifts: `docs/ROADMAP.md`; per-version log: `CHANGELOG.txt`.

## Licence

GPL. Bundled third-party software retains its own licences: Preact
(MIT), HTM (Apache 2.0). Full credits: chapter 22; compliance notes:
chapter 21.8.
