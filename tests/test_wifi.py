"""WiFi AP lifecycle tests.

Targets the failure modes that hit the user in the field after the
"idempotent AP" patch (d733c25) shipped:

  - "no hostapd, but service thinks AP is up" — false-positive
    idempotency check skipped a needed restart, leaving wlan0 in
    type=managed with no AP.
  - "two hostapds racing on wlan0" — restart spawned a new hostapd
    before the old one died, clients associated then immediately
    disassociated.

Tests run without any privileges: /proc, iw, subprocess and signals
are all faked.
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from raspimidihub import wifi
from raspimidihub.wifi import WifiManager

# ---------------------------------------------------------------------------
# /proc fixtures
# ---------------------------------------------------------------------------

def _make_proc(tmp_path: Path, processes: dict[int, list[str]]) -> Path:
    """Build a fake /proc tree: {pid: argv} → tmp_path/proc/<pid>/cmdline."""
    proc = tmp_path / "proc"
    proc.mkdir()
    for pid, argv in processes.items():
        d = proc / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    # A non-numeric directory should be silently ignored
    (proc / "self").mkdir()
    return proc


# ---------------------------------------------------------------------------
# Pure helpers — no subprocess
# ---------------------------------------------------------------------------

class TestRenderConfigs:
    def test_hostapd_conf_contains_ssid_password_channel(self):
        m = WifiManager()
        conf = m._render_hostapd_conf("MySSID", "secret123", 6)
        assert "ssid=MySSID" in conf
        assert "wpa_passphrase=secret123" in conf
        assert "channel=6" in conf
        assert "interface=wlan0" in conf
        assert "wpa=2" in conf

    def test_dnsmasq_conf_has_captive_portal(self):
        conf = WifiManager()._render_dnsmasq_conf()
        assert "interface=wlan0" in conf
        assert "address=/#/192.168.4.1" in conf  # DNS captive
        assert "no-resolv" in conf


class TestChannelFromConf:
    def test_extracts_channel(self):
        conf = "interface=wlan0\nchannel=11\nssid=foo\n"
        assert WifiManager._channel_from_conf(conf) == 11

    def test_returns_none_when_missing(self):
        assert WifiManager._channel_from_conf("ssid=foo\n") is None

    def test_returns_none_on_unparseable(self):
        assert WifiManager._channel_from_conf("channel=abc\n") is None


# ---------------------------------------------------------------------------
# _find_pids — the heart of the idempotency check
# ---------------------------------------------------------------------------

class TestFindPids:
    def test_matches_argv0_basename_and_required_arg(self, tmp_path):
        proc = _make_proc(tmp_path, {
            1234: ["/usr/sbin/hostapd", "-B", "/run/raspimidihub/hostapd.conf"],
        })
        pids = WifiManager._find_pids(
            "hostapd", "/run/raspimidihub/hostapd.conf", proc_root=proc)
        assert pids == [1234]

    def test_ignores_different_executable(self, tmp_path):
        # Bash with our keywords in argv (the actual real-world false positive)
        proc = _make_proc(tmp_path, {
            999: ["bash", "-c",
                  "pgrep -f hostapd.*raspimidihub; echo /run/raspimidihub/hostapd.conf"],
        })
        pids = WifiManager._find_pids(
            "hostapd", "/run/raspimidihub/hostapd.conf", proc_root=proc)
        assert pids == [], "shell wrapper must not be counted as hostapd"

    def test_ignores_hostapd_with_different_config(self, tmp_path):
        proc = _make_proc(tmp_path, {
            7000: ["hostapd", "-B", "/etc/hostapd/hostapd.conf"],  # distro one
        })
        pids = WifiManager._find_pids(
            "hostapd", "/run/raspimidihub/hostapd.conf", proc_root=proc)
        assert pids == [], "hostapd serving a different config must be ignored"

    def test_finds_multiple_pids(self, tmp_path):
        # The "two hostapds racing" failure mode this code is meant to catch
        proc = _make_proc(tmp_path, {
            100: ["hostapd", "-B", "/run/raspimidihub/hostapd.conf"],
            101: ["hostapd", "-B", "/run/raspimidihub/hostapd.conf"],
        })
        pids = WifiManager._find_pids(
            "hostapd", "/run/raspimidihub/hostapd.conf", proc_root=proc)
        assert sorted(pids) == [100, 101]

    def test_skips_non_numeric_proc_entries(self, tmp_path):
        # /proc/self, /proc/sys, /proc/cpuinfo — must not blow up
        proc = _make_proc(tmp_path, {})
        (proc / "sys").mkdir()
        (proc / "cpuinfo").write_text("processor : 0\n")
        pids = WifiManager._find_pids("hostapd", "x", proc_root=proc)
        assert pids == []

    def test_survives_disappearing_pid(self, tmp_path):
        # Process exits between scandir and read — we must not crash
        proc = _make_proc(tmp_path, {})
        (proc / "1234").mkdir()  # no cmdline file at all
        pids = WifiManager._find_pids("hostapd", "x", proc_root=proc)
        assert pids == []

    def test_skips_empty_cmdline(self, tmp_path):
        # Kernel threads have empty cmdline
        proc = _make_proc(tmp_path, {})
        (proc / "2").mkdir()
        (proc / "2" / "cmdline").write_bytes(b"")
        pids = WifiManager._find_pids("hostapd", "x", proc_root=proc)
        assert pids == []

    def test_required_arg_can_be_substring(self, tmp_path):
        # dnsmasq is invoked with --conf-file=PATH — the path is embedded in
        # one argv token, not its own. Must still match.
        proc = _make_proc(tmp_path, {
            500: ["dnsmasq",
                  "--conf-file=/run/raspimidihub/dnsmasq-ap.conf",
                  "--pid-file=/run/raspimidihub/dnsmasq.pid"],
        })
        pids = WifiManager._find_pids(
            "dnsmasq", "/run/raspimidihub/dnsmasq-ap.conf", proc_root=proc)
        assert pids == [500]

    def test_required_arg_must_appear_after_argv0(self, tmp_path):
        # The required_arg in argv0 alone (executable path) must not count —
        # otherwise self-matching becomes possible again.
        proc = _make_proc(tmp_path, {
            42: ["/run/raspimidihub/hostapd.conf"],  # weird, but argv0-only
        })
        pids = WifiManager._find_pids(
            "hostapd.conf", "/run/raspimidihub/hostapd.conf", proc_root=proc)
        assert pids == [], "required_arg must match an argv element after argv0"


# ---------------------------------------------------------------------------
# _wlan_mode — wraps `iw dev wlan0 info`
# ---------------------------------------------------------------------------

class TestWlanMode:
    def _fake_iw(self, stdout: str, returncode: int = 0):
        return SimpleNamespace(stdout=stdout, returncode=returncode)

    def test_parses_ap_mode(self, monkeypatch):
        out = (
            "Interface wlan0\n"
            "\tifindex 3\n"
            "\ttype AP\n"
            "\twiphy 0\n"
        )
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: self._fake_iw(out))
        assert WifiManager._wlan_mode() == "AP"

    def test_parses_managed_mode(self, monkeypatch):
        out = "Interface wlan0\n\ttype managed\n"
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: self._fake_iw(out))
        assert WifiManager._wlan_mode() == "managed"

    def test_returns_empty_on_iw_failure(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: self._fake_iw("", returncode=1))
        assert WifiManager._wlan_mode() == ""

    def test_returns_empty_when_iw_missing(self, monkeypatch):
        def boom(*a, **kw):
            raise FileNotFoundError("iw")
        monkeypatch.setattr(subprocess, "run", boom)
        assert WifiManager._wlan_mode() == ""

    def test_returns_empty_when_iw_times_out(self, monkeypatch):
        def boom(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="iw", timeout=2)
        monkeypatch.setattr(subprocess, "run", boom)
        assert WifiManager._wlan_mode() == ""


# ---------------------------------------------------------------------------
# _kill_and_wait — fixes the "two-hostapd race" failure mode
# ---------------------------------------------------------------------------

class TestKillAndWait:
    def test_no_pids_is_a_noop(self, monkeypatch):
        monkeypatch.setattr(WifiManager, "_find_pids",
                            staticmethod(lambda exe, arg, **kw: []))
        sent: list[tuple[int, int]] = []
        monkeypatch.setattr(os, "kill",
                            lambda pid, sig: sent.append((pid, sig)))
        WifiManager._kill_and_wait("hostapd", "x")
        assert sent == []

    def test_sigterm_then_die_before_sigkill(self, monkeypatch):
        # First call returns [pid], later calls (during the wait loop)
        # return [] — simulating SIGTERM working.
        calls = {"n": 0}

        def fake_find(*a, **kw):
            calls["n"] += 1
            return [777] if calls["n"] == 1 else []

        monkeypatch.setattr(WifiManager, "_find_pids",
                            staticmethod(fake_find))
        sent: list[tuple[int, int]] = []
        monkeypatch.setattr(os, "kill",
                            lambda pid, sig: sent.append((pid, sig)))
        # Fast loop
        monkeypatch.setattr(wifi.time, "sleep", lambda s: None)

        WifiManager._kill_and_wait("hostapd", "x", term_timeout=1.0)

        assert sent == [(777, signal.SIGTERM)], "must not escalate when SIGTERM works"

    def test_escalates_to_sigkill_when_sigterm_ignored(self, monkeypatch):
        # _find_pids always returns the same pid → SIGTERM ignored, must SIGKILL.
        # Then return [] after SIGKILL escalation finishes.
        state = {"escalated": False}

        def fake_find(*a, **kw):
            return [] if state["escalated"] else [888]

        monkeypatch.setattr(WifiManager, "_find_pids",
                            staticmethod(fake_find))

        sent: list[tuple[int, int]] = []

        def fake_kill(pid, sig):
            sent.append((pid, sig))
            if sig == signal.SIGKILL:
                state["escalated"] = True

        monkeypatch.setattr(os, "kill", fake_kill)
        # Fast loop — term_timeout=0 means escalate immediately
        monkeypatch.setattr(wifi.time, "monotonic",
                            iter([0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0]).__next__)
        monkeypatch.setattr(wifi.time, "sleep", lambda s: None)

        WifiManager._kill_and_wait("hostapd", "x", term_timeout=0.0)

        assert (888, signal.SIGTERM) in sent
        assert (888, signal.SIGKILL) in sent

    def test_tolerates_already_dead_pid(self, monkeypatch):
        # Process lookup error during kill — must not crash.
        monkeypatch.setattr(WifiManager, "_find_pids",
                            staticmethod(lambda *a, **kw: [123]
                                         if not getattr(WifiManager, "_dead", False)
                                         else []))

        def fake_kill(pid, sig):
            WifiManager._dead = True
            raise ProcessLookupError(pid)

        monkeypatch.setattr(os, "kill", fake_kill)
        monkeypatch.setattr(wifi.time, "sleep", lambda s: None)

        WifiManager._kill_and_wait("hostapd", "x", term_timeout=0.5)
        # No exception = pass
        del WifiManager._dead


# ---------------------------------------------------------------------------
# start_ap — the decision logic that the d733c25 patch got wrong
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_run(monkeypatch):
    """Capture every _run() invocation as a list of argv lists."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wifi, "_run", fake_run)
    return calls


