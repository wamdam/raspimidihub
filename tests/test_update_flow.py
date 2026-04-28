"""Tests for the Phase 5.5 update orchestrator.

The orchestrator switches the Pi between AP and client mode to fetch
new releases. We can't test that switch without real hardware, so the
unit tests here cover the deterministic pieces:

  - version sorting (handles pre-release tags correctly)
  - GitHub release list parsing (skips drafts, deals with missing assets)
  - storage layout (list_stored_versions, prune_stored)
  - status file round-trip
  - the orchestrator's branching (path picks, error messages) using a
    fake WiFi manager + fake config
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from raspimidihub import update_flow as uf

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestParseVersion:
    def test_orders_by_major_minor_patch(self):
        assert uf.parse_version("1.0.0") < uf.parse_version("1.0.1")
        assert uf.parse_version("1.0.10") > uf.parse_version("1.0.9")
        assert uf.parse_version("2.0.0") > uf.parse_version("1.99.99")

    def test_strips_v_prefix(self):
        assert uf.parse_version("v2.0.5") == uf.parse_version("2.0.5")

    def test_pre_release_sorts_below_release(self):
        # 2.0.0-alpha1 should be older than 2.0.0
        assert uf.parse_version("2.0.0-alpha1") < uf.parse_version("2.0.0")
        # And older than its successor too.
        assert uf.parse_version("2.0.0-alpha1") < uf.parse_version("2.0.1")

    def test_short_versions_pad_to_three(self):
        # '2' should equal '2.0.0' — patch versions default to 0.
        assert uf.parse_version("2") == uf.parse_version("2.0.0")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _seed_storage(tmp_path: Path, versions: list[str]) -> Path:
    """Create the storage dir with one fake deb (and changelog) per
    version. mtime is monotonic-by-call-order so newer-than ordering
    matches list order."""
    storage = tmp_path / "updates"
    storage.mkdir()
    import time as _t
    for i, v in enumerate(versions):
        deb = storage / f"raspimidihub_{v}-1_all.deb"
        deb.write_bytes(b"\0" * 16)
        cl = storage / f"raspimidihub_{v}-1_all.changelog.md"
        cl.write_text(f"# {v}\n\nNotes for {v}.")
        # Stagger mtimes so test results don't depend on filesystem
        # tie-break behaviour.
        ts = _t.time() - (len(versions) - i)
        import os as _os
        _os.utime(deb, (ts, ts))
        _os.utime(cl, (ts, ts))
    return storage


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Redirect UPDATES_DIR to a temp dir for the test."""
    d = tmp_path / "updates"
    monkeypatch.setattr(uf, "UPDATES_DIR", d)
    return d


class TestListStoredVersions:
    def test_empty_dir_returns_empty(self, storage):
        assert uf.list_stored_versions() == []

    def test_creates_dir_on_first_call(self, storage):
        assert not storage.exists()
        uf.list_stored_versions()
        assert storage.exists()

    def test_returns_newest_first(self, tmp_path, monkeypatch):
        d = _seed_storage(tmp_path, ["1.0.0", "2.0.0", "1.5.0"])
        monkeypatch.setattr(uf, "UPDATES_DIR", d)
        result = uf.list_stored_versions()
        assert [r["version"] for r in result] == ["2.0.0", "1.5.0", "1.0.0"]

    def test_includes_changelog_text(self, tmp_path, monkeypatch):
        d = _seed_storage(tmp_path, ["1.0.0"])
        monkeypatch.setattr(uf, "UPDATES_DIR", d)
        [entry] = uf.list_stored_versions()
        assert "Notes for 1.0.0" in entry["changelog"]

    def test_skips_non_matching_filenames(self, tmp_path, monkeypatch):
        d = tmp_path / "updates"
        d.mkdir()
        (d / "raspimidihub_1.0.0-1_all.deb").write_bytes(b"x")
        (d / "stray.deb").write_bytes(b"x")
        (d / "README.md").write_text("hi")
        monkeypatch.setattr(uf, "UPDATES_DIR", d)
        result = uf.list_stored_versions()
        assert [r["version"] for r in result] == ["1.0.0"]

    def test_changelog_optional(self, tmp_path, monkeypatch):
        d = tmp_path / "updates"
        d.mkdir()
        (d / "raspimidihub_1.0.0-1_all.deb").write_bytes(b"x")
        monkeypatch.setattr(uf, "UPDATES_DIR", d)
        [entry] = uf.list_stored_versions()
        assert entry["changelog"] == ""


