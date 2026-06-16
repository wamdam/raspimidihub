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

## Network MIDI -- Sharing Devices over the Network

**Settings → Network MIDI** can *export* any local MIDI device as
a standard **RTP-MIDI (AppleMIDI)** session. Each exported device
is advertised over mDNS under its own name -- `"TX-7 @<hostname>-<id>"`,
where `<id>` is the hardware suffix from the WiFi name (e.g.
`@raspimidihub-735C`). The suffix keeps two hubs with the default
hostname distinct on the wire -- without it both would advertise
`raspimidihub.local`, and a peer could resolve a device to the wrong
hub. Anything that speaks RTP-MIDI can connect to it:

- **a second RaspiMIDIHub** -- the long-cable scenario: two hubs
  joined by an Ethernet cable (up to 100 m) or any shared network,
  routing MIDI between stages or rooms;
- **macOS / iOS** -- exported devices appear in Audio MIDI Setup's
  *MIDI Network Setup* directory (macOS) and in RTP-MIDI-capable
  iOS apps, with no extra software;
- **Linux** -- `rtpmidid` (and compatible tools) discover and
  connect to exported sessions.

Turn the feature on with the master toggle, then tick the devices
to share. The export list is the curation step: export a single
plugin pair and you have a point-to-point tunnel; export
everything and the far end sees each device individually. Several
clients can be connected to the same exported device at once --
a Mac and a peer hub, for example.

### Mirroring -- the two-hub scenario

When two RaspiMIDIHubs see each other, the peer's exported
devices **mirror automatically**: each appears in the local
routing matrix as a violet network device, grouped under a
collapsible `@hubname` header (chapter 9, *Remote Hub Groups*).
No pairing flow, no taps -- plug the cable in, export on one
side, route on the other. Each side decides what it *shares*
(its export list) and the receiving side can opt out per session
(**Unmirror** in the device's header menu) and re-add later from
the Add menu.

Mirrored devices are full citizens of the matrix: filters,
mappings, renames and clock routing all work, and connections to
them are saved by a stable identity that survives reboots and IP
changes on both ends. While the peer is offline its devices show
as offline rows like unplugged hardware, and recover by
themselves when the peer returns.

Sessions from Macs, iPads or DAWs are **not** mirrored
automatically -- a DAW advertising a session is not an invitation,
and a studio WLAN full of them would flood the matrix. They are
listed under Settings → Network MIDI (and in the Add menu) and
can be mirrored with one tap.

Loops are prevented structurally: a mirrored device cannot be
re-exported, and a hub never mirrors its own sessions.

Exports survive reboots (the list is part of the config); the
network advert for a device exists only while the device is
actually present (unplug the synth and its session leaves the
network; replug and it returns). Notes, CCs, clock and SysEx all
cross the wire; on a wired LAN the added latency is well under a
millisecond.

### The direct cable, and life without mDNS

A direct Ethernet cable between two hubs needs no router:
whenever Network MIDI is enabled, the hub puts a fixed IPv4
link-local address (`169.254.x.y`, derived from the hub's own MAC
so two hubs never collide) on `eth0`, and discovery rides on that.
The address is added directly and *additively* -- it sits
alongside any DHCP or static address the interface already has,
so it is present in every mode and does not depend on a DHCP
server answering. It is re-applied on each boot, and re-asserted
every few seconds, so a hub that powers on with Network MIDI
enabled gets its link-local address with no re-toggling, and it
returns within seconds if anything clears it.

On networks that swallow multicast (routed LANs, some managed
switches), add the other hub's IP or hostname under **Manual
peers** -- the hub then asks the peer directly for its exported
devices and everything else behaves exactly as with discovery.

### Failure behaviour

Link loss is survived in both directions. A cable pull or peer
power-cut is detected within ~30 seconds (the clock-sync exchange
doubles as the liveness probe); the mirrored devices drop to the
offline state and the hub keeps retrying in the background, so
plugging the cable back in restores everything without a tap.
Network clients that vanish silently are dropped from an exported
session's participant list after 60 seconds.

The transport is plain UDP on ports 5004 and up (one even/odd
port pair per exported device), discovery is the same mDNS the
hub already uses for `raspimidihub.local`. It needs the
`python3-zeroconf` package (a standard dependency of the deb);
when missing, the Settings page says so instead of offering the
toggle.

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
underlying Pi OS. The bootstrap image ships with **sshd enabled**
so SSH works out of the box with the user and key/password set in
the Pi Imager wizard -- this is also what makes a failed first
boot diagnosable (chapter 3). A few commands are commonly useful:

- `sudo reset-wifi` -- forces AP mode with default credentials.
  Use when the WiFi state is wedged or when access to the unit
  has been locked out.
- `journalctl -u raspimidihub -e` -- tails the routing service
  log. Useful for diagnosing BLE issues, update failures, or any
  unexpected service restart.
- `sudo mount -o remount,rw / && sudo dpkg --configure -a && sudo
  mount -o remount,ro /` -- reconciles a half-applied dpkg state
  if **Install** keeps failing with `E: dpkg was interrupted, you
  must manually run 'dpkg --configure -a'`. Only relevant on
  builds older than the one that runs the same recovery
  automatically before every install.

## Updating the rosetup Package

Both Debian packages -- `raspimidihub` (the routing service +
web UI) and `raspimidihub-rosetup` (the read-only filesystem
hardening) -- are listed in **Settings → Software Versions**.
Updating the rosetup package is supported via the same install
flow but requires a reboot to apply (the read-only mount layer
re-initialises at boot).

