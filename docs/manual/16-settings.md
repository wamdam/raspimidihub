# Settings

The **Settings** tab is a hub of sub-pages. The hub shows a card
per sub-page; tapping a card opens it under a `< Settings / <title>`
back-bar. The active sub-page is part of the URL
(`/settings/<section>`) and the bottom-nav remembers your last
sub-page across tab switches, same as Routing / Controller / Play.

The sub-pages:

| Sub-page | What lives there |
|---|---|
| **Sys Info** | Live system stats (version, CPU, RAM, latency, IPs), **Reload App**, **Reboot Pi** |
| **Network** | WiFi card with mode picker + home / AP credentials, USB-tether status, Ethernet config |
| **MIDI** | Default routing for newly-plugged-in devices (all-to-all / disconnected) |
| **Display** | Per-device browser preferences — activity bar, knob/wheel tick sounds, scroll-assist FABs, layout density |
| **Update** | Check GitHub, manage stored versions, install |
| **Plugin Control Mappings** | Flat editable table of every CC binding across every plugin instance and every controller cell |
| **Backup** | Restore or download a rolling save checkpoint (see **Backup** below) |
| **Network MIDI** | Export local devices as RTP-MIDI sessions for a second hub, Macs, iPads (see **Network MIDI** below) |

(plus **Spectator mirroring**, documented in its own section below.)

The dirty-state asterisk (chapter 6.4) does **not** track most
Settings changes. WiFi credentials, ethernet config, and the AP
password apply the moment you save them. The handful that *do* feed
the dirty-state model (the default-routing choice; the activity-bar
toggle) are called out in the relevant subsection.

## Spectator mirroring

