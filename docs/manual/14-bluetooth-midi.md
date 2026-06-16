# Bluetooth MIDI

BLE-MIDI peripherals appear in the routing matrix alongside USB
devices and plugins, with the same filtering, mapping, and clipboard
behaviour. The Pi pairs with peripherals over Just-Works BLE and
bridges the GATT notifications into ALSA in software. This chapter
documents the pairing flow, the reconnect behaviour, the persistence
model that survives power-pulls, and the known limits.

(For sharing devices with a *second hub* or a computer over the
network -- wired or WiFi -- see chapter 17's *Network MIDI*
section; this chapter is about Bluetooth peripherals only.)

## The Bridge

RaspiMIDIHub includes its own BLE-MIDI bridge. It handles
Just-Works pairing and BLE-MIDI framing in both directions, then
presents each paired peripheral as an ordinary MIDI device in the
routing matrix.

The user-facing consequence: BLE-MIDI Just Works -- pair the
peripheral, and it appears in the matrix like any USB device.
The user-facing limitations are listed below.

## Pairing a Device

1. Power on the BLE-MIDI peripheral. Put it in pairing mode if it
   has a dedicated button.
2. Open the **Routing** tab → **Add** → scroll to the
   **Bluetooth MIDI** section.
3. Tap **Scan for BLE-MIDI Devices**. By default only
   MIDI-capable peripherals are listed; tick **Show all (N
   other)** if the device is hiding (some peripherals advertise
   the MIDI service only after the first connect).
4. Tap **Connect** on the entry for the device. Pairing happens
   automatically (Just-Works). After three to five seconds the
   device appears in the matrix with a blue Bluetooth glyph in
   its row and column headers.

## Persistence Across Power-Off

Pairing data lives in a tmpfs at `/var/lib/bluetooth` and is
snapshotted to `/boot/firmware/raspimidihub/bluetooth-state.tar`
on every BlueZ write (driven by an inotify watcher). Bonds survive
reboots *and* immediate power-off -- the persistent appliance
contract that the rest of the system extends to BLE-MIDI as well.

The snapshot path is on the boot partition. The boot partition
is mounted **read-only** in steady state; the bond-snapshot job
briefly remounts it rw, writes the tarball, syncs, and remounts
it ro. Same rw / write / ro cycle as Save Config (chapter 5).
The main root remains read-only throughout.

## Auto-Reconnect on Boot

On boot, after the snapshot is restored, the service iterates over
every paired BLE-MIDI device and asks BlueZ to connect to each.
BLE peripherals do not initiate reconnection themselves -- the Pi
has to ask.

If the peripheral is off or out of range at boot, the connect
attempt times out and the device shows up as paired-but-offline
in the matrix. To bring it back:

- **Long-press the row or column header → Reconnect**.

The same entry appears whenever a previously-connected device
goes offline (out of range, peripheral powered off) -- detection
happens within a couple of seconds.

## Disconnect and Forget

The row or column header menu of a connected BLE device contains:

- **Disconnect** -- tears the BLE link down but keeps the bond.
  **Reconnect** will bring it back without re-pairing.
- **Forget** -- removes the bond permanently. To use the device
  again, run the full **Add → Bluetooth MIDI → Scan → Connect**
  flow.

## Message Coverage

The bridge handles the full common MIDI message set:

- Notes (Note On / Note Off)
- CC (Control Change)
- PC (Program Change)
- Pitch Bend
- Aftertouch (channel and poly)
- MIDI Clock, Start / Stop / Continue, Song Position

**SysEx is not yet bridged in either direction.** All other
message types work. SysEx-heavy workflows (firmware updates,
patch dumps) still need a USB or DIN connection.

**Active Sensing (0xFE) and Reset (0xFF) are deliberately
filtered out.** Active Sensing spam from some controllers would
otherwise saturate the BLE connection; Reset can panic-stop
everything downstream. Both are dropped at the bridge.

## Latency