class TestPruneStored:
    def test_keeps_n_newest(self, tmp_path, monkeypatch):
        d = _seed_storage(tmp_path, ["1.0.0", "2.0.0", "3.0.0", "4.0.0"])
        monkeypatch.setattr(uf, "UPDATES_DIR", d)
        removed = uf.prune_stored(keep=2)
        assert sorted(removed) == [
            "raspimidihub_1.0.0-1_all.deb",
            "raspimidihub_2.0.0-1_all.deb",
        ]
        remaining = [v["version"] for v in uf.list_stored_versions()]
        assert remaining == ["4.0.0", "3.0.0"]

    def test_no_op_when_under_threshold(self, tmp_path, monkeypatch):
        d = _seed_storage(tmp_path, ["1.0.0", "2.0.0"])
        monkeypatch.setattr(uf, "UPDATES_DIR", d)
        assert uf.prune_stored(keep=3) == []

    def test_also_deletes_changelog(self, tmp_path, monkeypatch):
        d = _seed_storage(tmp_path, ["1.0.0", "2.0.0"])
        monkeypatch.setattr(uf, "UPDATES_DIR", d)
        uf.prune_stored(keep=1)
        assert not (d / "raspimidihub_1.0.0-1_all.changelog.md").exists()


# ---------------------------------------------------------------------------
# Status file
# ---------------------------------------------------------------------------

class TestStatusFile:
    def test_round_trip(self, tmp_path, monkeypatch):
        f = tmp_path / "update-status"
        monkeypatch.setattr(uf, "STATUS_FILE", f)
        uf.write_status({"step": "downloading", "version": "2.0.0"})
        assert uf.read_status() == {"step": "downloading", "version": "2.0.0"}

    def test_read_returns_idle_when_missing(self, tmp_path, monkeypatch):
        f = tmp_path / "update-status"
        monkeypatch.setattr(uf, "STATUS_FILE", f)
        assert uf.read_status() == {"step": "idle"}

    def test_read_returns_idle_when_corrupt(self, tmp_path, monkeypatch):
        f = tmp_path / "update-status"
        f.write_text("{not json")
        monkeypatch.setattr(uf, "STATUS_FILE", f)
        assert uf.read_status() == {"step": "idle"}

    def test_write_is_atomic(self, tmp_path, monkeypatch):
        # The atomic-rename pattern means a partially-written file
        # never appears at STATUS_FILE — only the .tmp does.
        f = tmp_path / "update-status"
        monkeypatch.setattr(uf, "STATUS_FILE", f)
        uf.write_status({"step": "x"})
        assert json.loads(f.read_text())["step"] == "x"
        # No leftover .tmp after a successful write.
        assert not f.with_suffix(".tmp").exists()


# ---------------------------------------------------------------------------
# Orchestrator branching
# ---------------------------------------------------------------------------

class _FakeWifi:
    """Minimal stand-in for WifiManager — lets us test the orchestrator's
    routing without touching real hostapd/wpa_supplicant."""

    def __init__(self, *, can_join: bool = True) -> None:
        self.mode = "ap"
        self.can_join = can_join
        self.ap_calls: list[tuple[str, str]] = []
        self.client_calls: list[tuple[str, str]] = []

    async def start_client_with_fallback(self, ssid, password, ap_ssid, ap_password):
        self.client_calls.append((ssid, password))
        if self.can_join:
            self.mode = "client"
        else:
            # Simulate the fallback branch: WifiManager itself flips
            # back to AP before returning when join fails.
            self.mode = "ap"

    def start_ap(self, ssid="", password=""):
        self.ap_calls.append((ssid, password))
        self.mode = "ap"


def _make_config(**wifi_overrides) -> SimpleNamespace:
    base = {
        "mode": "ap",
        "ap_ssid": "Test-AP",
        "ap_password": "midihub1",
        "client_ssid": "",
        "client_password": "",
        "wifi_mode_pref": "ap_only",
    }
    base.update(wifi_overrides)
    return SimpleNamespace(wifi=base)


def _redirect_status(monkeypatch, tmp_path):
    monkeypatch.setattr(uf, "STATUS_FILE", tmp_path / "update-status")