@pytest.fixture
def stub_kill(monkeypatch):
    """Replace _kill_and_wait with a no-op recorder."""
    killed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        WifiManager, "_kill_and_wait",
        classmethod(lambda cls, exe, arg, **kw: killed.append((exe, arg))),
    )
    return killed


@pytest.fixture
def fake_fs(tmp_path, monkeypatch):
    """Redirect HOSTAPD_CONF / DNSMASQ_AP_CONF to tmp_path."""
    h = tmp_path / "hostapd.conf"
    d = tmp_path / "dnsmasq-ap.conf"
    monkeypatch.setattr(wifi, "HOSTAPD_CONF", h)
    monkeypatch.setattr(wifi, "DNSMASQ_AP_CONF", d)
    return SimpleNamespace(hostapd=h, dnsmasq=d)


def _stub_helpers(monkeypatch, hostapd_active: bool,
                  dnsmasq_pids: list[int], wlan_mode: str,
                  spawn_ok: bool = True,
                  stray_hostapd_pids: list[int] | None = None):
    """Pin _hostapd_active / _find_pids / _wlan_mode / _spawn_hostapd
    return values for start_ap tests.

    `hostapd_active` is the systemd-side state. `stray_hostapd_pids`
    simulates an old subprocess-managed hostapd lingering through a
    package upgrade — start_ap kills it before delegating to systemd.
    `dnsmasq_pids` is still per-pid because dnsmasq stays subprocess-
    managed for now."""
    stray = list(stray_hostapd_pids or [])

    def find(executable, required_arg, **kw):
        if executable == "hostapd":
            return list(stray)
        if executable == "dnsmasq":
            return list(dnsmasq_pids)
        return []

    monkeypatch.setattr(WifiManager, "_find_pids", staticmethod(find))
    monkeypatch.setattr(WifiManager, "_hostapd_active",
                        classmethod(lambda cls: hostapd_active))
    monkeypatch.setattr(WifiManager, "_wlan_mode",
                        staticmethod(lambda: wlan_mode))
    monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                        classmethod(lambda cls: spawn_ok))
    # Each call advances monotonic by 1 s — guarantees every wait loop
    # exits within a handful of iterations regardless of its deadline.
    clock = {"t": 0.0}

    def fake_monotonic():
        clock["t"] += 1.0
        return clock["t"]

    monkeypatch.setattr(wifi.time, "sleep", lambda s: None)
    monkeypatch.setattr(wifi.time, "monotonic", fake_monotonic)


