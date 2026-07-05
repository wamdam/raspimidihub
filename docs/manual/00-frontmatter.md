# Front Matter {.unnumbered}

**RaspiMIDIHub User Manual.** The documented release is shown on the
cover page. `CHANGELOG.txt` in the project repository carries the
release-by-release deltas.

RaspiMIDIHub is distributed under the GPL. Bundled third-party
components retain their own licences (Preact -- MIT; HTM -- Apache 2.0).

## Conventions in this Manual {.unnumbered}

- **Tab names** and **page names** in the web UI are bold: the
  **Routing** tab, the **Settings** page.
- **Button labels** and **menu items** are bold with their exact
  on-screen casing: tap **Save Config**, pick **Edit** from the
  cell menu.
- **Parameter names** (knob/wheel/fader labels in plugin panels) are
  upper case: the **RATE** wheel on the CC LFO.
- File paths, shell commands, and config keys are `monospace`;
  multi-line commands appear in fenced code blocks.
- **Hardware MIDI devices** are called "the source" and "the
  destination" in routing examples.
- **Keyboard shortcuts** join modifiers with `+`: `Shift + Space`,
  `Cmd + R`.
- Network URLs are written as `http://raspimidihub-<id>.local/`,
  where `<id>` is the four-character code shown in the hub's title
  bar and WiFi name (e.g. `raspimidihub-735C.local`). Each hub's name
  is unique so several can share a network. Substitute the hub's IP
  if mDNS is unavailable on your network.

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

Chapters 1--7 are introductory -- the product, the hardware, the
system architecture, and a guided quick-start that gets MIDI flowing
-- and best read in order. Chapters 8--18 are per-subsystem reference
chapters (routing, filters and mappings, plugins, controllers, the
Tracker, Bluetooth, saving and exporting, settings, connectivity,
updates), each usable on its own. Chapters 19--22 collect setup
walkthroughs, troubleshooting, technical specifications, and credits.

The **Appendices** are the parameter-level reference: every plugin,
every controller, the MIDI mapping cheat sheet, and all keyboard
shortcuts. A short **Index** closes the manual.
