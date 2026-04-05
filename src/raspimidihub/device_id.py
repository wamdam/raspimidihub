"""Stable device identification using USB topology path + VID:PID.

ALSA client IDs change on every reconnect. We need stable identifiers
to persist routing configurations across reboots and reconnects.

Stable ID format: "usb-<bus>-<port_path>-<vid>:<pid>"
Example: "usb-1-1.2-0763:1044" (M-Audio Keystation on bus 1, port 1.2)

For non-USB ALSA devices (built-in audio, HDMI), we use:
"builtin-<card_id>"
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class StableDeviceInfo:
    stable_id: str
    vid: str  # USB vendor ID (hex)
    pid: str  # USB product ID (hex)
    usb_path: str  # USB topology path (e.g. "1-1.2")
    card_num: int  # ALSA card number
    display_name: str  # User-facing name (custom or default)
    custom_name: str = ""  # User-assigned name (empty = use default)

    @property
    def name(self) -> str:
        return self.custom_name or self.display_name


def _find_usb_ancestor(device_path: Path) -> Path | None:
    """Walk up sysfs to find the USB device node (has idVendor)."""
    path = device_path.resolve()
    for _ in range(10):  # max depth
        if (path / "idVendor").is_file():
            return path
        parent = path.parent
        if parent == path:
            break
        path = parent
    return None


def get_card_stable_id(card_num: int) -> StableDeviceInfo | None:
    """Get stable identification for an ALSA sound card."""
    card_path = Path(f"/sys/class/sound/card{card_num}")
    if not card_path.exists():
        return None

    device_link = card_path / "device"
    if not device_link.exists():
        # Built-in device without a device link
        try:
            card_id = (card_path / "id").read_text().strip()
        except OSError:
            card_id = f"card{card_num}"
        return StableDeviceInfo(
            stable_id=f"builtin-{card_id}",
            vid="", pid="", usb_path="",
            card_num=card_num,
            display_name=card_id,
        )

    usb_dev = _find_usb_ancestor(device_link)
    if usb_dev is None:
        # Non-USB device (e.g. platform device)
        try:
            card_id = (card_path / "id").read_text().strip()
        except OSError:
            card_id = f"card{card_num}"
        return StableDeviceInfo(
            stable_id=f"builtin-{card_id}",
            vid="", pid="", usb_path="",
            card_num=card_num,
            display_name=card_id,
        )

    try:
        vid = (usb_dev / "idVendor").read_text().strip()
        pid = (usb_dev / "idProduct").read_text().strip()
    except OSError:
        vid, pid = "0000", "0000"

    # USB path: extract bus and port path from the sysfs path
    # e.g. /sys/devices/platform/soc/3f980000.usb/usb1/1-1/1-1.2/...
    usb_path = ""
    dev_name = usb_dev.name  # e.g. "1-1.2" or "1-1.4:1.0"
    # Strip interface number if present
    dev_name = dev_name.split(":")[0]
    usb_path = dev_name

    try:
        card_id = (card_path / "id").read_text().strip()
    except OSError:
        card_id = f"card{card_num}"

    # Try to get a better display name from USB product string
    display_name = card_id
    try:
        product = (usb_dev / "product").read_text().strip()
        if product:
            display_name = product
    except OSError:
        pass

    stable_id = f"usb-{usb_path}-{vid}:{pid}"

    return StableDeviceInfo(
        stable_id=stable_id,
        vid=vid, pid=pid,
        usb_path=usb_path,
        card_num=card_num,
        display_name=display_name,
    )


def alsa_client_to_card(client_id: int) -> int | None:
    """Map an ALSA sequencer client ID to a sound card number.

    For kernel clients, the card number is embedded in /proc/asound/seq/clients.
    We parse it from there.
    """
    try:
        with open("/proc/asound/seq/clients") as f:
            current_client = None
            for line in f:
                m = re.match(r'^Client\s+(\d+)\s*:', line)
                if m:
                    current_client = int(m.group(1))
                    continue
                if current_client == client_id:
                    # Look for card number in the client's info
                    cm = re.search(r'\[.*card\s*=\s*(\d+)', line)
                    if cm:
                        return int(cm.group(1))
    except OSError:
        pass

    # Fallback: scan /proc/asound/cardN/midiN for matching client
    for card_dir in sorted(Path("/proc/asound").glob("card*")):
        try:
            card_num = int(card_dir.name.replace("card", ""))
        except ValueError:
            continue
        for midi_file in card_dir.glob("midi*"):
            try:
                content = midi_file.read_text()
                if f"Client {client_id}" in content or f"client {client_id}" in content:
                    return card_num
            except OSError:
                pass

    return None


class DeviceRegistry:
    """Maps between ALSA client IDs and stable device identifiers."""

    def __init__(self):
        self._by_client: dict[int, StableDeviceInfo] = {}
        self._by_stable_id: dict[str, StableDeviceInfo] = {}
        self._custom_names: dict[str, str] = {}  # stable_id -> custom name

    def load_custom_names(self, names: dict[str, str]):
        """Load custom device names from config."""
        self._custom_names = dict(names)

    def scan(self, alsa_client_ids: list[int]) -> dict[int, StableDeviceInfo]:
        """Scan and register devices for the given ALSA client IDs."""
        self._by_client.clear()
        self._by_stable_id.clear()

        for client_id in alsa_client_ids:
            card_num = alsa_client_to_card(client_id)
            if card_num is None:
                continue

            info = get_card_stable_id(card_num)
            if info is None:
                continue

            # Apply custom name if set
            if info.stable_id in self._custom_names:
                info.custom_name = self._custom_names[info.stable_id]

            self._by_client[client_id] = info
            self._by_stable_id[info.stable_id] = info

        return self._by_client

    def get_by_client(self, client_id: int) -> StableDeviceInfo | None:
        return self._by_client.get(client_id)

    def get_by_stable_id(self, stable_id: str) -> StableDeviceInfo | None:
        return self._by_stable_id.get(stable_id)

    def client_for_stable_id(self, stable_id: str) -> int | None:
        """Find current ALSA client ID for a stable device ID."""
        for client_id, info in self._by_client.items():
            if info.stable_id == stable_id:
                return client_id
        return None

    def set_custom_name(self, stable_id: str, name: str):
        """Set a custom display name for a device."""
        self._custom_names[stable_id] = name
        if stable_id in self._by_stable_id:
            self._by_stable_id[stable_id].custom_name = name

    def get_custom_names(self) -> dict[str, str]:
        return dict(self._custom_names)

    def all_devices(self) -> list[StableDeviceInfo]:
        return list(self._by_client.values())