class TestStartApSkipPath:
    """The fast path: configs match, daemons alive, wlan0 in AP — do nothing."""

    def test_skip_restart_when_everything_healthy(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        m = WifiManager()
        # Pre-seed the on-disk configs to exactly what the manager would render.
        fake_fs.hostapd.write_text(
            m._render_hostapd_conf("MyAP", "midihub1", 11))
        fake_fs.dnsmasq.write_text(m._render_dnsmasq_conf())

        _stub_helpers(monkeypatch, hostapd_active=True,
                      dnsmasq_pids=[101], wlan_mode="AP")

        m.start_ap(ssid="MyAP", password="midihub1")

        assert m.mode == "ap"
        assert stub_kill == [], "no kills expected on the skip path"
        # No hostapd / dnsmasq spawn either
        spawned = [c for c in stub_run if c and c[0] in ("hostapd", "dnsmasq")]
        assert spawned == []


class TestStartApRestartPath:
    """When something is wrong, restart only what's actually wrong."""

    def test_restarts_when_hostapd_inactive_even_if_config_matches(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        m = WifiManager()
        fake_fs.hostapd.write_text(
            m._render_hostapd_conf("MyAP", "midihub1", 11))
        fake_fs.dnsmasq.write_text(m._render_dnsmasq_conf())

        # Reproduces "systemctl says inactive / wlan0=managed" — the
        # user's exact failure mode after an external `pkill hostapd`.
        spawned = {"n": 0}
        _stub_helpers(monkeypatch, hostapd_active=False,
                      dnsmasq_pids=[101], wlan_mode="managed")
        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: spawned.update(n=spawned["n"] + 1) or True))

        m.start_ap(ssid="MyAP", password="midihub1")

        assert spawned["n"] == 1, "expected systemctl restart via _spawn_hostapd"

    def test_restarts_when_wlan_in_managed_even_if_unit_active(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        # Defends against: systemd unit reports active but wlan0 has
        # somehow reverted to managed (driver glitch, external nmcli, …).
        m = WifiManager()
        fake_fs.hostapd.write_text(
            m._render_hostapd_conf("MyAP", "midihub1", 11))
        fake_fs.dnsmasq.write_text(m._render_dnsmasq_conf())

        spawned = {"n": 0}
        _stub_helpers(monkeypatch, hostapd_active=True,
                      dnsmasq_pids=[101], wlan_mode="managed")
        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: spawned.update(n=spawned["n"] + 1) or True))

        m.start_ap(ssid="MyAP", password="midihub1")

        assert spawned["n"] == 1, \
            "wlan_mode != AP must trigger hostapd restart"

    def test_kills_stray_subprocess_hostapd_during_migration(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        # Upgrade-day scenario: the OLD raspimidihub package spawned
        # hostapd via subprocess.Popen. After `apt install` the new
        # raspimidihub starts up, sees the unit isn't active yet, and
        # finds the leftover hostapd PID — it must be killed before
        # systemctl spawns a fresh one, otherwise two would race.
        m = WifiManager()
        fake_fs.hostapd.write_text(
            m._render_hostapd_conf("MyAP", "midihub1", 11))
        fake_fs.dnsmasq.write_text(m._render_dnsmasq_conf())

        spawned = {"n": 0}
        _stub_helpers(monkeypatch, hostapd_active=False,
                      dnsmasq_pids=[200], wlan_mode="managed",
                      stray_hostapd_pids=[12345])
        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: spawned.update(n=spawned["n"] + 1) or True))

        m.start_ap(ssid="MyAP", password="midihub1")

        assert ("hostapd", str(fake_fs.hostapd)) in stub_kill, \
            "stray subprocess hostapd must be killed before systemctl restart"
        assert spawned["n"] == 1

    def test_restarts_when_config_changed(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        m = WifiManager()
        # On-disk config has a different SSID than the candidate
        fake_fs.hostapd.write_text(
            m._render_hostapd_conf("OldAP", "midihub1", 11))
        fake_fs.dnsmasq.write_text(m._render_dnsmasq_conf())

        spawned = {"n": 0}
        _stub_helpers(monkeypatch, hostapd_active=True,
                      dnsmasq_pids=[101], wlan_mode="AP")
        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: spawned.update(n=spawned["n"] + 1) or True))

        m.start_ap(ssid="NewAP", password="midihub1")

        # Hostapd must restart (via systemctl), dnsmasq must NOT.
        assert spawned["n"] == 1
        assert ("dnsmasq", str(fake_fs.dnsmasq)) not in stub_kill
        # New config written
        assert "ssid=NewAP" in fake_fs.hostapd.read_text()

    def test_restarts_dnsmasq_only_when_only_its_config_changed(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        # Hand-rolled — won't happen organically since _render_dnsmasq_conf
        # is deterministic, but the branch must exist for future edits.
        m = WifiManager()
        # Render the existing config the way start_ap now does (band +
        # resolved country) so it matches the candidate and hostapd is
        # left alone — otherwise the country_code line alone would force
        # a restart and defeat the point of the test.
        country = m._resolve_country("")
        fake_fs.hostapd.write_text(
            m._render_hostapd_conf("MyAP", "midihub1", 11, "2.4", country))
        fake_fs.dnsmasq.write_text("# stale dnsmasq conf\n")

        spawned = {"n": 0}
        _stub_helpers(monkeypatch, hostapd_active=True,
                      dnsmasq_pids=[101], wlan_mode="AP")
        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: spawned.update(n=spawned["n"] + 1) or True))

        m.start_ap(ssid="MyAP", password="midihub1")

        assert ("dnsmasq", str(fake_fs.dnsmasq)) in stub_kill
        assert spawned["n"] == 0, \
            "hostapd must stay untouched when only dnsmasq changed — " \
            "preserves the SSID and avoids blinking wlan0"

    def test_restarts_when_no_existing_config_yet(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        # First boot path — no config files on tmpfs yet, channel survey runs
        m = WifiManager()
        monkeypatch.setattr(m, "survey_ap_channel", lambda: 6)

        spawned = {"n": 0}
        _stub_helpers(monkeypatch, hostapd_active=False,
                      dnsmasq_pids=[], wlan_mode="managed")
        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: spawned.update(n=spawned["n"] + 1) or True))

        m.start_ap(ssid="MyAP", password="midihub1")

        assert "channel=6" in fake_fs.hostapd.read_text()
        assert spawned["n"] == 1
        assert ("dnsmasq", str(fake_fs.dnsmasq)) in stub_kill


