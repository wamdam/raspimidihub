# Introduction

Read this manual end-to-end on first use; afterwards each chapter
stands alone for reference.

## What This Manual Covers

RaspiMIDIHub is a software appliance that turns a Raspberry Pi into:

- A **MIDI routing hub** -- new devices arrive disconnected by
  default (flip to all-to-all in Settings); a tap-to-edit matrix
  wires up everything.
- A **host for virtual MIDI instruments** -- built-in plugins for
  LFO, chord generator, delay, scale remapper, velocity curve, and
  more.
- A **host for play surfaces** -- controller templates (Mixer 8,
  FX 6, Performance 16, XY 4) that make a phone or tablet a
  tap-to-play MIDI controller with drop-button scene recall, plus
  fullscreen play-surface plugins (Tracker, Arpeggiator, Euclidean,
  Cartesian) on the **Play** tab.
- A **MIDI access point** -- a built-in WiFi access point whose
  captive portal opens the configuration UI automatically.
- A **read-only-filesystem appliance** -- pull the power any time,
  boot back to the last saved state.

## Who This Manual Is For

Anyone who plugs the unit in and uses it -- on stage, in a home
studio, in a hardware chain. Basic MIDI concepts (notes, CCs,
channels, clock) are assumed; no Raspberry Pi or Linux knowledge is.
Developer material (Plugin Developer Guide, build notes, roadmap)
lives in the project repository, not here.

## How to Read This Manual

| Chapters | Group | Purpose |
|----------|-------|---------|
| 1--7 | Introduction and orientation | Read in order on first use |
| 8--18 | Per-subsystem reference | Read as needed |
| 19--20 | Examples and troubleshooting | Read when stuck |
| 21--22 | Technical information and credits | Look-up |
| A--D | Appendices | Parameter tables, mapping reference, keyboard shortcuts |

Read chapters 1--7 in order, follow the Quick Start (chapter 7) with
two MIDI devices plugged in, then dip in as needed. For a specific
detail, jump straight to the chapter or appendix.

## The Conventions Used

Typography, the **Note** / **Warning** / **Tip** admonitions, and
cross-reference style are documented in the front matter.

## Versioning Policy

The documented release is shown on the cover page. Patch-level
changes may not all be called out; `CHANGELOG.txt` is the
authoritative per-release delta. Major releases that change the
schema (chapter 5.10) get a full manual pass and a version bump.

## Supporting Material

In the project repository:

- **Project repository** -- `https://github.com/wamdam/raspimidihub`
- **Issue tracker** -- the GitHub Issues tab
- **Changelog** -- `CHANGELOG.txt`
- **Roadmap** -- `docs/ROADMAP.md`
- **Plugin Developer Guide** -- `plugins/README.md`
- **Building from source** -- `docs/BUILDING.md`

Chapter 22 (Credits and Contact) brings these together.
