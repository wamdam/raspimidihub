# Bluetooth MIDI

BLE-MIDI peripherals appear in the routing matrix alongside USB
devices and plugins, with the same filtering, mapping, and
clipboard behaviour. Sharing devices over the network:
chapter 13, *Network MIDI*.

## The Bridge

The built-in BLE-MIDI bridge does Just-Works pairing and BLE-MIDI
framing in both directions; a paired peripheral appears in the
matrix like any USB device (limits: 14.8).

## Pairing a Device

1. Power on the peripheral; put it in pairing mode if it has a
   dedicated button.
2. Open the **Routing** tab → **Add** → **Bluetooth MIDI** section.
3. Tap **Scan for BLE-MIDI Devices**. Only MIDI-capable
   peripherals are listed; tick **Show all (N other)** if the
   device is hiding (some advertise the MIDI service only after
   the first connect).
4. Tap **Connect**. Pairing is automatic; after three to five
   seconds the device appears in the matrix with a blue Bluetooth
   glyph in its row and column headers.

## Persistence Across Power-Off

Pairing state is snapshotted to the boot partition on every change
and restored on boot -- bonds survive reboots *and* hard
power-offs. The write uses the same brief remount cycle as Save
Config (chapter 14).

## Auto-Reconnect on Boot

BLE peripherals do not initiate reconnection -- the Pi has to ask.
Boot reconnects every paired peripheral; one that is off or out of
range shows as paired-but-offline. **Long-press the row or column
header → Reconnect** brings it back; the same entry appears
whenever a connected device goes offline (detected within
seconds).

## Disconnect and Forget

In the header menu of a connected peripheral:

- **Disconnect** -- tears the BLE link down but keeps the bond;
  **Reconnect** brings it back without re-pairing.
- **Forget** -- removes the bond permanently. To use the device
  again, re-run **Add → Bluetooth MIDI → Scan → Connect**.

## Message Coverage

The bridge handles Notes (On / Off), CC, Program Change, Pitch
Bend, Aftertouch (channel and poly), MIDI Clock,
Start / Stop / Continue, and Song Position.

**SysEx is not bridged in either direction** -- firmware updates
and patch dumps need USB or DIN. **Active Sensing (0xFE) and Reset
(0xFF) are deliberately dropped**: Active Sensing would saturate
the BLE link; Reset can panic-stop everything downstream.

## Latency

The bottleneck is BLE itself: the peripheral sets the connection
interval, typically 7.5--15 ms; the bridge adds under a
millisecond. For latency-critical use, prefer USB or DIN.

## Limits

- **SysEx is not bridged; Active Sensing / Reset are filtered**
  (10.6).
- **One adapter, one peripheral at a time** is the tested
  configuration; two BLE-MIDI peripherals at once is untested.
- **Pi 3-class boards (3B, 3B+, Zero 2 W) share one 2.4 GHz radio
  and antenna between Bluetooth and WiFi**: the running access
  point can starve BLE connects (unit- and chip-dependent).
  Pi 4 / 5 have separate radios (chapter 2). See *"Connection
  failed"* below.
- **External Bluetooth USB dongles are not supported** -- only the
  Pi's onboard radio is used.

## Troubleshooting

**Connect button hangs / "Connecting…" never returns.**
The peripheral demands a pairing mode other than Just-Works, the
only mode the bridge supports.

**Bluetooth section says "unavailable".**
`python3-dbus-next` is missing after some upgrade paths. Tap
**Reinstall to enable Bluetooth** in the banner; the Pi briefly
switches to client WiFi, installs it, and switches back.

**The Bluetooth MIDI section is missing entirely (no Scan
button).**
The radio can settle a moment after boot (the Pi 3 B+ loads its
Bluetooth firmware late); the hub re-checks whenever the **Add**
overlay opens, so close and re-open it. If it never appears, the
board has no Bluetooth radio or `bluealsa` is not installed.

**First Connect to a peripheral takes 5+ seconds.**
First-time pairing of some peripherals is genuinely slow on the
BLE side; reconnects take one to two seconds.

**Device shown as connected but no events flow.**
Watch the matrix monitor on a connection involving the device.
Silent at the source: the peripheral is not sending -- check its
power / sleep behaviour. Events at the source but not the
destination: check the cell's filter and mappings.

**"Connection failed" on a Pi 3-class board that's running the
access point.**
The shared radio (10.8) aborts the connect locally: the device
flashes "connected" and drops; BlueZ logs
`le-connection-abort-by-local`. To confirm coexistence rather than
the peripheral:

1. Connect to the Pi over **Ethernet** so stopping WiFi won't cut
   your session.
2. Stop the access point: `systemctl stop raspimidihub-hostapd`.
3. Re-scan and Connect -- success means coexistence.
4. Restart the AP: `systemctl start raspimidihub-hostapd`.

No software fix exists -- it is an RF limit. Mitigations: keep the
peripheral close for the first connect, reduce WiFi clients, or
move BLE-MIDI to a Pi 4 / 5. Also check
`dmesg | grep -i "default device address"`: a controller on a
generic fallback address (e.g. `43:45:c0:...`) instead of its real
`B8:27:EB:...` one indicates incomplete BT init -- less RF
headroom, far likelier failures.
