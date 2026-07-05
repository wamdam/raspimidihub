# Troubleshooting

Common failure modes seen in the wild, and how to fix them.

## Cannot Reach the UI

### The AP is not visible

No `RaspiMIDIHub-XXXX` SSID on the phone. Check the green ACT LED:
off = the service did not start; fast blink with the red PWR LED
on = the config failed to load. Power-cycle the Pi and wait the
full 30 seconds for boot. Last resort, over Ethernet or SSH:
`sudo reset-wifi` forces AP mode with default credentials.

### The AP is visible but the captive portal does not open

Navigate manually to `http://raspimidihub-<id>.local/` (needs
mDNS; chapter 13.5) or the AP gateway IP from the phone's
WiFi-info screen. Some phones cache "this network has no internet"
and suppress the portal probe; toggle the phone's WiFi off and on.

### `raspimidihub-<id>.local` doesn't resolve

Use the hub's unique name -- `<id>` is the four-character code on
its captive-portal page, title bar, and WiFi name (e.g.
`raspimidihub-735C.local`). Usual cause: no mDNS on the client
(Windows needs Apple Bonjour; some Linux systems lack
avahi-daemon). Fall back to the AP gateway IP, or the router's
DHCP table (WiFi-always mode).

## MIDI Not Flowing

### The device shows in the matrix but no rate meter ticks

Open the device's detail panel and watch the MIDI Monitor. Silent
on the *source* side: the device is not sending -- cable, port, or
device-side configuration. Events at the source but not the
destination: open the cell → **Edit**; check the channel filter
(anything red?), the message-type filter (Notes / CCs / Clock
disabled?), and any mappings.

### The device does not appear in the matrix

Try a different USB port (ports differ in power characteristics);
a powered USB hub helps a power-hungry device. Over SSH:
`dmesg | tail -20`, look for enumeration errors.

### Multiple clock sources

An orange (not green) pulsing play icon next to a row header: more
than one device is sending MIDI Clock. Pick one clock master and
disable clock output on every other emitter -- in its settings, or
via the **Clock** message-type filter on its outgoing cells.

## Bluetooth Issues

(Full coverage in chapter 10.9; the highlights here.)

### Peripheral will not pair

Confirm it is BLE-MIDI, not classic Bluetooth MIDI -- only
BLE-MIDI is supported. Some peripherals demand a pairing mode the
agent cannot satisfy (e.g. Numeric Comparison with a display).
Diagnose: `journalctl -u raspimidihub -e`, look for `Pair failed`
or `StartNotify timed out`.

### Peripheral keeps disconnecting

Check range (about 10 metres line-of-sight) and battery. The Pi
initiates reconnections, not the peripheral: after power-cycling
it, wait a moment or long-press the row header → **Reconnect**.

### Need to re-pair after firmware update on the peripheral

Some peripherals reset their bond table on firmware update.
Long-press the row header → **Forget**, then re-run
**Add → Bluetooth MIDI → Scan → Connect**.

## Network MIDI Issues

