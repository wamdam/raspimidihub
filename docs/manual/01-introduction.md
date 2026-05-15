# Introduction

To get the most out of your RaspiMIDIHub appliance, we recommend
reading this manual end-to-end on first use. After that, the
chapter-per-subsystem layout makes it easy to consult individual
topics without re-reading what came before.

## What This Manual Covers

RaspiMIDIHub is a software appliance for the Raspberry Pi. It turns
the Pi into:

- A **MIDI routing hub** with an all-to-all default and a tap-to-
  edit matrix UI for everything beyond the default.
- A **host for virtual MIDI instruments** -- the built-in plugins
  for LFO, chord generator, delay, scale remapper, velocity curve,
  and more.
- A **host for play surfaces** -- the four controller templates
  (Mixer 8, FX 6, Performance 16, XY 4) that turn the phone or
  tablet into a tap-to-play MIDI controller with drop-button
  scene recall, plus three fullscreen play-surface plugins
  (Tracker, Arpeggiator, Euclidean) on a dedicated **Play** tab.
- A **MIDI access point** -- a built-in WiFi access point with a
  captive portal so the configuration UI opens automatically on a
  phone the first time it connects.
- A **read-only-filesystem appliance** -- pull the power any time,
  boot back to the last saved state.

This manual is the full reference for all of that.

## Who This Manual Is For

The intended reader is *anyone who plugs the unit in and uses it*
-- musicians on stage, hobbyists wiring up a home studio, sound
designers patching together hardware chains. Familiarity with
basic MIDI concepts (notes, CCs, channels, clock) is assumed; no
Raspberry Pi experience or Linux knowledge is assumed.

Plugin authors and contributors will find additional developer-
oriented documentation in the project repository -- the Plugin
Developer Guide, the build-from-source notes, and the roadmap.
This manual stays user-facing and does not duplicate that
material.

## How to Read This Manual

The chapters fall into five groups:

| Chapters | Group | Purpose |
|----------|-------|---------|
| 1--7 | Introduction and orientation | Read in order on first use |
| 8--18 | Per-subsystem reference | Read as needed |
| 19--20 | Examples and troubleshooting | Read when stuck |
| 21--22 | Technical information and credits | Look-up |
| A--D | Appendices | Parameter tables, mapping reference, keyboard shortcuts |

A reader new to the project should read chapters 1--7 in order,
plug in two MIDI devices, follow the Quick Start (chapter 7), and
then dip into the per-subsystem chapters as the need arises.

A reader who knows the appliance but needs to consult a specific
detail (the exact CC range of the **FX 6** controller's faders,
or how the BLE auto-reconnect interacts with power-off) can jump
directly to the relevant chapter or appendix.

## The Conventions Used

The conventions used throughout this manual -- how key labels and
menu names are formatted, what the **Note**, **Warning**, and
**Tip** admonitions look like, how cross-references are written
-- are documented in the front matter.

## Versioning Policy

This manual is updated alongside the software. The currently
documented release is shown on the cover page. Patch-level
changes between minor releases (4.0.x → 4.0.y) may not all be
called out in the manual; the `CHANGELOG.txt` in the project
repository is the authoritative per-release delta.

Major releases that change the schema (chapter 5.10) are matched
by a bump of the manual's version field and a full pass through
every chapter.

## Supporting Material

- **Project repository** --
  `https://github.com/wamdam/raspimidihub`
- **Issue tracker** -- the GitHub Issues tab of the repository
- **Changelog** -- `CHANGELOG.txt` in the repository
- **Roadmap** -- `docs/ROADMAP.md` in the repository
- **Plugin Developer Guide** -- `plugins/README.md` in the
  repository
- **Building from source** -- `docs/BUILDING.md` in the
  repository

The chapter that brings this all together is chapter 22 (Credits
and Contact).

