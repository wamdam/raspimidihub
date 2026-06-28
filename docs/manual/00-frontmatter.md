# Front Matter {.unnumbered}

**RaspiMIDIHub User Manual.** The documented release is shown on
the cover page. Information in this document is subject to change
as the software evolves; check the project's `CHANGELOG.txt` for
release-by-release deltas.

RaspiMIDIHub is distributed under the LGPL. Bundled third-party
components retain their own licences (Preact -- MIT; HTM -- Apache 2.0).

## Conventions in this Manual {.unnumbered}

The following typographic conventions are used throughout:

- **Tab names** and **page names** in the web UI are written in bold:
  the **Routing** tab, the **Settings** page.
- **Button labels** and **menu items** as they appear on screen are
  written in bold with their exact casing: tap **Save Config**, pick
  **Edit** from the cell menu.
- **Parameter names** (knob/wheel/fader labels in plugin panels) are
  written in upper case: the **RATE** wheel on the CC LFO.
- File paths, shell commands, and config keys are written in
  `monospace`. Multi-line commands appear in fenced code blocks.
- **Hardware MIDI devices** are referred to generically as "the
  source" and "the destination" in routing examples.
- **Keyboard shortcuts** are written with `+` between modifiers:
  `Shift + Space`, `Cmd + R`.
- When a feature requires the Pi to be reachable over the network, the
  URL is written as `http://raspimidihub-<id>.local/`, where `<id>` is
  the four-character code shown in the hub's title bar and WiFi name
  (e.g. `raspimidihub-735C.local`). Each hub's name is unique so several
  can share a network. Substitute the hub's actual IP if mDNS is
  unavailable on your network.

The following admonitions are used:

::: note
Information that clarifies a point or anticipates a common
question.
:::

::: warning
Information that prevents data loss, a stuck WiFi state, or a
bricked SD card.
:::

::: tip
A shortcut, gesture, or workflow that makes a task faster.
:::

## How to Read This Manual {.unnumbered}

Chapters 1--7 are introductory and best read in order on a first
pass: they cover the product, the hardware, the system architecture,
and a short guided quick-start that gets MIDI flowing.

Chapters 8--18 are reference chapters for each subsystem (routing,
filters and mappings, plugins, controllers, the Tracker, Bluetooth,
saving and exporting, settings, connectivity, updates). Each can be
consulted on its own when a specific feature is in question.

Chapters 19--22 collect setup walkthroughs, troubleshooting,
technical specifications, and credits.

The **Appendices** are the parameter-level reference: every plugin,
every controller, the MIDI mapping cheat sheet, and all keyboard
shortcuts.

A short **Index** closes the manual.
