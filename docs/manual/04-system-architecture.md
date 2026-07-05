# How It All Fits Together

A tour of the moving parts. Nothing here is required to operate the
unit; it pays off when diagnosing edge cases.

## The Top-Level Block Diagram

![System architecture block diagram](../screenshots/architecture-block-diagram.svg)

The MIDI path on the left is the *hot* path -- every MIDI event
goes through it. The web UI on the right is the *cold* path --
configuration changes flow through it but never sit in the
per-event critical path.

## How MIDI Flows

Every MIDI event takes one of two paths:

- **Direct path.** A connection without filter or mapping is wired
  at the kernel level; events pass through no RaspiMIDIHub code.
  Added latency is effectively zero (sub-microsecond). Shown as a
  *red* cell in the matrix.
- **Filtered path.** A connection with a channel filter, a
  message-type filter, or any mapping is received, transformed,
  and re-emitted in software. Added latency is roughly 1--3 ms.
  Shown as a *purple* cell.

Toggling a filter off can shave a couple of milliseconds on a
latency-critical chain.

**MIDI 2.0 (UMP).** On kernels with MIDI 2.0 support (chapter 21,
*MIDI 2.0 Kernel Requirements*) the ALSA sequencer speaks the
Universal MIDI Packet format natively and converts between MIDI 1.0
and 2.0 clients per delivery: direct-path routing between two
MIDI 2.0 devices preserves full resolution, and mixed 1.0/2.0
wiring needs no special handling. The hub reads each device's UMP
*endpoint* description at scan time and models its ports from the
function blocks (chapter 9); discovery is automatic.

## Plugins Are Virtual Devices

Plugin instances appear in the matrix alongside USB devices and
Bluetooth peripherals -- one input port, one output port, the same
routing, filtering, and mapping behaviour. The play surfaces
(Tracker, Arpeggiator, Euclidean, Cartesian), the controllers
(Mixer 8, FX 6, Performance 16, XY 4), and every other plugin live
in the same routing graph; no plugin has a special-case path.

## The Bluetooth MIDI Bridge

The built-in BLE-MIDI bridge handles pairing, GATT subscription,
and BLE-MIDI framing, exposing each paired peripheral as a virtual
MIDI device indistinguishable from a USB device. Chapter 14 covers
pairing, reconnection, and persistence across power-off.

## The Network MIDI Bridge

The RTP-MIDI (AppleMIDI) counterpart to the BLE bridge. *Export*:
each shared local device is advertised over mDNS as its own
RTP-MIDI session; any standard participant (a second hub, macOS,
iOS, `rtpmidid`) can connect. *Mirror*: sessions exported by a peer
hub appear as virtual MIDI devices in the matrix. The
implementation is in-process and journal-free (RFC 6295's recovery
journal targets lossy open-internet paths; on a wired LAN the
engine's panic / note-release machinery covers the residual risk).
Discovery uses `python3-zeroconf` alongside the avahi daemon.
Chapter 17's *Network MIDI* section covers the user-facing side.

## The Web UI Connection

The configuration UI is a single-page web application served by the
Pi and rendered on your phone or tablet; the Pi needs no display.
The browser talks to the Pi over two channels: **HTTP** for actions
(Save Config, filter changes, plugin parameter edits) and
**Server-Sent Events** for live state (matrix changes, monitored
MIDI events, plugin scope values) pushed over a long-lived stream.

### Themes

Two themes, **Light** and **Dark**, selectable from Settings →
Display. Light is the daytime default and the theme of every
screenshot in this manual. First-time visitors inherit their OS's
`prefers-color-scheme`.

![Routing matrix in the **Light** theme.](../screenshots/01-routing.png){width=42%}

![Same matrix, **Dark** theme. Every surface, control and play-pad flips: white cards become deep navy, dark navy text becomes pale, accent pink and turquoise lift to a brighter tint to stay legible against the dark backdrop.](../screenshots/01-routing-dark.png){width=42%}

Every colour is a CSS custom property in
`static/themes/_tokens.css`; each theme is one CSS file in
`static/themes/` overriding tokens in a `[data-theme="<id>"]`
block, missing tokens falling through to the dark default. The
picker reads `static/themes/manifest.json` and writes the chosen id
to `<html data-theme="…">` and local storage; canvas surfaces read
live token values via `lib/theme.js`, so they reskin too. A third
theme is one CSS file plus one manifest row.

### Spectator Mirroring

The spectator feature -- one browser tab or OBS Browser Source
rendering the same UI as another connected device -- lives in its
own module: server side `src/raspimidihub/spectator.py` (mirror
state, watcher map, `spectator-state` fan-out filter, the
`/api/spectator/*` routes), client side `static/lib/spectator/`.
New surfaces mirror correctly via two opt-in patterns: popovers
call `useSharedUiState(key, init)` in place of `useState`, and
scrollable containers carry `data-spectator-scroll="<key>"`.

## Configuration Persistence

State on the boot partition (FAT32) comes in three tiers: a
**working copy** in RAM (tmpfs) that the running unit reads and
writes; the **persistent copy** (`config.json` + `config.json.bak`)
written by **Save Config**; and a rolling **autosave** (two
ping-pong slots) of the live edited state plus rolling **backups**
of each Save. Boot prefers the newest valid autosave, then
`config.json`, then `.bak`, then defaults.

**Save Config** writes atomically (temp file, flush, rename), and
the autosave is double-buffered and gzip-CRC validated -- a power
cut mid-write cannot corrupt state, and a hard cut resumes the last
*edited* state, not just the last Save (chapters 18.3 and 15.6).
Both root and boot partition are mounted **read-only** in normal
operation; save flows briefly remount `/boot/firmware` rw, sync,
and remount it ro, while the root stays ro throughout (chapter 18).

## The Reserved CPU

The routing service's main loop runs on a CPU core isolated from
the rest of the OS -- no other userland process or kernel timer is
scheduled there, so unrelated system activity cannot disturb the
MIDI path. This is why the Stats card in **Settings** reads
sub-millisecond loop lag even on a busy unit.

## The Two Packages

| Package | Role |
|---------|------|
| `raspimidihub` | The routing service, the plugin host, the web UI, the access point |
| `raspimidihub-rosetup` | Read-only filesystem hardening and CPU isolation |

`raspimidihub-rosetup` is technically optional -- the service runs
on a normal writable root -- but the read-only setup is what makes
the appliance power-safe, so the install one-liner installs both.
