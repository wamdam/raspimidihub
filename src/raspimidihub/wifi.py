"""WiFi Access Point, client mode, and network interface management.

Manages hostapd + dnsmasq for AP mode, NetworkManager for client/ethernet.
"""

import asyncio
import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

HOSTAPD_CONF = Path("/run/raspimidihub/hostapd.conf")
DNSMASQ_AP_CONF = Path("/run/raspimidihub/dnsmasq-ap.conf")
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
        """Write hostapd configuration to tmpfs."""
        HOSTAPD_CONF.parent.mkdir(parents=True, exist_ok=True)
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
        HOSTAPD_CONF.write_text(conf)
        log.info("Wrote hostapd config: SSID=%s", ssid)

    def write_dnsmasq_conf(self):
        """Write dnsmasq configuration for AP mode (DHCP + DNS captive portal)."""
        conf = f"""# RaspiMIDIHub AP mode
interface={WLAN_IFACE}
bind-interfaces
dhcp-range={DHCP_RANGE}
dhcp-leasefile=/run/raspimidihub/dnsmasq.leases
# Captive portal: resolve ALL DNS queries to our IP
address=/#/{AP_IP}
# Don't read /etc/resolv.conf or /etc/hosts
no-resolv
no-hosts
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

        # Stop system services (we run our own instances)
        _run(["systemctl", "stop", "hostapd"], check=False)
        _run(["systemctl", "stop", "dnsmasq"], check=False)

        # Kill any previous instances we started
        _run(["pkill", "-f", "hostapd.*raspimidihub"], check=False)
        _run(["pkill", "-f", "dnsmasq.*raspimidihub"], check=False)
        import time; time.sleep(0.5)

        # Start hostapd and dnsmasq directly with our config files
        _run(["hostapd", "-B", str(HOSTAPD_CONF)], check=False)
        _run(["dnsmasq", "--conf-file=" + str(DNSMASQ_AP_CONF), "--pid-file=/run/raspimidihub/dnsmasq.pid"], check=False)

        self._mode = "ap"
        log.info("WiFi AP started: SSID=%s, IP=%s", ssid, AP_IP)

    def stop_ap(self):
        """Stop WiFi access point."""
        _run(["pkill", "-f", "hostapd.*raspimidihub"], check=False)
        _run(["pkill", "-f", "dnsmasq.*raspimidihub"], check=False)
        _run(["ip", "addr", "flush", "dev", WLAN_IFACE], check=False)
        log.info("WiFi AP stopped")

    def start_client(self, ssid: str, password: str) -> bool:
        """Switch to client mode — connect to an existing WiFi network.
        Returns True on success.
        """
        import time
        import uuid

        self.stop_ap()

        # Write .nmconnection file directly (bypasses NM keyfile plugin writability check)
        _run(["mount", "-o", "remount,rw", "/"], check=False, timeout=5)
        try:
            conn_file = NM_CONN_DIR / f"{ssid}.nmconnection"
            conn_uuid = str(uuid.uuid4())
            conf = (
                f"[connection]\n"
                f"id={ssid}\n"
                f"uuid={conn_uuid}\n"
                f"type=wifi\n"
                f"interface-name={WLAN_IFACE}\n"
                f"\n"
                f"[wifi]\n"
                f"mode=infrastructure\n"
                f"ssid={ssid}\n"
                f"\n"
                f"[wifi-security]\n"
                f"key-mgmt=wpa-psk\n"
                f"psk={password}\n"
                f"\n"
                f"[ipv4]\n"
                f"method=auto\n"
                f"\n"
                f"[ipv6]\n"
                f"method=disabled\n"
            )
            conn_file.write_text(conf)
            conn_file.chmod(0o600)
            log.info("Wrote WiFi connection file for %s", ssid)
        except Exception:
            log.exception("Failed to write WiFi connection file")
            return False
        finally:
            _run(["mount", "-o", "remount,ro", "/"], check=False, timeout=5)

        # Give wlan0 back to NetworkManager
        _run(["nmcli", "device", "set", WLAN_IFACE, "managed", "yes"], check=False)
        # Reload NM to pick up the new connection file
        _run(["nmcli", "connection", "reload"], check=False, timeout=5)
        time.sleep(2)

        # Activate the connection
        try:
            result = _run(
                ["nmcli", "connection", "up", ssid, "ifname", WLAN_IFACE],
                check=True, timeout=CLIENT_TIMEOUT,
            )
            self._mode = "client"
            self._ssid = ssid
            log.info("Connected to WiFi: %s", ssid)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            log.warning("Failed to activate %s: %s", ssid, e)
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

    def check_client_connected(self) -> bool:
        """Check if wlan0 has an IP address in client mode."""
        if self._mode != "client":
            return True
        try:
            result = _run(["ip", "-4", "addr", "show", WLAN_IFACE],
                          check=False, timeout=5)
            return "inet " in result.stdout
        except Exception:
            return False

    def scan_networks(self) -> list[dict]:
        """Scan for available WiFi networks using iw (works in AP mode)."""
        try:
            result = _run(
                ["iw", "dev", "wlan0", "scan"],
                check=False, timeout=15,
            )
            networks = []
            seen = set()
            current = {}
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("BSS "):
                    if current.get("ssid") and current["ssid"] not in seen:
                        seen.add(current["ssid"])
                        networks.append(current)
                    current = {"ssid": "", "signal": 0, "security": ""}
                elif line.startswith("SSID: "):
                    current["ssid"] = line[6:]
                elif line.startswith("signal: "):
                    # e.g. "signal: -67.00 dBm" → convert to 0-100 quality
                    try:
                        dbm = float(line.split()[1])
                        current["signal"] = max(0, min(100, int(2 * (dbm + 100))))
                    except (ValueError, IndexError):
                        pass
                elif "WPA" in line or "RSN" in line:
                    current["security"] = "WPA"
            # Last entry
            if current.get("ssid") and current["ssid"] not in seen:
                networks.append(current)
            return sorted(networks, key=lambda n: n["signal"], reverse=True)
        except Exception:
            log.exception("WiFi scan failed")
            return []


NM_CONN_DIR = Path("/etc/NetworkManager/system-connections")


def get_interface_info(iface: str) -> dict:
    """Get current IP configuration for a network interface."""
    info = {"interface": iface, "method": "disabled", "address": "", "netmask": "", "gateway": ""}
    try:
        result = _run(["ip", "-4", "addr", "show", iface], check=False, timeout=5)
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                parts = line.split()
                addr_cidr = parts[1]
                addr, prefix = addr_cidr.split("/")
                info["address"] = addr
                # Convert CIDR prefix to netmask
                bits = int(prefix)
                mask = (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF
                info["netmask"] = f"{(mask >> 24) & 0xFF}.{(mask >> 16) & 0xFF}.{(mask >> 8) & 0xFF}.{mask & 0xFF}"
    except Exception:
        pass

    # Get gateway
    try:
        result = _run(["ip", "route", "show", "dev", iface], check=False, timeout=5)
        for line in result.stdout.splitlines():
            if line.startswith("default via "):
                info["gateway"] = line.split()[2]
    except Exception:
        pass

    # Get method from NM connection file
    for nm_file in NM_CONN_DIR.glob("*.nmconnection"):
        try:
            content = nm_file.read_text()
            if f"interface-name={iface}" in content:
                if "method=manual" in content:
                    info["method"] = "manual"
                elif "method=auto" in content:
                    info["method"] = "auto"
                break
        except OSError:
            pass

    if info["address"]:
        info["up"] = True
    else:
        info["up"] = False

    return info


def get_all_interfaces() -> list[dict]:
    """Get info for all physical network interfaces."""
    interfaces = []
    for iface in sorted(Path("/sys/class/net").iterdir()):
        name = iface.name
        if name == "lo" or name.startswith("vir"):
            continue
        interfaces.append(get_interface_info(name))
    return interfaces


def configure_interface(iface: str, method: str, address: str = "",
                        netmask: str = "255.255.255.0", gateway: str = "") -> bool:
    """Configure a network interface. Remounts rw/ro for persistence.

    method: "auto" (DHCP) or "manual" (static IP)
    """
    # Find the NM connection file for this interface
    conn_file = None
    conn_name = None
    for nm_file in NM_CONN_DIR.glob("*.nmconnection"):
        try:
            content = nm_file.read_text()
            if f"interface-name={iface}" in content:
                conn_file = nm_file
                for line in content.splitlines():
                    if line.startswith("id="):
                        conn_name = line[3:]
                break
        except OSError:
            pass

    if conn_file is None:
        log.warning("No NM connection found for %s", iface)
        return False

    try:
        # Remount rw
        _run(["mount", "-o", "remount,rw", "/"], check=True, timeout=5)

        # Read current file
        content = conn_file.read_text()
        lines = content.splitlines()
        new_lines = []
        in_ipv4 = False
        ipv4_written = False

        for line in lines:
            if line.strip() == "[ipv4]":
                in_ipv4 = True
                new_lines.append(line)
                # Write our config
                if method == "manual" and address:
                    # Convert netmask to CIDR prefix
                    octets = [int(o) for o in netmask.split(".")]
                    prefix = sum(bin(o).count("1") for o in octets)
                    new_lines.append(f"address1={address}/{prefix}")
                    if gateway:
                        new_lines[-1] += f",{gateway}"
                    new_lines.append("dns=8.8.8.8;8.8.4.4;")
                new_lines.append(f"method={method}")
                ipv4_written = True
                continue
            elif in_ipv4:
                if line.startswith("["):
                    # New section, end of ipv4
                    in_ipv4 = False
                    new_lines.append(line)
                elif line.startswith(("address", "method", "dns")):
                    continue  # Skip old ipv4 settings
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        conn_file.write_text("\n".join(new_lines) + "\n")

        # Reload NM and apply — timeouts are non-fatal (file is already written)
        try:
            _run(["nmcli", "connection", "reload"], check=False, timeout=10)
        except subprocess.TimeoutExpired:
            log.warning("nmcli reload timed out, continuing")
        if conn_name:
            try:
                _run(["nmcli", "connection", "up", conn_name], check=False, timeout=15)
            except subprocess.TimeoutExpired:
                log.warning("nmcli connection up timed out, continuing")

        log.info("Configured %s: method=%s address=%s gateway=%s", iface, method, address, gateway)
        return True

    except Exception:
        log.exception("Failed to configure %s", iface)
        return False
    finally:
        _run(["mount", "-o", "remount,ro", "/"], check=False, timeout=5)
