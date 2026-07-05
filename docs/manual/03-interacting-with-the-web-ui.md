# Interacting with the Web UI

Everything on RaspiMIDIHub happens in a browser. This chapter covers
the connection flow, the tabs, the universal gestures, the
always-visible indicators, and the shared set of touch-first controls
every panel is built from; later chapters assume this vocabulary.

## First Connection

By default the Pi is in **AP-only** mode, broadcasting an SSID of the
form `RaspiMIDIHub-XXXX` with password `midihub1`. Joining it
triggers the captive portal on most operating systems and the UI
opens automatically. Manual entry points if it does not:

- `http://raspimidihub-<id>.local/` -- mDNS. Works out of the box on
  macOS, iOS, modern Android, and Linux with avahi-daemon; Windows
  needs Bonjour installed.
- The AP gateway IP from the phone's WiFi-info screen (for example
  `http://172.24.1.1/`).

Chapter 13 covers the alternative connectivity modes (USB tethering,
ethernet, WiFi-always client mode).

## The Four Tabs

The bottom navigation has up to four tabs:

| Tab | Path | Purpose |
|------|------|---------|
| **Routing** | `/routing` | The connection matrix and everything attached to it |
| **Controller** | `/controller` | Fullscreen tap-to-play surfaces |
| **Play** | `/play` | The play-surface plugins (Tracker, Arpeggiator, Euclidean, Cartesian) |
| **Settings** | `/settings` | System configuration |

**Controller** appears only when a controller instance exists
(chapter 8); **Play** only when a play-surface plugin has been added
(chapter 9). **Routing** and **Settings** are always present;
**Routing** is the home screen. Saving and reloading project state
happens there, via the **Save / Load / Export / Import Config**
buttons at the bottom of the matrix (chapter 5.10 and chapter 11).

## URL Routing

Every tab has a path, the open device-detail panel is a path, and the
browser back/forward buttons work. Bookmarks survive reboots --
`http://raspimidihub-<id>.local/settings` opens directly on the
Settings page.

## The Dirty-State Asterisk

A dark-red `*` next to the **Routing** icon lights up whenever the
in-memory state diverges from the saved config -- a new plugin, a
rewired cell, a renamed device, a touched filter. Tap **Save Config**
on the **Routing** tab to clear it. The asterisk means the running
unit is not yet what the next boot will look like -- the single most
important indicator in the UI.

## The Header Badge

The header reads `RaspiMIDIHub v<version> · <name>`: the AP SSID with
the `RaspiMIDIHub-` prefix stripped, so the factory default shows the
MAC suffix (e.g. `735C`) and a custom SSID shows verbatim -- the same
identifier you pick the hub by in the WiFi list. Change it via
**AP SSID** under **Settings → WiFi**; the MAC suffix itself is not
editable. The name is re-read on every reconnection, so the header
always shows the hub you are actually talking to.

