# Hardware and Connectors

RaspiMIDIHub is a software appliance -- it runs on stock Raspberry
Pi hardware that you provide. This chapter lists the supported
hardware, describes the physical connectors used, documents the
on-board LED status pattern, and walks through the first physical
setup of the unit.

## Supported Raspberry Pi Models

+-------------+------------------+-------+----------------------------------------------+
| Model       | Ports            | Max   | Notes                                        |
+:============+:=================+:=====:+:=============================================+
| Pi Zero 2 W | 1 (OTG + hub)    | 3--4  | Single USB bus; entry-level                  |
+-------------+------------------+-------+----------------------------------------------+
| Pi 3B+      | 4                | 4     | Shared USB / Ethernet bus; budget option     |
+-------------+------------------+-------+----------------------------------------------+
| Pi 4B       | 4 (2 × USB 3.0)  | 8+    | **Recommended**                              |
+-------------+------------------+-------+----------------------------------------------+
| Pi 5        | 4 (2 × USB 3.0)  | 8+    | Best performance, fastest BLE                |
+-------------+------------------+-------+----------------------------------------------+

The Pi 4B is the sweet spot for most users -- four USB ports, two
of them USB 3.0, plenty of CPU for plugin work, BLE-MIDI on board,
and widely available. The Pi 5 is the right answer if the rig is
heavy on plugins (multiple Trackers, drop-button-heavy controllers)
or BLE-MIDI is in the critical path. The Pi 3B+ and Pi Zero 2 W
work but constrain the device count.

The Pi 1, Pi 2, and original Pi Zero are **not** supported: the
read-only filesystem and the CPU 3 reservation assume a multi-core
ARMv8 system.

## Storage

The Pi boots from a microSD card. Requirements:

- **Capacity** -- 4 GB minimum, 8 GB or 16 GB recommended.
- **Class** -- A1 or better. The endurance class (A2) is *not*
  required; the read-only filesystem means the card is rarely
  written.
- **Brand** -- any reputable brand. Counterfeit cards are the
  most common source of "the Pi doesn't boot" reports; buy from
  a known vendor.

A 4 GB card is enough; software updates store the latest three
debs (chapter 17.6) which fit in well under 100 MB.

## USB-A Ports -- MIDI Devices

The Pi 4B and Pi 5 expose four USB-A ports, two of which are USB
3.0 (blue) and two USB 2.0 (black). MIDI devices work equally well
on either; USB 3.0 ports are sometimes preferable for class-
compliant audio interfaces that *also* expose MIDI ports, but for
MIDI-only devices the speed difference is irrelevant.

The Pi 3B+ exposes four USB 2.0 ports sharing a single bus with
the Ethernet adapter. The Pi Zero 2 W has a single micro-USB OTG
port; a powered USB hub is required to attach multiple MIDI
devices.

Hot-plug is supported (chapter 18.6.3). Plugging or unplugging a
device during operation updates the matrix within a second or
two.

## USB-A Ports -- Tethered Phone

Any USB-A port doubles as a tethered-phone input (chapter 17.4).
Plug a phone with Personal Hotspot / USB Tethering enabled and
the Pi acquires internet over the USB-CDC interface. The phone
keeps the AP running; the Pi keeps the AP up alongside the
tethered link.

## Power

- **Pi 4B / Pi 5** -- USB-C, official 5V/3A (Pi 4) or 5V/5A (Pi 5)
  power supply. Underpowered supplies cause undervolt warnings in
  the logs and possible USB device drop-outs.
- **Pi 3B+** -- micro-USB, 5V/2.5A.
- **Pi Zero 2 W** -- micro-USB OTG, 5V/2.5A.

The included Raspberry Pi Foundation power adapter is the
reference; phone chargers and laptop USB-C ports are not always
adequate, particularly when the Pi powers bus-powered MIDI
devices.

## Ethernet (RJ45)

The Pi 4B and Pi 5 expose a Gigabit Ethernet port; the Pi 3B+
exposes Fast Ethernet. The Pi Zero 2 W has no built-in Ethernet
(a USB-Ethernet dongle is supported on any of the USB-A ports).

Ethernet on RaspiMIDIHub is used exclusively for IP connectivity
-- specifically, for software updates (chapter 17.3). The Pi
*never* uses ethernet for MIDI. See **Settings → Ethernet**
(chapter 16.2) for the IP configuration.

## Bluetooth

The Pi 4B, Pi 5, and Pi Zero 2 W have on-board Bluetooth and use
it for BLE-MIDI peripherals (chapter 14). The Pi 3B+ also has
on-board Bluetooth and works for BLE-MIDI, though the radio is
older and connection ranges are shorter.

External Bluetooth USB dongles are not supported -- the bridge
binds to the on-board adapter only.

## WiFi

The Pi 4B, Pi 5, Pi Zero 2 W, and Pi 3B+ all have on-board WiFi.
The Pi 4B and Pi 5 support 2.4 GHz and 5 GHz; the Pi 3B+ and Pi
Zero 2 W support 2.4 GHz only.

The on-board radio is used both for the access point and for
client mode (chapter 17.1). It is one radio shared between two
modes, which is the reason the **WiFi for updates** mode briefly
drops the AP while in client mode.

## Audio Output

RaspiMIDIHub does not currently use the Pi's analog audio output
or HDMI audio. The appliance is MIDI-only: it routes events; the
audio is generated by the connected synths and the receiving
gear.

(USB audio interfaces with class-compliant audio support are
*present* on the system but unused by RaspiMIDIHub -- there is
no plugin or feature that emits audio at this time.)

## On-Board LEDs

The Pi exposes two LEDs, repurposed by the routing service for
appliance status (chapter 18.5):

| Green ACT | Red PWR | Meaning |
|-----------|---------|---------|
| Steady on | Off | Running normally |
| Flickering | Off | MIDI activity |
| Fast blink | On | Config fallback (error) |
| Off | Default | Service stopped |

The "fast blink, PWR on" pattern is the visual cue that the
routing service started but could not parse its config and fell
back to a clean state. Look at `journalctl -u raspimidihub -e`
over SSH to see why.

## First-Time Setup

Step by step, from a sealed Pi to a running unit:

1. **Image the SD card** with Raspberry Pi OS **Lite** (Trixie or
   Bookworm). The graphical "Desktop" image works but installs a
   lot of unneeded packages; Lite is leaner. The Raspberry Pi
   Imager tool is the easiest path.
2. **Configure SSH and a hostname** in the Imager's advanced
   options. RaspiMIDIHub uses `raspimidihub.local` as its mDNS
   name; the OS hostname does not matter.
3. **Boot the Pi** from the SD card with a wired ethernet or a
   home WiFi network reachable for the install -- the install
   pulls debs from GitHub.
4. **Run the install one-liner** over SSH:
   ```
   curl -sL https://github.com/wamdam/raspimidihub/releases/latest/download/install.sh | bash
   sudo reboot
   ```
5. **Wait for the reboot.** After roughly 30 seconds the green
   ACT LED settles to steady-on. The AP starts broadcasting
   `RaspiMIDIHub-XXXX`.
6. **Join the AP** from a phone or laptop with the default
   password `midihub1`. The captive portal opens the UI.
7. **Plug in MIDI devices** and continue with chapter 7 (Quick
   Start) or chapter 16 (Settings) to change the AP password
   first.

::: warning
Install on a **fresh** Raspberry Pi OS Lite image only. The
`raspimidihub-rosetup` package converts the filesystem to
read-only and may conflict with other software. Do not install
on a Pi you use for other purposes.
:::

