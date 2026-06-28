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
read-only filesystem and the isolated-core reservation assume a
multi-core ARMv8 system.

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

Ethernet on RaspiMIDIHub carries IP only -- never raw 5-pin / USB
MIDI signalling. It is used for software updates (chapter 17.3) and,
since the addition of **Network MIDI**, for **RTP-MIDI (AppleMIDI)**
sessions -- MIDI tunnelled inside IP packets to Macs, iPads, and other
hubs over the LAN. So MIDI *does* travel over the wire, as RTP-MIDI
rather than a direct MIDI cable. See **Settings → Ethernet**
(chapter 16.2) for the IP configuration and **Settings → Network MIDI**
for sessions.

## Bluetooth

The Pi 4B, Pi 5, and Pi Zero 2 W have on-board Bluetooth and use
it for BLE-MIDI peripherals (chapter 14). The Pi 3B and 3B+ also
have on-board Bluetooth and work for BLE-MIDI, though the radio is
older and connection ranges are shorter.

On the Pi 3B, Pi 3B+, and Pi Zero 2 W, Bluetooth and WiFi share a
single combo chip and antenna. Running the access point (the
normal mode) loads the 2.4 GHz band continuously, and on some of
these boards that stops BLE-MIDI peripherals from connecting at
all -- the link is aborted the instant it forms. It is unit-
dependent: some Pi 3 boards are fine, others fail every time. For
a rig that depends on BLE-MIDI, use a Pi 4 or Pi 5, whose separate
radios coexist cleanly. Chapter 14's *Limits* and *Troubleshooting*
cover how to confirm and work around it.

External Bluetooth USB dongles are not supported -- the bridge
binds to the on-board adapter only.

## WiFi

The Pi 4B, Pi 5, Pi Zero 2 W, Pi 3B+, and Pi 3B all have on-board
WiFi. The Pi 4B, Pi 5, and Pi 3B+ are dual-band (2.4 GHz and
5 GHz); the Pi 3B and Pi Zero 2 W are 2.4 GHz only.

The access point runs on 2.4 GHz by default, and can be switched to
5 GHz on a dual-band Pi (Settings → Network → *AP radio*, chapter
16). Running the AP on 5 GHz keeps it off the 2.4 GHz band that
Bluetooth shares, which is the fix for the BLE-MIDI coexistence
trouble on the combo-chip boards (see *Bluetooth* above and chapter
14, *Limits*).

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

The recommended path is to flash the **RaspiMIDIHub bootstrap
image** with **Raspberry Pi Imager**. The image is a fresh
Raspberry Pi OS Lite (64-bit, Trixie) with a oneshot that
downloads and installs the latest RaspiMIDIHub release on first
boot. Re-flashing the same image at any later time installs the
newest RaspiMIDIHub release automatically -- the image stays
valid across many software releases.

Step by step, from a sealed Pi to a running unit:

1. **Install Raspberry Pi Imager** from
   [raspberrypi.com/software](https://www.raspberrypi.com/software/).
   Pi Imager is free, official, and runs on macOS, Windows, and
   Linux.
2. **Download the RaspiMIDIHub OS image** -- the file
   `raspimidihub-bootstrap-YYYY-MM-DD.img.xz` (~535 MB) -- from
   the [Image release page](https://github.com/wamdam/raspimidihub/releases/tag/image-2026-04-21).
3. **Open Pi Imager.** Click **CHOOSE OS** → scroll to the
   bottom → **Use custom**, and select the downloaded `.img.xz`.
   Click **CHOOSE STORAGE** and pick the SD card. Click **NEXT**.
   Pi Imager asks "would you like to apply OS customisation
   settings?" -- click **EDIT SETTINGS**. The first-boot install
   needs internet, so set at least one network path here:
    - **WiFi SSID + password** -- the cleanest option; sets the
      regulatory country at the same time. The image works around
      a known Pi Imager / Trixie bug that otherwise leaves the
      WiFi radio rfkilled (see chapter 17.5).
    - **Or plug in ethernet** when you boot the Pi -- in that
      case the WiFi field can be left empty.

   Also set in the wizard:
    - **Username and password** (or an SSH public key under
      "Use password authentication / Allow public key
      authentication").
    - **Keyboard layout** and region.

4. **Save** the settings → **YES** → **YES** to write. Eject the
   card, insert into the Pi, power on.
5. **Wait roughly 5 minutes.** The green ACT LED progresses
   through five distinct patterns:

   +------+-------------------+------------------------+
   | Step | LED pattern       | Stage                  |
   +:====:+:==================+:=======================+
   |  1   | Slow heartbeat    | Booting, waiting for   |
   |      | (lub-dub)         | network                |
   +------+-------------------+------------------------+
   |  2   | Medium blink      | Downloading the        |
   |      | (\~2 Hz)          | installer              |
   +------+-------------------+------------------------+
   |  3   | Fast blink        | `apt install` running  |
   |      | (\~5 Hz)          | -- *don't unplug*      |
   +------+-------------------+------------------------+
   |  4   | Solid on          | Install complete,      |
   |      |                   | rebooting in 2 s       |
   +------+-------------------+------------------------+
   |  5   | Steady on (after  | Routing service        |
   |      | reboot)           | running, AP up         |
   +------+-------------------+------------------------+

   If you instead see **one short flash per second with a long
   dark gap**, the install failed. SSH in (the wizard's user
   account still works) and run
   `journalctl -u raspimidihub-bootstrap` to see why.

6. **Join the AP** `RaspiMIDIHub-XXXX` from a phone or laptop
   with the default password `midihub1`. The captive portal
   opens the UI.
7. **Plug in MIDI devices** and continue with chapter 7 (Quick
   Start) or chapter 16 (Settings) to change the AP password
   first.

::: tip
The customization wizard's user, SSH key, locale, and timezone
flow through cloud-init on the first boot. They survive the
RaspiMIDIHub install -- the wizard's user account is the one you
will SSH in with later for maintenance (chapter 17).
:::

::: tip
Pi Imager 2.0 and newer also support a "custom repository" URL
under **⚙ Settings**. Pointing it at
`https://raw.githubusercontent.com/wamdam/raspimidihub/main/image/os-list.json`
makes **RaspiMIDIHub OS** show up directly in the OS picker --
no need to download the file manually. The option is hidden on
Pi Imager 1.x, which is why the steps above use the direct-
download path: it works on every Pi Imager version.
:::

### Alternative: manual installation on existing Raspberry Pi OS Lite

If you already have a fresh Raspberry Pi OS Lite system running
(installed via Pi Imager *without* the RaspiMIDIHub repository),
you can install RaspiMIDIHub from the shell:

```
curl -sL https://github.com/wamdam/raspimidihub/releases/latest/download/install.sh | bash
sudo reboot
```

This is exactly what the bootstrap image runs on first boot --
the two paths converge on the same packages and the same
post-install state.

::: warning
Install on a **fresh** Raspberry Pi OS Lite image only. The
`raspimidihub-rosetup` package converts the filesystem to
read-only and may conflict with other software. Do not install
on a Pi you use for other purposes.
:::

