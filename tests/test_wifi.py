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


def _stub_helpers(monkeypatch, hostapd_pids: list[int],
                  dnsmasq_pids: list[int], wlan_mode: str,
                  spawn_ok: bool = True):
    """Pin _find_pids / _wlan_mode / _spawn_hostapd return values for
    start_ap tests."""
    def find(executable, required_arg, **kw):
        if executable == "hostapd":
            return list(hostapd_pids)
        if executable == "dnsmasq":
            return list(dnsmasq_pids)
        return []

    monkeypatch.setattr(WifiManager, "_find_pids", staticmethod(find))
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

        _stub_helpers(monkeypatch, hostapd_pids=[100],
                      dnsmasq_pids=[101], wlan_mode="AP")

        m.start_ap(ssid="MyAP", password="midihub1")

        assert m.mode == "ap"
        assert stub_kill == [], "no kills expected on the skip path"
        # No hostapd / dnsmasq spawn either
        spawned = [c for c in stub_run if c and c[0] in ("hostapd", "dnsmasq")]
        assert spawned == []


class TestStartApRestartPath:
    """When something is wrong, restart only what's actually wrong."""

    def test_restarts_when_hostapd_dead_even_if_config_matches(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        m = WifiManager()
        fake_fs.hostapd.write_text(
            m._render_hostapd_conf("MyAP", "midihub1", 11))
        fake_fs.dnsmasq.write_text(m._render_dnsmasq_conf())

        # Reproduces "no hostapd / wlan0=managed" — the user's exact failure
        spawned = {"n": 0}
        _stub_helpers(monkeypatch, hostapd_pids=[],
                      dnsmasq_pids=[101], wlan_mode="managed")
        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: spawned.update(n=spawned["n"] + 1) or True))

        m.start_ap(ssid="MyAP", password="midihub1")

        assert ("hostapd", str(fake_fs.hostapd)) in stub_kill
        assert spawned["n"] == 1, "expected fresh hostapd spawn via _spawn_hostapd"

    def test_restarts_when_wlan_in_managed_even_if_pid_present(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        # Defends against: stale hostapd PID still alive but interface
        # somehow reverted to managed (driver glitch, external nmcli, …).
        m = WifiManager()
        fake_fs.hostapd.write_text(
            m._render_hostapd_conf("MyAP", "midihub1", 11))
        fake_fs.dnsmasq.write_text(m._render_dnsmasq_conf())

        _stub_helpers(monkeypatch, hostapd_pids=[100],
                      dnsmasq_pids=[101], wlan_mode="managed")

        m.start_ap(ssid="MyAP", password="midihub1")

        assert ("hostapd", str(fake_fs.hostapd)) in stub_kill, \
            "wlan_mode != AP must trigger hostapd restart"

    def test_restarts_when_two_hostapd_pids(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        # The "two hostapds racing" failure mode: any pid count != 1 must
        # not be considered healthy.
        m = WifiManager()
        fake_fs.hostapd.write_text(
            m._render_hostapd_conf("MyAP", "midihub1", 11))
        fake_fs.dnsmasq.write_text(m._render_dnsmasq_conf())

        spawned = {"n": 0}
        _stub_helpers(monkeypatch, hostapd_pids=[100, 101],
                      dnsmasq_pids=[200], wlan_mode="AP")
        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: spawned.update(n=spawned["n"] + 1) or True))

        m.start_ap(ssid="MyAP", password="midihub1")

        assert ("hostapd", str(fake_fs.hostapd)) in stub_kill
        # Both old pids must be killed before respawn — _kill_and_wait
        # iterates over _find_pids which we stubbed to return both.
        assert spawned["n"] == 1

    def test_restarts_when_config_changed(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        m = WifiManager()
        # On-disk config has a different SSID than the candidate
        fake_fs.hostapd.write_text(
            m._render_hostapd_conf("OldAP", "midihub1", 11))
        fake_fs.dnsmasq.write_text(m._render_dnsmasq_conf())

        _stub_helpers(monkeypatch, hostapd_pids=[100],
                      dnsmasq_pids=[101], wlan_mode="AP")

        m.start_ap(ssid="NewAP", password="midihub1")

        # Hostapd must restart, dnsmasq must NOT (config didn't change there)
        assert ("hostapd", str(fake_fs.hostapd)) in stub_kill
        assert ("dnsmasq", str(fake_fs.dnsmasq)) not in stub_kill
        # New config written
        assert "ssid=NewAP" in fake_fs.hostapd.read_text()

    def test_restarts_dnsmasq_only_when_only_its_config_changed(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        # Hand-rolled — won't happen organically since _render_dnsmasq_conf
        # is deterministic, but the branch must exist for future edits.
        m = WifiManager()
        fake_fs.hostapd.write_text(
            m._render_hostapd_conf("MyAP", "midihub1", 11))
        fake_fs.dnsmasq.write_text("# stale dnsmasq conf\n")

        _stub_helpers(monkeypatch, hostapd_pids=[100],
                      dnsmasq_pids=[101], wlan_mode="AP")

        m.start_ap(ssid="MyAP", password="midihub1")

        assert ("dnsmasq", str(fake_fs.dnsmasq)) in stub_kill
        assert ("hostapd", str(fake_fs.hostapd)) not in stub_kill, \
            "hostapd must stay untouched when only dnsmasq changed — " \
            "preserves the SSID and avoids blinking wlan0"

    def test_restarts_when_no_existing_config_yet(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        # First boot path — no config files on tmpfs yet, channel survey runs
        m = WifiManager()
        monkeypatch.setattr(m, "survey_ap_channel", lambda: 6)

        _stub_helpers(monkeypatch, hostapd_pids=[],
                      dnsmasq_pids=[], wlan_mode="managed")

        m.start_ap(ssid="MyAP", password="midihub1")

        assert "channel=6" in fake_fs.hostapd.read_text()
        assert ("hostapd", str(fake_fs.hostapd)) in stub_kill
        assert ("dnsmasq", str(fake_fs.dnsmasq)) in stub_kill


class TestSpawnHostapd:
    """The fresh-boot fix: hostapd may silently fail to take wlan0 if NM
    is still releasing it. We need stderr surfaced and a wlan-mode check."""

    def _stub_run(self, monkeypatch, returncode=0, stderr=""):
        seen: list[list[str]] = []

        def fake_run(cmd, **kw):
            seen.append(list(cmd))
            return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

        monkeypatch.setattr(subprocess, "run", fake_run)
        return seen

    def test_returns_true_when_wlan_enters_ap_mode(self, monkeypatch):
        self._stub_run(monkeypatch)
        monkeypatch.setattr(WifiManager, "_wlan_mode",
                            staticmethod(lambda: "AP"))
        monkeypatch.setattr(wifi.time, "sleep", lambda s: None)
        monkeypatch.setattr(wifi.time, "monotonic", lambda: 0.0)
        assert WifiManager._spawn_hostapd() is True

    def test_returns_false_when_hostapd_exits_nonzero(self, monkeypatch, caplog):
        self._stub_run(monkeypatch, returncode=1,
                       stderr="Could not set interface to AP mode")
        with caplog.at_level("ERROR", logger="raspimidihub.wifi"):
            assert WifiManager._spawn_hostapd() is False
        # The stderr must surface in the log — that's the whole point
        assert any("Could not set interface to AP mode" in r.message
                   for r in caplog.records)

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

    def test_returns_false_on_spawn_timeout(self, monkeypatch, caplog):
        def boom(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="hostapd", timeout=10)
        monkeypatch.setattr(subprocess, "run", boom)
        with caplog.at_level("ERROR", logger="raspimidihub.wifi"):
            assert WifiManager._spawn_hostapd() is False


class TestStartApRetryPath:
    """At fresh boot, hostapd's first spawn can lose a race with NM /
    wpa_supplicant releasing wlan0. start_ap must retry once after
    bouncing the interface."""

    def test_retries_when_first_spawn_fails(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        m = WifiManager()
        # No existing config — fresh boot path
        monkeypatch.setattr(m, "survey_ap_channel", lambda: 11)
        _stub_helpers(monkeypatch, hostapd_pids=[],
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
        _stub_helpers(monkeypatch, hostapd_pids=[],
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
        _stub_helpers(monkeypatch, hostapd_pids=[],
                      dnsmasq_pids=[], wlan_mode="managed")

        attempts = {"n": 0}

        def fake_spawn(cls=None):
            attempts["n"] += 1
            return True

        monkeypatch.setattr(WifiManager, "_spawn_hostapd",
                            classmethod(lambda cls: fake_spawn()))

        m.start_ap(ssid="MyAP", password="midihub1")
        assert attempts["n"] == 1, "no retry when first spawn succeeds"


class TestStopAp:
    def test_calls_kill_and_wait_for_both_daemons(
            self, monkeypatch, fake_fs, stub_run, stub_kill):
        m = WifiManager()
        m.stop_ap()
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
