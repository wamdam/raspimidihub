"""USB tether detection tests.

Targets the detector's two responsibilities:
  - match the phone-tether name patterns (usb<N>, enx<MAC>) but ignore
    built-in interfaces (eth0, wlan0, lo) — the false-positive case
    that matters most is Pi 3B+ where eth0 sits on the USB bus and a
    "is on USB" check would catch it.
  - require an actual IPv4 lease — an interface that exists but has no
    IP yet is not "active".
"""

from __future__ import annotations

from pathlib import Path

from raspimidihub.usb_tether import detect_tether


def _net_dir(tmp_path: Path, names: list[str]) -> Path:
    d = tmp_path / "net"
    d.mkdir()
    for n in names:
        (d / n).mkdir()
    return d


class TestDetectTether:
    def test_no_interfaces(self, tmp_path):
        d = _net_dir(tmp_path, [])
        assert detect_tether(net_dir=d, ip_lookup=lambda _i: None) == {
            "active": False, "interface": None, "ip": None,
        }

    def test_only_built_in_interfaces(self, tmp_path):
        d = _net_dir(tmp_path, ["lo", "eth0", "wlan0", "end0"])
        result = detect_tether(net_dir=d, ip_lookup=lambda _i: "10.0.0.1")
        assert result["active"] is False

    def test_usb0_with_ip(self, tmp_path):
        d = _net_dir(tmp_path, ["wlan0", "usb0"])
        ips = {"usb0": "192.168.42.65"}
        result = detect_tether(net_dir=d, ip_lookup=lambda i: ips.get(i))
        assert result == {"active": True, "interface": "usb0", "ip": "192.168.42.65"}

    def test_enx_predictable_name_with_ip(self, tmp_path):
        d = _net_dir(tmp_path, ["enxaa11bb22cc33", "wlan0"])
        ips = {"enxaa11bb22cc33": "172.20.10.2"}
        result = detect_tether(net_dir=d, ip_lookup=lambda i: ips.get(i))
        assert result["active"] is True
        assert result["interface"] == "enxaa11bb22cc33"
        assert result["ip"] == "172.20.10.2"

    def test_iface_present_but_no_ip(self, tmp_path):
        d = _net_dir(tmp_path, ["usb0"])
        result = detect_tether(net_dir=d, ip_lookup=lambda _i: None)
        assert result["active"] is False

    def test_enx_with_uppercase_is_rejected(self, tmp_path):
        # Linux normalises predictable names to lowercase; uppercase
        # would be a malformed name and is not a real tether iface.
        d = _net_dir(tmp_path, ["enxAABBCCDDEEFF"])
        result = detect_tether(net_dir=d, ip_lookup=lambda _i: "1.2.3.4")
        assert result["active"] is False

    def test_first_active_iface_wins(self, tmp_path):
        # iterdir is sorted in our helper; usb0 should beat usb1.
        d = _net_dir(tmp_path, ["usb1", "usb0"])
        ips = {"usb0": "10.0.0.5", "usb1": "10.0.0.6"}
        result = detect_tether(net_dir=d, ip_lookup=lambda i: ips.get(i))
        assert result["interface"] == "usb0"

    def test_missing_net_dir(self, tmp_path):
        # Defensive: if /sys/class/net somehow can't be read, return
        # inactive instead of raising.
        result = detect_tether(net_dir=tmp_path / "does-not-exist",
                                ip_lookup=lambda _i: "1.2.3.4")
        assert result["active"] is False