A small red dot next to the title means the SPA in the browser is
older than the backend; tap it to reload. The same reload sits under
**Settings → Reload App** (busts mobile Safari's cache reliably).

## Universal Gestures

Five touch gestures recur everywhere:

- **Single tap** -- open a menu, fire an action, toggle a value.
- **Long-press** -- capture-style actions: capture a drop button's
  state, or Edit / Copy / Remove on a mapping row.
- **Drag** -- move a fader, scroll a wheel, draw a curve.
- **Swipe-down** -- dismiss the topmost overlay (same as tapping the
  dark overlay or pressing `ESC`).
- **Vertical scroll** -- normal browser scrolling on long panels.

The Tracker has its own keyboard scheme on the **Play** tab (chapter
9, appendix D); `ESC` closes the topmost overlay everywhere.

## The Captive Portal

The hub answers the captive-portal probes of Android, iOS, macOS, and
Windows with a redirect to its root, cueing the OS to open the UI in
a sandboxed browser. If the portal does not fire (some phones cache
"no internet" too aggressively; some carrier WiFi policies suppress
the probe), use the URLs from section 3.1.

## PWA Install

The web UI is a Progressive Web App. **Settings → PWA Install** shows
the "Install App" button; the installed app launches fullscreen with
no URL bar. On iOS install via Safari's Share → Add to Home Screen;
on Android via Chrome's install prompt.

## The MIDI Activity Bar

Above the bottom navigation, a one-line bar shows the two most recent
non-clock MIDI events, one per source side; entries expire after two
seconds of inactivity. Clock events do not appear -- the matrix's
pulsing-play icon indicates clock. Toggle the bar in **Settings →
Display**.

## Reconnect After Network Disruption

If the hub flips WiFi modes (chapter 13), reboots, or the browser
drops the connection, the SPA shows a banner offering to reconnect;
the reconnect itself is automatic.

## Themes

Two themes, **Light** and **Dark**, selectable from **Settings →
Display → Theme**. Light is the daytime default and the theme of
every screenshot in this manual; dark mode reads as backlit studio
gear, light mode as pale brushed aluminium, with identical behaviour
in both. First-time visitors inherit their OS's
`prefers-color-scheme`.

![Routing matrix in the **Light** theme.](../screenshots/01-routing.png){width=42%}

![Same matrix, **Dark** theme. Every surface, control and play-pad flips: white cards become deep navy, dark navy text becomes pale, accent pink and turquoise lift to a brighter tint to stay legible against the dark backdrop.](../screenshots/01-routing-dark.png){width=42%}

## The Controls

Every panel shares one small set of touch-first controls, from the
routing matrix through plugin config panels and controller surfaces
to **Settings**. Controls render against the active theme with
identical behaviour in both.

### Wheel

A vertical scrollable drum for discrete ordered values: note pitch,
BPM, MIDI channel, depth percentage. Drag up or down; the value
snaps to a tick, and the drum shows the range above and below.
Wheels may show labels (the **Scale Remapper** root selector shows
note names) or scaled values (the **CC LFO** **Frequency** wheel
stores `5`, displays `0.5 Hz`).

### Fader

A horizontal or vertical mixer-style slider for continuous "level"
values (volume, depth, mix, LFO rate); the value follows the finger
without lag and may display scaled.

*Fine* faders (marked per parameter by the plugin, e.g. the CC LFO's
Depth) step and display at fractional precision — `63.7` instead of
`64` — and follow a bound MIDI 2.0 controller at full resolution.

### Knob

The circular control on controller surfaces (chapter 8) only:
vertical drag changes the value, the pointer angle shows it,
mouse-wheel / two-finger scroll nudges one step. The matching "set
Ch / CC / On / Off" controls on a controller's *configuration* panel
are wheels — knobs are for performance, wheels for setup.

### Radio

Pill-shaped tap-to-select for small enumerations (waveform shape,
scale type, drop-button mode, arpeggiator pattern): the selected
pill is filled, the others outlined. Used wherever there are five
options or fewer.

### Step Editor

A step-sequencer row of cells: on/off dot, optional per-step note
offset, optional accent flag. Tap a cell to cycle its state; drag
vertically to set the note offset; a surrounding length parameter
greys out cells beyond it. The **Arpeggiator** cycles default → on →
on+accent → default; the **Euclidean** uses a four-state variant on
an algorithm-underlay preview (default → FORCE_ON → FORCE_ON+accent
→ FORCE_OFF → default); the **Tracker** a larger, specialised
variant (chapter 9).

### Cartesian Grid

The two-dimensional Step Editor of the **Cartesian** play surface
(chapter 9): the same cells — on/off dot, accent, per-cell
mini-wheel offset, identical tap cycle — in a square grid
(2×2 … 4×4). A size parameter sets the side length; the cell under
the X-clock playhead is outlined bright as the two clocks sweep the
grid.

### Curve Editor

A drawable 128-point canvas, one value per MIDI integer 0--127, used
by the **Velocity Curve** plugin. Draw with finger or stylus; the
curve re-samples cleanly between control points. Edge presets
(linear, ease-in, ease-out, S-curve, ...) set a starting curve to
draw on top of.

### XY Pad

A two-dimensional drag surface, used by the **XY 4** controller: the
X axis sends one CC, the Y axis another, each with independent MIDI
Learn. Pads can **spring** back to a home position (centre or
bottom-left) on release, with per-cell spring force, firing a CC on
the return home as well as when dragged away.

### Scope

A live waveform of plugin output: the **CC LFO** shows what it
generates, the **CC Smoother** two traces (in / out). Scopes scroll
right-to-left over a fixed window of about two seconds.

### Meter

A segmented level / beat indicator: the **Master Clock** shows the
beat within the bar on four segments; generic level meters scale
0--127 across the segments. No history, no scroll.

### Button

A rubber push-button with a coloured LED, in two flavours:

- **Latching** (default) — one tap toggles on, the next off; the
  LED follows the value. **Sync to Clock** (CC LFO), **Play**
  (Master Clock), **Send Clock** / **Send Trnsp.** (Tracker),
  **Retrig** (Euclidean), and similar.
- **Trigger** (momentary) — each tap fires an action, the LED
  flashes, the value self-resets. The red **Panic!** button and
  drop-button captures on controller surfaces.

Colour is a cue: green normal, yellow "are you sure?", red
destructive.

### Note Select

A wheel rendering note names (`C-2` to `G8`) instead of raw 0--127,
used wherever a parameter *is* a note — the **Hold** plugin's
release note, the **Note Splitter** split point.

### Channel Select

A wheel rendering MIDI channels 1--16 (the stored value is 0--15).

### Group

A labelled section grouping related parameters in a config panel;
layout only. The **Arpeggiator** and **Euclidean** each use a
`Setup` group (config-only) for channel filters, sync mode and
per-slot trigger notes; the **Tracker** uses **Track Channels**,
**Pattern Notes** and so on.

## MIDI Learn

The universal capture flow: every parameter that takes a MIDI source
(a mapping's source CC, a drop button's trigger note, an XY axis CC,
a controller cell's CC) has a Learn button. Tap it (it shows
**Listening...**), then play a note or move a knob; the first
recognised event fills the source fields and Learn turns off. Learn
disarms on its own if nothing arrives (10 s in the filter/mapping
panel, 30 s in the CC-binding popups); tap again to cancel early.

## CC Automation Feedback

When a hardware CC drives a plugin parameter (through a **CC → CC**
mapping, or a CC the plugin accepts directly), turning the hardware
knob animates the on-screen control in real time. Touching the UI
while the hardware is active resolves to exactly one value — no
fight between sources.

## The Four Ways an Overlay Closes

Every modal overlay accepts the same four dismiss gestures:

1. **Swipe down** on the overlay header.
2. **Tap the dark overlay** outside the panel.
3. **Press `ESC`** if a physical keyboard is connected.
4. **Tap the `X`** button at the top of the overlay.

There is no fifth way.

## Tick / Haptic Feedback

Wheels and faders click on each integer step — optional, via the
**knob / wheel tick sounds** toggle in **Settings → Display**.
