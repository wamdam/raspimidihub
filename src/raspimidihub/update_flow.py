"""Update fetch orchestrator for Phase 5.5.

The Pi runs in AP mode by default so phones/laptops can reach it
without infrastructure. To fetch new releases from GitHub it has
to talk to the public internet, which the AP can't do. This module
handles "go online for as little time as possible, then come back".

Two paths, decided per call by `probe_internet`:

  a) The current network already has internet (e.g. ethernet plugged
     in, or someone selected "WiFi always"). Just use it.

  b) The current network has no internet. If the user opted into
     "WiFi for updates" AND saved credentials, briefly switch to
     client mode, do the work, switch back to AP. Otherwise surface
     an actionable error.

Independent of the orchestrator path, a `systemd-run --on-active=180s`
watchdog is scheduled before any WiFi switch. If the orchestrator
hangs in client mode the watchdog forces a service restart, which
brings the AP back unconditionally — so the user never loses access
to their phone-reachable Pi due to a buggy update step.

State is exposed via `/run/raspimidihub/update-status` (JSON). The
UI polls it. Each step writes a breadcrumb so progress AND post-
mortem are precise: "joining-wifi" / "downloading" / "error-no-creds"
beat a generic spinner.

Storage: `/var/lib/raspimidihub/updates/` keeps deb + sibling
`.changelog.md` files. Newest 3 retained; older pruned per call.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import subprocess
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

UPDATES_DIR = Path("/var/lib/raspimidihub/updates")
STATUS_FILE = Path("/run/raspimidihub/update-status")
INTERNET_PROBE_URL = "https://api.github.com/zen"  # tiny, no rate-limit
INTERNET_PROBE_TIMEOUT_SEC = 4.0
DOWNLOAD_TIMEOUT_SEC = 90.0
KEEP_VERSIONS = 3
WATCHDOG_SECONDS = 180


# --- Status file ----------------------------------------------------------

def write_status(payload: dict[str, Any]) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    tmp.replace(STATUS_FILE)


def read_status() -> dict[str, Any]:
    if not STATUS_FILE.is_file():
        return {"step": "idle"}
    try:
        return json.loads(STATUS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"step": "idle"}


# --- Internet reachability ------------------------------------------------

def probe_internet(timeout: float = INTERNET_PROBE_TIMEOUT_SEC) -> bool:
    """Sync probe of GitHub's `/zen` endpoint. Returns True if reachable
    (any 2xx/3xx). Called from an executor by async callers."""
    try:
        req = urllib.request.Request(
            INTERNET_PROBE_URL,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "raspimidihub"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception as e:
        log.info("Internet probe failed: %s", e)
        return False


# --- GitHub release list --------------------------------------------------

GITHUB_RELEASES_URL = (
    "https://api.github.com/repos/wamdam/raspimidihub/releases?per_page=20"
)
GITHUB_RELEASES_TIMEOUT_SEC = 10.0


def parse_version(s: str) -> tuple:
    """Sortable tuple from a version string. '2.0.10' < '2.0.11' < '3.0.0';
    pre-release tags ('2.0.0-alpha1') sort below the same plain version
    (so a '-alpha1' tag is correctly older than its release counterpart)."""
    s = s.lstrip("v")
    parts = s.replace("-", ".").split(".")
    nums: list[int] = []
    pre = ""
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            pre = p
            break
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums) + (pre or "~",)  # '~' sorts after alpha/beta


def fetch_github_releases() -> list[dict[str, Any]]:
    """Synchronous GET against the GitHub releases endpoint, parsed into
    release entries our UI can render. Caller is responsible for being
    online — the orchestrator's `run()` only invokes work callables once
    that's been verified.

    Returns one dict per release with: version, changelog, deb_url,
    prerelease. Releases without a `raspimidihub_*_all.deb` asset are
    skipped (drafts, accidentally-tagged commits)."""
    rq = urllib.request.Request(
        GITHUB_RELEASES_URL,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "raspimidihub"},
    )
    with urllib.request.urlopen(rq, timeout=GITHUB_RELEASES_TIMEOUT_SEC) as resp:
        releases = json.loads(resp.read())

    out: list[dict[str, Any]] = []
    for rel in releases:
        if rel.get("draft"):
            continue
        tag = rel.get("tag_name", "")
        ver_str = tag.lstrip("v")
        deb_url = ""
        for asset in rel.get("assets", []):
            name = asset.get("name", "")
            if name.startswith("raspimidihub_") and name.endswith("_all.deb"):
                deb_url = asset.get("browser_download_url", "")
                break
        if not deb_url:
            continue
        out.append({
            "version": ver_str,
            "changelog": rel.get("body", ""),
            "deb_url": deb_url,
            "prerelease": rel.get("prerelease", False),
        })
    out.sort(key=lambda e: parse_version(e["version"]), reverse=True)
    return out


# --- Storage --------------------------------------------------------------

@contextlib.contextmanager
def _rw_rootfs():
    """Remount / read-write for the duration of the with-block, then
    back to ro. Required because UPDATES_DIR lives on the rosetup'd
    rootfs which is mounted ro under normal operation."""
    subprocess.run(["mount", "-o", "remount,rw", "/"],
                   check=False, capture_output=True, timeout=5)
    try:
        yield
    finally:
        subprocess.run(["mount", "-o", "remount,ro", "/"],
                       check=False, capture_output=True, timeout=5)


_DEB_NAME_RE = re.compile(
    r"^raspimidihub_(?P<ver>[0-9]+\.[0-9]+\.[0-9]+)-(?P<rev>\d+)_all\.deb$"
)


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split(".") if p.isdigit())


def list_stored_versions() -> list[dict[str, Any]]:
    """One entry per stored deb, newest first. Each entry has version,
    deb_name, deb_path, size_bytes, downloaded_at (epoch), changelog
    (sibling .changelog.md contents, '' if absent)."""
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    for deb in UPDATES_DIR.glob("*.deb"):
        m = _DEB_NAME_RE.match(deb.name)
        if not m:
            continue
        version = m.group("ver")
        changelog_path = deb.with_suffix(".changelog.md")
        try:
            stat = deb.stat()
        except OSError:
            continue
        out.append({
            "version": version,
            "deb_name": deb.name,
            "deb_path": str(deb),
            "size_bytes": stat.st_size,
            "downloaded_at": int(stat.st_mtime),
            "changelog": (
                changelog_path.read_text(errors="replace")
                if changelog_path.is_file() else ""
            ),
        })
    out.sort(key=lambda e: _version_tuple(e["version"]), reverse=True)
    return out


def prune_stored(keep: int = KEEP_VERSIONS) -> list[str]:
    """Delete all but the N newest stored debs (and their changelogs).
    Returns the removed deb names. Wrapped in rw remount because
    UPDATES_DIR is on the read-only rootfs."""
    versions = list_stored_versions()
    if len(versions) <= keep:
        return []
    removed: list[str] = []
    with _rw_rootfs():
        for entry in versions[keep:]:
            deb = Path(entry["deb_path"])
            cl = deb.with_suffix(".changelog.md")
            for p in (deb, cl):
                try:
                    p.unlink()
                except OSError:
                    pass
            removed.append(entry["deb_name"])
    return removed


# --- Watchdog -------------------------------------------------------------

def schedule_watchdog(reason: str) -> bool:
    """Run a transient systemd-run unit that fires in WATCHDOG_SECONDS,
    forcing the Pi back to AP. Cancelled via cancel_watchdog() once the
    orchestrator returns to AP cleanly. Survives even if our service
    crashes mid-flow, which is the whole point."""
    cmd = [
        "systemd-run",
        "--unit=raspimidihub-update-watchdog",
        f"--on-active={WATCHDOG_SECONDS}s",
        "--description", f"raspimidihub update watchdog: {reason}",
        "/usr/local/bin/raspimidihub-update-watchdog",
        reason,
    ]
    try:
        # Replace any leftover watchdog so we always start a fresh deadline.
        subprocess.run(["systemctl", "stop", "raspimidihub-update-watchdog.timer"],
                       check=False, capture_output=True)
        subprocess.run(["systemctl", "stop", "raspimidihub-update-watchdog.service"],
                       check=False, capture_output=True)
        r = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if r.returncode != 0:
            log.warning("watchdog schedule failed: %s", r.stderr.strip())
            return False
        log.info("watchdog scheduled for %ds (reason: %s)", WATCHDOG_SECONDS, reason)
        return True
    except OSError as e:
        log.warning("watchdog schedule errored: %s", e)
        return False


def cancel_watchdog() -> None:
    for name in ("raspimidihub-update-watchdog.timer",
                 "raspimidihub-update-watchdog.service"):
        try:
            subprocess.run(["systemctl", "stop", name],
                           check=False, capture_output=True)
        except OSError:
            pass


# --- Download primitive ---------------------------------------------------

def download_release(deb_url: str, dest: Path,
                      changelog_text: str = "") -> tuple[bool, str]:
    """Synchronous deb download to `dest`. Writes `<dest_stem>.changelog.md`
    alongside if changelog_text is given. Wraps the writes in an rw
    rootfs remount because UPDATES_DIR lives on the read-only root.
    Returns (ok, error_message)."""
    tmp = dest.with_suffix(".part")
    try:
        req = urllib.request.Request(
            deb_url, headers={"User-Agent": "raspimidihub"},
        )
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SEC) as resp:
            if resp.status >= 400:
                return False, f"HTTP {resp.status}"
            # Hold rw open only for the actual disk writes — the network
            # read happens regardless of fs mode.
            with _rw_rootfs():
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tmp.open("wb") as f:
                    while True:
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                tmp.replace(dest)
                if changelog_text:
                    try:
                        dest.with_suffix(".changelog.md").write_text(changelog_text)
                    except OSError as e:
                        log.warning("failed to write changelog alongside %s: %s",
                                    dest, e)
    except Exception as e:
        try:
            with _rw_rootfs():
                tmp.unlink()
        except OSError:
            pass
        return False, str(e)
    return True, ""


# --- Orchestrator ---------------------------------------------------------

class NoInternetError(Exception):
    """Raised when neither the current network nor a fallback can reach
    the internet. Carries a user-facing message the API surfaces verbatim."""
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UpdateFetcher:
    """Wraps a callable in 'be online for it' logic.

    Three shapes:
      a) current-net works → run callable → done.
      b) current-net broken, mode == ap_only → NoInternetError.
      c) current-net broken, no creds → NoInternetError.
      d) current-net broken, mode == wifi_for_updates, creds present →
         switch to client → run callable → switch back to AP.

    The callable is async, takes no args, and may itself write status
    breadcrumbs via write_status (e.g. for per-deb download progress)."""

    def __init__(self, wifi_manager, config) -> None:
        self.wifi = wifi_manager
        self.config = config

    async def run(self, work: Callable[[], Awaitable[Any]],
                  *, version_label: str = "") -> Any:
        """Execute `work` while ensuring internet access. Returns whatever
        `work` returns. Raises NoInternetError if no path to GitHub."""
        loop = asyncio.get_event_loop()
        write_status({"step": "probing", "version": version_label})

        if await loop.run_in_executor(None, probe_internet):
            return await self._run_work(work, switched=False,
                                         version_label=version_label)

        wifi_pref = self.config.wifi.get("wifi_mode_pref", "ap_only")
        saved_ssid = self.config.wifi.get("client_ssid", "")
        saved_password = self.config.wifi.get("client_password", "")

        if wifi_pref != "wifi_for_updates" or not saved_ssid:
            msg = self._explain_no_internet(wifi_pref, saved_ssid)
            self._abort("error-no-internet", msg)
            raise NoInternetError(msg)

        schedule_watchdog("transient-update")
        try:
            return await self._transient_wifi_path(
                work, saved_ssid, saved_password, version_label)
        finally:
            cancel_watchdog()

    async def _run_work(self, work, *, switched: bool, version_label: str):
        """Run the user's callable, handle the AP restoration, and write
        the final 'done' status afterwards. The work callable should NOT
        itself write 'done' — only progress/error breadcrumbs — because
        on the WiFi-switched path we still need to flip back to AP
        before the flow is truly finished, and the UI watches for the
        'done' step to clear its spinner."""
        result = None
        try:
            result = await work()
            return result
        finally:
            if switched:
                write_status({"step": "switching-to-ap",
                              "version": version_label})
                await self._switch_to_ap()
            # Replace the transient last-step (switching-to-ap, or
            # whatever progress write the work left in place) with a
            # terminal 'done' the UI can match on.
            done = {"step": "done", "version": version_label}
            if isinstance(result, dict):
                done.update({k: v for k, v in result.items()
                             if k in ("newly_downloaded", "pruned")})
            write_status(done)

    async def _transient_wifi_path(self, work, ssid: str, password: str,
                                    version_label: str):
        loop = asyncio.get_event_loop()
        write_status({"step": "switching-to-client", "version": version_label,
                      "ssid": ssid})
        wifi_cfg = self.config.wifi
        ap_ssid = wifi_cfg.get("ap_ssid", "")
        ap_password = wifi_cfg.get("ap_password", "midihub1")

        try:
            await self.wifi.start_client_with_fallback(
                ssid, password, ap_ssid, ap_password)
        except Exception as e:
            self._abort("error-wifi-assoc",
                        f"Failed to switch to WiFi: {e}")
            raise NoInternetError(f"Failed to switch to WiFi: {e}") from e

        if self.wifi.mode != "client":
            msg = (f"Couldn't join '{ssid}'. Check the saved password "
                   f"and that the network is in range.")
            self._abort("error-wifi-assoc", msg)
            raise NoInternetError(msg)

        write_status({"step": "verifying-internet", "version": version_label,
                      "ssid": ssid})
        # start_client_with_fallback already waits for an IP. Re-probe to
        # confirm internet is actually reachable via the new connection
        # (joining a captive portal or a router with no WAN would otherwise
        # silently dump us into a "downloading…" that just hangs).
        reachable = await loop.run_in_executor(None, probe_internet)
        if not reachable:
            await self._switch_to_ap()
            msg = (f"Joined '{ssid}' but no internet — check the "
                   "network's router has internet access.")
            self._abort("error-no-internet-on-wifi", msg)
            raise NoInternetError(msg)

        return await self._run_work(work, switched=True,
                                     version_label=version_label)

    async def _switch_to_ap(self) -> None:
        wifi_cfg = self.config.wifi
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None, self.wifi.start_ap,
                wifi_cfg.get("ap_ssid", ""),
                wifi_cfg.get("ap_password", "midihub1"),
            )
        except Exception:
            log.exception("failed to return to AP mode (watchdog will retry)")

    def _explain_no_internet(self, pref: str, saved_ssid: str) -> str:
        if pref == "ap_only":
            return ("No internet on the current connection, and the WiFi "
                    "mode is set to 'AP only'. Plug in ethernet, or set "
                    "WiFi to 'WiFi for updates' and save credentials.")
        if not saved_ssid:
            return ("No internet on the current connection, and no WiFi "
                    "credentials are saved. Save credentials in the WiFi "
                    "card or plug in ethernet.")
        return ("No internet on the current connection. Plug in ethernet "
                "or set WiFi to 'WiFi for updates'.")

    def _abort(self, step: str, message: str) -> None:
        write_status({"step": step, "message": message})


# --- Concrete work callable: fetch + download newer releases ---------------

async def download_newer_releases(current_version: str) -> dict[str, Any]:
    """Async work the orchestrator runs once internet is reachable.

    Pulls the GitHub releases list, downloads every release strictly
    newer than `current_version` that isn't already on disk, and
    prunes back to KEEP_VERSIONS. Each step writes a status breadcrumb
    so the UI poll can show precise progress.

    Designed to be passed into `UpdateFetcher.run()`:
        await fetcher.run(lambda: download_newer_releases(__version__))
    """
    loop = asyncio.get_event_loop()
    write_status({"step": "fetching-release-list"})
    releases = await loop.run_in_executor(None, fetch_github_releases)
    current = parse_version(current_version)
    newly_downloaded: list[str] = []
    stored_versions = {v["version"] for v in list_stored_versions()}
    for rel in releases:
        if parse_version(rel["version"]) <= current:
            continue
        if rel["version"] in stored_versions:
            continue
        dest = UPDATES_DIR / f"raspimidihub_{rel['version']}-1_all.deb"
        write_status({"step": "downloading", "version": rel["version"]})
        ok, err = await loop.run_in_executor(
            None, download_release, rel["deb_url"], dest, rel["changelog"])
        if not ok:
            write_status({"step": "error-download",
                          "version": rel["version"],
                          "message": f"Download failed: {err}"})
            continue
        newly_downloaded.append(rel["version"])
    return {
        "newly_downloaded": newly_downloaded,
        "pruned": prune_stored(),
    }
