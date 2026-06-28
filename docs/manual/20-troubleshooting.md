# Troubleshooting

Common failure modes, what each one looks like, and how to fix
it. Items here have been seen in the wild. Speculative failure
modes are not listed; they belong in the per-feature chapters as
warnings instead.

## Cannot Reach the UI

### The AP is not visible

- **What you see.** No `RaspiMIDIHub-XXXX` SSID appears on the
  phone.
- **First check.** Look at the green ACT LED. If it is off, the
  service did not start. If it is fast-blinking with the red PWR
  LED on, the config could not load and the service is in the
  fallback state.
- **Try.** Power-cycle the Pi. Wait the full 30 seconds for boot.
- **Last resort.** If reachable over Ethernet or SSH from another
  network, run `sudo reset-wifi` to force AP mode with default
  credentials.

### The AP is visible but the captive portal does not open

- **What you see.** Connecting to the AP works, but the phone
  does not pop the UI.
- **Try.** Open a browser and navigate manually:
  - `http://raspimidihub.local/` (requires mDNS support; chapter
    17.5).
  - The AP gateway IP shown in the phone's WiFi-info screen.
- **Common cause.** Some phones aggressively cache "this network
  has no internet" and suppress the captive-portal probe.
  Toggling WiFi off-and-on on the phone usually clears it.

### `raspimidihub.local` fails

- **What you see.** The browser cannot resolve the hostname.
- **Common cause.** mDNS support on the client OS is missing or
  disabled. Windows needs Apple Bonjour installed; some Linux
  systems do not run avahi-daemon by default.
- **Common cause (multiple hubs).** The bare `raspimidihub.local`
  only points at a *single* hub. With more than one hub on the
  network, use each hub's unique `raspimidihub-<id>.local` instead --
  `<id>` is the four-character code in its title bar / WiFi name.
- **Try.** The AP gateway IP or the static / DHCP IP shown in the
  home router's DHCP table (in WiFi-always mode).

## MIDI Not Flowing

### The device shows in the matrix but no rate meter ticks

- **What you see.** The row / column is visible and lit, but no
  events register.
- **First check.** Open the device's detail panel and watch the
  MIDI Monitor. If the monitor is silent on the *source* side,
  the device itself is not sending -- cable, port, or device-
  side configuration issue.
- **If the monitor shows events on the source but not at the
  destination.** Open the connecting cell, pick **Edit**, and
  check: channel filter (anything red?), message-type filter
  (Notes / CCs / Clock disabled?), and any active mappings that
  might be dropping the event.

### The device does not appear in the matrix

- **What you see.** A USB device that should be visible is
  missing.
- **First check.** Plug it into a different USB port. Some Pi
  models have ports on different USB buses with different power
  characteristics.
- **Second check.** A powered USB hub helps when the device
  needs more power than the Pi can supply on its bus.
- **Diagnostic.** Over SSH: `dmesg | tail -20`. Look for
  enumeration errors.

### Multiple clock sources

- **What you see.** The pulsing play icon next to a row header
  is orange instead of green.
- **Cause.** More than one device is sending MIDI Clock at the
  same time -- a typical misconfiguration when both a drum
  machine and the Master Clock plugin are running clock.
- **Fix.** Decide which device should be the clock master. On
  every other clock-emitting device, disable clock output (in
  the device's settings, or via the **Clock** message-type
  filter on its outgoing matrix cells).

## Bluetooth Issues

(Full coverage in chapter 14.9; the highlights here.)

### Peripheral will not pair

- **First check.** Confirm the peripheral is BLE-MIDI, not
  classic Bluetooth MIDI. The bridge supports BLE-MIDI only.
- **Cause.** Some peripherals demand a pairing mode the agent
  cannot satisfy (Numeric Comparison with a display, for
  example).
- **Diagnose.** Over SSH: `journalctl -u raspimidihub -e`, look
  for `Pair failed` or `StartNotify timed out`.

### Peripheral keeps disconnecting

- **First check.** Range. BLE typically works to about 10 metres
  with line-of-sight, less with obstacles.
- **Second check.** Peripheral battery / power.
- **Third check.** The Pi initiates BLE reconnections -- the
  peripheral does not. If the peripheral is power-cycled, give
  the Pi a moment to detect it, or long-press the row header →
  **Reconnect**.

### Need to re-pair after firmware update on the peripheral

