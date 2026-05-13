# How It All Fits Together

A short tour of the moving parts under the hood, written for the
user who wants to understand *why* things behave the way they do.
Nothing in this chapter is required to operate the unit; everything
in it pays off when diagnosing edge cases.

## The Top-Level Block Diagram

![System architecture block diagram](../screenshots/architecture-block-diagram.svg)

The MIDI path on the left is the *hot* path -- every MIDI event
goes through it. The web UI on the right is the *cold* path --
configuration changes flow through it and result in routing
updates, but it does not sit in the per-event critical path.

## How MIDI Flows

Every MIDI event takes one of two paths through the appliance:

- **Direct path.** A connection without any filter or mapping is
  wired at the kernel level. Events do not pass through any
  RaspiMIDIHub code at all -- the kernel forwards them straight
  from the source to the destination. Added latency is
  effectively zero (sub-microsecond).
- **Filtered path.** A connection with a channel filter, a
  message-type filter, or any mapping is handled in software. The
  event is received, transformed, and re-emitted. Added latency
  is roughly 1--3 ms.

The routing matrix shows the difference visually: a *red* cell
is the direct path; a *purple* cell is the filtered path. Most
of the time the latency difference does not matter, but the rule
is worth knowing: filters and mappings have a cost; toggling a
filter off temporarily can shave a couple of milliseconds on a
latency-critical chain.

## Plugins Are Virtual Devices

Plugin instances appear as rows and columns in the routing matrix
alongside USB devices and Bluetooth peripherals. From the matrix's
point of view there is no difference -- a plugin has an input port
and an output port, just like a USB synth has an input port and an
output port. The same routing, filtering, and mapping behaviour
that works on USB devices works on plugins.

The Tracker, the controllers (Mixer 8, FX 6, Performance 16,
XY 4), and every other plugin are implemented this way. There is
no special-case path for any plugin -- they all live in the same
routing graph.

## The Bluetooth MIDI Bridge

BLE-MIDI peripherals do not appear to the operating system as MIDI
devices automatically. RaspiMIDIHub includes its own BLE-MIDI
bridge that handles pairing, GATT subscription, and the BLE-MIDI
framing, then exposes each paired peripheral as a virtual MIDI
device in the routing matrix. From there, the peripheral is
indistinguishable from a USB device.

Chapter 14 covers the user-facing side of BLE-MIDI (pairing,
reconnection, persistence across power-off).

## The Web UI Connection

The configuration UI is a single-page web application served by
the Pi. When you open the AP and the captive portal pops the UI,
your browser is loading a small set of static files and then
talking to the Pi over two channels:

- **HTTP** for actions: every tap of Save Config, every change to
  a filter, every plugin parameter edit goes out as an HTTP
  request.
- **Server-Sent Events** for live state: every change in the
  matrix, every MIDI event the UI is asked to show, every plugin
  scope value is pushed back over a long-lived event stream.

The web UI runs on the Pi, but the *rendering* happens on your
phone or tablet. The Pi does not need a display of its own.

## Configuration Persistence

Two filesystem locations hold the project state:

- A **working copy** in RAM (tmpfs). This is what the running
  unit reads from and writes to.
- A **persistent copy** on the boot partition (FAT32). This is
  what loads on next boot.

Tapping **Save Config** copies the working state to the
persistent location with an atomic write (write a temp file,
flush to disk, rename). Pulling the power mid-edit cannot
corrupt the persistent copy because the rename either completes
or doesn't.

The boot partition stays writable by design; the main root
filesystem stays read-only during normal operation. Chapter 18
documents the read-only model.

## The Reserved CPU

The routing service runs its main loop on a CPU core that is
isolated from the rest of the operating system. The kernel does
not schedule any other userland process or kernel timer on that
core. The effect is that loop-lag spikes from unrelated system
activity (apt updates, log rotation, scheduled backups) cannot
disturb the MIDI path.

The reserved core is what makes the Stats card in **Settings**
typically read sub-millisecond loop lag even on a busy unit.

## The Two Packages

The appliance ships as two Debian packages:

| Package | Role |
|---------|------|
| `raspimidihub` | The routing service, the plugin host, the web UI, the access point |
| `raspimidihub-rosetup` | Read-only filesystem hardening and CPU isolation |

The `raspimidihub-rosetup` package is technically optional -- the
service runs without it on a normal writable root. In practice the
read-only setup is what makes the appliance power-safe, so the
install one-liner installs both.