class TestSpawnHostapd:
    """_spawn_hostapd now delegates to `systemctl restart
    raspimidihub-hostapd.service`. The wlan-mode poll is unchanged
    (and slightly wider to give systemd's Restart=on-failure cycle
    a chance), and we still have to surface systemctl errors so a
    stuck unit isn't a mystery."""

    def _stub_run(self, monkeypatch, returncode=0, stderr=""):
        seen: list[list[str]] = []

        def fake_run(cmd, **kw):
            seen.append(list(cmd))
            return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

        monkeypatch.setattr(subprocess, "run", fake_run)
        return seen

    def test_returns_true_when_wlan_enters_ap_mode(self, monkeypatch):
        seen = self._stub_run(monkeypatch)
        monkeypatch.setattr(WifiManager, "_wlan_mode",
                            staticmethod(lambda: "AP"))
        monkeypatch.setattr(wifi.time, "sleep", lambda s: None)
        monkeypatch.setattr(wifi.time, "monotonic", lambda: 0.0)
        assert WifiManager._spawn_hostapd() is True
        # Sanity: we delegated to systemctl, not subprocess.Popen of hostapd.
        assert seen and seen[0][:2] == ["systemctl", "restart"]
        assert "raspimidihub-hostapd.service" in seen[0]

    def test_returns_false_when_systemctl_fails(self, monkeypatch, caplog):
        self._stub_run(monkeypatch, returncode=1,
                       stderr="Failed to start raspimidihub-hostapd.service: Unit not found")
        with caplog.at_level("ERROR", logger="raspimidihub.wifi"):
            assert WifiManager._spawn_hostapd() is False
        # Stderr must surface so a missing unit isn't a silent dead AP.
        assert any("Unit not found" in r.message for r in caplog.records)

    def test_returns_false_when_wlan_never_enters_ap(self, monkeypatch, caplog):
        self._stub_run(monkeypatch)
        monkeypatch.setattr(WifiManager, "_wlan_mode",
                            staticmethod(lambda: "managed"))
        monkeypatch.setattr(wifi.time, "sleep", lambda s: None)
        # Increment monotonic so the loop terminates
        clock = {"t": 0.0}
        monkeypatch.setattr(wifi.time, "monotonic",
                            lambda: clock.update(t=clock["t"] + 1.0) or clock["t"])
        with caplog.at_level("ERROR", logger="raspimidihub.wifi"):
            assert WifiManager._spawn_hostapd() is False
        assert any("stayed in mode" in r.message for r in caplog.records)

    def test_returns_false_on_systemctl_timeout(self, monkeypatch, caplog):
        def boom(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="systemctl", timeout=10)
        monkeypatch.setattr(subprocess, "run", boom)
        with caplog.at_level("ERROR", logger="raspimidihub.wifi"):
            assert WifiManager._spawn_hostapd() is False


