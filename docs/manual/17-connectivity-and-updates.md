# Connectivity and Software Updates

How the Pi talks to the rest of the network, and how it gets new
software when AP-mode is the default. The two topics are bundled
here because the update path *is* the connectivity question: the
choice of cable or radio determines whether the AP has to be
dropped during the install.

## Connectivity Modes

Three WiFi modes are selectable in **Settings → WiFi → WiFi
mode**.

### AP only (default)

The Pi broadcasts the `RaspiMIDIHub-XXXX` SSID and never
associates as a client. No internet on the Pi. This is the right
default for stage / studio use where the Pi is meant to be a
self-contained appliance.

Software updates from AP-only require an alternative internet
path (ethernet or USB tethering -- sections 17.3 and 17.4) or a
temporary mode switch.

### WiFi for updates

The AP stays up at idle; the Pi briefly flips `wlan0` from AP to
client when a software-update install is requested, fetches the
deb, then flips back. The phone or laptop AP connection drops for
roughly 30 seconds during the round-trip and again on the way
back. The Pi has only one wireless radio, so this trade-off is
intrinsic.

A 180-second watchdog force-restarts the routing service if
anything hangs while `wlan0` is in client mode -- the AP always
comes back even if the update step itself fails.

### WiFi always

The AP is off. The Pi acts as a normal WiFi client on the
configured home network. Use this for fixed-installation rigs
where the Pi is on the venue or home network all the time.

In this mode, the Pi has no captive portal; reach the UI via
`http://raspimidihub.local/` or the static / DHCP IP shown on the
home router.

## The Captive Portal

The Pi answers the captive-portal probe URLs that Android, iOS,
macOS, and Windows use to detect "is this network real, or is it
a hotel-style captive network?" Each probe is redirected to the
RaspiMIDIHub root, which signals to the OS that the network is a
captive portal and to pop the configuration UI in a sandboxed
browser.

If the captive portal does not fire (some phones cache "this
network has no internet" too aggressively; some MDM / carrier
WiFi policies suppress the probe), use the manual entry URLs:

- `http://raspimidihub.local/` -- the mDNS hostname.
- The AP gateway IP (shown in the phone's WiFi-info screen).

## Ethernet

The simplest update path. Plug a cable into the Pi's RJ45 port
and the Pi acquires a DHCP address (or applies the static config
set in **Settings → Ethernet**). The Settings page surfaces the
resulting URL.

The AP stays up the whole time; the phone or laptop connection to
the Pi is unaffected. **Recommended for headless setups** where
swapping WiFi modes is inconvenient.

The Pi keeps the AP up regardless of ethernet state -- the AP and
the wired interface are independent.

## USB Tethering

A phone plugged into one of the Pi's USB-A ports with Personal
Hotspot / USB Tethering enabled provides internet without
touching `wlan0`. The kernel brings up a `usb0` (Android) or
`enx…` (some iPhones / Android devices) interface and the phone
hands the Pi an IP via DHCP over USB.

Settings shows the tethered URL as a clickable link so you can
switch the browser to the faster link, but you do not have to --
the AP stays up either way. Works on iOS (Personal Hotspot via
USB) and Android (USB Tethering toggle).

The tethered phone provides internet to the Pi only while it is
plugged in; unplugging it takes the Pi back to AP-only internet
state (which is "none").

## mDNS

The Pi advertises itself as `raspimidihub.local` over multicast
DNS. Resolution requirements:

- **macOS, iOS** -- native, no setup.
- **Linux** -- avahi-daemon must be running (default on most
  distributions).
- **Modern Android** -- works on Android 12+ for most apps; some
  browsers still require manual IP entry.
- **Windows** -- Apple Bonjour must be installed (free download
  from Apple's site, or bundled with iTunes).

If mDNS is unavailable on the network or the client, fall back to
the gateway IP (AP-mode) or the static / DHCP IP from the
router's DHCP table (WiFi-always mode).

## Software Updates: The Three Paths

The **Check GitHub for newer versions** button in **Settings →
Software Versions** runs the same fetch-and-install pipeline
regardless of which internet path is available. The pipeline:

1. Resolve GitHub.
2. List the latest releases.
3. Download anything newer than the running build.
4. Keep the newest three `.deb` files on disk; delete older ones.
5. Install on demand from the local cache.

The three paths the Pi can use to *reach* GitHub:

| Path | AP impact | Recommended for |
|------|-----------|-----------------|
| **Ethernet** (17.3) | AP stays up | Headless / fixed installations |
| **USB tethering** (17.4) | AP stays up | Field updates when no ethernet |
| **WiFi for updates** (17.1) | AP drops ~30 s twice | When neither cable is available |

Once a deb is on disk, **Install** applies it offline regardless
of which path fetched it.

## The 180-Second Watchdog

When `wlan0` is in client mode (WiFi for updates mid-update, or
WiFi always), a 180-second watchdog force-restarts the routing
service if anything hangs. The watchdog covers cases where:

- The client-mode association succeeds but the DHCP lease fails.
- The DHCP lease succeeds but DNS does not resolve.
- The install step itself hangs partway through.
- The orchestrator script enters an unexpected state.

After the watchdog fires, the Pi reverts to AP mode and the AP
comes back up. The user reconnects to the AP and tries again or
checks the logs.

## The 90-Second AP Fallback

A more conservative safety net: in **WiFi always** mode, if the
client-mode connection is lost (router reboot, taken out of
range, password changed elsewhere), the routing service falls
back to AP mode within roughly 90 seconds. The AP comes back up
with the configured AP credentials. No user action is required to
trigger the fallback.

## Console Recovery

A console (USB keyboard + HDMI display, or SSH from another
network with `ssh user@raspimidihub.local`) gives access to the
underlying Pi OS. Two commands are commonly useful:

- `sudo reset-wifi` -- forces AP mode with default credentials.
  Use when the WiFi state is wedged or when access to the unit
  has been locked out.
- `journalctl -u raspimidihub -e` -- tails the routing service
  log. Useful for diagnosing BLE issues, update failures, or any
  unexpected service restart.

## Updating the rosetup Package

Both Debian packages -- `raspimidihub` (the routing service +
web UI) and `raspimidihub-rosetup` (the read-only filesystem
hardening) -- are listed in **Settings → Software Versions**.
Updating the rosetup package is supported via the same install
flow but requires a reboot to apply (the read-only mount layer
re-initialises at boot).

