"""WiFi Access Point and client mode management.

Manages hostapd + dnsmasq for AP mode, NetworkManager for client mode.
"""

import asyncio
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

HOSTAPD_CONF = Path("/etc/hostapd/hostapd.conf")
DNSMASQ_AP_CONF = Path("/etc/dnsmasq.d/raspimidihub-ap.conf")
AP_IP = "192.168.4.1"
AP_SUBNET = "192.168.4.0/24"
DHCP_RANGE = "192.168.4.10,192.168.4.100,12h"
WLAN_IFACE = "wlan0"
CLIENT_TIMEOUT = 30  # seconds to wait for client connection


def _get_mac_suffix() -> str:
    """Get last 4 hex digits of wlan0 MAC for unique SSID."""
    try:
        mac = Path(f"/sys/class/net/{WLAN_IFACE}/address").read_text().strip()
        return mac.replace(":", "")[-4:].upper()
    except Exception:
        return "0000"


def _run(cmd: list[str], check: bool = True, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=timeout)


class WifiManager:
    """Manages WiFi AP and client modes."""

    def __init__(self):
        self._mode = "unknown"
        self._ssid = ""
        self._fallback_task: asyncio.Task | None = None

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def ssid(self) -> str:
        return self._ssid

    @property
    def ip(self) -> str:
        if self._mode == "ap":
            return AP_IP
        try:
            result = _run(["ip", "-4", "addr", "show", WLAN_IFACE], check=False)
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("inet "):
                    return line.split()[1].split("/")[0]
        except Exception:
            pass
        return ""

    def write_hostapd_conf(self, ssid: str, password: str, channel: int = 7):
        """Write hostapd configuration."""
        conf = f"""interface={WLAN_IFACE}
driver=nl80211
ssid={ssid}
hw_mode=g
channel={channel}
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase={password}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
"""
        HOSTAPD_CONF.parent.mkdir(parents=True, exist_ok=True)
        HOSTAPD_CONF.write_text(conf)
        log.info("Wrote hostapd config: SSID=%s", ssid)

    def write_dnsmasq_conf(self):
        """Write dnsmasq configuration for AP mode (DHCP + DNS captive portal)."""
        conf = f"""# RaspiMIDIHub AP mode
interface={WLAN_IFACE}
bind-interfaces
dhcp-range={DHCP_RANGE}
# Captive portal: resolve ALL DNS queries to our IP
address=/#/{AP_IP}
"""
        DNSMASQ_AP_CONF.parent.mkdir(parents=True, exist_ok=True)
        DNSMASQ_AP_CONF.write_text(conf)
        log.info("Wrote dnsmasq AP config")

    def start_ap(self, ssid: str = "", password: str = "midihub1"):
        """Start WiFi access point mode."""
        if not ssid:
            ssid = f"RaspiMIDIHub-{_get_mac_suffix()}"

        self._ssid = ssid

        # Tell NetworkManager to leave wlan0 alone
        _run(["nmcli", "device", "set", WLAN_IFACE, "managed", "no"], check=False)

        # Configure static IP on wlan0
        _run(["ip", "addr", "flush", "dev", WLAN_IFACE], check=False)
        _run(["ip", "addr", "add", f"{AP_IP}/24", "dev", WLAN_IFACE], check=False)
        _run(["ip", "link", "set", WLAN_IFACE, "up"], check=False)

        # Write configs
        self.write_hostapd_conf(ssid, password)
        self.write_dnsmasq_conf()

        # Start services
        _run(["systemctl", "unmask", "hostapd"], check=False)
        _run(["systemctl", "restart", "hostapd"], check=False)
        _run(["systemctl", "restart", "dnsmasq"], check=False)

        self._mode = "ap"
        log.info("WiFi AP started: SSID=%s, IP=%s", ssid, AP_IP)

    def stop_ap(self):
        """Stop WiFi access point."""
        _run(["systemctl", "stop", "hostapd"], check=False)
        _run(["systemctl", "stop", "dnsmasq"], check=False)
        _run(["ip", "addr", "flush", "dev", WLAN_IFACE], check=False)
        log.info("WiFi AP stopped")

    def start_client(self, ssid: str, password: str) -> bool:
        """Switch to client mode — connect to an existing WiFi network.
        Returns True on success.
        """
        self.stop_ap()

        # Give wlan0 back to NetworkManager
        _run(["nmcli", "device", "set", WLAN_IFACE, "managed", "yes"], check=False)

        # Try to connect
        try:
            result = _run(
                ["nmcli", "device", "wifi", "connect", ssid,
                 "password", password, "ifname", WLAN_IFACE],
                check=True, timeout=CLIENT_TIMEOUT,
            )
            self._mode = "client"
            self._ssid = ssid
            log.info("Connected to WiFi: %s", ssid)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            log.warning("Failed to connect to %s: %s", ssid, e)
            return False

    async def start_client_with_fallback(self, ssid: str, password: str,
                                          ap_ssid: str, ap_password: str):
        """Try client mode, fall back to AP after timeout."""
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, self.start_client, ssid, password)
        if not success:
            log.warning("Client mode failed, falling back to AP")
            await loop.run_in_executor(None, self.start_ap, ap_ssid, ap_password)

    def set_ap_password(self, new_password: str):
        """Update AP password in hostapd config and reload."""
        if len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters")

        if HOSTAPD_CONF.is_file():
            conf = HOSTAPD_CONF.read_text()
            lines = conf.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("wpa_passphrase="):
                    new_lines.append(f"wpa_passphrase={new_password}")
                else:
                    new_lines.append(line)
            HOSTAPD_CONF.write_text("\n".join(new_lines) + "\n")
            _run(["systemctl", "reload", "hostapd"], check=False)
            log.info("AP password updated")

    def scan_networks(self) -> list[dict]:
        """Scan for available WiFi networks."""
        try:
            result = _run(
                ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                 "--rescan", "yes"],
                check=False, timeout=15,
            )
            networks = []
            seen = set()
            for line in result.stdout.strip().splitlines():
                parts = line.split(":")
                if len(parts) >= 3 and parts[0] and parts[0] not in seen:
                    seen.add(parts[0])
                    networks.append({
                        "ssid": parts[0],
                        "signal": int(parts[1]) if parts[1].isdigit() else 0,
                        "security": parts[2],
                    })
            return sorted(networks, key=lambda n: n["signal"], reverse=True)
        except Exception:
            log.exception("WiFi scan failed")
            return []