class TestHostapdActive:
    """`_hostapd_active` reads `systemctl is-active raspimidihub-hostapd`."""

    def test_active_returns_true(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: SimpleNamespace(
                                returncode=0, stdout="active\n", stderr=""))
        assert WifiManager._hostapd_active() is True

    def test_inactive_returns_false(self, monkeypatch):
        # is-active returns rc=3 + "inactive" stdout for a stopped unit
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: SimpleNamespace(
                                returncode=3, stdout="inactive\n", stderr=""))
        assert WifiManager._hostapd_active() is False

    def test_failed_returns_false(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: SimpleNamespace(
                                returncode=3, stdout="failed\n", stderr=""))
        assert WifiManager._hostapd_active() is False

    def test_systemctl_missing_returns_false(self, monkeypatch):
        def boom(*a, **kw):
            raise FileNotFoundError("systemctl")
        monkeypatch.setattr(subprocess, "run", boom)
        assert WifiManager._hostapd_active() is False

    def test_systemctl_timeout_returns_false(self, monkeypatch):
        def boom(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="systemctl", timeout=3)
        monkeypatch.setattr(subprocess, "run", boom)
        assert WifiManager._hostapd_active() is False


class TestStartApRetryPath:
    """At fresh boot, hostapd's first spawn can lose a race with NM /
    wpa_supplicant releasing wlan0. start_ap must retry once after
    bouncing the interface."""

    def test_retries_when_first_spawn_fails(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        m = WifiManager()
        # No existing config — fresh boot path
        monkeypatch.setattr(m, "survey_ap_channel", lambda: 11)
        _stub_helpers(monkeypatch, hostapd_active=False,
                      dnsmasq_pids=[], wlan_mode="managed")

        # First _spawn_hostapd → False, second → True
        attempts = {"n": 0}

        def fake_spawn(cls=None):  # classmethod
            attempts["n"] += 1
            return attempts["n"] >= 2

        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: fake_spawn()))

        m.start_ap(ssid="MyAP", password="midihub1")

        assert attempts["n"] == 2, "expected exactly one retry on first failure"
        # The retry must bounce wlan0 down before respawning
        assert any(c[:5] == ["ip", "link", "set", "wlan0", "down"]
                   for c in stub_run), "retry must bounce wlan0 down"

    def test_logs_error_when_retry_also_fails(
            self, monkeypatch, fake_fs, stub_run, stub_kill, caplog):
        m = WifiManager()
        monkeypatch.setattr(m, "survey_ap_channel", lambda: 11)
        _stub_helpers(monkeypatch, hostapd_active=False,
                      dnsmasq_pids=[], wlan_mode="managed")

        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: False))

        with caplog.at_level("ERROR", logger="raspimidihub.wifi"):
            m.start_ap(ssid="MyAP", password="midihub1")
        assert any("retry also failed" in r.message for r in caplog.records)

    def test_no_retry_when_first_spawn_succeeds(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        m = WifiManager()
        monkeypatch.setattr(m, "survey_ap_channel", lambda: 11)
        _stub_helpers(monkeypatch, hostapd_active=False,
                      dnsmasq_pids=[], wlan_mode="managed")

        attempts = {"n": 0}

        def fake_spawn(cls=None):
            attempts["n"] += 1
            return True

        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: fake_spawn()))

        m.start_ap(ssid="MyAP", password="midihub1")
        assert attempts["n"] == 1, "no retry when first spawn succeeds"


