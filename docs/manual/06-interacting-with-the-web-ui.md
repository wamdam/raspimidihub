# Interacting with the Web UI

Everything on RaspiMIDIHub happens in a browser. This chapter covers
the connection flow, the tabs, the universal gestures, and the
always-visible indicators; later chapters assume this vocabulary.

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

Chapter 17 covers the alternative connectivity modes (USB tethering,
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
(chapter 12); **Play** only when a play-surface plugin has been added
(chapter 13). **Routing** and **Settings** are always present;
**Routing** is the home screen. Saving and reloading project state
happens there, via the **Save / Load / Export / Import Config**
buttons at the bottom of the matrix (chapter 9.8 and chapter 15).

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
13, appendix D); `ESC` closes the topmost overlay everywhere.

## The Captive Portal

The hub answers the captive-portal probes of Android, iOS, macOS, and
Windows with a redirect to its root, cueing the OS to open the UI in
a sandboxed browser. If the portal does not fire (some phones cache
"no internet" too aggressively; some carrier WiFi policies suppress
the probe), use the URLs from section 6.1.

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

If the hub flips WiFi modes (chapter 17), reboots, or the browser
drops the connection, the SPA shows a banner offering to reconnect;
the reconnect itself is automatic.
