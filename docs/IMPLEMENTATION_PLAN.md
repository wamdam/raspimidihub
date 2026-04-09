# RaspiMIDIHub — Implementation Plan: Bluetooth MIDI

**Branch:** `feature/bluetooth-midi`
**Target:** v1.4.0
**Date:** 2026-04-09

---

## Goal

Allow BLE-MIDI devices (wireless keyboards, controllers) to appear in the RaspiMIDIHub connection matrix alongside USB devices — scan, pair, connect, and route them identically.

---

## Technical Approach

### Dependencies

**No bundling needed.** All required packages are in Raspberry Pi OS apt repos:

| Package | Version (Trixie) | Purpose |
|---------|-------------------|---------|
| `bluez` | 5.82 (stock) | Bluetooth stack, `bluetoothctl`, D-Bus API |
| `bluez-alsa-utils` | 4.3.1 | BLE-MIDI GATT profile, creates ALSA seq ports |
| `libasound2-plugin-bluez` | 4.3.1 | ALSA plugin for bluez-alsa |

- **License:** bluez-alsa is MIT — fully compatible with our LGPL project.
- **No bundling, no recompilation:** Just `apt install` as a dependency of our `.deb`.
- **BlueZ's `--enable-midi` is NOT needed.** bluez-alsa registers the BLE-MIDI GATT profile itself via D-Bus, works with stock BlueZ.

### How it works

1. `bluealsa` daemon runs as a system service (started by package install)
2. When a BLE-MIDI device is paired + connected, bluez-alsa creates an ALSA sequencer port (client name "BlueALSA", port name = device name)
3. Our existing `midi_engine.py` discovers this port via the normal ALSA scan — no changes to the routing core
4. The device appears in the matrix like any USB device

### What we need to build

Only two things:

1. **`bluetooth.py`** — Python module to manage BLE-MIDI scan/pair/connect via BlueZ D-Bus API
2. **UI** — "Bluetooth MIDI" section in Settings page

---

## Stable Device IDs

Current USB stable IDs use `usb-{bus}-{port_path}-{vid}:{pid}`. For Bluetooth:

```
bt-{mac_address}
```

Example: `bt-AA:BB:CC:DD:EE:FF`

MAC address is permanent and unique — perfect for stable identification. Requires extending `device_id.py` to detect ALSA clients from bluez-alsa and generate `bt-` IDs.

---

## UI: Pairing Story

### Settings Page — New "Bluetooth MIDI" Card

```
BLUETOOTH MIDI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[Scan for Devices]

  WIDI Master              [Pair]
  Seaboard Block           [Pair]

Paired Devices:
  ● WIDI Core         Connected
  ○ Lightpad Block    Disconnected  [Connect] [Forget]
```

### Pairing Flow (User Perspective)

1. User opens Settings, scrolls to "Bluetooth MIDI"
2. Taps **[Scan for Devices]** — Pi scans for 10 seconds, shows BLE-MIDI devices (filtered by MIDI GATT UUID)
3. User taps **[Pair]** next to a device
4. Pairing happens automatically ("Just Works" — no PIN needed for BLE-MIDI)
5. Device appears under "Paired Devices" as "Connected"
6. Device immediately shows up in the connection matrix with a `⸙` Bluetooth icon
7. User routes it like any other device

### Reconnection

- Paired devices auto-reconnect when powered on (BlueZ handles this)
- If device is off/out of range → shown as "Disconnected" in Settings, offline (grayed out) in matrix
- Tapping **[Connect]** manually triggers reconnection
- **[Forget]** removes pairing

### Matrix Label

Bluetooth devices get a small `⸙` icon prefix in the matrix row/column header to distinguish from USB:

```
FROM ↓          | Digitone | ⸙ WIDI | KeyStep
────────────────+──────────+────────+────────
Digitone ▶      |          |   ✓    |   ✓
⸙ WIDI Master   |    ✓     |        |   ✓
KeyStep mk2     |    ✓     |   ✓    |
```

---

## Implementation Steps

### Step 1: bluetooth.py — BlueZ D-Bus wrapper

New file `src/raspimidihub/bluetooth.py`:

```python
class BluetoothMidi:
    """Manage BLE-MIDI devices via BlueZ D-Bus API."""

    async def scan(self, timeout=10) -> list[dict]
        # Start discovery, filter for MIDI GATT UUID
        # Return [{name, address, rssi, paired, connected}]

    async def pair(self, address: str) -> bool
        # Pair + trust + connect
        # Uses "Just Works" (NoInputNoOutput agent)

    async def connect(self, address: str) -> bool
        # Reconnect already-paired device

    async def disconnect(self, address: str) -> bool

    async def forget(self, address: str) -> bool
        # Remove pairing

    async def get_paired_devices(self) -> list[dict]
        # List paired BLE-MIDI devices with connection state
```

D-Bus calls via `dbus-next` (async, pure Python, no compiled deps) or subprocess `bluetoothctl` as fallback.

### Step 2: Extend device_id.py

- Detect ALSA clients from bluez-alsa (client name starts with "BlueALSA" or check via D-Bus)
- Generate stable ID: `bt-{mac_address}`
- Return `StableDeviceInfo` with `is_bluetooth=True` flag

### Step 3: API endpoints

```
GET    /api/bluetooth              # Paired devices + connection state
POST   /api/bluetooth/scan         # Start scan, return results
POST   /api/bluetooth/pair         # {address} → pair + connect
POST   /api/bluetooth/connect      # {address} → reconnect
POST   /api/bluetooth/disconnect   # {address}
DELETE /api/bluetooth/{address}    # Forget device
```

### Step 4: UI — BluetoothCard component in app.js

- Scan button with spinner + results list
- Pair/Connect/Forget buttons per device
- Connection status indicators (green dot = connected, gray = disconnected)
- Add `⸙` prefix to Bluetooth device labels in ConnectionMatrix

### Step 5: Packaging

- Add `Depends: bluez-alsa-utils, libasound2-plugin-bluez` to debian/control
- Ensure `bluealsa` service is enabled in postinst
- Config: save paired device names in `config.json` under `bluetooth_devices`

---

## Latency Considerations

BLE-MIDI adds ~15-40ms latency + jitter vs USB's <1ms. This is:
- **Fine for:** CC, program change, transport, non-time-critical control
- **Noticeable for:** Live keyboard playing, tight drum sequencing
- **Mitigated by:** BLE 5.0 connection intervals (Pi 4/5 support BLE 5.0)

The UI should show a subtle latency indicator (e.g., `⸙` icon tooltip: "Bluetooth — higher latency than USB").

---

## Open Questions

1. Should the Pi also advertise as a BLE-MIDI peripheral (so phones/tablets can send MIDI to it)? → Probably not for v1.4, adds complexity.
2. Does bluez-alsa handle reconnection automatically, or do we need to call `Connect()` on boot? → Test needed.
3. Does `bluealsa` conflict with our WiFi AP on shared antenna (Pi 3B+ uses same chip for WiFi+BT)? → Test needed.

---

## Build & Deploy

```bash
make deb              # Build .deb package
make deploy           # Build + scp + install on Pi
make clean            # Remove build artifacts
```

## Release Checklist

1. Bump version in `src/raspimidihub/__init__.py` and `Makefile`
2. `git commit && git push`
3. `git tag vX.Y.Z && git push origin vX.Y.Z`
4. `make clean && make deb`
5. `gh release create vX.Y.Z dist/*.deb --title "vX.Y.Z" --notes "..."`