- **Cause.** Some peripherals reset their bond table on firmware
  update.
- **Fix.** Long-press the row header → **Forget**, then re-run
  the **Add → Bluetooth MIDI → Scan → Connect** flow.

## Network MIDI Issues

(Full coverage in chapter 17's *Network MIDI* section.)

### Peer hub not discovered

- **First check.** Is **Network MIDI enabled on both hubs**, and
  does the *other* hub actually export anything? Only exported
  devices are advertised.
- **Second check (direct cable).** Both hubs always carry a
  `169.254.x.y/16` link-local on `eth0` (maintained from boot,
  independent of the Network MIDI toggle), so two hubs on a
  back-to-back cable **share that subnet and reach each other even
  if their other addresses don't match** -- one on a static
  `10.1.1.2/24` and the other on DHCP-with-no-server still meet over
  link-local. Give a freshly-plugged cable ~30 seconds to settle.
  *The hub re-binds mDNS by itself when `eth0` gains an address, so
  a cable plugged in after boot is discovered without toggling
  Network MIDI off and on.*
- **Same subnet (via a switch/router).** When the hubs are *not*
  directly cabled, mirroring uses whatever routable addresses they
  advertise -- make sure both are reachable from each other (same
  `/24`, or DHCP leases on the same network).
- **Third check.** On a routed LAN or behind a managed switch,
  multicast (mDNS) may not get through -- add the peer's IP under
  **Settings → Network MIDI → Manual peers**. (Manual peers use
  plain unicast and work regardless of multicast.)
- **Diagnose.** Over SSH: `journalctl -u raspimidihub -e`, look
  for `network-midi:` lines.

### Mirrored device greyed out

- **Cause.** The peer hub is unreachable (cable pulled, peer
  powered off) or stopped exporting the device. Detection takes
  up to ~30 seconds.
- **Fix.** Nothing to do -- restore the link / the export and the
  device reconnects by itself, with all connections intact.

### Mirror button shows an error code

When **Mirror** (or **Add** from the matrix's Add menu) cannot bring
the device up, it now reports a short diagnostic code in a toast --
quote it in a bug report and it points straight at the cause:

- **`NETMIDI-E01` -- session not found.** The peer's advert vanished
  between the moment you saw it and the moment you tapped Mirror
  (cable pulled, peer powered off, Network MIDI toggled). Refresh the
  list and retry.
- **`NETMIDI-E02` -- no reachable address.** The peer advertised only
  an address that is also one of *this* hub's own addresses (classically
  the shared `192.168.4.1` access-point address) and no routable path
  was left. On a direct cable this should be rare -- both hubs always
  carry a `169.254.x` link-local that gives a shared subnet -- so if
  you hit it there, check the link-local is actually present on `eth0`
  (Settings → Network, or `ip -4 addr show eth0`).
- **`NETMIDI-E03` -- handshake timed out.** The invitation reached no
  one that answered (`no OK`): a firewall, the wrong address advertised,
  or the peer's session port is blocked. Check both hubs are on the
  same subnet and that nothing filters UDP 5004+.
- **`NETMIDI-E04` -- session start failed.** A local error while
  bringing the mirror up. Over SSH: `journalctl -u raspimidihub -e`
  and look for the `NETMIDI-E04` line for the underlying exception.

All four are also written to the hub log with the same code, so
`journalctl -u raspimidihub -e | grep NETMIDI-` shows the history
even after the toast is gone.

### Network MIDI page says "unavailable"

- **Cause.** The `python3-zeroconf` package is missing (image
  upgraded via a path that skipped new dependencies).
- **Fix.** Over SSH: `sudo apt install python3-zeroconf`, then
  restart the service or reboot.

## Software Updates

### Stuck on download

- **First check.** Which WiFi mode is the Pi in? AP-only has no
  internet. **Settings → WiFi → WiFi mode** must be **WiFi for
  updates** or **WiFi always**, or an Ethernet / USB-tethered
  phone must be providing internet.
- **Diagnose.** Watch the Stats card to confirm the service is
  alive; if the asyncio loop is healthy, the install is
  proceeding (slow downloads happen).

### "Check GitHub for newer versions" finds nothing

- **First check.** Internet path. Try opening a URL on the
  phone *while it is connected to the AP*; if the phone has no
  internet through the AP, neither does the Pi.
- **Second check.** The currently-running version *might be* the
  latest, in which case "found nothing newer" is the correct
  answer. Look at **Settings → Software Versions** and compare
  with the GitHub releases page.

### Install failed

- **First check.** The error toast usually has a specific
  message. Common ones:
  - Disk full -- unlikely on the 4 GB+ SD card unless the deb
    cache was prevented from cleaning.
  - Package conflict -- only when the Pi has been used for non-
    RaspiMIDIHub purposes (chapter 3 warns against this).
- **Recovery.** The 180-second watchdog (chapter 17.7) forces
  the routing service to restart if it hung mid-install. The
  AP comes back; retry from there.

## Plugins

### Plugin not in the Add menu

- **First check.** Reboot the Pi. Plugin discovery runs at
  startup, so a freshly-installed plugin only appears after a
  restart.
- **Second check.** If you have written a custom plugin
  yourself, consult the plugin developer guide in the project
  repository for the file-layout requirements.

### Plugin parameters revert after restart

- **Cause.** **Save Config** was not tapped between the parameter
  change and the restart / reboot.
- **Fix.** Set the parameters, tap **Save Config**, *then*
  restart.

### Master Clock and external clock fighting

- **Cause.** Both the Master Clock plugin and an external clock
  source (a drum machine, a DAW) are routed to a downstream
  destination, and the destination receives clock from both.
- **Fix.** Decide which source is authoritative. Block clock from
  the other source -- either at the device-level filter (chapter
  10.3) or by not routing it through.

## Controllers

### Drop button never fires

- **First check.** **Sync to bars** is on but no master clock is
  routed -- the drop button is waiting for a bar that never
  arrives.
- **Fix.** Either route a clock source (Master Clock plugin, or
  an external clock) to the controller, or turn **Sync to bars**
  off.

### MIDI Learn does not latch

- **Cause.** The Learn window is around five seconds; if no event
  arrives in that window, Learn reverts.
- **Fix.** Tap Learn and then play / move the hardware
  immediately. The pulsing border on the field is the visual
  confirmation that capture succeeded.

### XY pad spring not behaving

- **First check.** Spring **Force** is non-zero in the cell's
  config. Force `0` disables the spring.
- **Second check.** **Home** is set to the expected position
  (Bottom-left or Centre).

## Read-Only Filesystem and Saving

### Save Config fails

- **What you see.** The save reports an error toast.
- **Common cause.** The remount-rw step failed because the boot
  partition is unhappy. Over SSH: `rw` then check the boot
  partition mount state; `dmesg | tail -20` will usually show
  the cause.
- **Recovery.** Re-run **Save Config** after addressing the
  underlying issue. The runtime copy in tmpfs is intact during
  the failure -- nothing is lost.

### Custom Pi tweaks lost on reboot

- **Cause.** Expected behaviour. The appliance is read-only by
  design; nothing manually edited on the root filesystem
  survives a reboot unless done from a `rw`-remount session and
  followed by `ro`.
- **Note.** This is intentional; chapter 18 explains the
  rationale.

## Stats and Performance

### Loop lag spikes

- **First check.** Stats card -- which value is climbing? Loop
  lag spikes usually come from a misbehaving plugin or a USB
  device hogging the bus.
- **Diagnose.** Remove plugins one at a time until lag falls.
  The removed plugin is the culprit.

### SSE backlog rising

- **Cause.** Multiple browsers connected, one of them frozen.
  The SSE backlog rises until the stale connection times out.
- **Fix.** Close stale tabs / browsers. The backlog clears on
  its own.

### CPU consistently above 70%

- **Cause.** Heavy plugins or large numbers of mapped
  connections.
- **Diagnose.** Remove the heaviest plugin (a long MIDI Delay
  with feedback is a common offender) and re-check.

## When All Else Fails

### From the UI

- **Settings → System → Reboot.** Clean shutdown and restart.

### From a console

- `sudo systemctl restart raspimidihub` -- restart the routing
  service.
- `sudo reset-wifi` -- force AP mode with default credentials.
- `journalctl -u raspimidihub -e` -- read the service logs.
- `sudo reboot` -- restart the Pi.

### Last resort

- Re-flash the SD card with Raspberry Pi OS Lite and re-run the
  install one-liner. Use **Export Config** beforehand to keep
  the routing state recoverable.