The bridge runs in Python, pinned to the isolated CPU 3, but the
bottleneck is BLE itself: the connection interval is set by the
peripheral and is typically 7.5--15 ms. Per-event userspace
overhead in the bridge under typical load is well under one
millisecond.

For latency-critical use, prefer USB or DIN. BLE-MIDI is
convenient for wireless control and for compact stage rigs; it
is not a replacement for a hard cable on a busy session.

## Limits

- **SysEx is not bridged** -- see 14.6.
- **One adapter, one peripheral at a time** is what has been
  tested. BlueZ supports multiple simultaneous BLE connections on
  the Pi 4 / 5 onboard adapter, but two BLE-MIDI peripherals at
  once is not a tested configuration.
- **BLE-MIDI competes with the access point for the 2.4 GHz radio
  on Pi 3-class boards.** The Pi 3B, 3B+, and Zero 2 W use a single
  combo chip and antenna for both Bluetooth and WiFi. When the hub
  runs its access point (the normal case), the constant 2.4 GHz
  beaconing can starve BLE *central* connections: the link reaches
  "connected" for an instant and is then aborted locally, surfacing
  as **Connection failed** in the matrix. Whether it happens is
  unit- and chip-dependent -- some Pi 3 boards tolerate it, others
  fail every time. Pi 4 / 5 use separate radios, coexist cleanly,
  and are the right choice when BLE-MIDI is in the critical path
  (chapter 21.1). See Troubleshooting below to confirm and work
  around it.
- **Active Sensing / Reset filtered** -- see 14.6.
- **External Bluetooth USB dongles** are not supported. Only the
  Pi's onboard radio is used.

## Troubleshooting

**Connect button hangs / "Connecting…" never returns.**
The peripheral may demand a non-standard pairing mode the bridge
cannot satisfy. Most BLE-MIDI peripherals only need Just-Works,
which is what the bridge provides. If a peripheral asks for
anything else, it is not currently supported.

**Bluetooth section says "unavailable".**
This happens on some upgrade paths. Click the **Reinstall to
enable Bluetooth** button in the banner; the Pi briefly switches
to client WiFi, installs the missing dependency, and switches
back.

**First Connect to a peripheral takes 5+ seconds.**
First-time pairing of some peripherals is genuinely slow on the
BLE side. Subsequent reconnects are faster (one to two seconds).

**Device shown as connected but no events flow.**
Check the matrix monitor on a connection involving the device.
If the source side shows no events, the BLE link is up but the
peripheral isn't actually sending -- check its power /
sleep-mode behaviour. If the source shows events but the
destination doesn't, look at the cell's filter and mappings.

**"Connection failed" on a Pi 3-class board that's running the
access point.**
The Pi 3B / 3B+ / Zero 2 W share one 2.4 GHz radio between WiFi
and Bluetooth. With the AP active, a BLE connect can be aborted by
the local controller before it finishes -- the device flashes
"connected" and immediately drops (BlueZ logs
`le-connection-abort-by-local`; the matrix shows **Connection
failed**). To confirm it's coexistence and not the peripheral:

1. Connect to the Pi over **Ethernet** so stopping WiFi won't
   cut your session.
2. Stop the access point: `systemctl stop raspimidihub-hostapd`.
3. Re-scan and Connect. If it now succeeds, it was coexistence.
4. Restart the AP: `systemctl start raspimidihub-hostapd`.

There is no software fix -- it is an RF limit of the shared radio.
Mitigations: keep the peripheral close during the first connect,
reduce the number of WiFi clients, or move BLE-MIDI to a Pi 4 / 5
(recommended for any BLE-critical rig).

One thing to check first: `dmesg | grep -i "default device
address"`. If the Bluetooth controller came up on a generic
fallback address (e.g. `43:45:c0:...`) instead of its real
`B8:27:EB:...` one, its BT init didn't complete cleanly -- that
leaves even less RF headroom and makes the coexistence failure far
more likely. A board whose BT address initialised correctly is
more likely to tolerate the AP.

