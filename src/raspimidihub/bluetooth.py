"""Bluetooth MIDI device management via BlueZ D-Bus API.

Manages BLE-MIDI device scanning, pairing, and connection using bluetoothctl
subprocess calls. When a BLE-MIDI device is connected, bluez-alsa creates an
ALSA sequencer port that the MIDI engine discovers automatically.
"""

import asyncio
import logging
import re
import subprocess

log = logging.getLogger(__name__)

# BLE-MIDI GATT service UUID (Apple BLE-MIDI / RFC 8160)
MIDI_SERVICE_UUID = "03b80e5a-ede8-4b33-a751-6ce34ec4c700"


def _run(cmd: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _btctl(*args, timeout: int = 10) -> str:
    """Run a bluetoothctl command and return stdout."""
    result = _run(["bluetoothctl", *args], timeout=timeout)
    return result.stdout


class BluetoothMidi:
    """Manage BLE-MIDI devices via bluetoothctl."""

    def __init__(self):
        self._scanning = False
        self.ble_bridge = None  # Set externally: BleMidiBridge instance

    @staticmethod
    def _get_device_name(address: str) -> str:
        """Get device name from bluetoothctl info."""
        try:
            info = _btctl("info", address, timeout=5)
            for line in info.splitlines():
                if "Name:" in line:
                    return line.split("Name:", 1)[1].strip()
        except Exception:
            pass
        return address

    @staticmethod
    def is_available() -> bool:
        """Check if Bluetooth hardware and bluez-alsa are available."""
        try:
            result = _run(["bluetoothctl", "show"], timeout=5)
            if "Powered: yes" not in result.stdout:
                # Try to power on
                _btctl("power", "on", timeout=5)
                result = _run(["bluetoothctl", "show"], timeout=5)
            has_bt = "Powered: yes" in result.stdout
            has_bluealsa = _run(["which", "bluealsa"], timeout=5).returncode == 0
            return has_bt and has_bluealsa
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    async def scan(self, timeout: int = 10) -> list[dict]:
        """Scan for BLE-MIDI devices. Returns list of {name, address, rssi, paired}."""
        if self._scanning:
            return []
        self._scanning = True
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self._scan_sync, timeout)
        finally:
            self._scanning = False

    def _scan_sync(self, timeout: int) -> list[dict]:
        """Synchronous BLE scan. Shows all BLE devices (not just MIDI).

        We can't reliably filter by MIDI UUID during scan because some devices
        (like the Teenage Engineering TX-6) don't advertise the standard
        BLE-MIDI UUID until after connection.
        """
        # Clear previous scan results
        _btctl("scan", "off", timeout=3)

        # Scan using BLE (Low Energy) transport
        proc = subprocess.Popen(
            ["bluetoothctl", "--timeout", str(timeout), "scan", "le"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            proc.wait(timeout=timeout + 5)
        except subprocess.TimeoutExpired:
            proc.kill()

        # Get all discovered devices
        output = _btctl("devices", timeout=5)
        devices = []
        for line in output.splitlines():
            m = re.match(r"^Device\s+([0-9A-Fa-f:]{17})\s+(.+)$", line)
            if not m:
                continue
            address, name = m.group(1), m.group(2)
            if name == address or not name.strip():
                continue  # Skip unnamed devices

            info = _btctl("info", address, timeout=5)
            paired = "Paired: yes" in info
            connected = "Connected: yes" in info
            has_midi = MIDI_SERVICE_UUID in info.lower()
            rssi = 0
            rssi_match = re.search(r"RSSI:\s*(-?\d+)", info)
            if rssi_match:
                rssi = int(rssi_match.group(1))

            devices.append({
                "name": name,
                "address": address,
                "rssi": rssi,
                "paired": paired,
                "connected": connected,
                "midi": has_midi,
            })

        return sorted(devices, key=lambda d: (d["midi"], d["rssi"]), reverse=True)

    async def pair(self, address: str) -> bool:
        """Pair, trust, and connect a BLE-MIDI device."""
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, self._pair_sync, address)
        if ok and self.ble_bridge:
            name = self._get_device_name(address)
            await self.ble_bridge.start_bridge(address, name)
        return ok

    def _pair_sync(self, address: str) -> bool:
        try:
            # Set agent for Just Works pairing
            _btctl("agent", "NoInputNoOutput", timeout=5)
            _btctl("default-agent", timeout=5)

            # Pair
            result = _run(["bluetoothctl", "pair", address], timeout=30)
            if "Failed" in result.stdout and "Already Exists" not in result.stdout:
                log.warning("Pair failed for %s: %s", address, result.stdout.strip())
                return False

            # Trust (auto-reconnect)
            _btctl("trust", address, timeout=5)

            # Connect
            result = _run(["bluetoothctl", "connect", address], timeout=15)
            if "Failed" in result.stdout:
                log.warning("Connect failed for %s: %s", address, result.stdout.strip())
                return False

            log.info("Paired and connected BLE-MIDI device: %s", address)
            return True
        except subprocess.TimeoutExpired:
            log.warning("Pairing timed out for %s", address)
            return False

    async def connect(self, address: str) -> bool:
        """Reconnect an already-paired device via BLE-MIDI bridge.

        The bridge handles the D-Bus connection (keeps it alive) and
        GATT service discovery. We don't use bluetoothctl connect because
        it drops the connection when the process exits.
        """
        if self.ble_bridge:
            name = self._get_device_name(address)
            ok = await self.ble_bridge.start_bridge(address, name)
            return ok
        # Fallback if no bridge
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._connect_sync, address)

    def _connect_sync(self, address: str) -> bool:
        try:
            result = _run(["bluetoothctl", "connect", address], timeout=15)
            ok = "Connection successful" in result.stdout
            if ok:
                log.info("Reconnected BLE-MIDI device: %s", address)
            return ok
        except subprocess.TimeoutExpired:
            return False

    async def disconnect(self, address: str) -> bool:
        """Disconnect a device (keeps pairing)."""
        if self.ble_bridge:
            await self.ble_bridge.stop_bridge(address)
        loop = asyncio.get_event_loop()

        def _do():
            try:
                _btctl("disconnect", address, timeout=10)
                return True
            except subprocess.TimeoutExpired:
                return False

        return await loop.run_in_executor(None, _do)

    async def forget(self, address: str) -> bool:
        """Remove pairing for a device."""
        if self.ble_bridge:
            await self.ble_bridge.stop_bridge(address)
        loop = asyncio.get_event_loop()

        def _do():
            try:
                _btctl("disconnect", address, timeout=5)
                _btctl("untrust", address, timeout=5)
                _btctl("remove", address, timeout=10)
                log.info("Removed BLE-MIDI device: %s", address)
                return True
            except subprocess.TimeoutExpired:
                return False

        return await loop.run_in_executor(None, _do)

    async def get_paired_devices(self) -> list[dict]:
        """List paired BLE-MIDI devices with connection state."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_paired_sync)

    def _get_paired_sync(self) -> list[dict]:
        output = _btctl("devices", "Paired", timeout=5)
        devices = []
        for line in output.splitlines():
            m = re.match(r"^Device\s+([0-9A-Fa-f:]{17})\s+(.+)$", line)
            if not m:
                continue
            address, name = m.group(1), m.group(2)

            # Check if it's a MIDI device
            info = _btctl("info", address, timeout=5)
            if MIDI_SERVICE_UUID not in info.lower():
                continue

            connected = "Connected: yes" in info
            devices.append({
                "name": name,
                "address": address,
                "paired": True,
                "connected": connected,
            })
        return devices
