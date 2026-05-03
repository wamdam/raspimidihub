# Bluetooth MIDI

RaspiMIDIHub bridges BLE-MIDI peripherals (e.g. WIDI Master, CME WIDI
Bud Pro, Yamaha MD-BT01, BLE-MIDI capable keyboards) into the same
matrix as USB devices and plugins. Once paired, a peripheral appears
as a regular row/column with notes, CCs, MIDI Clock, transport, etc.

## Why a custom bridge

BlueZ ships its own `midi` plugin but it does not actually forward
GATT notifications to its ALSA seq client on at least the WIDI Master
(verified with `btmon` + `aseqdump`: notifications arrive at the
radio, the seq client emits zero events). We disable that plugin via
a systemd drop-in (`bluetoothd -P midi`) and bridge BLE-MIDI in
`raspimidihub.ble_midi_bridge` instead. The bridge handles Just-Works
pairing, GATT subscription, and the BLE-MIDI framing in both
directions.

## Pairing a device

1. Power on the BLE-MIDI peripheral and put it in pairing mode if it
   has a button for that.
2. Open the Routing tab → tap **Add** → the bottom of the overlay
   has a **Bluetooth MIDI** section.
3. Tap **Scan for BLE-MIDI Devices**. By default only MIDI-capable
   peripherals are listed; tick **Show all (N other)** if your device
   is hiding (some announce the MIDI service only after the first
   connect).
4. Tap **Connect** on the device. Pairing happens automatically
   (Just-Works). After ~3-5 s the device appears in the matrix with a
   blue Bluetooth glyph.

Pairing data is stored in a tmpfs at `/var/lib/bluetooth` and
snapshotted to `/boot/firmware/raspimidihub/bluetooth-state.tar` on
every BlueZ write. Bonds survive both reboots and immediate
power-off.

## Auto-reconnect

On Pi boot, after the snapshot is restored, the service iterates
every paired BLE-MIDI device and asks BlueZ to connect to each. BLE
peripherals don't initiate reconnection themselves, so this is the
only way they come back automatically.

If the peripheral is off or out of range at boot, that connect
attempt times out and the device is left as paired-but-offline. It
shows up in the matrix as an offline row/column. To bring it back:
**right-click / tap-and-hold the row or column header → Reconnect**.

## Disconnect / Forget

- **Tap the connected device's row or column header** in the matrix
  → Edit → **Disconnect** or **Forget**.
- Disconnect tears the BLE link down but keeps the bond — Reconnect
  brings it back without re-pairing.
- Forget removes the bond permanently — to use the device again
  you'll go through the pair flow.

## Latency

The bridge is implemented in Python, but the bottleneck is BLE itself
(7.5-15 ms connection interval is set by the peripheral, not us). Per-
event userspace overhead measured under typical load is well under
1 ms; the asyncio loop runs pinned to the isolated CPU 3 to keep
jitter predictable.

## Troubleshooting

**Connect button hangs / "Connecting…" never returns.**
The peripheral may demand a pairing mode our agent can't satisfy
(e.g. Numeric Comparison with display). Check
`journalctl -u raspimidihub -e` -- look for `StartNotify timed out`
or `Pair failed`. Most BLE-MIDI peripherals only need Just-Works,
which we provide by default.

**Bluetooth section says "unavailable: needs python3-dbus-next".**
This happens after upgrading from a 2.x release whose `dpkg -i`
install path skipped Recommends. Click the **Reinstall to enable
Bluetooth** button in the banner -- the Pi briefly switches to client
WiFi, runs `apt install python3-dbus-next`, and switches back. Or
from a terminal: `sudo apt install python3-dbus-next` then restart
the service.

**WIDI Master takes 5+ seconds to appear after Connect.**
First-time GATT discovery on this peripheral is genuinely slow. A
disconnect-bounce in the bridge clears stuck-state edge cases, but
the underlying BLE handshake takes what it takes. Subsequent
reconnects are faster (1-2 s).

**Device shown as connected but no events flow.**
Check the matrix monitor on a connection involving the device --
events on **handle 0x001b** in `btmon` confirm the radio is
receiving. If `aseqdump` against the bridge's port also shows
events, the bridge is working and the issue is downstream
(connection toggled off, filter blocking, channel mismatch).

## Limits

- **SysEx is not yet bridged in either direction.** All other MIDI
  message types work.
- **One adapter, one peripheral at a time** is what's been tested.
  BlueZ supports multiple simultaneous BLE connections on the Pi 4
  / 5 onboard adapter -- two BLE-MIDI peripherals should work but
  isn't a tested configuration.
- **Active Sensing (0xFE) and Reset (0xFF)** are deliberately
  filtered. Active Sensing spam from some controllers would otherwise
  saturate BLE; Reset can panic-stop everything downstream.
