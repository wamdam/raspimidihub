# Introduction

Plug a Raspberry Pi running RaspiMIDIHub into power, plug USB MIDI
devices into its ports, and they are talking to each other -- no
computer, no driver install, no app to configure. Everything else is
layered on top of this default. Read this manual end-to-end on first
use; afterwards each chapter stands alone for reference.

## The Three Pillars

### Routing matrix

A tap-to-edit grid of connections between MIDI devices. Per-cell
channel filters, message-type filters, and four mapping types
(Note → CC, Note → CC toggle, CC → CC, Channel Remap) reshape the
flow without code.

### Virtual instruments and play surfaces

Plugins -- LFOs, chord generators, delays, scale remappers, velocity
curves, a dozen others -- appear in the matrix as virtual MIDI
devices; the Tracker, Arpeggiator, Euclidean, and Cartesian also
render fullscreen play surfaces on the **Play** tab. Controllers
(Mixer 8, FX 6, Performance 16, XY 4) turn a phone or tablet into a
tap-to-play surface the matrix routes like any other device.

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

## Who This Manual Is For

Anyone who plugs the unit in and uses it -- on stage, in a home
studio, in a hardware chain. Basic MIDI concepts (notes, CCs,
channels, clock) are assumed; no Raspberry Pi or Linux knowledge is.
Developer material (Plugin Developer Guide, build notes, roadmap)
lives in the project repository, not here.

## How to Read This Manual

| Chapters | Group | Purpose |
|----------|-------|---------|
| 1--4 | Introduction and orientation | Read in order on first use |
| 5--14 | Per-subsystem reference | Read as needed |
| 15--16 | Examples and troubleshooting | Read when stuck |
| 17--18 | Technical reference and credits | Look-up |
| A--E | Appendices | Parameter tables, mapping and API reference, keyboard shortcuts |

Read chapters 1--4 in order, follow the Quick Start (chapter 4) with
two MIDI devices plugged in, then dip in as needed. Typography, the
**Note** / **Warning** / **Tip** admonitions, and cross-reference
style are documented in the front matter.

## Versioning and Licence

The documented release is shown on the cover page. Patch-level
changes may not all be called out; `CHANGELOG.txt` is the
authoritative per-release delta. Major releases that change the
config schema (chapter 17) get a full manual pass and a version bump.

RaspiMIDIHub is GPL. Bundled third-party software retains its own
licences: Preact (MIT), HTM (Apache 2.0). Full credits and compliance
notes: chapters 18 and 17.

## Supporting Material

In the project repository:

- **Project repository** -- `https://github.com/wamdam/raspimidihub`
- **Issue tracker** -- the GitHub Issues tab
- **Changelog** -- `CHANGELOG.txt`
- **Roadmap** -- `docs/ROADMAP.md`
- **Plugin Developer Guide** -- `plugins/README.md`
- **Building from source** -- `docs/BUILDING.md`

Chapter 18 (Credits and Contact) brings these together.
