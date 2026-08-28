"""WiFi status/credentials/AP/mode routes. Moved verbatim from the
old api.py."""

import asyncio
import logging

from ..web import Request, Response
from ..wifi import WifiManager
from ._ctx import ApiContext

log = logging.getLogger(__name__)


def register_wifi(ctx: ApiContext) -> None:
    """Register the /api/wifi routes (no-op without a WifiManager)."""
    if ctx.wifi is None:
        return
    server = ctx.server
    config = ctx.config
    wifi = ctx.wifi
    autosaver = ctx.autosaver

    # ================================================================
    # WiFi API
    # ================================================================

    if wifi is None:
        return

    @server.route("GET", "/api/wifi", summary="WiFi status: mode, SSID, IP, saved home-WiFi SSID, AP band/country, 5 GHz support.")
    async def api_wifi_status(req: Request) -> Response:
        # Expose the saved update-WiFi SSID (NOT the password) so the
        # Settings UI can show "Update WiFi: HomeWiFi - change?" without
        # the user re-entering it on every visit. wifi_mode_pref drives
        # the AP-only / WiFi-for-updates / WiFi-always radio.
        loop = asyncio.get_running_loop()
        band_5ghz_supported = await loop.run_in_executor(
            None, WifiManager.radio_supports_5ghz)
        resolved_country = await loop.run_in_executor(
            None, WifiManager._resolve_country, config.wifi.get("ap_country", ""))
        return Response.json({
            "mode": wifi.mode,
            "ssid": wifi.ssid,
            "ip": wifi.ip,
            "saved_client_ssid": config.wifi.get("client_ssid", ""),
            "wifi_mode_pref": config.wifi.get("wifi_mode_pref", "ap_only"),
            "ap_band": config.wifi.get("ap_band", "2.4"),
            "ap_country": config.wifi.get("ap_country", ""),
            "resolved_country": resolved_country,
            "band_5ghz_supported": band_5ghz_supported,
        })

    # ----- Home WiFi credentials --------------------------------------
    #
    # The Pi's "home WiFi" is the network it can briefly join (or stay on
    # permanently) to reach the public internet. Saved as a pair of
    # SSID + password in the persistent config; the actual mode flip is
    # decided by `wifi_mode_pref` and the apply-mode endpoint, NOT by
    # saving credentials. So this endpoint is data-only — no live
    # network changes.
    @server.route("POST", "/api/wifi/credentials", summary="Save or forget home-WiFi credentials (data only; no live mode change).")
    async def api_wifi_credentials(req: Request) -> Response:
        data = req.json
        cfg_wifi = config.wifi

        if data.get("action") == "forget":
            cfg_wifi["client_ssid"] = ""
            cfg_wifi["client_password"] = ""
            # Two of the three modes need credentials. Without them only
            # ap_only is meaningful, so demote silently.
            if cfg_wifi.get("wifi_mode_pref") in ("wifi_for_updates", "wifi_always"):
                cfg_wifi["wifi_mode_pref"] = "ap_only"
            await config.asave()
            await autosaver.autosave_now()  # keep the resume snapshot in sync
            return Response.json({"status": "forgotten"})

        ssid = data.get("ssid", "").strip()
        if not ssid:
            return Response.error("SSID required")
        cfg_wifi["client_ssid"] = ssid
        # Empty password = keep existing (so the user can change SSID
        # without re-typing the password).
        if "password" in data and data["password"] != "":
            cfg_wifi["client_password"] = data["password"]
        await config.asave()
        await autosaver.autosave_now()  # keep the resume snapshot in sync
        return Response.json({"status": "saved", "ssid": ssid})

    @server.route("POST", "/api/wifi/ap-password", summary="Change the access-point password (existing connections survive).")
    async def api_wifi_ap_password(req: Request) -> Response:
        """Change the AP password without flipping modes. Existing
        connections survive (PSK is checked at association, not per
        packet); new connections need the new password."""
        password = req.json.get("password", "")
        if len(password) < 8:
            return Response.error("Password must be at least 8 characters")
        try:
            wifi.set_ap_password(password)
        except ValueError as e:
            return Response.error(str(e))
        config.wifi["ap_password"] = password
        await config.asave()
        await autosaver.autosave_now()  # keep the resume snapshot in sync
        return Response.json({"status": "saved"})

    @server.route("POST", "/api/wifi/ap-radio", summary="Set the AP radio band (2.4/5 GHz) and country, restarting the AP to apply.")
    async def api_wifi_ap_radio(req: Request) -> Response:
        """Set the AP radio band (2.4 / 5 GHz) and regulatory country,
        then restart the AP to apply. Restarting drops wlan0, which would
        kill a phone's held-open request, so the restart runs as a
        backgrounded task — same pattern as apply-mode. 5 GHz on a
        2.4-only radio is rejected up front; a 5 GHz bring-up that fails
        later still self-heals to 2.4 inside start_ap."""
        data = req.json
        band = str(data.get("band", "")).strip()
        country = str(data.get("country", "")).strip().upper()
        if band not in ("2.4", "5"):
            return Response.error("band must be '2.4' or '5'")
        if country and not (len(country) == 2 and country.isalpha()):
            return Response.error(
                "country must be a 2-letter ISO code (or empty for auto)")
        loop = asyncio.get_running_loop()
        if band == "5":
            if not await loop.run_in_executor(
                    None, WifiManager.radio_supports_5ghz):
                return Response.error(
                    "This Pi's radio does not support 5 GHz", 400)
        cfg_wifi = config.wifi
        cfg_wifi["ap_band"] = band
        cfg_wifi["ap_country"] = country
        await config.asave()
        await autosaver.autosave_now()  # appliance setting — keep resume snapshot
        # Only restart when actually in AP mode; in client mode the new
        # band applies the next time the AP comes up.
        if wifi.mode != "ap":
            return Response.json({"status": "saved", "switched": False})
        ap_ssid = cfg_wifi.get("ap_ssid", "")
        ap_password = cfg_wifi.get("ap_password", "midihub1")

        async def restart():
            try:
                await loop.run_in_executor(
                    None, wifi.start_ap, ap_ssid, ap_password, band, country)
            except Exception:
                log.exception("ap-radio restart failed")

        loop.create_task(restart())
        return Response.json({"status": "saved", "switched": True, "band": band})

    # The mode-pref is the only thing that drives the live wlan0 state.
    # Apply saves the pref and triggers the underlying mode flip (if
    # any) as a backgrounded asyncio task — same reason as
    # /api/system/check-update: switching to client mode tears down the
    # AP and would kill any held-open HTTP request from a phone.
    @server.route("POST", "/api/wifi/apply-mode", summary="Set the WiFi mode (ap_only / wifi_for_updates / wifi_always) and flip wlan0 if needed.")
    async def api_wifi_apply_mode(req: Request) -> Response:
        pref = req.json.get("pref", "")
        if pref not in ("ap_only", "wifi_for_updates", "wifi_always"):
            return Response.error("invalid pref")
        cfg_wifi = config.wifi
        saved_ssid = cfg_wifi.get("client_ssid", "")
        if pref in ("wifi_for_updates", "wifi_always") and not saved_ssid:
            return Response.error(
                "Save home WiFi credentials before selecting this mode")

        cfg_wifi["wifi_mode_pref"] = pref
        await config.asave()
        # Appliance setting (not a MIDI edit), so it never bumps the dirty
        # counter — without forcing the autosave here, boot would prefer a
        # staler resume snapshot and the mode would revert to ap_only on the
        # next restart/update. Mirrors the network_midi endpoints.
        await autosaver.autosave_now()

        # Decide whether the live wlan0 mode needs to change. Only two
        # of the four (current_mode, target_pref) combinations are
        # disruptive: AP→client (going to wifi_always) and client→AP
        # (leaving wifi_always).
        target_live = "client" if pref == "wifi_always" else "ap"
        if wifi.mode == target_live:
            return Response.json({"status": "saved", "switched": False})

        loop = asyncio.get_running_loop()
        ap_ssid = cfg_wifi.get("ap_ssid", "")
        ap_password = cfg_wifi.get("ap_password", "midihub1")
        client_password = cfg_wifi.get("client_password", "")

        async def switch():
            try:
                if target_live == "client":
                    await wifi.start_client_with_fallback(
                        saved_ssid, client_password, ap_ssid, ap_password)
                else:
                    await loop.run_in_executor(
                        None, wifi.start_ap, ap_ssid, ap_password,
                        cfg_wifi.get("ap_band", "2.4"),
                        cfg_wifi.get("ap_country", ""))
            except Exception:
                log.exception("apply-mode switch failed")

        loop.create_task(switch())
        return Response.json({"status": "saved", "switched": True,
                              "target_mode": target_live})

    @server.route("GET", "/api/wifi/scan", summary="Scan for nearby WiFi networks.")
    async def api_wifi_scan(req: Request) -> Response:
        loop = asyncio.get_running_loop()
        networks = await loop.run_in_executor(None, wifi.scan_networks)
        return Response.json(networks)

