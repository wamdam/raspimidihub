"""WiFi Access Point, client mode, and network interface management.

Manages hostapd + dnsmasq for AP mode, NetworkManager for client/ethernet.
"""

import asyncio
import contextlib
import logging
import os
import re
import signal
import subprocess
import time
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


@contextlib.contextmanager
def _rw_rootfs():
    """Context manager: remount / read-write, then read-only on exit."""
    _run(["mount", "-o", "remount,rw", "/"], check=False, timeout=5)
    try:
        yield
    finally:
        _run(["mount", "-o", "remount,ro", "/"], check=False, timeout=5)


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

    def survey_ap_channel(self) -> int:
        """Pick the least-busy of {1, 6, 11} from a quick 2.4 GHz scan.

        Runs `iwlist wlan0 scan` and weighs each detected AP's signal power
        against the three non-overlapping channels (bleed ±2 channels because
        2.4 GHz channels are 22 MHz wide on a 5 MHz grid). Returns 11 on any
        failure — rare empty scan, tool missing, etc. Called once at AP start;
        scan takes about 2-3 seconds.
        """
        try:
            # Scan needs wlan0 up in managed mode. On boot this is the default;
            # if a previous AP session left it in master mode, force it back.
            _run(["ip", "link", "set", WLAN_IFACE, "up"], check=False, timeout=3)
            result = _run(["iwlist", WLAN_IFACE, "scan"],
                          check=False, timeout=8)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            log.warning("channel survey: scan failed (%s), defaulting to 11", e)
            return 11

        if result.returncode != 0 or not result.stdout:
            log.warning("channel survey: empty scan, defaulting to 11")
            return 11

        # Parse Channel: + Signal level per cell. Sum linear-power weight per
        # target channel, with ±2 channel bleed.
        scores = {1: 0.0, 6: 0.0, 11: 0.0}
        ch = None
        ap_count = 0
        for line in result.stdout.splitlines():
            m = re.search(r"Channel\s*[:=]\s*(\d+)", line)
            if m:
                ch = int(m.group(1))
                continue
            m = re.search(r"Signal level\s*=\s*(-?\d+)\s*dBm", line)
            if m and ch is not None:
                signal_dbm = int(m.group(1))
                power = 10 ** (signal_dbm / 10.0)  # linear scale
                for target in scores:
                    dist = abs(ch - target)
                    if dist <= 2:
                        scores[target] += power / (1 + dist)
                ap_count += 1
                ch = None

        if ap_count == 0:
            log.info("channel survey: no APs detected, defaulting to 11")
            return 11

        best = min(scores, key=scores.get)
        log.info("channel survey: %d APs, scores=%s, picked %d",
                 ap_count, {k: f"{v:.2e}" for k, v in scores.items()}, best)
        return best

    def _render_hostapd_conf(self, ssid: str, password: str, channel: int) -> str:
        """Build the hostapd config text without writing it.

        hostapd runs as raspimidihub-hostapd.service (Type=simple, no
        -B), so its stderr lands in journald automatically — no need
        for `logger_syslog`. Association / deauth events show up under
        the `raspimidihub-hostapd` unit, not interleaved with the main
        service log.
        """
        return f"""interface={WLAN_IFACE}
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

    def _render_dnsmasq_conf(self) -> str:
        """Build the dnsmasq AP config text without writing it."""
        return f"""# RaspiMIDIHub AP mode
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

    def write_hostapd_conf(self, ssid: str, password: str, channel: int = 7):
        """Write hostapd configuration to tmpfs."""
        HOSTAPD_CONF.parent.mkdir(parents=True, exist_ok=True)
        HOSTAPD_CONF.write_text(self._render_hostapd_conf(ssid, password, channel))
        log.info("Wrote hostapd config: SSID=%s", ssid)

    def write_dnsmasq_conf(self):
        """Write dnsmasq configuration for AP mode (DHCP + DNS captive portal)."""
        DNSMASQ_AP_CONF.parent.mkdir(parents=True, exist_ok=True)
        DNSMASQ_AP_CONF.write_text(self._render_dnsmasq_conf())
        log.info("Wrote dnsmasq AP config")

    @staticmethod
    def _channel_from_conf(conf: str) -> int | None:
        """Extract the channel= value from a hostapd config."""
        for line in conf.splitlines():
            if line.startswith("channel="):
                try:
                    return int(line.split("=", 1)[1].strip())
                except ValueError:
                    return None
        return None

    @staticmethod
    def _find_pids(executable: str, required_arg: str,
                   proc_root: Path = Path("/proc")) -> list[int]:
        """PIDs whose argv0 basename is `executable` and whose argv contains
        `required_arg` as a literal substring of one of the args after argv0.

        Bypasses pgrep -f, which matches against the full cmdline of any
        process — including shell wrappers, journalctl tails, or our own
        python -c snippets that happen to mention "hostapd" and the config
        path. Reading /proc/<pid>/cmdline directly is precise: we only count
        a process if it really *is* an `executable` invocation with our
        config as one of its argv tokens.

        `proc_root` is parameterised so tests can inject a synthetic /proc.
        """
        pids: list[int] = []
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes()
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
            if not cmdline:
                continue
            argv = cmdline.split(b"\0")
            if not argv or not argv[0]:
                continue
            try:
                argv_str = [a.decode("utf-8") for a in argv if a]
            except UnicodeDecodeError:
                continue
            if not argv_str:
                continue
            if argv_str[0].rsplit("/", 1)[-1] != executable:
                continue
            if any(required_arg in a for a in argv_str[1:]):
                pids.append(int(entry.name))
        return pids

    @staticmethod
    def _wlan_mode() -> str:
        """Return wlan0 type from `iw dev wlan0 info` ('AP' / 'managed' / '')."""
        try:
            r = subprocess.run(["iw", "dev", WLAN_IFACE, "info"],
                               capture_output=True, text=True, timeout=2)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""
        if r.returncode != 0:
            return ""
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("type "):
                return line.split(None, 1)[1].strip()
        return ""

    @classmethod
    def _kill_and_wait(cls, executable: str, required_arg: str,
                      term_timeout: float = 2.0, kill_timeout: float = 0.5) -> None:
        """SIGTERM matching processes, wait, then SIGKILL stragglers.

        Prevents the "two hostapds racing on wlan0" failure mode: spawning
        a fresh hostapd while the old one is still bound produces a
        half-broken AP that clients associate with and immediately drop.
        """
        pids = cls._find_pids(executable, required_arg)
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + term_timeout
        while time.monotonic() < deadline:
            if not cls._find_pids(executable, required_arg):
                return
            time.sleep(0.05)
        stragglers = cls._find_pids(executable, required_arg)
        for pid in stragglers:
            log.warning("%s pid=%d ignored SIGTERM, sending SIGKILL", executable, pid)
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + kill_timeout
        while time.monotonic() < deadline:
            if not cls._find_pids(executable, required_arg):
                return
            time.sleep(0.05)
        if cls._find_pids(executable, required_arg):
            log.error("%s pids %s survived SIGKILL", executable,
                      cls._find_pids(executable, required_arg))

    @staticmethod
    def _claim_wlan0_for_ap() -> None:
        """Detach wlan0 from NetworkManager and assign the AP IP.

        Idempotent — safe to call multiple times. Used both on the first
        bring-up and during the retry path when the initial hostapd
        spawn loses a race with wpa_supplicant releasing the interface.
        """
        _run(["nmcli", "device", "set", WLAN_IFACE, "managed", "no"], check=False)
        _run(["ip", "addr", "flush", "dev", WLAN_IFACE], check=False)
        _run(["ip", "addr", "add", f"{AP_IP}/24", "dev", WLAN_IFACE], check=False)
        _run(["ip", "link", "set", WLAN_IFACE, "up"], check=False)

    @classmethod
    def _spawn_hostapd(cls) -> bool:
        """Start (or restart) hostapd via raspimidihub-hostapd.service.

        Replaces the old subprocess.Popen + taskset + -B daemonise flow.
        systemd handles lifecycle (Restart=on-failure), CPU pin (CPUAffinity
        drop-in pins to 0–2 so the asyncio loop's CPU 3 stays clean), and
        stderr → journald capture. Method name kept so the existing
        retry-on-fresh-boot path in start_ap doesn't change.

        Returns True iff wlan0 reaches AP mode within 5 s of systemctl
        returning. The window is wider than the old 3 s because systemd
        may restart hostapd once if it lost a race with NetworkManager
        releasing wlan0.
        """
        try:
            r = subprocess.run(
                ["systemctl", "restart", "raspimidihub-hostapd.service"],
                capture_output=True, text=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            log.error("systemctl restart raspimidihub-hostapd timed out")
            return False

        if r.returncode != 0:
            log.error("systemctl restart raspimidihub-hostapd exited %d: %s",
                      r.returncode,
                      (r.stderr or "").strip() or "(empty)")
            return False

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if cls._wlan_mode() == "AP":
                return True
            time.sleep(0.1)

        log.error("systemctl reported success but wlan0 stayed in mode=%r",
                  cls._wlan_mode())
        return False

    @classmethod
    def _hostapd_active(cls) -> bool:
        """Is raspimidihub-hostapd.service currently active? Used by the
        idempotency check in start_ap — combined with config-text match,
        it decides whether to leave the existing AP alone or kick a
        restart. Returns False on any error so we err on the side of
        restarting (the recovery path), not silently skipping (the
        false-positive that bit us before)."""
        try:
            r = subprocess.run(
                ["systemctl", "is-active", "raspimidihub-hostapd.service"],
                capture_output=True, text=True, timeout=3,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
        return (r.stdout or "").strip() == "active"

    def start_ap(self, ssid: str = "", password: str = "midihub1"):
        """Bring up WiFi AP mode. Idempotent.

        If the candidate config matches the on-disk config, our hostapd +
        dnsmasq are alive, and wlan0 is actually in AP mode, returns
        without touching wlan0 — so a service restart doesn't blink the
        SSID and confuse client devices. Otherwise (re)writes the configs
        and (re)spawns whichever process actually changed.
        """
        if not ssid:
            ssid = f"RaspiMIDIHub-{_get_mac_suffix()}"
        self._ssid = ssid

        # Re-use channel from the existing config if present. /run is tmpfs,
        # so a real reboot clears it and the next survey runs naturally.
        existing_hostapd = HOSTAPD_CONF.read_text() if HOSTAPD_CONF.is_file() else None
        existing_dnsmasq = DNSMASQ_AP_CONF.read_text() if DNSMASQ_AP_CONF.is_file() else None

        if existing_hostapd:
            channel = self._channel_from_conf(existing_hostapd) or 11
            log.info("WiFi AP: re-using channel %d from prior config", channel)
        else:
            channel = self.survey_ap_channel()

        candidate_hostapd = self._render_hostapd_conf(ssid, password, channel)
        candidate_dnsmasq = self._render_dnsmasq_conf()

        # Idempotency guard: only skip restart when ALL three hold —
        # config matches, the systemd unit is actually active, AND the
        # kernel reports wlan0 as type AP. Without the wlan_mode check,
        # an external `pkill hostapd` leaves wlan0 in type=managed and
        # we'd silently keep "skipping restart" forever.
        hostapd_active = self._hostapd_active()
        dnsmasq_pids = self._find_pids("dnsmasq", str(DNSMASQ_AP_CONF))
        wlan_mode = self._wlan_mode()

        hostapd_ok = (existing_hostapd == candidate_hostapd
                      and hostapd_active
                      and wlan_mode == "AP")
        dnsmasq_ok = (existing_dnsmasq == candidate_dnsmasq
                      and len(dnsmasq_pids) == 1)

        if hostapd_ok and dnsmasq_ok:
            self._mode = "ap"
            self._disable_wlan_power_save()
            log.info("WiFi AP already up and matching: SSID=%s, channel=%d — skipping restart",
                     ssid, channel)
            return

        # Log why the fast path was bypassed — invaluable when diagnosing
        # the exact reproduction the patch above guards against.
        if not hostapd_ok:
            log.info("WiFi AP: hostapd needs (re)start "
                     "(config_match=%s active=%s wlan_mode=%s)",
                     existing_hostapd == candidate_hostapd,
                     hostapd_active, wlan_mode or "?")
        if not dnsmasq_ok:
            log.info("WiFi AP: dnsmasq needs (re)start "
                     "(config_match=%s pids=%s)",
                     existing_dnsmasq == candidate_dnsmasq, dnsmasq_pids)

        # Only touch wlan0's network layer when hostapd itself needs to be
        # restarted. Replacing dnsmasq alone shouldn't blink the IP — that
        # would make avahi withdraw + re-register and confuse clients.
        if not hostapd_ok:
            self._claim_wlan0_for_ap()

            HOSTAPD_CONF.parent.mkdir(parents=True, exist_ok=True)
            HOSTAPD_CONF.write_text(candidate_hostapd)
            log.info("Wrote hostapd config: SSID=%s, channel=%d", ssid, channel)

            # Migration cleanup: an older raspimidihub package spawned
            # hostapd directly via subprocess.Popen. If a process is
            # still alive from that path during the upgrade, kill it
            # before letting systemd start a fresh one — otherwise two
            # hostapds would race on wlan0. No-op on clean installs.
            old_pids = self._find_pids("hostapd", str(HOSTAPD_CONF))
            if old_pids:
                log.info("Cleaning up subprocess-managed hostapd PIDs: %s", old_pids)
                self._kill_and_wait("hostapd", str(HOSTAPD_CONF))
            # systemctl stop covers the distro hostapd.service if it ever
            # got enabled — keeps it from racing with our unit on wlan0.
            _run(["systemctl", "stop", "hostapd"], check=False)

            if not self._spawn_hostapd():
                # First attempt failed — most likely because NM /
                # wpa_supplicant hadn't finished releasing wlan0 yet
                # (visible at fresh boot only). Bounce the interface,
                # let NM settle, and try once more. Stop the service
                # cleanly so systemd doesn't keep its own
                # Restart=on-failure cycle running in parallel with
                # our retry.
                log.warning("hostapd first spawn failed; bouncing wlan0 and retrying")
                _run(["systemctl", "stop", "raspimidihub-hostapd.service"],
                     check=False)
                _run(["ip", "link", "set", WLAN_IFACE, "down"], check=False)
                time.sleep(1.5)
                self._claim_wlan0_for_ap()
                if not self._spawn_hostapd():
                    log.error("hostapd retry also failed — AP is not running")

        if not dnsmasq_ok:
            DNSMASQ_AP_CONF.parent.mkdir(parents=True, exist_ok=True)
            DNSMASQ_AP_CONF.write_text(candidate_dnsmasq)
            log.info("Wrote dnsmasq AP config")

            _run(["systemctl", "stop", "dnsmasq"], check=False)
            self._kill_and_wait("dnsmasq", str(DNSMASQ_AP_CONF))
            # Same reasoning as hostapd above — keep dnsmasq off the
            # isolated core so it can answer DHCP / DNS without
            # waiting for the asyncio loop's CPU.
            _run(["taskset", "-c", "0-2",
                  "dnsmasq", "--conf-file=" + str(DNSMASQ_AP_CONF),
                  "--pid-file=/run/raspimidihub/dnsmasq.pid"], check=False)

        self._mode = "ap"
        self._disable_wlan_power_save()

        what = (["hostapd"] if not hostapd_ok else []) + \
               (["dnsmasq"] if not dnsmasq_ok else [])
        log.info("WiFi AP started: SSID=%s, IP=%s, channel=%d (restarted: %s)",
                 ssid, AP_IP, channel, ",".join(what) or "none")

    @staticmethod
    def _disable_wlan_power_save() -> None:
        """Force wlan0 power save off via `iw`.

        The Pi 3 brcmfmac driver re-enables WiFi power management on
        every cfg80211 init — most visibly when wpa_supplicant connects
        in client mode, which leaves the flag stuck on the next AP
        bring-up. With power save on in AP mode the radio accepts
        clients at first but starts dropping probe / auth frames after
        a while, so the AP looks fine but new associations time out
        (this exact symptom broke our user's phone connection).

        Idempotent. Cheap. The check=False / timeout makes it
        non-fatal if `iw` is missing — we still warn so it shows up
        in journalctl when reproducing.
        """
        r = _run(["iw", "dev", WLAN_IFACE, "set", "power_save", "off"],
                 check=False, timeout=3)
        if r.returncode != 0:
            log.warning("Failed to disable wlan0 power save (iw rc=%d): %s",
                        r.returncode, (r.stderr or "").strip() or "(empty)")
        else:
            log.info("wlan0 power_save disabled via iw")

    def stop_ap(self):
        """Stop WiFi access point."""
        _run(["systemctl", "stop", "raspimidihub-hostapd.service"], check=False)
        # Belt-and-braces: kill any leftover subprocess-spawned hostapd
        # from a pre-systemd-migration install. No-op once the upgrade
        # has gone through one start_ap cycle.
        self._kill_and_wait("hostapd", str(HOSTAPD_CONF))
        self._kill_and_wait("dnsmasq", str(DNSMASQ_AP_CONF))
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
        try:
            with _rw_rootfs():
                conn_file = NM_CONN_DIR / f"{ssid}.nmconnection"
                conn_file.write_text(
                    f"[connection]\nid={ssid}\nuuid={uuid.uuid4()}\ntype=wifi\n"
                    f"interface-name={WLAN_IFACE}\n\n[wifi]\nmode=infrastructure\nssid={ssid}\n\n"
                    f"[wifi-security]\nkey-mgmt=wpa-psk\npsk={password}\n\n"
                    f"[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=disabled\n"
                )
                conn_file.chmod(0o600)
            log.info("Wrote WiFi connection file for %s", ssid)
        except Exception:
            log.exception("Failed to write WiFi connection file")
            return False

        # Give wlan0 back to NetworkManager. Best-effort: a stuck or busy
        # NM should not torpedo the whole switch — the subsequent
        # `connection up` is the real arbiter of success.
        for cmd in (
            ["nmcli", "device", "set", WLAN_IFACE, "managed", "yes"],
            # Reload NM to pick up the new connection file. We saw a 5s
            # cap fire `TimeoutExpired` in the wild (#wifi-stuck-after-
            # update-check) while the reload still completed in the
            # background — bump to 15s and swallow timeouts. `check=False`
            # doesn't suppress TimeoutExpired in subprocess.run, so we
            # have to catch it explicitly.
            ["nmcli", "connection", "reload"],
        ):
            try:
                _run(cmd, check=False, timeout=15)
            except subprocess.TimeoutExpired:
                log.warning("%s timed out (continuing — `connection up` "
                            "will decide success)", " ".join(cmd))
        time.sleep(2)

        # Activate the connection
        try:
            _run(
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
        """Try client mode, fall back to AP on failure.

        "Failure" covers both `start_client` returning False *and*
        `start_client` raising — the latter happens when an underlying
        subprocess (nmcli, ip, ...) times out unexpectedly. The function
        name promises a fallback; honour it on every error path."""
        loop = asyncio.get_event_loop()
        try:
            success = await loop.run_in_executor(
                None, self.start_client, ssid, password)
        except Exception:
            log.exception("start_client raised, treating as failure")
            success = False
        if not success:
            log.warning("Client mode failed, falling back to AP")
            try:
                await loop.run_in_executor(
                    None, self.start_ap, ap_ssid, ap_password)
            except Exception:
                # start_ap failing here is bad but not the worst case —
                # the update_flow watchdog stays armed when wifi.mode is
                # not "ap" and will systemctl-restart raspimidihub,
                # whose async_main brings the AP back unconditionally.
                log.exception("start_ap fallback raised — relying on watchdog")

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


def ensure_eth_link_local(iface: str = "eth0") -> bool:
    """Make a direct hub-to-hub Ethernet cable work without a router:
    add `link-local=enabled` to the [ipv4] section of the interface's
    NM profile (NetworkManager ≥ 1.40; Pi-OS Bookworm ships 1.42).
    With DHCP present nothing changes; without it, NM self-assigns a
    169.254.x.x address instead of failing the connection — which is
    what mDNS discovery between two hubs rides on. Profiles with
    method=manual are left alone (the user chose static addressing).
    Called when Network MIDI is switched on. Returns True if the
    profile already had the key or was upgraded."""
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
    try:
        if conn_file is None:
            # No profile yet: create one via the normal path (DHCP),
            # then re-enter to add the link-local key to it.
            if not configure_interface(iface, "auto"):
                return False
            return ensure_eth_link_local(iface)

        content = conn_file.read_text()
        if "link-local=enabled" in content:
            return True
        if "method=manual" in content:
            return True  # static config: the user chose addressing

        new_lines = []
        in_ipv4 = False
        for line in content.splitlines():
            if line.strip() == "[ipv4]":
                in_ipv4 = True
                new_lines.append(line)
                new_lines.append("link-local=enabled")
                continue
            if in_ipv4 and line.startswith("link-local"):
                continue
            if line.startswith("["):
                in_ipv4 = False
            new_lines.append(line)
        with _rw_rootfs():
            conn_file.write_text("\n".join(new_lines) + "\n")
        try:
            _run(["nmcli", "connection", "reload"], check=False, timeout=10)
            if conn_name:
                _run(["nmcli", "connection", "up", conn_name],
                     check=False, timeout=15)
        except subprocess.TimeoutExpired:
            log.warning("nmcli apply timed out after link-local upgrade")
        log.info("Enabled IPv4 link-local fallback on %s", iface)
        return True
    except Exception:
        # Old NM without ipv4.link-local support, or read-only hiccup —
        # the user can still set static IPs via the Network settings.
        log.exception("link-local upgrade for %s failed", iface)
        return False


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

    try:
        with _rw_rootfs():
            if conn_file is None:
                # Create a new .nmconnection file for this interface
                import uuid
                conn_name = f"{iface}"
                conn_file = NM_CONN_DIR / f"{conn_name}.nmconnection"
                conn_file.write_text(
                    f"[connection]\nid={conn_name}\nuuid={uuid.uuid4()}\ntype=ethernet\n"
                    f"interface-name={iface}\n\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=disabled\n"
                )
                conn_file.chmod(0o600)
                log.info("Created NM connection file for %s", iface)

            # Rewrite [ipv4] section
            lines = conn_file.read_text().splitlines()
            new_lines = []
            in_ipv4 = False
            for line in lines:
                if line.strip() == "[ipv4]":
                    in_ipv4 = True
                    new_lines.append(line)
                    if method == "manual" and address:
                        octets = [int(o) for o in netmask.split(".")]
                        prefix = sum(bin(o).count("1") for o in octets)
                        new_lines.append(f"address1={address}/{prefix}")
                        if gateway:
                            new_lines.append(f"gateway={gateway}")
                        new_lines.append("dns=8.8.8.8;8.8.4.4;")
                    new_lines.append(f"method={method}")
                    continue
                elif in_ipv4:
                    if line.startswith("["):
                        in_ipv4 = False
                        new_lines.append(line)
                    elif line.startswith(("address", "method", "dns", "gateway")):
                        continue
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            conn_file.write_text("\n".join(new_lines) + "\n")

        # Reload NM and apply — down+up needed to reapply gateway changes
        if conn_name:
            try:
                _run(["nmcli", "connection", "down", conn_name], check=False, timeout=10)
            except subprocess.TimeoutExpired:
                pass
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