class TestStartClient:
    """Regression coverage for #wifi-stuck-after-update-check.

    A 5s cap on `nmcli connection reload` was raising TimeoutExpired in
    the field while the reload actually completed in the background.
    `check=False` does NOT suppress TimeoutExpired in subprocess.run,
    so the exception unwound through start_client and bypassed every
    fallback the orchestrator had.
    """

    def test_nmcli_reload_timeout_does_not_kill_start_client(
            self, monkeypatch, tmp_path):
        """The reload call is best-effort. If it times out, start_client
        must keep going and let `connection up` (which has its own
        timeout *and* a try/except below) decide success."""
        import contextlib

        m = WifiManager()
        monkeypatch.setattr(m, "stop_ap", lambda: None)
        monkeypatch.setattr(wifi, "NM_CONN_DIR", tmp_path)

        # Stub rw remount — it would otherwise shell out to `mount`.
        @contextlib.contextmanager
        def _noop():
            yield
        monkeypatch.setattr(wifi, "_rw_rootfs", _noop)

        calls: list[list[str]] = []

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            # Simulate NM being slow: the reload call hits its 15s cap
            # before nmcli returns. Pre-fix this propagated out of
            # start_client; post-fix it's caught and we move on.
            if cmd[:3] == ["nmcli", "connection", "reload"]:
                raise subprocess.TimeoutExpired(
                    cmd=" ".join(cmd), timeout=kw.get("timeout", 15))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(wifi, "_run", fake_run)

        ok = m.start_client("Home", "hunter2")

        # start_client got past the reload and ran `connection up`.
        assert any(c[:3] == ["nmcli", "connection", "up"] for c in calls), \
            "start_client must reach `connection up` even when reload times out"
        # `connection up` was stubbed to succeed → start_client returns True
        # and self._mode is "client".
        assert ok is True
        assert m.mode == "client"


class TestStartClientWithFallback:
    """The orchestrator promises: on any client-mode failure, the AP
    comes back. Pre-fix, an exception bubbling out of start_client
    (rather than a False return) bypassed the fallback. Pin the
    invariant in both directions."""

    def test_start_client_raising_still_triggers_ap_fallback(self, monkeypatch):
        """An uncaught exception inside start_client must NOT skip the
        fallback to AP. This is the exact path that stranded a real Pi."""
        import asyncio
        m = WifiManager()
        ap_calls: list[tuple[str, str]] = []

        def boom(ssid, password):
            raise RuntimeError("simulated nmcli timeout")

        monkeypatch.setattr(m, "start_client", boom)
        monkeypatch.setattr(m, "start_ap",
                            lambda ssid="", password="":
                            ap_calls.append((ssid, password)))

        asyncio.run(m.start_client_with_fallback(
            "Home", "hunter2", "RaspiMIDIHub-XXXX", "midihub1"))

        assert ap_calls == [("RaspiMIDIHub-XXXX", "midihub1")], \
            "start_client raising must route to the AP fallback"

    def test_start_client_returning_false_still_triggers_ap_fallback(
            self, monkeypatch):
        """Unchanged behaviour — the False-return path still runs the
        fallback. Kept as a guard against regressions in the new
        try/except wrapper."""
        import asyncio
        m = WifiManager()
        ap_calls: list[tuple[str, str]] = []

        monkeypatch.setattr(m, "start_client", lambda s, p: False)
        monkeypatch.setattr(m, "start_ap",
                            lambda ssid="", password="":
                            ap_calls.append((ssid, password)))

        asyncio.run(m.start_client_with_fallback(
            "Home", "wrong", "RaspiMIDIHub-XXXX", "midihub1"))

        assert ap_calls == [("RaspiMIDIHub-XXXX", "midihub1")]


