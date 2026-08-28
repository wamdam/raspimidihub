"""Network-interface, USB-tether, Bluetooth-MIDI and network-MIDI
(RTP) routes. Moved verbatim from the old api.py."""

import asyncio
import logging

from ..device_id import invalidate_bluealsa_macs_cache
from ..network_midi import ERR_SESSION_NOT_FOUND
from ..web import Request, Response
from ..wifi import configure_interface, get_all_interfaces
from ._ctx import ApiContext

log = logging.getLogger(__name__)


def register_network(ctx: ApiContext) -> None:
    """Register the /api/network, /api/bluetooth and
    /api/network-midi routes."""
    server = ctx.server
    config = ctx.config
    bluetooth = ctx.bluetooth
    network_midi = ctx.network_midi
    autosaver = ctx.autosaver

    # ================================================================
    # Network API
    # ================================================================


    @server.route("GET", "/api/network", summary="List network interfaces and their IPv4 configuration.")
    async def api_network(req: Request) -> Response:
        loop = asyncio.get_running_loop()
        interfaces = await loop.run_in_executor(None, get_all_interfaces)
        return Response.json(interfaces)

    @server.route("GET", "/api/network/usb-tether", summary="Report USB-tether (phone internet-sharing) status.")
    async def api_usb_tether(req: Request) -> Response:
        from ..usb_tether import detect_tether
        loop = asyncio.get_running_loop()
        state = await loop.run_in_executor(None, detect_tether)
        return Response.json(state)

    @server.route("POST", "/api/network/", exact=False, summary="Configure an interface's IPv4 (auto/DHCP or manual static).")
    async def api_configure_network(req: Request) -> Response:
        iface = req.path_param("/api/network/")
        if not iface:
            return Response.error("Missing interface name")

        data = req.json
        method = data.get("method", "auto")
        if method not in ("auto", "manual"):
            return Response.error("method must be 'auto' or 'manual'")

        address = data.get("address", "")
        netmask = data.get("netmask", "255.255.255.0")
        gateway = data.get("gateway", "")

        if method == "manual" and not address:
            return Response.error("address required for static IP")
        # A 169.254.x.x link-local is never a valid static IP. It's the
        # fallback eth0 carries when the cable is unplugged; refusing it
        # here stops a stale form prefill from clobbering the real static
        # address with the link-local.
        if method == "manual" and address.startswith("169.254."):
            return Response.error(
                "link-local (169.254.x.x) cannot be used as a static IP")

        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, configure_interface,
                                         iface, method, address, netmask, gateway)
        if ok:
            return Response.json({"status": "configured", "interface": iface})
        return Response.error("Failed to configure interface", 500)

    # ================================================================
    # Bluetooth MIDI API
    # ================================================================
    # The only static gate is whether a manager object exists at all
    # (the import succeeded). Everything else — radio powered, bluealsa
    # on PATH, dbus-next importable — is re-checked *live on each GET*
    # via availability(), not frozen at startup. This matters because
    # the radio can settle to `Powered: yes` slightly after we boot
    # (notably the Pi 3 B+, whose BCM firmware-patch path is slower):
    # a one-shot check at startup could catch it mid-power-on, cache
    # `no-bt-radio`, and hide the BT UI for the whole process lifetime
    # even though the radio came up fine moments later. Re-checking per
    # request lets the UI self-heal — the next time the Add overlay
    # re-fetches /api/bluetooth, it sees the now-powered radio. The
    # check is read-only when the radio is already powered (it only
    # issues `power on` from the *off* state, so it never disturbs a
    # live BLE-MIDI link), but it shells out to bluetoothctl with up to
    # ~5s of timeouts, so run it off-loop to keep routing/SSE smooth.
    # Bare GET /api/bluetooth always returns a payload so the UI can
    # render an "unsupported on this hardware" hint without polling 404s.

    if bluetooth:
        async def _bt_availability() -> dict:
            return await asyncio.to_thread(bluetooth.availability)

        @server.route("GET", "/api/bluetooth", summary="List paired Bluetooth-MIDI devices and radio availability.")
        async def api_bluetooth_status(req: Request) -> Response:
            avail = await _bt_availability()
            if not avail["available"]:
                return Response.json({
                    "available": False,
                    "reason": avail.get("reason"),
                    "devices": [],
                })
            devices = await bluetooth.get_paired_devices()
            return Response.json({"available": True, "devices": devices})

        @server.route("POST", "/api/bluetooth/scan", summary="Scan for nearby Bluetooth-MIDI devices (~10s).")
        async def api_bluetooth_scan(req: Request) -> Response:
            devices = await bluetooth.scan(timeout=10)
            return Response.json(devices)


        @server.route("POST", "/api/bluetooth/pair", summary="Pair a Bluetooth-MIDI device by address.")
        async def api_bluetooth_pair(req: Request) -> Response:
            address = req.json.get("address", "")
            if not address:
                return Response.error("address required")
            ok = await bluetooth.pair(address)
            invalidate_bluealsa_macs_cache()
            if ok:
                # Brief settle + kick a device-connected SSE so the
                # matrix re-fetches /api/devices and picks up the
                # new BLE-MIDI port.
                await asyncio.sleep(2)
                await server.send_sse("device-connected", {})
                return Response.json({"status": "paired"})
            return Response.error("Pairing failed", 502)

        @server.route("POST", "/api/bluetooth/connect", summary="Connect a paired Bluetooth-MIDI device by address.")
        async def api_bluetooth_connect(req: Request) -> Response:
            address = req.json.get("address", "")
            if not address:
                return Response.error("address required")
            ok = await bluetooth.connect(address)
            invalidate_bluealsa_macs_cache()
            if ok:
                # Hotplug detection on the ALSA seq fd already fires
                # device-connected when bluetoothd publishes its seq
                # client, so we don't need to sit on a sleep here.
                # Send one anyway as a belt-and-braces nudge.
                await server.send_sse("device-connected", {})
                return Response.json({"status": "connected"})
            return Response.error("Connection failed", 502)

        @server.route("POST", "/api/bluetooth/disconnect", summary="Disconnect a Bluetooth-MIDI device by address.")
        async def api_bluetooth_disconnect(req: Request) -> Response:
            address = req.json.get("address", "")
            if not address:
                return Response.error("address required")
            await bluetooth.disconnect(address)
            invalidate_bluealsa_macs_cache()
            await server.send_sse("device-disconnected", {})
            return Response.json({"status": "disconnected"})

        @server.route("DELETE", "/api/bluetooth/", exact=False, summary="Forget (unpair) a Bluetooth-MIDI device by address.")
        async def api_bluetooth_forget(req: Request) -> Response:
            address = req.path_param("/api/bluetooth/")
            if not address:
                return Response.error("address required")
            await bluetooth.forget(address)
            invalidate_bluealsa_macs_cache()
            await server.send_sse("device-disconnected", {})
            return Response.json({"status": "removed"})
    else:
        @server.route("GET", "/api/bluetooth", summary="List paired Bluetooth-MIDI devices and radio availability.")
        async def api_bluetooth_unavailable(req: Request) -> Response:
            return Response.json({
                "available": False,
                "reason": "no-bluetooth-manager",
                "devices": [],
            })

    # ================================================================
    # Network MIDI API (RTP-MIDI hub-to-hub link + standard clients)
    # ================================================================
    # Gated like Bluetooth: routes exist only when python3-zeroconf is
    # importable; the bare GET always answers so the Settings page can
    # render an "unsupported" hint without polling 404s. All settings
    # here are appliance settings (wifi pattern): mutate config +
    # asave() immediately, no dirty/asterisk.

    nm_avail = network_midi.availability() if network_midi else \
        {"available": False, "reason": "no-network-midi-manager"}
    if network_midi and nm_avail["available"]:
        @server.route("GET", "/api/network-midi", summary="Network-MIDI (RTP) status: exports, discovered sessions, mirrors, and peers.")
        async def api_network_midi(req: Request) -> Response:
            return Response.json(network_midi.status())

        @server.route("POST", "/api/network-midi/enable", summary="Enable or disable network-MIDI (RTP) on the hub.")
        async def api_network_midi_enable(req: Request) -> Response:
            enabled = bool(req.json.get("enabled"))
            config.data.setdefault("network_midi", {})["enabled"] = enabled
            await config.asave()
            # config.json holds the setting, but the autosave slot is
            # what boot resumes from — and a settings-only change never
            # bumps the engine change-seq, so the debounced autosaver
            # would never refresh it. Force a resume-snapshot now so the
            # toggle survives a reboot (same rule as Load/Restore/Import).
            await autosaver.autosave_now()
            await network_midi.set_enabled(enabled)
            return Response.json({"status": "saved", "enabled": enabled})

        @server.route("POST", "/api/network-midi/export", summary="Export (or stop exporting) a device over network-MIDI by stable_id.")
        async def api_network_midi_export(req: Request) -> Response:
            stable_id = req.json.get("stable_id", "")
            exported = bool(req.json.get("exported"))
            if not stable_id:
                return Response.error("stable_id required")
            if exported:
                ok, reason = network_midi.is_exportable(stable_id)
                if not ok:
                    return Response.error(reason)
            cfg = config.data.setdefault("network_midi", {})
            current = cfg.setdefault("exported", [])
            if exported and stable_id not in current:
                current.append(stable_id)
            elif not exported and stable_id in current:
                current.remove(stable_id)
            await config.asave()
            await autosaver.autosave_now()  # keep the resume snapshot in sync
            await network_midi.set_export(stable_id, exported)
            return Response.json({"status": "saved"})

        @server.route("POST", "/api/network-midi/mirror", summary="Mirror a discovered network-MIDI session as a local device.")
        async def api_network_midi_mirror(req: Request) -> Response:
            key = req.json.get("service") or req.json.get("stable_id", "")
            svc = network_midi.service_for(key)
            if svc is None:
                return Response.error(
                    f"Session not found ({ERR_SESSION_NOT_FOUND}).")
            cfg = config.data.setdefault("network_midi", {})
            if svc.is_hub:
                # Hub sessions auto-mirror; "mirror" = clear the opt-out.
                disabled = cfg.setdefault("mirror_disabled", [])
                if svc.service in disabled:
                    disabled.remove(svc.service)
            else:
                added = cfg.setdefault("mirrored_foreign", [])
                if svc.service not in added:
                    added.append(svc.service)
            await config.asave()
            await autosaver.autosave_now()  # keep the resume snapshot in sync
            # The config entry above records the *intent* (the policy
            # retries when the peer re-advertises); a failure here means
            # it isn't live yet, so report the diagnostic code rather
            # than claim success.
            err = await network_midi.set_mirrored(svc.service, True)
            if err:
                return Response.error(
                    f"Could not mirror this device ({err}). "
                    f"See the hub log for details.")
            await server.send_sse("device-connected", {})
            return Response.json({"status": "mirrored"})

        @server.route("POST", "/api/network-midi/unmirror", summary="Stop mirroring a network-MIDI session.")
        async def api_network_midi_unmirror(req: Request) -> Response:
            key = req.json.get("service") or req.json.get("stable_id", "")
            svc = network_midi.service_for(key)
            if svc is None:
                return Response.error(
                    f"Session not found ({ERR_SESSION_NOT_FOUND}).")
            cfg = config.data.setdefault("network_midi", {})
            if svc.is_hub:
                disabled = cfg.setdefault("mirror_disabled", [])
                if svc.service not in disabled:
                    disabled.append(svc.service)
            else:
                added = cfg.setdefault("mirrored_foreign", [])
                if svc.service in added:
                    added.remove(svc.service)
            await config.asave()
            await autosaver.autosave_now()  # keep the resume snapshot in sync
            await network_midi.set_mirrored(svc.service, False)
            await server.send_sse("device-disconnected", {})
            return Response.json({"status": "unmirrored"})

        @server.route("POST", "/api/network-midi/peers", summary="Add a manual network-MIDI peer host (discovery fallback).")
        async def api_network_midi_peer_add(req: Request) -> Response:
            host = (req.json.get("host") or "").strip()
            if not host:
                return Response.error("host required")
            cfg = config.data.setdefault("network_midi", {})
            peers = cfg.setdefault("manual_peers", [])
            if host not in peers:
                peers.append(host)
                await config.asave()
                await autosaver.autosave_now()  # keep resume snapshot in sync
            return Response.json({"status": "added"})

        @server.route("DELETE", "/api/network-midi/peers/", exact=False, summary="Remove a manual network-MIDI peer host.")
        async def api_network_midi_peer_remove(req: Request) -> Response:
            host = req.path_param("/api/network-midi/peers/")
            if not host:
                return Response.error("host required")
            cfg = config.data.setdefault("network_midi", {})
            peers = cfg.setdefault("manual_peers", [])
            if host in peers:
                peers.remove(host)
                await config.asave()
                await autosaver.autosave_now()  # keep resume snapshot in sync
            return Response.json({"status": "removed"})
    else:
        @server.route("GET", "/api/network-midi", summary="Network-MIDI (RTP) status: exports, discovered sessions, mirrors, and peers.")
        async def api_network_midi_unavailable(req: Request) -> Response:
            return Response.json({
                "available": False,
                "reason": nm_avail.get("reason"),
                "exports": [],
            })

