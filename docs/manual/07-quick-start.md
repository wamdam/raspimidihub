# Quick Start

This chapter walks from "no MIDI flowing" to "two devices routed
through a plugin, saved across reboots" in under ten minutes. Each
step is one paragraph; nothing is skipped, but nothing is repeated
either -- each later chapter goes into the same topic in depth.

The walkthrough assumes the Pi has already been imaged with the
RaspiMIDIHub installation (chapter 3). If you have not done that yet,
do that first and come back here.

## Boot the Pi

Plug power into the Pi. After roughly twenty seconds the red **PWR**
LED turns off and the green **ACT** LED settles to a steady-on state.
That is the signal that the routing service is running. The WiFi
access point comes up at the same time and starts broadcasting an
SSID of the form `RaspiMIDIHub-XXXX`. (See chapter 3 for the full LED
table; see chapter 18 for what happens when the steady-on state is
*not* reached.)

## Join the Access Point

On a phone, tablet, or laptop, open the WiFi settings, find the
`RaspiMIDIHub-XXXX` SSID, and connect with the default password
`midihub1`. The captive portal opens the configuration UI
automatically on most modern operating systems; if it does not, point
a browser at `http://raspimidihub.local/` or at the gateway IP shown
in the phone's WiFi-info screen.

::: warning
The default AP password is published in every copy of this manual.
Change it from **Settings → WiFi → AP Password** before the unit
is taken out of a trusted environment.
:::

## Plug In Two MIDI Devices

Plug a MIDI keyboard (or any USB MIDI device that *sends* events) and
a synth (or any USB MIDI device that *receives* events) into two of
the Pi's USB-A ports. They appear as rows and columns in the
**Routing** matrix within a second or two. The default routing is
*all-to-all*, so the cell at the intersection of the keyboard row and
the synth column is already lit -- the devices are already talking.

Play a key on the keyboard. The destination synth makes sound; the
matrix cell briefly shows a live rate-meter tick.

![The Routing matrix with plugins as rows and columns. Devices appear here as soon as they're plugged in.](../screenshots/01-routing.png){width=42%}

## Verify With the MIDI Monitor

Tap the keyboard's row header to open its device-detail panel. The
**MIDI Monitor** section scrolls every event coming *from* the
keyboard as a human-readable line (for example, `Note On ch1 C3
vel=100`). Tap the synth's column header to confirm the destination
is receiving the same events.

If nothing shows on either side, see chapter 20 -- the first three
items there cover the most common "no MIDI" cases.

## Add a Plugin

Tap **Add** at the bottom of the matrix. The Add overlay opens with a
list of available plugins (chapter 11), controllers (chapter 12),
play surfaces (chapter 13), and the Bluetooth scan section
(chapter 14). Pick **Arpeggiator**. A new
row and column appear in the matrix for the new plugin instance.

Plugins start *unconnected* by design (see chapter 11 for why). Tap
the cell where the keyboard row meets the Arpeggiator column to route
the keyboard *into* the arpeggiator. Tap the cell where the
Arpeggiator row meets the synth column to route the arpeggiator
*out* to the synth. Now hold a chord on the keyboard -- the
arpeggiator runs it.

Tap the Arpeggiator's row or column label to open its config panel
and play with **PATTERN**, **RATE**, and **GATE**. Changes take
effect immediately. Appendix A is the full parameter reference for
every plugin.

![The Arpeggiator's config panel opens inline. Tap any control to edit; CC-automated parameters animate live.](../screenshots/09-plugin-arpeggiator.png){width=42%}

## Add a Controller

Tap **Add → Controller → Mixer 8**. A new **Controller** tab appears
in the bottom navigation. Tap it; the fullscreen surface shows 24
knobs, 8 faders, and 16 buttons (default CCs 16--63 on channel 1).

Drag a fader. The matrix routes Mixer 8 just like any other device
-- pick a destination column for the Mixer 8 row and the CCs flow.
Long-press one of the four drop buttons at the top of the surface
to capture the current state of the controls; tap to fire. Chapter
12 has the full controller story.

![Mixer 8: 24 knobs, 8 faders, 16 buttons. Every cell is renameable and MIDI-Learnable.](../screenshots/controller-mixer-8.png){width=42%}

## Save the Routing

Everything you have done so far lives in memory. The dark-red
asterisk next to the **Routing** icon in the bottom navigation is the
reminder. Open the **Routing** tab and tap **Save Config** at the
bottom. The asterisk disappears; the configuration now survives a
reboot.

To capture the same setup as a JSON file -- for backup, for sharing
with another RaspiMIDIHub unit, or for keeping a "before/after"
snapshot of an experiment -- use **Export Config**. **Import
Config** restores it later. See chapter 15.

## Change the AP Password

Open **Settings → WiFi → AP Password**, type a new password (at
least 8 characters), and tap **Save**. The AP restarts -- your phone
will momentarily drop and reconnect with the new credentials. Done.

## What to Read Next

- **Chapter 6** if the four-tab navigation is not yet familiar.
- **Chapter 9** for the routing matrix gestures (single-tap context
  menu, copy/paste between cells, multi-port devices, offline rows).
- **Chapter 10** for filtering MIDI channels and message types,
  and for the four mapping types (Note → CC, CC → CC, ...).
- **Chapter 11** for the full plugin model, and chapter 12 for
  controllers.
- **Chapter 17** when it comes time to update the software.