class TestStopAp:
    def test_stops_systemd_unit_and_kills_strays(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        m = WifiManager()
        m.stop_ap()
        # Systemd-managed hostapd: stop the unit.
        assert any(c[:2] == ["systemctl", "stop"]
                   and "raspimidihub-hostapd.service" in c
                   for c in stub_run), \
            "stop_ap must systemctl stop the hostapd unit"
        # Belt-and-braces: still kill subprocess strays from a
        # pre-systemd-migration install.
        assert ("hostapd", str(fake_fs.hostapd)) in stub_kill
        assert ("dnsmasq", str(fake_fs.dnsmasq)) in stub_kill
        # And it flushed the IP
        assert any(c[:3] == ["ip", "addr", "flush"] for c in stub_run)


# ---------------------------------------------------------------------------
# Regression: the exact false-positive from the field
# ---------------------------------------------------------------------------

class TestRegressionFalsePositive:
    """Pre-fix, an SSH bash wrapper whose argv contained both 'hostapd' and
    'raspimidihub' was enough to make `pgrep -f hostapd.*raspimidihub`
    return success, even when no hostapd was actually running. The new
    /proc-based check must not be fooled by such a wrapper."""

    def test_bash_wrapper_with_keywords_does_not_count(self, tmp_path):
        proc = _make_proc(tmp_path, {
            5000: ["bash", "-c",
                   "pgrep -af hostapd.*raspimidihub; "
                   "ls /run/raspimidihub/hostapd.conf"],
            # No actual hostapd process
        })
        pids = WifiManager._find_pids(
            "hostapd", "/run/raspimidihub/hostapd.conf", proc_root=proc)
        assert pids == []

    def test_journalctl_tail_with_keywords_does_not_count(self, tmp_path):
        proc = _make_proc(tmp_path, {
            6000: ["journalctl", "-u", "raspimidihub",
                   "-g", "hostapd", "--follow"],
        })
        pids = WifiManager._find_pids(
            "hostapd", "/run/raspimidihub/hostapd.conf", proc_root=proc)
        assert pids == []


class TestInterfaceAddresses:
    """get_interface_info must surface *every* IPv4 address (a DHCP lease
    and a 169.254.x.x link-local fallback can coexist) and pick a routable
    one as the primary that prefills the static-IP form."""

    def _fake_run(self, addr_out):
        def run(cmd, *a, **k):
            if "addr" in cmd:
                return SimpleNamespace(stdout=addr_out, returncode=0)
            return SimpleNamespace(stdout="", returncode=0)
        return run

    def test_collects_all_skips_link_local_for_primary(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wifi, "NM_CONN_DIR", tmp_path)
        out = ("2: eth0: <BROADCAST,MULTICAST,UP> mtu 1500\n"
               "    inet 192.168.1.50/24 brd 192.168.1.255 scope global eth0\n"
               "    inet 169.254.5.5/16 brd 169.254.255.255 scope link eth0\n")
        monkeypatch.setattr(subprocess, "run", self._fake_run(out))
        info = wifi.get_interface_info("eth0")
        assert info["addresses"] == ["192.168.1.50/24", "169.254.5.5/16"]
        assert info["address"] == "192.168.1.50"
        assert info["netmask"] == "255.255.255.0"
        assert info["up"] is True

    def test_link_local_only_shown_but_not_prefilled(self, monkeypatch, tmp_path):
        # Cable unplugged: eth0 carries only the 169.254.x.x fallback. It
        # must still be *listed* (for display), but must NOT become the
        # primary/static prefill -- otherwise a Save writes the link-local
        # as the static IP and clobbers the real one.
        monkeypatch.setattr(wifi, "NM_CONN_DIR", tmp_path)
        out = "    inet 169.254.5.5/16 brd 169.254.255.255 scope link eth0\n"
        monkeypatch.setattr(subprocess, "run", self._fake_run(out))
        info = wifi.get_interface_info("eth0")
        assert info["addresses"] == ["169.254.5.5/16"]
        assert info["address"] == ""
        assert info["netmask"] == ""
        assert info["up"] is True

    def test_no_address(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wifi, "NM_CONN_DIR", tmp_path)
        monkeypatch.setattr(subprocess, "run", self._fake_run(""))
        info = wifi.get_interface_info("eth0")
        assert info["addresses"] == []
        assert info["address"] == ""
        assert info["up"] is False


class TestWithIpv4LinkLocal:
    """`_with_ipv4_link_local` injects the NM-native always-on link-local
    keys into an .nmconnection's [ipv4] section: link-local=3 always, plus
    dhcp-timeout=infinity for method=auto."""

    def test_auto_gets_link_local_and_infinite_timeout(self):
        out = wifi._with_ipv4_link_local(
            "[connection]\nid=eth0\ninterface-name=eth0\n\n"
            "[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=disabled\n")
        assert "link-local=3" in out
        assert "dhcp-timeout=2147483647" in out
        assert "method=auto" in out

    def test_manual_gets_link_local_no_timeout(self):
        out = wifi._with_ipv4_link_local(
            "[connection]\ninterface-name=eth0\n\n[ipv4]\nmethod=manual\n"
            "address1=10.1.1.9/24\ngateway=10.1.1.1\n")
        assert "link-local=3" in out
        assert "dhcp-timeout" not in out  # only for DHCP
        # static config preserved
        assert "address1=10.1.1.9/24" in out
        assert "gateway=10.1.1.1" in out

    def test_strips_stale_string_form(self):
        """Older builds wrote `link-local=enabled` (a string NM rejects)."""
        out = wifi._with_ipv4_link_local(
            "[connection]\ninterface-name=eth0\n\n[ipv4]\nmethod=auto\n"
            "link-local=enabled\n")
        assert "link-local=enabled" not in out
        assert "link-local=3" in out
        assert out.count("link-local=") == 1

    def test_idempotent(self):
        src = ("[connection]\ninterface-name=eth0\n\n[ipv4]\nmethod=auto\n\n"
               "[ipv6]\nmethod=disabled\n")
        once = wifi._with_ipv4_link_local(src)
        twice = wifi._with_ipv4_link_local(once)
        assert once == twice
        assert once.count("link-local=") == 1
        assert once.count("dhcp-timeout=") == 1

    def test_leaves_other_sections_untouched(self):
        out = wifi._with_ipv4_link_local(
            "[connection]\nid=eth0\ninterface-name=eth0\n\n"
            "[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=disabled\n")
        assert "[ipv6]\nmethod=disabled" in out
        assert "id=eth0" in out


class TestEnsureEth0NmLinkLocal:
    """`ensure_eth0_nm_link_local` makes NM keep an always-on link-local
    on eth0 — creating/updating the keyfile only when needed."""

    def _stub_run(self, monkeypatch):
        calls = []
        monkeypatch.setattr(wifi, "_run", lambda cmd, *a, **k: calls.append(cmd)
                            or SimpleNamespace(returncode=0, stdout="", stderr=""))
        return calls

    def test_updates_existing_profile(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wifi, "NM_CONN_DIR", tmp_path)
        calls = self._stub_run(monkeypatch)
        f = tmp_path / "eth0.nmconnection"
        f.write_text("[connection]\nid=eth0\ninterface-name=eth0\n\n"
                     "[ipv4]\nmethod=auto\n")
        assert wifi.ensure_eth0_nm_link_local("eth0") is True
        body = f.read_text()
        assert "link-local=3" in body
        assert "dhcp-timeout=2147483647" in body
        assert ["nmcli", "connection", "reload"] in calls

    def test_noop_when_already_correct(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wifi, "NM_CONN_DIR", tmp_path)
        calls = self._stub_run(monkeypatch)
        f = tmp_path / "eth0.nmconnection"
        # Pre-write the canonical form so nothing changes.
        f.write_text(wifi._with_ipv4_link_local(
            "[connection]\nid=eth0\ninterface-name=eth0\n\n[ipv4]\nmethod=auto\n"))
        before = f.read_text()
        assert wifi.ensure_eth0_nm_link_local("eth0") is True
        assert f.read_text() == before          # no rewrite
        assert calls == []                       # no NM prod, no remount

    def test_strips_stale_string_form(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wifi, "NM_CONN_DIR", tmp_path)
        self._stub_run(monkeypatch)
        f = tmp_path / "eth0.nmconnection"
        f.write_text("[connection]\ninterface-name=eth0\n\n"
                     "[ipv4]\nmethod=manual\naddress1=10.1.1.9/24\n"
                     "link-local=enabled\n")
        assert wifi.ensure_eth0_nm_link_local("eth0") is True
        body = f.read_text()
        assert "link-local=enabled" not in body
        assert "link-local=3" in body
        assert "address1=10.1.1.9/24" in body   # static preserved

    def test_creates_profile_when_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wifi, "NM_CONN_DIR", tmp_path)
        self._stub_run(monkeypatch)
        assert wifi.ensure_eth0_nm_link_local("eth0") is True
        f = tmp_path / "eth0.nmconnection"
        assert f.exists()
        body = f.read_text()
        assert "interface-name=eth0" in body
        assert "method=auto" in body
        assert "link-local=3" in body
        assert "dhcp-timeout=2147483647" in body


