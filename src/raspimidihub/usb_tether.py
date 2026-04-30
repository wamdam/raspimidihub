"""USB tether detection.

When a phone is plugged into a USB-A port and has USB tethering
(Personal Hotspot via USB on iOS) enabled, the kernel exposes a new
network interface and the phone's DHCP server gives the Pi an IP. This
module reports that state so the UI can show the user a clickable URL
to switch from the Pi's AP to the faster tethered link.

Detection is name-based, not bus-based: Pi 3B+ puts its built-in eth0
on the USB bus too, so "is on USB" would false-positive there. The
phone-tether names are stable: usb<N> for RNDIS, enx<MAC> for the
predictable-name path used by NCM/CDC-ECM (Android NCM and iOS).
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

_TETHER_NAME_RE = re.compile(r"^(usb\d+|enx[0-9a-f]{12})$")


def _list_iface_names(net_dir: Path) -> list[str]:
    try:
        return sorted(p.name for p in net_dir.iterdir())
    except OSError:
        return []


def _iface_ipv4(iface: str) -> str | None:
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", iface],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            try:
                return line.split()[1].split("/")[0]
            except IndexError:
                return None
    return None


def detect_tether(
    net_dir: Path = Path("/sys/class/net"),
    ip_lookup: Callable[[str], str | None] = _iface_ipv4,
) -> dict:
    """Return {active, interface, ip}. First matching iface with an IPv4 wins."""
    for name in _list_iface_names(net_dir):
        if not _TETHER_NAME_RE.match(name):
            continue
        ip = ip_lookup(name)
        if ip:
            return {"active": True, "interface": name, "ip": ip}
    return {"active": False, "interface": None, "ip": None}