class TestUpdateFetcher:
    def test_uses_current_network_when_reachable(self, monkeypatch, tmp_path):
        _redirect_status(monkeypatch, tmp_path)
        monkeypatch.setattr(uf, "probe_internet", lambda timeout=4.0: True)
        wifi_mgr = _FakeWifi()
        cfg = _make_config()
        fetcher = uf.UpdateFetcher(wifi_mgr, cfg)

        called = []

        async def work():
            called.append(True)
            return "result"

        result = asyncio.run(fetcher.run(work))
        assert result == "result"
        assert called == [True]
        # No WiFi switches, no AP restoration.
        assert wifi_mgr.client_calls == []
        assert wifi_mgr.ap_calls == []

    def test_no_internet_ap_only_aborts(self, monkeypatch, tmp_path):
        _redirect_status(monkeypatch, tmp_path)
        monkeypatch.setattr(uf, "probe_internet", lambda timeout=4.0: False)
        wifi_mgr = _FakeWifi()
        cfg = _make_config(wifi_mode_pref="ap_only")
        fetcher = uf.UpdateFetcher(wifi_mgr, cfg)

        async def work():
            raise AssertionError("work shouldn't run")

        with pytest.raises(uf.NoInternetError) as exc:
            asyncio.run(fetcher.run(work))
        assert "ethernet" in exc.value.message.lower() \
            or "wifi for updates" in exc.value.message.lower()
        # Status file recorded the error so the UI can read it.
        status = uf.read_status()
        assert status["step"].startswith("error")

    def test_no_internet_no_creds_aborts(self, monkeypatch, tmp_path):
        _redirect_status(monkeypatch, tmp_path)
        monkeypatch.setattr(uf, "probe_internet", lambda timeout=4.0: False)
        wifi_mgr = _FakeWifi()
        # User selected wifi_for_updates but never saved credentials.
        cfg = _make_config(wifi_mode_pref="wifi_for_updates", client_ssid="")
        fetcher = uf.UpdateFetcher(wifi_mgr, cfg)

        async def work():
            raise AssertionError("work shouldn't run")

        with pytest.raises(uf.NoInternetError) as exc:
            asyncio.run(fetcher.run(work))
        assert "credentials" in exc.value.message.lower()

    def test_transient_wifi_path_succeeds(self, monkeypatch, tmp_path):
        _redirect_status(monkeypatch, tmp_path)
        # Probe sequence: first call (current net) fails; second call
        # (after switching to client) succeeds. Use a stateful counter
        # so both probes go through this single fixture.
        calls = {"n": 0}

        def probe(timeout=4.0):
            calls["n"] += 1
            return calls["n"] >= 2

        monkeypatch.setattr(uf, "probe_internet", probe)
        # Watchdog calls would shell out to systemd-run / systemctl.
        monkeypatch.setattr(uf, "schedule_watchdog", lambda reason: True)
        monkeypatch.setattr(uf, "cancel_watchdog", lambda: None)

        wifi_mgr = _FakeWifi(can_join=True)
        cfg = _make_config(
            wifi_mode_pref="wifi_for_updates",
            client_ssid="Home", client_password="hunter2",
        )
        fetcher = uf.UpdateFetcher(wifi_mgr, cfg)

        log = []

        async def work():
            log.append(("work", wifi_mgr.mode))
            return "ok"

        result = asyncio.run(fetcher.run(work))
        assert result == "ok"
        # Joined the user's network for the work, then back to AP.
        assert wifi_mgr.client_calls == [("Home", "hunter2")]
        assert wifi_mgr.ap_calls == [("Test-AP", "midihub1")]
        assert log == [("work", "client")]
        # Orchestrator's terminal 'done' (written after switching back)
        # is what the UI matches on to clear its spinner. If we left it
        # at 'switching-to-ap' instead, the UI never knew it could stop
        # polling.
        status = uf.read_status()
        assert status["step"] == "done"

    def test_transient_wifi_path_join_failure_restores_ap(
            self, monkeypatch, tmp_path):
        _redirect_status(monkeypatch, tmp_path)
        monkeypatch.setattr(uf, "probe_internet", lambda timeout=4.0: False)
        monkeypatch.setattr(uf, "schedule_watchdog", lambda reason: True)
        monkeypatch.setattr(uf, "cancel_watchdog", lambda: None)

        wifi_mgr = _FakeWifi(can_join=False)  # Wrong password / out of range
        cfg = _make_config(
            wifi_mode_pref="wifi_for_updates",
            client_ssid="Home", client_password="wrong",
        )
        fetcher = uf.UpdateFetcher(wifi_mgr, cfg)

        async def work():
            raise AssertionError("shouldn't run when join fails")

        with pytest.raises(uf.NoInternetError) as exc:
            asyncio.run(fetcher.run(work))
        assert "Home" in exc.value.message
        # Tried to join, fallback already restored AP via WifiManager
        # itself — orchestrator just sees mode != "client".
        assert wifi_mgr.client_calls == [("Home", "wrong")]
