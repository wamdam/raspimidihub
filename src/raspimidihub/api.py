"""REST API routes for RaspiMIDIHub.

Registers all /api/* handlers on the WebServer instance.
"""

import asyncio
import logging
import os
import socket
import time
from pathlib import Path

from . import __version__
from .config import Config
from .midi_engine import MidiEngine, Connection
from .midi_filter import MidiFilter, ALL_CHANNELS, ALL_MSG_TYPES
from .web import Request, Response, WebServer
from .wifi import WifiManager

log = logging.getLogger(__name__)


def register_api(server: WebServer, engine: MidiEngine, config: Config,
                  wifi: WifiManager | None = None):
    """Register all API routes on the web server."""

    # ================================================================
    # Captive portal detection endpoints
    # These must return specific responses so mobile OS shows the
    # captive portal popup and then stays connected to the AP.
    # ================================================================

    @server.route("GET", "/generate_204")
    async def captive_android(req: Request) -> Response:
        # Android/Chrome: expects 204 from real internet, non-204 triggers portal
        return Response.redirect("http://192.168.4.1/")

    @server.route("GET", "/hotspot-detect.html")
    async def captive_apple(req: Request) -> Response:
        # Apple CNA: expects "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"
        # Returning anything else triggers the captive portal popup
        return Response.redirect("http://192.168.4.1/")

    @server.route("GET", "/library/test/success.html")
    async def captive_apple2(req: Request) -> Response:
        return Response.redirect("http://192.168.4.1/")

    @server.route("GET", "/connecttest.txt")
    async def captive_windows(req: Request) -> Response:
        # Windows: expects "Microsoft Connect Test"
        return Response.redirect("http://192.168.4.1/")

    @server.route("GET", "/ncsi.txt")
    async def captive_windows2(req: Request) -> Response:
        return Response.redirect("http://192.168.4.1/")

    @server.route("GET", "/redirect")
    async def captive_firefox(req: Request) -> Response:
        return Response.redirect("http://192.168.4.1/")

    @server.route("GET", "/canonical.html")
    async def captive_firefox2(req: Request) -> Response:
        return Response.redirect("http://192.168.4.1/")

    # ================================================================
    # GET /api/system — system info
    # ================================================================

    @server.route("GET", "/api/system")
    async def api_system(req: Request) -> Response:
        hostname = socket.gethostname()

        # IP addresses
        try:
            ips = []
            for iface in os.listdir("/sys/class/net"):
                if iface == "lo":
                    continue
                addr_path = f"/sys/class/net/{iface}/address"
                try:
                    with open(f"/proc/net/if_inet6") as f:
                        pass
                except FileNotFoundError:
                    pass
                import subprocess
                result = subprocess.run(
                    ["ip", "-4", "addr", "show", iface],
                    capture_output=True, text=True, timeout=2
                )
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("inet "):
                        ip = line.split()[1].split("/")[0]
                        ips.append({"interface": iface, "address": ip})
        except Exception:
            ips = []

        # CPU temperature
        temp = None
        try:
            raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
            temp = round(int(raw) / 1000, 1)
        except Exception:
            pass

        # RAM
        ram = {}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        ram["total_mb"] = int(line.split()[1]) // 1024
                    elif line.startswith("MemAvailable:"):
                        ram["available_mb"] = int(line.split()[1]) // 1024
        except Exception:
            pass

        # Uptime
        uptime = None
        try:
            raw = Path("/proc/uptime").read_text().strip()
            uptime = int(float(raw.split()[0]))
        except Exception:
            pass

        return Response.json({
            "hostname": hostname,
            "version": __version__,
            "ip_addresses": ips,
            "cpu_temp_c": temp,
            "ram": ram,
            "uptime_seconds": uptime,
            "config_fallback": config.fallback_active,
        })

    # ================================================================
    # GET /api/devices — list MIDI devices
    # ================================================================

    @server.route("GET", "/api/devices")
    async def api_devices(req: Request) -> Response:
        devices = engine.scan_devices()
        registry = engine.device_registry
        result = []
        for dev in devices:
            ports = []
            for port in dev.ports:
                ports.append({
                    "port_id": port.port_id,
                    "name": port.name,
                    "is_input": port.is_input,
                    "is_output": port.is_output,
                })
            info = registry.get_by_client(dev.client_id)
            entry = {
                "client_id": dev.client_id,
                "name": info.name if info else dev.name,
                "default_name": dev.name,
                "ports": ports,
            }
            if info:
                entry["stable_id"] = info.stable_id
                entry["vid"] = info.vid
                entry["pid"] = info.pid
                entry["usb_path"] = info.usb_path
            result.append(entry)
        return Response.json(result)

    # ================================================================
    # POST /api/devices/{client_id}/rename — rename a device
    # ================================================================

    @server.route("POST", "/api/devices/", exact=False)
    async def api_device_action(req: Request) -> Response:
        path = req.path_param("/api/devices/")

        # POST /api/devices/{client_id}/rename
        if path.endswith("/rename"):
            try:
                client_id = int(path[:-len("/rename")])
            except ValueError:
                return Response.error("Invalid client ID")

            data = req.json
            name = data.get("name", "").strip()
            if not name:
                return Response.error("Name required")

            registry = engine.device_registry
            info = registry.get_by_client(client_id)
            if info is None:
                return Response.not_found()

            registry.set_custom_name(info.stable_id, name)
            # Persist custom names in config
            config.data["device_names"] = registry.get_custom_names()
            config.save()

            return Response.json({"status": "renamed", "name": name})

        return Response.not_found()

    # ================================================================
    # GET /api/connections — list active connections
    # ================================================================

    @server.route("GET", "/api/connections")
    async def api_connections(req: Request) -> Response:
        conns = []
        fe = engine.filter_engine
        for c in sorted(engine.connections,
                        key=lambda c: (c.src_client, c.src_port, c.dst_client, c.dst_port)):
            conn_id = f"{c.src_client}:{c.src_port}-{c.dst_client}:{c.dst_port}"
            entry = {
                "id": conn_id,
                "src_client": c.src_client,
                "src_port": c.src_port,
                "dst_client": c.dst_client,
                "dst_port": c.dst_port,
                "filtered": False,
            }
            if fe:
                f = fe.get_filter(conn_id)
                if f:
                    entry["filtered"] = True
                    entry["filter"] = f.to_dict()
            conns.append(entry)
        return Response.json(conns)

    # ================================================================
    # POST /api/connections — create a connection
    # ================================================================

    @server.route("POST", "/api/connections", exact=True)
    async def api_create_connection(req: Request) -> Response:
        data = req.json
        for key in ("src_client", "src_port", "dst_client", "dst_port"):
            if key not in data or not isinstance(data[key], int):
                return Response.error(f"Missing or invalid field: {key}")

        if data["src_client"] == data["dst_client"]:
            return Response.error("Self-connections not allowed")

        conn = Connection(
            src_client=data["src_client"],
            src_port=data["src_port"],
            dst_client=data["dst_client"],
            dst_port=data["dst_port"],
        )
        try:
            engine._seq.subscribe(conn.src_client, conn.src_port,
                                  conn.dst_client, conn.dst_port)
            engine._connections.add(conn)
        except OSError as e:
            return Response.error(str(e))

        await server.send_sse("connection-changed", {
            "action": "created",
            "connection": {
                "src_client": conn.src_client, "src_port": conn.src_port,
                "dst_client": conn.dst_client, "dst_port": conn.dst_port,
            }
        })

        # Update config mode
        config.set_mode("custom")

        return Response.json({"status": "created"}, 201)

    # ================================================================
    # DELETE /api/connections/{id} — remove a connection
    # ================================================================

    @server.route("DELETE", "/api/connections/", exact=False)
    async def api_delete_connection(req: Request) -> Response:
        conn_id = req.path_param("/api/connections/")
        if not conn_id:
            # DELETE /api/connections — disconnect all
            engine.disconnect_all()
            config.set_mode("custom")
            await server.send_sse("connection-changed", {"action": "disconnected-all"})
            return Response.json({"status": "disconnected all"})

        # Parse id: "src_client:src_port-dst_client:dst_port"
        try:
            src, dst = conn_id.split("-")
            src_client, src_port = map(int, src.split(":"))
            dst_client, dst_port = map(int, dst.split(":"))
        except (ValueError, IndexError):
            return Response.error("Invalid connection ID format")

        conn = Connection(src_client, src_port, dst_client, dst_port)
        try:
            engine._seq.unsubscribe(conn.src_client, conn.src_port,
                                    conn.dst_client, conn.dst_port)
            engine._connections.discard(conn)
        except OSError as e:
            return Response.error(str(e))

        config.set_mode("custom")
        await server.send_sse("connection-changed", {
            "action": "deleted",
            "id": conn_id,
        })
        return Response.json({"status": "deleted"})

    # ================================================================
    # PATCH /api/connections/{id} — update filter on a connection
    # ================================================================

    @server.route("PATCH", "/api/connections/", exact=False)
    async def api_patch_connection(req: Request) -> Response:
        conn_id = req.path_param("/api/connections/")
        if not conn_id:
            return Response.error("Missing connection ID")

        # Parse connection ID
        try:
            src, dst = conn_id.split("-")
            src_client, src_port = map(int, src.split(":"))
            dst_client, dst_port = map(int, dst.split(":"))
        except (ValueError, IndexError):
            return Response.error("Invalid connection ID format")

        # Check connection exists
        conn = Connection(src_client, src_port, dst_client, dst_port)
        if conn not in engine.connections:
            return Response.not_found()

        fe = engine.filter_engine
        if not fe:
            return Response.error("Filter engine not available", 500)

        data = req.json
        channel_mask = data.get("channel_mask", ALL_CHANNELS)
        msg_types = set(data.get("msg_types", list(ALL_MSG_TYPES)))

        midi_filter = MidiFilter(channel_mask=channel_mask, msg_types=msg_types)

        if midi_filter.is_passthrough:
            # Remove filter — switch back to direct ALSA subscription
            if fe.has_filter(conn_id):
                fe.remove_filter(conn_id)
                # Re-establish direct subscription
                engine._seq.subscribe(src_client, src_port, dst_client, dst_port)
        else:
            # Add/update filter — switch to userspace passthrough
            if not fe.has_filter(conn_id):
                # Remove direct ALSA subscription first
                try:
                    engine._seq.unsubscribe(src_client, src_port, dst_client, dst_port)
                except OSError:
                    pass
                fe.add_filter(src_client, src_port, dst_client, dst_port, midi_filter)
            else:
                fe.update_filter(conn_id, midi_filter)

        config.set_mode("custom")
        await server.send_sse("connection-changed", {
            "action": "filter-updated",
            "id": conn_id,
            "filter": midi_filter.to_dict(),
        })
        return Response.json({"status": "updated", "filter": midi_filter.to_dict()})

    # ================================================================
    # POST /api/connections/connect-all — restore all-to-all
    # ================================================================

    @server.route("POST", "/api/connections/connect-all")
    async def api_connect_all(req: Request) -> Response:
        engine.disconnect_all()
        engine.scan_devices()
        conns = engine.connect_all()
        config.set_mode("all-to-all")
        await server.send_sse("connection-changed", {"action": "connected-all"})
        return Response.json({"status": "connected", "count": len(conns)})

    # ================================================================
    # Presets API
    # ================================================================

    @server.route("GET", "/api/presets", exact=True)
    async def api_list_presets(req: Request) -> Response:
        return Response.json(config.list_presets())

    @server.route("POST", "/api/presets", exact=True)
    async def api_save_preset(req: Request) -> Response:
        data = req.json
        name = data.get("name")
        if not name or not isinstance(name, str):
            return Response.error("Missing preset name")

        # Serialize current connections
        conns = [{
            "src_client": c.src_client, "src_port": c.src_port,
            "dst_client": c.dst_client, "dst_port": c.dst_port,
        } for c in engine.connections]

        if not config.save_preset(name, conns):
            return Response.error("Too many presets (max 100)")

        config.save()
        return Response.json({"status": "saved", "name": name}, 201)

    @server.route("POST", "/api/presets/import", exact=True)
    async def api_import_preset(req: Request) -> Response:
        data = req.json
        name = config.import_preset(data)
        if name is None:
            return Response.error("Invalid preset data")
        config.save()
        return Response.json({"status": "imported", "name": name}, 201)

    @server.route("POST", "/api/presets/", exact=False)
    async def api_preset_action(req: Request) -> Response:
        path = req.path_param("/api/presets/")
        # POST /api/presets/{name}/activate
        if path.endswith("/activate"):
            name = path[:-len("/activate")]
            preset = config.get_preset(name)
            if preset is None:
                return Response.not_found()

            # Apply preset connections
            engine.disconnect_all()
            for c in preset.get("connections", []):
                try:
                    conn = Connection(c["src_client"], c["src_port"],
                                      c["dst_client"], c["dst_port"])
                    engine._seq.subscribe(conn.src_client, conn.src_port,
                                          conn.dst_client, conn.dst_port)
                    engine._connections.add(conn)
                except (OSError, KeyError):
                    pass

            config.set_mode("custom")
            await server.send_sse("connection-changed", {
                "action": "preset-activated",
                "name": name,
            })
            return Response.json({"status": "activated", "name": name})

        return Response.not_found()

    @server.route("GET", "/api/presets/", exact=False)
    async def api_get_preset(req: Request) -> Response:
        path = req.path_param("/api/presets/")
        # GET /api/presets/{name}/export
        if path.endswith("/export"):
            name = path[:-len("/export")]
            data = config.export_preset(name)
            if data is None:
                return Response.not_found()
            return Response.json(data)

        return Response.not_found()

    @server.route("DELETE", "/api/presets/", exact=False)
    async def api_delete_preset(req: Request) -> Response:
        name = req.path_param("/api/presets/")
        if not name:
            return Response.error("Missing preset name")
        if not config.delete_preset(name):
            return Response.not_found()
        config.save()
        return Response.json({"status": "deleted"})

    # ================================================================
    # POST /api/config/save — explicitly save current config
    # ================================================================

    @server.route("POST", "/api/config/save")
    async def api_save_config(req: Request) -> Response:
        # Serialize current connections + filters into config
        fe = engine.filter_engine
        conns = []
        for c in engine.connections:
            conn_id = f"{c.src_client}:{c.src_port}-{c.dst_client}:{c.dst_port}"
            entry = {
                "src_client": c.src_client, "src_port": c.src_port,
                "dst_client": c.dst_client, "dst_port": c.dst_port,
            }
            if fe:
                f = fe.get_filter(conn_id)
                if f:
                    entry["filter"] = f.to_dict()
            conns.append(entry)
        config.set_connections(conns)

        if config.save():
            return Response.json({"status": "saved"})
        return Response.error("Failed to save config", 500)

    # ================================================================
    # WiFi API
    # ================================================================

    if wifi is None:
        return

    @server.route("GET", "/api/wifi")
    async def api_wifi_status(req: Request) -> Response:
        return Response.json({
            "mode": wifi.mode,
            "ssid": wifi.ssid,
            "ip": wifi.ip,
        })

    @server.route("POST", "/api/wifi/ap")
    async def api_wifi_ap(req: Request) -> Response:
        data = req.json
        ssid = data.get("ssid", "")
        password = data.get("password", "midihub1")
        if password and len(password) < 8:
            return Response.error("Password must be at least 8 characters")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, wifi.start_ap, ssid, password)

        # Update config
        cfg_wifi = config.wifi
        if ssid:
            cfg_wifi["ap_ssid"] = ssid
        if password:
            cfg_wifi["ap_password"] = password
        cfg_wifi["mode"] = "ap"
        config.save()

        server.enable_captive_portal(AP_IP)
        return Response.json({"status": "ap started", "ssid": wifi.ssid, "ip": wifi.ip})

    @server.route("POST", "/api/wifi/client")
    async def api_wifi_client(req: Request) -> Response:
        data = req.json
        ssid = data.get("ssid", "")
        password = data.get("password", "")
        if not ssid:
            return Response.error("SSID required")

        server.disable_captive_portal()

        cfg_wifi = config.wifi
        ap_ssid = cfg_wifi.get("ap_ssid", "")
        ap_password = cfg_wifi.get("ap_password", "midihub1")

        # Run in background with fallback
        await wifi.start_client_with_fallback(ssid, password, ap_ssid, ap_password)

        if wifi.mode == "client":
            cfg_wifi["mode"] = "client"
            cfg_wifi["client_ssid"] = ssid
            cfg_wifi["client_password"] = password
            config.save()
            return Response.json({"status": "connected", "ssid": ssid, "ip": wifi.ip})
        else:
            server.enable_captive_portal(AP_IP)
            return Response.error("Connection failed, fell back to AP mode", 502)

    @server.route("GET", "/api/wifi/scan")
    async def api_wifi_scan(req: Request) -> Response:
        loop = asyncio.get_event_loop()
        networks = await loop.run_in_executor(None, wifi.scan_networks)
        return Response.json(networks)

    from .wifi import AP_IP
