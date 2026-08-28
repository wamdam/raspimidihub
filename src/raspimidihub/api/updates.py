"""System update-flow routes: check for updates, versions list,
prerelease toggle, install, reinstall, live status. Moved verbatim
from the old api.py."""

import asyncio
import logging
import subprocess
from pathlib import Path

from .. import __version__
from ..update_flow import (
    NoInternetError,
    UpdateFetcher,
    download_newer_releases,
    list_stored_versions,
    read_status,
    write_status,
)
from ..web import Request, Response
from ._ctx import ApiContext

INSTALL_DEB_SCRIPT = Path("/usr/local/bin/raspimidihub-install-deb")

log = logging.getLogger(__name__)


def register_updates(ctx: ApiContext) -> None:
    """Register the /api/system/update* routes."""
    server = ctx.server
    config = ctx.config
    wifi = ctx.wifi

    # ================================================================
    # Phase 5.5 update flow: orchestrator-backed check & install
    #
    # Check: WiFi dance → fetch release list + download newer debs →
    # back to AP. Stored debs sit in /var/lib/raspimidihub/updates so
    # the user can downgrade offline.
    #
    # Install: peeks the deb's Depends. If every dep is already
    # satisfied (typical for downgrades) the install runs offline, no
    # WiFi dance. If any dep is missing (typical for upgrades that
    # add new packages, e.g. python3-dbus-next for BLE-MIDI) the
    # install is wrapped in UpdateFetcher.run() so the same dance
    # used by the check makes apt come back online for the dep fetch.
    # `apt install <path.deb>` then resolves and pulls anything
    # missing transparently.
    #
    # All kickoffs return immediately (the orchestrator runs as a
    # backgrounded asyncio task) — otherwise switching WiFi tears
    # down the AP and would kill the held-open HTTP request from a
    # phone. The UI polls GET /api/system/update-status and silently
    # absorbs fetches that fail during the AP outage.
    # ================================================================

    # One in-flight orchestrator task at a time; second click returns
    # 409 so the UI can ignore it without erroring out.
    in_flight_check: list = [None]

    @server.route("POST", "/api/system/check-update", summary="Check GitHub for a newer release and download it (runs in the background).")
    async def api_check_update(req: Request) -> Response:
        if wifi is None:
            return Response.error("WiFi manager unavailable", 503)
        if in_flight_check[0] and not in_flight_check[0].done():
            return Response.error("Update check already running", 409)

        fetcher = UpdateFetcher(wifi, config)

        include_pre = bool(
            config.data.get("updates", {}).get("include_prereleases", False))

        async def run_orchestrator():
            try:
                await fetcher.run(
                    lambda: download_newer_releases(
                        __version__, include_prereleases=include_pre),
                    version_label="check",
                )
            except NoInternetError:
                # _abort already wrote the actionable status — UI sees it.
                pass
            except Exception as e:
                log.exception("check-update failed")
                write_status({"step": "error", "message": str(e)})

        write_status({"step": "starting", "version": "check"})
        in_flight_check[0] = asyncio.get_running_loop().create_task(run_orchestrator())
        return Response.json({"status": "started"})

    @server.route("GET", "/api/system/versions", summary="List downloaded release debs (newest first) plus the running version.")
    async def api_system_versions(req: Request) -> Response:
        """List stored debs (newest first) plus the running version so
        the UI can mark which one's currently installed. Also returns
        the prerelease-channel toggle so the Settings card can render
        its state without a separate fetch."""
        return Response.json({
            "running": __version__,
            "stored": list_stored_versions(),
            "include_prereleases": bool(
                config.data.get("updates", {}).get("include_prereleases", False)),
        })

    @server.route("POST", "/api/system/include-prereleases", summary="Toggle whether update checks consider GitHub pre-releases.")
    async def api_set_include_prereleases(req: Request) -> Response:
        """Toggle whether `download_newer_releases` considers GitHub
        releases marked as prerelease (alpha / beta tags). Persists in
        config.data["updates"]["include_prereleases"]; takes effect on
        the next check-update click — does not retroactively download
        previously-skipped prereleases."""
        enabled = bool(req.json.get("enabled", False))
        updates_cfg = config.data.setdefault("updates", {})
        updates_cfg["include_prereleases"] = enabled
        await config.asave()
        return Response.json({"status": "ok", "include_prereleases": enabled})

    def _deb_unmet_deps(deb_path: str) -> list[str]:
        """Return the list of Depends in the deb that aren't satisfied
        on the current system. Empty list = the install can run fully
        offline."""
        try:
            depends_raw = subprocess.run(
                ["dpkg-deb", "-f", deb_path, "Depends"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except Exception:
            return []  # can't tell — let apt sort it out
        if not depends_raw:
            return []
        # dpkg's Depends syntax: "pkg1 (>= 1.0), pkg2 | pkg3, pkg4".
        # We're looking for any clause where NONE of the alternatives
        # is installed; version constraints are best-effort (we just
        # check pkg presence — apt will reject version mismatches
        # later, but those only happen on a corrupted system).
        unmet: list[str] = []
        for clause in depends_raw.split(","):
            alts = [a.strip().split()[0] for a in clause.split("|") if a.strip()]
            if not alts:
                continue
            # Strip ${...} substvars resolved at build time.
            alts = [a for a in alts if not a.startswith("${")]
            if not alts:
                continue
            satisfied = False
            for alt in alts:
                rc = subprocess.run(
                    ["dpkg-query", "-W", "-f=${Status}", alt],
                    capture_output=True, text=True, timeout=5,
                ).stdout
                if "install ok installed" in rc:
                    satisfied = True
                    break
            if not satisfied:
                unmet.append(clause.strip())
        return unmet

    @server.route("POST", "/api/system/install", summary="Install a previously-downloaded release deb. Body: {version}.")
    async def api_system_install(req: Request) -> Response:
        """Install a previously-downloaded deb. Body: {version: "X.Y.Z"}.

        If the deb has unmet deps, the install runs through
        UpdateFetcher so a transient WiFi switch happens automatically
        and apt can fetch them. Otherwise the install runs offline —
        no AP outage, no dance. Returns immediately (the install is
        backgrounded) because dpkg restarts raspimidihub.service mid-
        flight."""
        version = req.json.get("version", "")
        if not version:
            return Response.error("version required")
        match = next((v for v in list_stored_versions()
                      if v["version"] == version), None)
        if match is None:
            return Response.error(f"Version {version} not in storage", 404)
        if not INSTALL_DEB_SCRIPT.is_file():
            return Response.error("Install script missing", 500)

        unmet = _deb_unmet_deps(match["deb_path"])
        log.info("install %s: unmet deps = %r", version, unmet)

        if not unmet:
            # Offline-capable path: run the install script directly.
            write_status({"step": "installing", "version": version})
            subprocess.Popen(
                [str(INSTALL_DEB_SCRIPT), match["deb_path"]],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return Response.json({
                "status": "started", "version": version, "online": False,
            })

        # Online-required path: wrap the install in the UpdateFetcher
        # so the same WiFi dance used by check-update kicks in.
        if wifi is None:
            return Response.error(
                "Install needs network for new deps but WiFi manager "
                "is unavailable", 503)
        if in_flight_check[0] and not in_flight_check[0].done():
            return Response.error(
                "Update flow already running", 409)

        def _run_install_script():
            # The install script is blocking; run it in the executor so
            # the orchestrator's status pump keeps moving. It normally
            # reports via the status JSON ("installing" / "done" /
            # "error-install"), but its early failures (a bad or missing
            # deb path) exit non-zero to stderr *before* writing any
            # status — so capture returncode + stderr here as the only
            # trace of that path.
            r = subprocess.run(
                [str(INSTALL_DEB_SCRIPT), match["deb_path"]],
                capture_output=True, text=True)
            if r.returncode != 0:
                log.error("install script exited %d for %s: %s",
                          r.returncode, version,
                          (r.stderr or r.stdout or "").strip())
            return r.returncode

        async def install_work():
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _run_install_script)

        fetcher = UpdateFetcher(wifi, config)

        async def run_orchestrator():
            try:
                await fetcher.run(install_work, version_label=version)
            except NoInternetError:
                # _abort already wrote the actionable status.
                pass
            except Exception as e:
                log.exception("install %s failed", version)
                write_status({"step": "error-install",
                              "version": version, "message": str(e)})

        write_status({"step": "starting", "version": version})
        in_flight_check[0] = asyncio.get_running_loop().create_task(
            run_orchestrator())
        return Response.json({
            "status": "started", "version": version, "online": True,
            "unmet_deps": unmet,
        })

    @server.route("POST", "/api/system/reinstall", summary="Reinstall the currently-running version (apt reinstall).")
    async def api_system_reinstall(req: Request) -> Response:
        """Reinstall the currently-running version with apt's
        Recommends pulled in. Used to recover from upgrades that came
        via the old `dpkg -i` path: those skip Recommends, so the
        BLE-MIDI bridge silently has no python3-dbus-next on it.
        Always routes through UpdateFetcher because the whole point
        is to fetch missing optional packages — needs network."""
        match = next((v for v in list_stored_versions()
                      if v["version"] == __version__), None)
        if match is None:
            return Response.error(
                f"No stored deb for the running version ({__version__}). "
                "Run check-for-updates first to download it.", 404)
        if not INSTALL_DEB_SCRIPT.is_file():
            return Response.error("Install script missing", 500)
        if wifi is None:
            return Response.error("WiFi manager unavailable", 503)
        if in_flight_check[0] and not in_flight_check[0].done():
            return Response.error("Update flow already running", 409)

        def _run_reinstall_script():
            # Same contract as _run_install_script above: the script
            # self-reports via the status JSON; log the early-failure
            # stderr that would otherwise be swallowed.
            r = subprocess.run(
                [str(INSTALL_DEB_SCRIPT), match["deb_path"], "--reinstall"],
                capture_output=True, text=True)
            if r.returncode != 0:
                log.error("reinstall script exited %d: %s",
                          r.returncode,
                          (r.stderr or r.stdout or "").strip())
            return r.returncode

        async def reinstall_work():
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _run_reinstall_script)

        fetcher = UpdateFetcher(wifi, config)

        async def run_orchestrator():
            try:
                await fetcher.run(reinstall_work, version_label=__version__)
            except NoInternetError:
                pass
            except Exception as e:
                log.exception("reinstall failed")
                write_status({"step": "error-install",
                              "version": __version__, "message": str(e)})

        write_status({"step": "starting", "version": __version__})
        in_flight_check[0] = asyncio.get_running_loop().create_task(
            run_orchestrator())
        return Response.json({"status": "started", "version": __version__})

    @server.route("GET", "/api/system/update-status", summary="Live state of the current update flow (the UI polls this for progress).")
    async def api_update_status(req: Request) -> Response:
        """Live state of the most recent update flow. UI polls this for
        progress + post-mortem error messages. Always returns running
        version so the UI can detect a successful self-restart after
        an install."""
        return Response.json({"status": read_status(), "version": __version__})