![Settings → Spectator mirroring. The top card sets this device's name and copies its spectator URL; the bottom card lists other connected clients with one-tap mirror links.](../screenshots/36-settings-spectator.png){width=48%}

A way to stream a device's UI into OBS (or another browser tab) with
effectively zero latency, without screen-capture or `scrcpy`. Useful
for showcase videos where you want viewers to see what the phone is
doing -- including ripples where you tap -- but with crisp text and
correct resolution regardless of the recording setup.

The mechanism: every browser tab running RaspiMIDIHub already
maintains an SSE connection. Spectator mode adds a *mirror* URL --
`/?spectate=<conn_id>` -- that re-renders the same view as the
target connection, driven by a small "current UI state" channel
the source publishes (route, viewport, scroll, density, theme, all
overlay state, the toast, touch points). OBS Browser Source loads
that URL and CEF renders the app natively at any resolution -- no
video encoding on the phone, no encode latency.

### This device

- **Name shown to spectators** -- a human-readable label that other
  devices see in their list. Without a label they see only a short
  UUID; with one they see "Living-room phone". Per-device,
  persisted to localStorage. Empty is allowed.
- **Spectator URL** -- the URL another tab or OBS should open to
  mirror *this* device. Copy it via the button, or tap **Open
  mirror →** to test it in a new tab. The copied URL already
  includes the touch-ripple param `&touches=1`; remove it if you
  prefer a feed without the pointer trail.

The source device doesn't broadcast anything until a spectator
opens the URL. The server tells the source the moment the watcher
count goes from 0 to 1, the broadcaster attaches its DOM listeners,
and the source starts publishing ~30 Hz updates of viewport / scroll
/ touch / overlay state. When the spectator closes, the server tells
the source again and the listeners detach. Result: zero CPU and zero
bandwidth on phones nobody is mirroring.

### Spectate another device

A live list of every other RaspiMIDIHub tab currently connected to
the Pi. Each row shows the device's label (or short UUID), its last
known viewport size, and how recently it published state. Tapping
opens the mirror URL in a new tab.

The mirror tab opens at the source's viewport size, applies its
density and theme, mirrors every popup (context menu, CC-binding
popup with live wheel values, Cell-binding popup, Plugin Control
Mappings), the matrix horizontal scroll, the bottom-bar toast, and
the Save/Load/Panic button state. In the rack view it also mirrors
the cable highlight (the peek/spread fan when the source selects a
jack) and the live patch cable while the source is dragging one. A
touch overlay paints fading
ripples where the source is being touched (`?touches=1`, on by
default). If the source disconnects, the mirror shows a "Source
disconnected" notice and waits for it to come back.

### Presentation knobs

The mirror URL accepts four optional query params that control how
the mirror is *presented* (independent of what the source is showing):

- **`frame=1`** -- wrap the mirrored screen in a stylised phone
  bezel (rounded corners, speaker slot, home indicator). Default
  off, so the unconfigured URL looks like a naked feed.
- **`chroma=<color>`** -- paints the full-window backdrop *around*
  the mirror in the given colour (`#ff00ff`, `magenta`, `#00ff00`,
  any CSS colour). The frame and the mirror itself stay opaque, so
  an OBS Chroma Key filter on this colour leaves the device cleanly
  cut out. Default is the regular dark UI background -- chroma-key
  not requested.
- **`tilt-x=<deg>` / `tilt-y=<deg>`** -- rotate the framed device
  in 3D. Useful for a perspective shot that doesn't look like a flat
  webpage capture. Clamps at ±35°.

These are wired to a floating control panel that appears in the
top-right of the spectator URL: a frame on/off toggle, two tilt
sliders, a chroma colour picker with magenta / green / black /
default chips, **Reset tilt**, and **Copy URL**. The panel
auto-fades after 2.5 s of pointer inactivity; OBS Browser Source
doesn't deliver pointer events, so once the panel fades it stays
invisible in the recorded feed.

A faster way to set the tilt: just drag anywhere on the
backdrop. The URL rewrites live (via `replaceState`) so the final
adjusted view is shareable -- copy the URL after dragging and
paste it into OBS.

### Use in OBS

![Spectator mirror with `frame=1`, magenta chroma backdrop, and a moderate tilt. OBS's Chroma Key filter on the same colour leaves the framed device floating free of the background.](../screenshots/37-spectator-mirror.png){width=42%}

1. Open the spectator URL in a regular browser tab. Adjust the
   frame, tilt, and chroma until it looks the way you want.
2. Click **Copy URL** (or just copy from the address bar).
3. In OBS: **Sources → + → Browser**. Paste the URL. Set the
   width and height to match your scene region (e.g. 1080×1920 for
   a vertical phone capture).
4. If you set a chroma colour, add a **Chroma Key** filter on the
   Browser Source with the same colour and adjust similarity to
   taste -- the device floats free of any background.

Scrollbars are explicitly hidden across the whole spectator
document so OBS's CEF doesn't paint them onto the captured feed.

## Plugin Control Mappings

![Plugin Control Mappings sub-page: every CC binding across every plugin instance and every controller cell, one row each. Plugin params (Arpeggiator) and controller cells (Mixer 8) interleave; tap any row to open the matching popup.](../screenshots/31-settings-cc-bindings.png){width=48%}

A scroll of rows, one per CC binding across every plugin instance
on the Pi. Columns:

- **Plugin** -- the instance's display name (the one you set via
  the matrix row header, or the spawn-time default).
- **Param** -- the control's label. For controller cells: the
  cell label as edited in the device-detail panel; XY pads expand
  to two rows with `(X)` and `(Y)` suffixes.
- **Ch** -- channel (`Any` or 1..16).
- **CC** -- the CC number (or `—` for a cleared binding).

Tap any row to open the same long-press popup you'd get on the
control itself -- CcBinding for plugin params (chapter 11.7),
CellBinding for controller cells (chapter 12). Edit, MIDI Learn,
Reset to factory, Clear, Save. Cleared bindings render dimmed
with `—` in the CC column.

The table is live: any binding edit made from this page, from a
long-press popup, or via the REST API broadcasts `cc_map_changed`
SSE and the table refreshes within milliseconds. Renaming an
instance also reflects immediately via `plugin-changed`.

When there are no plugin instances yet, the page shows a
placeholder pointing at the Routing tab's **Add** button. There's
no "create" affordance here -- this is a viewer / editor over
existing instances, not a way to spawn new ones.

## Backup

A list of **rolling save checkpoints**. Every time you tap **Save
Config** (chapter 15.2) the unit writes a compressed copy of the
whole project state here, newest first; the last 50 are kept and
the oldest are pruned automatically. These are distinct from the
background **autosave** (chapter 15.6) -- backups are deliberate,
labelled checkpoints you can step back to.

At the top, a **Last autosave** line shows how long ago the
background resume-snapshot was last written (`30s ago`, `2 min
ago`, …) -- the same uptime-relative "n ago" the checkpoints use,
so it reads **before last reboot** for an autosave carried over
from a previous boot and **no autosave yet** before the first one
this session. It is a snapshot as of when the page loaded; the
**↻** button next to the heading re-reads it (and the list).

![Settings → Backup: the **Last autosave** line at the top (uptime-relative), then the rolling Save checkpoints newest-first — each with its `#number`, relative age, a one-line summary ("settings changed", "+1 connection", "(no changes)", "(initial)"), size, and Restore / Download.](../screenshots/32-settings-backup.png){width=42%}

Each row shows:

- **#number** -- a monotonic sequence number. It only ever
  increases, so it orders checkpoints even across reboots.
- **When** -- a relative "n ago" (`125s ago`, `3 min ago`, `2 h
  ago`). The appliance has no real-time clock, so this is measured
  against uptime, not a wall-clock date, and is only honest within
  the current boot. A checkpoint written before the last reboot
  shows **before last reboot** -- its `#number` is the only
  ordering you get.
- **Summary** -- a coarse one-line diff against the *previous*
  checkpoint. It counts only the four big categories (instruments,
  connections, mappings, device names), e.g. "+1 instrument · −18
  mappings". When none of those moved it reads **"settings
  changed"** if anything else differs (a renamed cell, a re-bound
  CC, a drop-button or theme tweak, an edited plugin parameter --
  things the counts don't track), or **"(no changes)"** if the
  snapshot is identical to the previous one; **"(initial)"** for
  the first checkpoint. The summary tells you roughly what a
  checkpoint captured, not which exact knob moved -- but the stored
  copy always holds the *full* state, so a Restore is faithful
  regardless of what the summary says.
- **Size** -- the compressed size of the stored copy.

Two actions per row:

- **Restore** replaces the live config with that checkpoint
  (plugins are stopped and recreated, routing is re-diffed onto
  the matrix). After confirming, the restored state is running but
  the dirty-state asterisk lights: tap **Save Config** to commit it
  as the new boot default, or **Load Config** to go back to your
  last Save. A Restore is autosaved immediately, so it survives a
  power cut even before you Save.
- **Download** saves that checkpoint to the browser as a plain
  JSON file (`raspimidihub-backup-NNNNN.json`) -- the same format
  **Export Config** produces, so it can be re-imported anywhere.

When no checkpoints exist yet (a fresh unit that has never been
Saved), the page shows a short placeholder.

## WiFi

A single card with the WiFi status badge plus rows for credentials
and mode.

### Status badge

Shows the current WiFi state in one line: AP mode SSID, client
mode SSID + IP, or "Bringing up..." during a transition. The badge
colour mirrors the operational state.

### Home WiFi

Two fields: **SSID** and **Password**. Saving the form provisions
the home network for the **WiFi for updates** and **WiFi always**
modes. The credentials are stored on the Pi as part of the saved
project state and *are* therefore included in **Export Config**
JSON files -- edit the WiFi section out before sharing an export
externally (chapter 15.8).

### AP Password

Sets the password for the RaspiMIDIHub access point. Minimum 8
characters (WPA2 requirement). Saving prompts a brief AP restart
-- the phone or laptop drops momentarily and reconnects with the
new password.

::: warning
The default AP password is `midihub1` and is published. Change it
the first time the unit is used in any environment outside a
personal home.
:::

### WiFi mode

Three radio buttons:

- **AP only** -- the default. The Pi broadcasts the AP and never
  associates as a client. No internet on the Pi.
- **WiFi for updates** -- the AP stays up at idle; when a software
  update is requested the Pi briefly flips `wlan0` from AP to
  client to fetch the deb, then flips back. The phone/laptop AP
  connection drops for ~30 seconds during the round-trip.
- **WiFi always** -- the AP is off. The Pi acts as a normal WiFi
  client. Use this when the Pi is on the home or venue network
  permanently.

### USB-tethered phone link

When a phone is USB-tethered to the Pi (chapter 17.4), the card
surfaces the tethered URL as a clickable "Open
http://x.y.z.w/ on your phone" row -- handy for switching the
browser to the faster link without leaving the AP.

## Ethernet (eth0)

Configures the wired interface. Two modes:

- **DHCP** -- the Pi accepts an address from the network's DHCP
  server. This is the default and the right answer for most home
  routers.
- **Static** -- four fields (Address, Netmask, Gateway, DNS) for
  manual configuration.

When `eth0` is connected, the card lists **every** IPv4 address the
interface currently holds, just above the Mode pulldown. An
interface often has more than one: a DHCP lease *and* a
`169.254.x.x` link-local address, the latter tagged
*(link-local)*. This is the quickest way to confirm a direct
hub-to-hub cable came up -- if the only address shown is a
`169.254.x.x`, the two ends self-assigned link-local because no
DHCP server answered (see chapter 17's *direct cable* note), and
they can still reach each other.

## Network MIDI

Shares local MIDI devices over the network as standard RTP-MIDI
(AppleMIDI) sessions -- the concept, the clients that can connect
and the wire details live in chapter 17's *Network MIDI* section.
This page is the control surface:

- **Share devices over the network** -- the master toggle.
  Advertising (and, with a peer hub, discovery) runs only while
  this is on.
- **Exported devices** -- one checkbox per local device that is
  currently online. Ticking it advertises the device as
  `"<name> @<hostname>"`; the sub-line below an exported device
  shows the advertised session name and how many network clients
  are connected to it right now.
- **Remote hubs** -- everything discovered on the network, grouped
  per hub. Peer-hub sessions mirror into the matrix automatically;
  each row shows a state dot (green connected / amber connecting /
  grey discovered), the measured link latency, and a
  Mirror / Unmirror button. Sessions from Macs, iPads or DAWs are
  listed under *Other sessions* and only mirror when you add them.
- **Manual peers** -- an IP/hostname list for networks where mDNS
  multicast doesn't get through (routed LANs, some managed
  switches). The hub polls each entry directly for its exported
  devices; everything else behaves exactly as with discovery.

Like the WiFi settings, everything here applies immediately and
does **not** feed the dirty-state asterisk -- the export list is
an appliance setting, saved the moment you change it, and it
survives reboots on its own.

On systems without the `python3-zeroconf` package the page shows
an "unavailable" hint instead of the toggles.

Screenshots needed:

- `16-settings-network-midi.png` -- the Network MIDI sub-page with
  the master toggle on, two devices exported and one showing a
  connected participant. Needs real hardware (a connected RTP-MIDI
  client); not yet covered by the scripted screenshot scenes.

## MIDI Routing

A single radio with two options:

- **Connect all** -- new USB devices are auto-routed to and from
  every existing device. The default. Plug-and-play.
- **None** -- new USB devices appear in the matrix but with no
  connections. The user wires them up by hand.

This choice **does** participate in the dirty-state model -- it
is part of the project state and survives **Save Config**.

The plugin "starts unconnected" rule (chapter 11.3) is
independent of this setting; plugins always start with no
connections regardless of the **MIDI Routing** choice.

## Display

Three toggles, a layout selector and a theme picker, all marked
**(this device only)** in the heading -- every Display preference
is browser-local; nothing on this card travels with **Save /
Export Config**.

- **MIDI activity bar** -- shows or hides the persistent
  two-source activity bar above the bottom navigation.
- **Knob / wheel tick sounds** -- enables a small click on each
  integer step of a wheel or fader drag.
- **Scroll-assist buttons** -- shows round accent-coloured
  floating buttons in the top-right (▲) and bottom-right (▼) of
  any overflowing page. Each tap scrolls roughly 200 px in that
  direction; the buttons only appear when content actually runs
  past the viewport edge. Default on.
- **Layout density** -- a dropdown with **Default** and **Small
  screen (tighter)**. Small mode shrinks the header, bottom
  navigation, page padding, and the per-plugin controller bar so
  more content fits on a 360-px-wide phone. The same hub can
  render in Default on a tablet and Small on a phone without one
  overriding the other.
- **Theme** -- a dropdown listing every theme present in
  `themes/manifest.json`. **Light** is the daytime default
  (every screenshot in this manual is captured in Light); **Dark**
  is the night-rig alternative. The choice is browser-local,
  persists across reloads, and seeds the PWA status-bar colour
  so the mobile chrome matches the theme on the next page load.
  First-time visitors with no saved preference inherit their
  OS's `prefers-color-scheme` setting. The picker hides itself
  if only one theme is installed. See chapter 4 §"Themes" for a
  side-by-side comparison of how the matrix looks in each mode.

## Stats

A pocket-sized health dashboard. Live readouts:

- **Loop lag** -- how long the asyncio loop took to run its last
  cycle on the reserved CPU 3. Around 2 ms is the normal state and
  anything under 5 ms is fine; sustained values above 5 ms
  indicate something is starving the loop.
- **MIDI in → out latency** -- the time from a USB MIDI input
  event arriving to its corresponding output event leaving. Probed
  with a synthetic round-trip; the typical value is under 2 ms
  for filtered/mapped connections.
- **Control in → MIDI out latency** -- the round-trip from a UI
  control change to the resulting MIDI event leaving on a routed
  port. Useful for understanding controller responsiveness.
- **Process CPU %** -- the routing service's own CPU usage.
- **ALSA ports** -- sequencer ports held by the hub's own ALSA
  client, against the kernel's per-client cap of 254. Every
  filtered or mapped connection holds two. The value turns red at
  80% of the cap; at the cap, new filters can no longer be
  created. A steadily climbing count with a stable setup would
  indicate a port leak -- worth a reboot and a bug report.
- **SSE rate / backlog** -- events per second going out over the
  SSE channel, and the backlog if the browser has fallen behind.

The Stats card is the first place to look when the unit feels
sluggish. Chapter 20 lists what each metric means when it is out
of the normal range.

## Software Versions

A list of every locally-stored `.deb`, newest first, each with its
changelog and an **Install** button.

**Check GitHub for newer versions** auto-downloads anything newer
than the running build, keeps the latest three on disk, and lets
you install offline with one tap. A live progress bar plus a
hopping "we're alive" dot reassures during the install. The
180-second service watchdog forces the Pi back to AP mode if the
orchestrator hangs.

The retention policy (latest three) means once anything has been
fetched, re-installs work fully offline -- no internet path needed.

The version installer also handles the
`raspimidihub-rosetup` package alongside the main
`raspimidihub` package. Both are kept on disk and offered
together.

See chapter 17 for the three internet paths the install can use
(ethernet, USB tethering, WiFi for updates) and the trade-offs of
each.

## PWA Install

A single **Install App** button. Tapping it triggers the
operating system's "Add to Home Screen" flow:

- **iOS Safari** -- the OS dialog appears; confirm to install.
- **Chrome on Android** -- the install prompt appears at the
  bottom of the screen.

After install, RaspiMIDIHub launches from a home-screen icon and
runs fullscreen, with no URL bar and no browser chrome. The PWA
state survives reboots and software updates.

## Reload App

A single **Reload App** button. Force-reloads the SPA bundle,
bypassing the browser cache. Use this when the header version
badge shows the "stale, reload" hint, or when troubleshooting a
UI quirk that smells like a stale bundle. The button busts mobile
Safari's bf-cache reliably -- a regular pull-to-refresh does not.

## System

A single **Reboot** button. Triggers a clean shutdown and reboot
of the Pi. The web UI shows a "Rebooting..." screen and reconnects
automatically when the unit is back up.

## The Safety Net

If the Pi is in WiFi-client mode and the configured network goes
away (router rebooted, taken out of range, password changed
elsewhere), the service falls back to AP mode within roughly 90
seconds. The fallback is automatic; no user action is required.

For a hard reset of the WiFi state from a console (USB keyboard
+ HDMI display, or SSH from another network):

```
sudo reset-wifi
```

This forces the Pi to AP mode with default credentials. Use it
when even the fallback has failed or when access to the unit has
been locked out.

