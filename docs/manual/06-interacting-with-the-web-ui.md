# Interacting with the Web UI

Everything you do on RaspiMIDIHub happens in a browser. This chapter
covers the connection flow, the four-tab layout, the universal
gestures, URL routing, and the indicators that appear on every
screen. The chapters that follow assume the vocabulary defined here.

## First Connection

By default the Pi is in **AP-only** mode and broadcasts an SSID of
the form `RaspiMIDIHub-XXXX` with password `midihub1`. Joining the
SSID triggers the captive portal on most operating systems and the
configuration UI opens automatically. If the captive portal does not
fire, two manual entry points work:

- `http://raspimidihub-<id>.local/` -- mDNS hostname. Works out of the
  box on macOS, iOS, modern Android, and Linux distributions running
  avahi-daemon. Windows needs Bonjour to be installed.
- The AP gateway IP shown in the phone's WiFi-info screen (for
  example `http://172.24.1.1/`).

Chapter 17 documents the alternative connectivity modes (USB
tethering, ethernet, WiFi-always client mode) for when the AP is not
the appropriate default.

## The Four Tabs

The bottom navigation has up to four tabs:

| Tab | Path | Purpose |
|------|------|---------|
| **Routing** | `/routing` | The connection matrix and everything attached to it |
| **Controller** | `/controller` | Fullscreen tap-to-play surfaces |
| **Play** | `/play` | The play-surface plugins (Tracker, Arpeggiator, Euclidean, Cartesian) |
| **Settings** | `/settings` | System configuration |

Two of these tabs are conditional:

- The **Controller** tab only appears when at least one controller
  instance has been added (chapter 12).
- The **Play** tab only appears when at least one play-surface
  plugin (Tracker, Arpeggiator, Euclidean, Cartesian) has been added
  (chapter 13).

The **Routing** and **Settings** tabs are always there. The
**Routing** tab is the home screen of the appliance.

Saving and reloading project state -- which would be a "Presets"
tab in some applications -- happens on the **Routing** tab itself
via the **Save / Load / Export / Import Config** buttons at the
bottom of the matrix (chapter 9.8 and chapter 15).

## URL Routing

The SPA uses real URL routing. Every tab has a path, the open
device-detail panel is a path, and the browser back/forward buttons
work as expected. Bookmarks survive reboots -- pointing a bookmark
at `http://raspimidihub-<id>.local/settings` opens the UI directly on the
Settings page.

## The Dirty-State Asterisk

A dark-red `*` next to the **Routing** icon in the bottom navigation
lights up whenever the in-memory state diverges from the saved
config: a new plugin, a rewired cell, a renamed device, a touched
filter, anything. Tap **Save Config** at the bottom of the **Routing**
tab to clear it.

The asterisk is a reminder that *the running unit is not yet what
the next boot will look like*. It is the single most important
indicator in the UI and worth memorising.

## The Header Badge

The header reads `RaspiMIDIHub v<version> · <name>`, where `<name>`
is the hub's WiFi name -- the access-point SSID with the redundant
`RaspiMIDIHub-` prefix stripped, so the factory default shows just
its MAC suffix (e.g. `735C`) and a custom SSID shows verbatim. It is
the same identifier you pick the hub by in the WiFi list, so two
hubs on one bench are told apart at a glance. Change it by setting a
custom **AP SSID** under **Settings → WiFi** (the `735C` suffix
itself is the wlan0 MAC and not separately editable). The name is
re-read on every (re)connection, so if you move a phone from one
hub's access point to another's the header updates to the hub you
are actually talking to -- it never keeps showing the previous
hub's name.

When the server has been redeployed and the SPA running in the
browser is older than the backend, a small red dot appears next to
the title. Tapping it reloads the SPA. The same effect is available
manually from **Settings → Reload App**, which busts mobile Safari's
bf-cache reliably.

## Universal Gestures

The whole UI is touch-first. Five gestures recur everywhere:

- **Single tap** -- open a menu, fire an action, toggle a value.
  Tapping a matrix cell opens its context menu; tapping a button
  fires it; tapping a toggle flips it.
- **Long-press** -- capture-style actions. Long-press a drop button
  to capture the controller's current state; long-press a mapping
  row for Edit / Copy / Remove.
- **Drag** -- move a fader, scroll a wheel, draw a curve.
- **Swipe-down** -- dismiss the topmost overlay. Equivalent to tap-
  on-the-dark-overlay or pressing `ESC`.
- **Vertical scroll** -- on long panels (the **Settings** page is
  the obvious one), normal browser scrolling works.

Some controls also respond to keyboard input. The Tracker has its
own keyboard scheme on the **Play** tab (chapter 13 and appendix
D); `ESC` is the universal "close the topmost overlay" key
everywhere.

## The Captive Portal

The Pi's HTTP server answers the captive-portal probe URLs that
Android, iOS, macOS, and Windows use to detect "is this network
real?" Each probe returns a redirect to the RaspiMIDIHub root, which
is the cue for the OS to pop the UI in a sandboxed browser.

If the captive portal does not fire (some phones cache "this network
has no internet" too aggressively, and some carrier WiFi policies
suppress the probe), use the manual entry URLs from section 6.1.

## PWA Install

The web UI is a Progressive Web App. **Settings → PWA Install**
exposes the "Install App" button that prompts the operating system
to add RaspiMIDIHub to the home screen. The installed app launches
fullscreen, with no URL bar, and behaves like a native app for
performance use. On iOS the install flow runs through Safari's
Share → Add to Home Screen; on Android through Chrome's install
prompt.

## The MIDI Activity Bar

Above the bottom navigation, a one-line activity bar shows the two
most recent non-clock MIDI events, one per source side. Device names
are truncated to fit. Entries auto-expire after two seconds of
inactivity. Clock events do **not** appear here -- the matrix's
pulsing-play icon is the clock indicator instead. Toggle the bar in
**Settings → Display**.

## Reconnect After Network Disruption

If the Pi flips WiFi modes (chapter 17), reboots, or the browser tab
is left idle long enough for the OS to drop the connection, the SPA
shows a banner offering to reconnect. The reconnect itself is
automatic over SSE; the banner is just acknowledgement.

