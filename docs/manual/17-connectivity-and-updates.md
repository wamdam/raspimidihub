# Connectivity and Software Updates

How the hub reaches the network and gets new software. The choice
of cable or radio determines whether the AP drops during an
install.

## Connectivity Modes

Three WiFi modes are selectable in **Settings → WiFi → WiFi mode**.

### AP only (default)

The Pi broadcasts the `RaspiMIDIHub-XXXX` SSID and never joins
another network -- no internet on the Pi, the right default for
stage / studio use. The AP runs on 2.4 GHz by default; a dual-band
Pi can move it to 5 GHz (**Settings → Network → AP radio**,
chapter 16), freeing the band the onboard Bluetooth shares --
worth doing when BLE-MIDI is unreliable (chapter 14, *Limits*).
Updates need another internet path (17.3, 17.4) or a temporary
mode switch.

### WiFi for updates

The AP stays up at idle; an install flips `wlan0` to client mode,
fetches the deb, and flips back, dropping the phone or laptop AP
connection roughly 30 seconds each way (the Pi has one wireless
radio). If anything hangs in client mode, the 180-second watchdog
(17.7) brings the AP back.

### WiFi always

The AP is off; the Pi is a normal WiFi client on the configured
home network -- for fixed installations. No captive portal: reach
the UI via `http://raspimidihub-<id>.local/` or the static / DHCP
IP shown on the home router.

## The Captive Portal

The Pi answers the captive-portal probes of Android, iOS, macOS,
and Windows, popping the UI in a sandboxed browser. If the portal
does not fire (probe answer cached as "no internet", or suppressed
by MDM / carrier WiFi policy), enter manually:

