# Hardware and Connectors

RaspiMIDIHub runs on stock Raspberry Pi hardware that you provide.

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

The Pi 4B suits most users; choose a Pi 5 for plugin-heavy rigs or
BLE-MIDI in the critical path. The Pi 1, Pi 2, and original Pi Zero
are **not** supported: the read-only filesystem and isolated-core
reservation require a multi-core ARMv8 system.

## Storage

The Pi boots from a microSD card:

- **Capacity** -- 4 GB minimum (enough -- updates keep only the
  latest three debs, chapter 13.7); 8 or 16 GB recommended.
- **Class** -- A1 or better; endurance class A2 is unnecessary on
  the read-only filesystem.
- **Brand** -- reputable vendors; counterfeit cards are the top
  cause of "the Pi doesn't boot".

## USB-A Ports -- MIDI Devices

Pi 4B and Pi 5: two USB 3.0 (blue) and two USB 2.0 (black) ports;
MIDI works equally well on either (USB 3.0 only matters for audio
interfaces that also expose MIDI ports). Pi 3B+: four USB 2.0 ports
on one bus shared with Ethernet. Pi Zero 2 W: one micro-USB OTG
port; use a powered USB hub for multiple devices.

Hot-plug is supported (chapter 14.7.3); the matrix updates within
seconds.

## USB-A Ports -- Tethered Phone

Any USB-A port accepts a tethered phone (chapter 13.4): enable
Personal Hotspot / USB Tethering and the Pi gets internet over USB
while its AP stays up.

## Power

- **Pi 4B / Pi 5** -- USB-C, official 5V/3A (Pi 4) or 5V/5A (Pi 5)
  supply.
- **Pi 3B+ / Pi Zero 2 W** -- micro-USB, 5V/2.5A.

Use the official adapter: phone chargers and laptop USB-C ports can
be inadequate with bus-powered MIDI devices attached, causing
undervolt warnings and USB drop-outs.

## Ethernet (RJ45)

Gigabit on Pi 4B and Pi 5, Fast Ethernet on Pi 3B+, none on the
Pi Zero 2 W (a USB-Ethernet dongle works). Ethernet carries IP
only, never raw MIDI signalling: software updates (chapter 13.3)
and **Network MIDI** -- RTP-MIDI (AppleMIDI) sessions to Macs,
iPads, and other hubs. Configure under **Settings → Ethernet**
(chapter 12.5) and **Settings → Network MIDI**.

## Bluetooth

All supported models have on-board Bluetooth for BLE-MIDI
peripherals (chapter 10); the Pi 3B / 3B+ radio has shorter range.

On the Pi 3B, 3B+, and Pi Zero 2 W, Bluetooth and WiFi share one
chip and antenna; the AP's continuous 2.4 GHz load can abort
BLE-MIDI connections the instant they form (unit-dependent). For a
BLE-dependent rig use a Pi 4 or Pi 5, whose separate radios coexist
cleanly; chapter 10's *Limits* and *Troubleshooting* cover
confirmation and workarounds.

External Bluetooth USB dongles are not supported -- the bridge
binds to the on-board adapter only.

## WiFi

All supported models have on-board WiFi; the Pi 4B, Pi 5, and
Pi 3B+ are dual-band (2.4 and 5 GHz), the Pi 3B and Pi Zero 2 W
2.4 GHz only.

The AP defaults to 2.4 GHz; a dual-band Pi can switch it to 5 GHz
(Settings → Network → *AP radio*, chapter 12), freeing the band
Bluetooth shares -- the fix for the coexistence trouble above. One
radio serves both AP and client mode (chapter 13.1), which is why
**WiFi for updates** briefly drops the AP.

## Audio Output

Not used -- the appliance is MIDI-only. USB audio interfaces are
recognised for their MIDI ports only.

## On-Board LEDs

The routing service repurposes the Pi's two LEDs for status
(chapter 14.5):

| Green ACT | Red PWR | Meaning |
|-----------|---------|---------|
| Steady on | Off | Running normally |
| Flickering | Off | MIDI activity |
| Fast blink | On | Config fallback (error) |
| Off | Default | Service stopped |

"Fast blink, PWR on" means the service could not parse its config
and fell back to a clean state; check
`journalctl -u raspimidihub -e` over SSH.

## First-Time Setup

Flash the **RaspiMIDIHub bootstrap image** with **Raspberry Pi
Imager**: Raspberry Pi OS Lite (64-bit, Trixie) plus a first-boot
installer that always fetches the latest release, so the same image
stays valid across releases.

1. **Install Raspberry Pi Imager** (free) from
   [raspberrypi.com/software](https://www.raspberrypi.com/software/).
2. **Download the image** --
   `raspimidihub-bootstrap-YYYY-MM-DD.img.xz` (~535 MB) -- from
   the [Image release page](https://github.com/wamdam/raspimidihub/releases/tag/image-2026-04-21).
3. In Pi Imager: **CHOOSE OS** → **Use custom** → the downloaded
   `.img.xz`; **CHOOSE STORAGE** → the SD card → **NEXT** →
   **EDIT SETTINGS**. The install needs internet, so set one path:
    - **WiFi SSID + password** -- cleanest; also sets the
      regulatory country and works around a Pi Imager / Trixie bug
      that otherwise leaves WiFi rfkilled.
    - **Or plug in ethernet** at boot; the WiFi field can stay
      empty.

   Also set a **username and password** (or an SSH public key),
   keyboard layout, and region.

4. **Save** → **YES** → **YES** to write. Insert the card, power
   on.
5. **Wait roughly 5 minutes.** The green ACT LED progresses
   through five patterns:

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

   **One short flash per second with a long dark gap** means the
   install failed: SSH in with the wizard's account and run
   `journalctl -u raspimidihub-bootstrap`.

6. **Join the AP** `RaspiMIDIHub-XXXX` (default password
   `midihub1`); the captive portal opens the UI.
7. **Plug in MIDI devices** and continue with chapter 4 (Quick
   Start), or change the AP password first (chapter 12).

::: tip
The wizard's user, SSH key, locale, and timezone survive the
install; use that account for later SSH maintenance (chapter 13).
:::

::: tip
Pi Imager 2.0+ accepts a "custom repository" URL under
**⚙ Settings**: point it at
`https://raw.githubusercontent.com/wamdam/raspimidihub/main/image/os-list.json`
and **RaspiMIDIHub OS** appears in the OS picker. Pi Imager 1.x
hides the option, hence the direct download above.
:::

### Alternative: manual installation on existing Raspberry Pi OS Lite

On a fresh Raspberry Pi OS Lite system:

```
curl -sL https://github.com/wamdam/raspimidihub/releases/latest/download/install.sh | bash
sudo reboot
```

This is exactly what the bootstrap image runs on first boot.

::: warning
Install on a **fresh** Raspberry Pi OS Lite image only. The
`raspimidihub-rosetup` package converts the filesystem to read-only
and may conflict with other software; do not install on a Pi used
for other purposes.
:::
