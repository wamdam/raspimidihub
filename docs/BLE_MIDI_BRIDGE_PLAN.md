# BLE-MIDI Bridge Implementation Plan

## Context

BLE-MIDI devices (TX-6, WIDI, MD-BT01, etc.) connect via Bluetooth LE but
Debian's BlueZ package doesn't include the MIDI plugin. Rather than compiling
BlueZ from source, we implement our own bridge in `ble_midi_bridge.py` that:

1. Connects to the BLE-MIDI GATT characteristic via D-Bus
2. Creates ALSA sequencer ports (IN/OUT) per device
3. Translates BLE-MIDI packets <-> ALSA events
4. Measures latency and exposes it to the UI

## BLE-MIDI Protocol (RFC 8160)

**Service UUID:** `03b80e5a-ede8-4b33-a751-6ce34ec4c700`
**Characteristic UUID:** `7772e5db-3868-4112-a1a9-f2669d106bf3`

Packet format:
```
[header] [timestamp_high | 0x80] [timestamp_low | 0x80] [MIDI bytes...]
```

- Header byte: bit 7 set + upper 6 bits of 13-bit ms timestamp
- Timestamp byte: bit 7 set + lower 7 bits of timestamp
- MIDI bytes: raw status + data bytes, running status applies
- Multiple MIDI messages per packet possible (each prefixed by timestamp byte)
- 13-bit timestamp wraps every 8192ms

## Architecture

```
BLE Device (TX-6)
    |  BLE GATT notifications
    v
BlueZ D-Bus (org.bluez.GattCharacteristic1)
    |  PropertiesChanged signal -> Value bytes
    v
ble_midi_bridge.py :: BleMidiBridge
    |  - One instance per connected BLE-MIDI device
    |  - Parses BLE-MIDI packets -> MIDI events
    |  - Encodes MIDI events -> BLE-MIDI packets
    |  - Measures round-trip latency
    v
AlsaSeq client (per device)
    |  IN port (readable) + OUT port (writable)
    v
MidiEngine discovers it via hotplug -> routing matrix
```

## File: `src/raspimidihub/ble_midi_bridge.py`

### Class: BleMidiBridge

Manages all active BLE-MIDI device bridges.

```python
class BleMidiBridge:
    def __init__(self): ...
    async def start_bridge(self, address: str, name: str) -> bool
    async def stop_bridge(self, address: str)
    def get_bridges(self) -> list[dict]  # address, name, latency_ms, alsa_client_id
```

### Class: _BleDevice (internal)

One per connected BLE-MIDI device.

```python
class _BleDevice:
    def __init__(self, address, name, alsa_seq): ...
    async def connect(self)       # Find GATT char, StartNotify, create ALSA ports
    async def disconnect()        # StopNotify, close ALSA
    # Internal:
    _on_notification(value)       # Parse BLE-MIDI packet, send to ALSA
    _alsa_to_ble_loop()          # Poll ALSA IN port, encode + WriteValue
    _parse_ble_midi(data) -> list[(status, data_bytes)]
    _encode_ble_midi(midi_bytes) -> bytes
```

## D-Bus Integration

Use `dbus-next` (async, pure Python, no C deps) to:
1. Find the GATT characteristic by walking `/org/bluez/hci0/dev_XX_XX/serviceNNN/charNNN`
2. Match characteristic UUID `7772e5db-...`
3. Call `StartNotify()` to subscribe
4. Listen for `PropertiesChanged` signals on `Value` property
5. Send MIDI via `WriteValue(bytes, {})`

Fallback if `dbus-next` not available: use `subprocess` + `gatttool` or `bluetoothctl`
(higher latency but no pip dependency).

## ALSA Integration

Per device, create an AlsaSeq client with:
- OUT port (readable): BLE data -> ALSA events -> other devices subscribe
- IN port (writable): other devices send -> ALSA events -> BLE WriteValue

Reuse existing `AlsaSeq` class from `alsa_seq.py`.

## Latency Measurement

- On each incoming notification, record `time.monotonic()`
- Compare BLE-MIDI timestamp to local arrival time
- Track rolling average over last 100 packets
- Expose via `get_latency_ms(address)` for UI display

## Integration Points

### bluetooth.py
After successful `connect()`, call `ble_bridge.start_bridge(address, name)`.
On `disconnect()`, call `ble_bridge.stop_bridge(address)`.

### midi_engine.py
The bridge's ALSA client appears as a user-space client.
`scan_devices(include_user_clients=...)` already supports whitelisting user clients.
Add bridge client IDs to the whitelist (same pattern as plugins).

### api.py
Extend `GET /api/bluetooth` to include bridge status + latency.
Extend device API to include `is_bluetooth` flag + latency_ms.

### app.js
Show latency badge on BLE devices in the matrix (yellow warning if >20ms).

## Implementation Order

1. Install `dbus-next` as dependency (add to debian/control Depends or bundle)
2. Create `ble_midi_bridge.py` with packet parser + ALSA bridge
3. Wire into `bluetooth.py` connect/disconnect flow
4. Wire into `midi_engine.py` device scan
5. Add latency display to UI
6. Test with TX-6
7. Add tests for packet parser

## Dependencies

- `python3-dbus-next` (pip: `dbus-next`) — async D-Bus client
  - Check: `apt-cache show python3-dbus-next` on Pi OS
  - Fallback: bundle or use GLib bindings

## Verification

1. `aconnect -l` shows BLE device as ALSA client after bridge starts
2. MIDI events from TX-6 appear in RaspiMIDIHub routing matrix
3. Events routed from other devices reach TX-6 via BLE
4. Latency shown in UI
5. `make test` passes with BLE packet parser tests