class TestConfigureInterfaceLinkLocal:
    """configure_interface writes the always-on link-local keys for both
    DHCP and static eth0 configs."""

    def _stub(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wifi, "NM_CONN_DIR", tmp_path)
        monkeypatch.setattr(wifi, "_run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="", stderr=""))

    def test_auto_writes_link_local_and_timeout(self, monkeypatch, tmp_path):
        self._stub(monkeypatch, tmp_path)
        assert wifi.configure_interface("eth0", "auto") is True
        body = (tmp_path / "eth0.nmconnection").read_text()
        assert "method=auto" in body
        assert "link-local=3" in body
        assert "dhcp-timeout=2147483647" in body

    def test_manual_writes_link_local_no_timeout(self, monkeypatch, tmp_path):
        self._stub(monkeypatch, tmp_path)
        assert wifi.configure_interface(
            "eth0", "manual", address="10.1.1.2", gateway="10.1.1.1") is True
        body = (tmp_path / "eth0.nmconnection").read_text()
        assert "method=manual" in body
        assert "address1=10.1.1.2/24" in body
        assert "link-local=3" in body
        assert "dhcp-timeout" not in body


class TestApBandCountry:
    """5 GHz AP band, regulatory country, capability gating, and the
    lockout-safe fallback to 2.4 GHz."""

    def test_render_5ghz_band_and_country(self):
        conf = WifiManager()._render_hostapd_conf(
            "AP", "midihub1", 36, band="5", country="DE")
        assert "hw_mode=a" in conf
        assert "channel=36" in conf
        assert "ieee80211n=1" in conf
        assert "wmm_enabled=1" in conf
        assert "country_code=DE" in conf
        assert "ieee80211d=1" in conf

    def test_render_24_default_has_no_country(self):
        conf = WifiManager()._render_hostapd_conf("AP", "midihub1", 6)
        assert "hw_mode=g" in conf
        assert "country_code" not in conf
        assert "ieee80211d" not in conf

    def test_resolve_country_explicit_wins(self):
        assert WifiManager._resolve_country("de") == "DE"
        assert WifiManager._resolve_country("AT") == "AT"

    def test_resolve_country_from_regdomain(self, monkeypatch):
        monkeypatch.setattr(wifi, "_run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="global\ncountry AT: DFS-ETSI\n", stderr=""))
        assert WifiManager._resolve_country("") == "AT"

    def test_resolve_country_fallback_de_when_world(self, monkeypatch):
        monkeypatch.setattr(wifi, "_run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="global\ncountry 00: DFS-UNSET\n", stderr=""))
        assert WifiManager._resolve_country("") == "DE"

    def test_radio_supports_5ghz_true(self, monkeypatch):
        monkeypatch.setattr(wifi, "_run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="\t* 2412 MHz [1]\n\t* 5180 MHz [36]\n", stderr=""))
        assert WifiManager.radio_supports_5ghz() is True

    def test_radio_supports_5ghz_false(self, monkeypatch):
        monkeypatch.setattr(wifi, "_run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="\t* 2412 MHz [1]\n\t* 2437 MHz [6]\n", stderr=""))
        assert WifiManager.radio_supports_5ghz() is False

    def test_5ghz_falls_back_to_24_when_bringup_fails(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        """Lockout guard: if a 5 GHz AP won't come up, the hub must
        rewrite the config as 2.4 GHz and spawn again so the AP — the
        only path to the UI — is never left down."""
        m = WifiManager()
        monkeypatch.setattr(m, "radio_supports_5ghz", lambda: True)
        monkeypatch.setattr(m, "survey_ap_channel_5ghz", lambda: 36)
        monkeypatch.setattr(m, "survey_ap_channel", lambda: 11)
        # hostapd never reports active -> the 5 GHz spawn is judged failed
        # and the fallback path runs.
        _stub_helpers(monkeypatch, hostapd_active=False,
                      dnsmasq_pids=[101], wlan_mode="managed")
        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: True))
        monkeypatch.setattr(WifiManager, "_claim_wlan0_for_ap",
                            classmethod(lambda cls: None))

        m.start_ap(ssid="AP", password="midihub1", band="5", country="DE")

        conf = fake_fs.hostapd.read_text()
        assert "hw_mode=g" in conf      # fell back to 2.4 GHz
        assert "channel=11" in conf
        assert "hw_mode=a" not in conf


