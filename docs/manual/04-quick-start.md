# Quick Start

From "no MIDI flowing" to "two devices routed through a plugin, saved
across reboots" in under ten minutes. Later chapters cover each topic
in depth. The Pi must already be imaged with the RaspiMIDIHub
installation (chapter 2).

## Boot the Pi

Plug in power. After roughly twenty seconds the red **PWR** LED turns
off and the green **ACT** LED settles to steady-on: the routing
service is running. The WiFi access point comes up at the same time,
broadcasting an SSID of the form `RaspiMIDIHub-XXXX`. (Full LED
table: chapter 2; if steady-on is never reached: chapter 14.)

## Join the Access Point

Open the WiFi settings on a phone, tablet, or laptop, find the
`RaspiMIDIHub-XXXX` SSID, and connect with the default password
`midihub1`. The captive portal opens the UI automatically on most
operating systems; if not, browse to `http://raspimidihub-<id>.local/`
or the gateway IP from the phone's WiFi-info screen.

::: warning
The default AP password is published in every copy of this manual.
Change it (**Settings → WiFi → AP Password**) before the unit leaves
a trusted environment.
:::

## Plug In Two MIDI Devices

Plug a MIDI keyboard (any USB device that *sends* events) and a synth
(any that *receives*) into the Pi's USB-A ports. They appear as rows
and columns in the **Routing** matrix within a second or two. New
devices arrive **disconnected**, so a device plugged in mid-set never
injects unexpected MIDI. Tap the cell where the keyboard row meets
the synth column; it lights up.

Play a key. The synth sounds; the cell shows a live rate-meter tick.
(For auto-routing of every new device, flip **Default routing** to
**Connect all** under **Settings → MIDI**.)

![The Routing matrix with plugins as rows and columns. Devices appear here as soon as they're plugged in.](../screenshots/01-routing.png){width=42%}

## Verify With the MIDI Monitor

Tap the keyboard's row header. The **MIDI Monitor** section of its
device-detail panel scrolls every event *from* the keyboard as a
readable line (e.g. `Note On ch1 C3 vel=100`). Tap the synth's column
header to confirm the destination receives the same events. If
nothing shows, see chapter 16 -- the first three items cover the
common "no MIDI" cases.

## Add a Plugin

Tap **Add** at the bottom of the matrix. The overlay lists plugins
(chapter 7), controllers (chapter 8), play surfaces (chapter 9),
and the Bluetooth scan (chapter 10). Pick **Arpeggiator** under
**Play** (Tracker, Arpeggiator, Euclidean, and Cartesian all render
fullscreen play surfaces; chapter 9). A new row and column appear
for the instance.

Plugins start *unconnected* by design (chapter 7). Tap the cell
where the keyboard row meets the Arpeggiator column to route the
keyboard *in*; tap where the Arpeggiator row meets the synth column
to route it *out*. Hold a chord -- the arpeggiator runs it.

Tap the **Play** tab. The Arpeggiator's surface opens fullscreen with
**Pattern**, **Rate**, and the four shapers laid out for one-finger
live use. The slide-up panel from the matrix offers the same plus the
**Setup** group (channel filters, sync mode), but the Play tab is the
home for in-set tweaks. Appendix A is the full parameter reference.

![The Arpeggiator play surface: Pattern + Rate wide wheels above the four shapers and the step grid.](../screenshots/arpeggiator-play.png){width=42%}

## Add a Controller

Tap **Add → Controller → Mixer 8**. A new **Controller** tab appears;
tap it. The fullscreen surface shows 24 knobs, 8 faders, and 16
buttons (default CCs 16--63 on channel 1).

Drag a fader. The matrix routes Mixer 8 like any other device -- pick
a destination column for the Mixer 8 row and the CCs flow. Long-press
one of the four drop buttons at the top to capture the current
control state; tap to fire. Chapter 12 has the full controller story.

![Mixer 8: 24 knobs, 8 faders, 16 buttons. Every cell is renameable and MIDI-Learnable.](../screenshots/controller-mixer-8.png){width=42%}

## Save the Routing

Everything so far lives in memory; the dark-red asterisk next to the
**Routing** icon is the reminder. Tap **Save Config** at the bottom
of the **Routing** tab. The asterisk disappears; the configuration
survives a reboot. To capture the setup as a JSON file -- backup,
sharing with another unit, before/after snapshots -- use **Export
Config**; **Import Config** restores it later (chapter 11).

## Change the AP Password

Open **Settings → WiFi → AP Password**, type a new password (at least
8 characters), and tap **Save**. The AP restarts; the phone
momentarily drops and reconnects with the new credentials.

## What to Read Next

- **Chapter 6** for the four-tab navigation.
- **Chapter 9** for the matrix gestures (single-tap context menu,
  copy/paste between cells, multi-port devices, offline rows).
- **Chapter 10** for channel and message-type filters and the five
  mapping types (Note → CC, Note → Note, CC → CC, ...).
- **Chapter 11** for the full plugin model; chapter 8 for
  controllers.
- **Chapter 17** when it comes time to update the software.