(Full coverage in chapter 13's *Network MIDI* section.)

### Peer hub not discovered

- Network MIDI must be enabled on **both hubs**, and the peer must
  export something -- only exported devices are advertised.
- Direct cable: both hubs always carry a `169.254.x.y/16`
  link-local on `eth0` and share that subnet. Give a fresh cable
  ~30 seconds; mDNS re-binds when `eth0` gains an address.
- Via a switch/router: both hubs must be mutually reachable (same
  `/24`, or DHCP leases on one network).
- Multicast filtered (routed LAN, managed switch): add the peer's
  IP under **Settings → Network MIDI → Manual peers** -- manual
  peers use plain unicast.
- Diagnose: `journalctl -u raspimidihub -e`, look for
  `network-midi:` lines.

### Mirrored device greyed out

The peer hub is unreachable or stopped exporting the device;
detection takes up to ~30 seconds. Restore the link / export and
the device reconnects by itself, connections intact.

### Mirror button shows an error code

A failed **Mirror** (or **Add**) reports a diagnostic code in a
toast -- quote it in bug reports:

- **`NETMIDI-E01` -- session not found.** The peer's advert
  vanished before the tap (cable pulled, peer off, Network MIDI
  toggled). Refresh and retry.
- **`NETMIDI-E02` -- no reachable address.** The peer advertised
  only an address this hub also owns (classically the shared
  `192.168.4.1` AP address). Check the link-local on `eth0`
  (Settings → Network, or `ip -4 addr show eth0`).
- **`NETMIDI-E03` -- handshake timed out.** No answer to the
  invitation: firewall, wrong advertised address, or blocked
  session port. Check the hubs share a subnet and nothing filters
  UDP 5004+.
- **`NETMIDI-E04` -- session start failed.** A local error; find
  the `NETMIDI-E04` line in `journalctl -u raspimidihub -e` for
  the underlying exception.

`journalctl -u raspimidihub -e | grep NETMIDI-` shows the code
history after the toast is gone.

### Network MIDI page says "unavailable"

The `python3-zeroconf` package is missing (an upgrade path skipped
new dependencies). `sudo apt install python3-zeroconf`, then
restart the service or reboot.

## Software Updates

### Stuck on download

AP-only mode has no internet: set **Settings → WiFi → WiFi mode**
to **WiFi for updates** or **WiFi always**, or plug in Ethernet or
a USB-tethered phone. If the Stats card shows a healthy loop, the
install is proceeding -- slow downloads happen.

### "Check GitHub for newer versions" finds nothing

Test internet on the phone *while connected to the AP* -- if the
phone has none through the AP, neither does the Pi. Or the running
version is simply the latest; compare **Settings → Software
Versions** with the GitHub releases page.

### Install failed

The error toast usually names the cause: disk full (unlikely
unless the deb cache could not clean) or a package conflict (only
when the Pi is used for other purposes; chapter 1 warns against
this). If the install hung, the 180-second watchdog (chapter 13.8)
restarts the routing service and the AP comes back; retry.

## Plugins

### Plugin not in the Add menu

Reboot the Pi -- plugin discovery runs at startup, so a
freshly-installed plugin appears only after a restart. For a
custom plugin, the developer guide in the project repository has
the file-layout requirements.

### Plugin parameters revert after restart

**Save Config** was not tapped before the restart. Set the
parameters, tap **Save Config**, *then* restart.

### Master Clock and external clock fighting

A destination receives clock from both the Master Clock plugin and
an external source. Pick one; block clock from the other at the
device-level filter (chapter 6.3) or by not routing it through.

## Controllers

### Drop button never fires

**Sync to bars** is on but no master clock is routed -- the button
waits for a bar that never arrives. Route a clock source to the
controller, or turn **Sync to bars** off.

### MIDI Learn does not latch

The Learn window is limited (ten seconds in the filter/mapping
panel, thirty in the CC-binding popups). Tap Learn, then play /
move the hardware promptly; a pulsing border on the field
confirms capture.

### XY pad spring not behaving

In the cell's config, spring **Force** must be non-zero (`0`
disables the spring) and **Home** the expected position
(Bottom-left or Centre).

## Read-Only Filesystem and Saving

### Save Config fails

Usually the remount-rw step failed on the boot partition. Over
SSH: `rw`, then check the boot partition mount state;
`dmesg | tail -20` shows the cause. The runtime copy in tmpfs is
intact; re-run **Save Config** after fixing it.

### Custom Pi tweaks lost on reboot

Expected: the appliance is read-only by design (chapter 14).
Manual edits survive only when made in a `rw`-remount session
followed by `ro`.

## Stats and Performance

### Loop lag spikes

Check the Stats card for the climbing value. Usual culprits: a
misbehaving plugin or a USB device hogging the bus. Remove plugins
one at a time until lag falls.

### SSE backlog rising

Multiple browsers, one frozen; the backlog rises until the stale
connection times out. Close stale tabs and it clears.

### CPU consistently above 70%

Heavy plugins or many mapped connections. Remove the heaviest
plugin (a long MIDI Delay with feedback is a common offender) and
re-check.

## When All Else Fails

### From the UI

**Settings → System → Reboot** -- clean shutdown and restart.

### From a console

- `sudo systemctl restart raspimidihub` -- restart the routing
  service.
- `sudo reset-wifi` -- force AP mode with default credentials.
- `journalctl -u raspimidihub -e` -- read the service logs.
- `sudo reboot` -- restart the Pi.

### Last resort

Re-flash the SD card (chapter 14, *Re-flashing the SD card*).
**Export Config** first — a re-flash loses all saved state.