- `http://raspimidihub-<id>.local/` -- the mDNS hostname.
- The AP gateway IP (in the phone's WiFi-info screen).

## Ethernet

The simplest update path. Plug a cable into the RJ45 port; the Pi
acquires DHCP (or the static config from **Settings → Ethernet**)
and Settings shows the resulting URL. The AP stays up -- AP and
wired interface are independent. **Recommended for headless
setups.**

## USB Tethering

A phone on a USB-A port with Personal Hotspot (iOS) or USB
Tethering (Android) enabled provides internet without touching
`wlan0`. Settings shows the tethered URL as a clickable link; the
AP stays up. Unplugging the phone returns the internet state to
"none".

## mDNS

Each hub advertises a unique mDNS name: `raspimidihub-<id>.local`,
where `<id>` is the four-character hardware code shown in the
title bar, WiFi name, and captive-portal page (e.g.
`raspimidihub-735C.local`) -- two hubs on one network never
collide. Resolution requirements:

- **macOS, iOS** -- native, no setup.
- **Linux** -- avahi-daemon must run (default on most
  distributions).
- **Modern Android** -- Android 12+ for most apps; some browsers
  still need the IP.
- **Windows** -- needs Apple Bonjour (free from Apple's site, or
  bundled with iTunes).

Without mDNS, use the gateway IP (AP mode) or the static / DHCP IP
from the router's DHCP table (WiFi-always mode).

## Network MIDI -- Sharing Devices over the Network

**Settings → Network MIDI** exports any local MIDI device as a
standard **RTP-MIDI (AppleMIDI)** session, advertised over mDNS as
`"TX-7 @raspimidihub-<id>"`; the unique suffix means a peer always
resolves a device to the right hub. Anything that speaks RTP-MIDI
can connect:

- **a second RaspiMIDIHub** -- an Ethernet cable (up to 100 m) or
  any shared network;
- **macOS / iOS** -- Audio MIDI Setup's *MIDI Network Setup*
  (macOS) and RTP-MIDI-capable iOS apps, no extra software;
- **Linux** -- `rtpmidid` (and compatible tools).

Turn on the master toggle, then tick the devices to share -- one
plugin pair for a point-to-point tunnel, or everything. Several
clients can connect to one exported device at once. Exports are
saved in the config; the advert exists only while the device is
present -- unplug and the session leaves the network, replug and
it returns. Notes, CCs, clock and SysEx all cross the wire;
wired-LAN latency is well under a millisecond.

### Mirroring -- the two-hub scenario

When two RaspiMIDIHubs see each other, the peer's exported devices
**mirror automatically** into the local matrix as violet network
devices, grouped under a collapsible `@hubname` header (chapter 9,
*Remote Hub Groups*). No pairing flow: export on one side, route
on the other. Each side controls its own export list; the
receiving side can **Unmirror** per session (device's header menu)
and re-add from the Add menu.

Mirrored devices are full matrix citizens -- filters, mappings,
renames, clock routing -- and connections are saved under a stable
identity that survives reboots and IP changes on both ends. An
offline peer's devices show as offline rows and recover by
themselves.

Sessions from Macs, iPads or DAWs are **not** mirrored
automatically (a studio WLAN full of them would flood the matrix);
they are listed under Settings → Network MIDI and in the Add menu,
one tap to mirror.

Loops cannot form: a mirrored device cannot be re-exported, and a
hub never mirrors its own sessions.

### The direct cable, and life without mDNS

A direct Ethernet cable between two hubs needs no router: each hub
keeps an IPv4 link-local address (`169.254.x.y`) on `eth0` at all
times, in every mode, alongside any DHCP lease or static
address -- so two cabled hubs always share a subnet. The hub keeps
looking for a DHCP server; plugging into a real network later
picks up a lease automatically.

Where multicast is filtered (routed LANs, some managed switches),
add the other hub's IP or hostname under **Manual peers**; the hub
asks the peer directly for its exports and everything else behaves
as with discovery.

### Failure behaviour

A cable pull or peer power-cut is detected within ~30 seconds;
mirrored devices drop to offline and the hub keeps retrying --
replugging restores everything without a tap. Silently vanished
clients are dropped from an exported session after 60 seconds.

Transport is plain UDP on ports 5004 and up (one even/odd port
pair per exported device); discovery is the same mDNS as
`raspimidihub-<id>.local`. Needs `python3-zeroconf` (a standard
dependency of the deb); when missing, the Settings page says so
instead of offering the toggle.

## Software Updates: The Three Paths

**Check GitHub for newer versions** in **Settings → Software
Versions** runs the same pipeline regardless of internet path:

1. Resolve GitHub.
2. List the latest releases.
3. Download anything newer than the running build.
4. Keep the newest three `.deb` files on disk; delete older ones.
5. Install on demand from the local cache.

| Path | AP impact | Recommended for |
|------|-----------|-----------------|
| **Ethernet** (17.3) | AP stays up | Headless / fixed installations |
| **USB tethering** (17.4) | AP stays up | Field updates when no ethernet |
| **WiFi for updates** (17.1) | AP drops ~30 s twice | When neither cable is available |

Once a deb is on disk, **Install** needs no internet at all.

## The 180-Second Watchdog

When `wlan0` is in client mode (WiFi for updates mid-update, or
WiFi always), a 180-second watchdog force-restarts the routing
service if anything hangs -- association without a DHCP lease, a
lease without DNS, an install stuck partway, or the update
orchestrator wedged. After it fires the Pi reverts to AP mode;
reconnect and retry, or check the logs.

## The 90-Second AP Fallback

In **WiFi always** mode, a lost client connection (router reboot,
out of range, password changed elsewhere) makes the hub fall back
to AP mode within roughly 90 seconds, with the configured AP
credentials. No user action required.

## Console Recovery

A console (USB keyboard + HDMI, or
`ssh user@raspimidihub-<id>.local`) reaches the underlying Pi OS.
The bootstrap image ships with **sshd enabled**, using the user
and key/password from the Pi Imager wizard -- which also makes a
failed first boot diagnosable (chapter 3). Commonly useful:

- `sudo reset-wifi` -- forces AP mode with default credentials;
  use when the WiFi state is wedged or access is locked out.
- `journalctl -u raspimidihub -e` -- tails the routing service log
  (BLE issues, update failures, unexpected restarts).
- `sudo mount -o remount,rw / && sudo dpkg --configure -a && sudo
  mount -o remount,ro /` -- reconciles a half-applied dpkg state
  when **Install** keeps failing with `E: dpkg was interrupted…`;
  only needed on builds older than the one that runs this
  automatically before every install.

## Updating the rosetup Package

**Settings → Software Versions** lists both Debian packages:
`raspimidihub` (routing service + web UI) and
`raspimidihub-rosetup` (read-only filesystem hardening). rosetup
updates via the same install flow but needs a reboot to apply (the
read-only mount layer re-initialises at boot).
