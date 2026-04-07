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
from .midi_filter import MidiFilter, MidiMapping, MappingType, ALL_CHANNELS, ALL_MSG_TYPES
from .web import Request, Response, WebServer
from .wifi import WifiManager

log = logging.getLogger(__name__)


def register_api(server: WebServer, engine: MidiEngine, config: Config,
                  wifi: WifiManager | None = None):
    """Register all API routes on the web server."""

    # ================================================================
    # Captive portal probe responses
    # Return "success" responses so the OS thinks we have internet
    # and stays connected. No portal popup, user opens 192.168.4.1.
    # ================================================================

    @server.route("GET", "/generate_204")
    async def captive_android(req: Request) -> Response:
        return Response(status=204)

    @server.route("GET", "/hotspot-detect.html")
    async def captive_apple(req: Request) -> Response:
        return Response.html("<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>")

    @server.route("GET", "/library/test/success.html")
    async def captive_apple2(req: Request) -> Response:
        return Response.html("<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>")

    @server.route("GET", "/connecttest.txt")
    async def captive_windows(req: Request) -> Response:
        return Response.text("Microsoft Connect Test")

    @server.route("GET", "/ncsi.txt")
    async def captive_windows2(req: Request) -> Response:
        return Response.text("Microsoft NCSI")

    @server.route("GET", "/redirect")
    async def captive_firefox(req: Request) -> Response:
        return Response.text("success\n")

    @server.route("GET", "/canonical.html")
    async def captive_firefox2(req: Request) -> Response:
        return Response.text("success\n")

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
            "default_routing": config.default_routing,
        })

    # ================================================================
    # PATCH /api/system — update system settings
    # ================================================================

    @server.route("PATCH", "/api/system")
    async def api_patch_system(req: Request) -> Response:
        data = req.json
        if "default_routing" in data:
            val = data["default_routing"]
            if val not in ("all", "none"):
                return Response.error("default_routing must be 'all' or 'none'")
            config.data["default_routing"] = val
            config.save()
        return Response.json({"status": "updated"})

    # ================================================================
    # GET /api/devices — list MIDI devices
    # ================================================================

    @server.route("GET", "/api/devices")
    async def api_devices(req: Request) -> Response:
        devices = engine.scan_devices()
        registry = engine.device_registry
        result = []
        port_names = config.data.get("port_names", {})
        for dev in devices:
            info = registry.get_by_client(dev.client_id)
            ports = []
            for port in dev.ports:
                sid = info.stable_id if info else None
                port_key = f"{sid}:{port.port_id}" if sid else None
                ports.append({
                    "port_id": port.port_id,
                    "name": port_names.get(port_key, port.name) if port_key else port.name,
                    "default_name": port.name,
                    "is_input": port.is_input,
                    "is_output": port.is_output,
                })
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
            entry["online"] = True
            result.append(entry)

        # Add offline devices from saved config
        online_stable_ids = {e.get("stable_id") for e in result if "stable_id" in e}
        device_names = config.data.get("device_names", {})
        offline_ports = {}  # sid -> set of port_ids
        for c in config.connections + config.disconnected:
            for prefix in ("src", "dst"):
                sid = c.get(f"{prefix}_stable_id")
                if sid and sid not in online_stable_ids:
                    offline_ports.setdefault(sid, set()).add(c.get(f"{prefix}_port", 0))
        for sid, port_ids in offline_ports.items():
            name = device_names.get(sid, sid)
            ports = []
            for pid in sorted(port_ids):
                port_key = f"{sid}:{pid}"
                pname = port_names.get(port_key, f"MIDI {pid + 1}")
                ports.append({"port_id": pid, "name": pname, "default_name": f"MIDI {pid + 1}",
                              "is_input": True, "is_output": True})
            result.append({
                "client_id": None,
                "stable_id": sid,
                "name": name,
                "default_name": name,
                "ports": ports,
                "online": False,
            })

        return Response.json(result)

    # ================================================================
    # DELETE /api/devices/{stable_id} — remove an offline device from saved config
    # ================================================================

    @server.route("DELETE", "/api/devices/", exact=False)
    async def api_delete_device(req: Request) -> Response:
        stable_id = req.path_param("/api/devices/")
        if not stable_id:
            return Response.error("Missing stable ID")

        # Remove from saved connections
        config.data["connections"] = [
            c for c in config.connections
            if c.get("src_stable_id") != stable_id and c.get("dst_stable_id") != stable_id
        ]
        # Remove from disconnected
        config.data["disconnected"] = [
            c for c in config.disconnected
            if c.get("src_stable_id") != stable_id and c.get("dst_stable_id") != stable_id
        ]
        # Remove from runtime disconnected — filter out entries involving this device
        registry = engine.device_registry
        engine._disconnected = {
            k: v for k, v in engine._disconnected.items()
            if not any(
                (info := registry.get_by_client(int(part.split(":")[0]))) and info.stable_id == stable_id
                for part in k.split("-")
            )
        }
        # Remove from device names
        names = config.data.get("device_names", {})
        names.pop(stable_id, None)

        config.save()
        await server.send_sse("connection-changed", {"action": "device-removed"})
        return Response.json({"status": "removed"})

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

        # POST /api/devices/{client_id}/rename-port
        if path.endswith("/rename-port"):
            try:
                client_id = int(path[:-len("/rename-port")])
            except ValueError:
                return Response.error("Invalid client ID")

            data = req.json
            port_id = data.get("port_id")
            name = data.get("name", "").strip()
            if port_id is None:
                return Response.error("port_id required")

            registry = engine.device_registry
            info = registry.get_by_client(client_id)
            if info is None:
                return Response.not_found()

            port_names = config.data.get("port_names", {})
            port_key = f"{info.stable_id}:{port_id}"
            if name:
                port_names[port_key] = name
            else:
                port_names.pop(port_key, None)
            config.data["port_names"] = port_names
            config.save()

            return Response.json({"status": "renamed", "port_key": port_key, "name": name})

        # POST /api/devices/{client_id}/send
        if path.endswith("/send"):
            try:
                client_id = int(path[:-len("/send")])
            except ValueError:
                return Response.error("Invalid client ID")

            if not engine._seq:
                return Response.error("MIDI not available", 500)

            data = req.json
            msg_type = data.get("type", "")
            channel = data.get("channel", 0)
            port = data.get("port", 0)

            if msg_type == "note_on":
                note = data.get("note", 60)
                velocity = data.get("velocity", 100)
                engine._seq.send_note_on(client_id, port, channel, note, velocity)
                return Response.json({"status": "sent", "type": "note_on"})
            elif msg_type == "note_off":
                note = data.get("note", 60)
                engine._seq.send_note_off(client_id, port, channel, note)
                return Response.json({"status": "sent", "type": "note_off"})
            elif msg_type == "cc":
                cc = data.get("cc", 1)
                value = data.get("value", 0)
                engine._seq.send_cc(client_id, port, channel, cc, value)
                return Response.json({"status": "sent", "type": "cc"})
            else:
                return Response.error("Unknown type. Use: note_on, note_off, cc")

        return Response.not_found()

    # ================================================================
    # GET /api/connections — list active + offline connections
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
                mappings = fe.get_mappings(conn_id)
                if mappings:
                    entry["mappings"] = [m.to_dict() for m in mappings]
            conns.append(entry)

        # Add saved connections involving offline devices
        registry = engine.device_registry
        online_sids = set()
        for dev in engine.devices:
            info = registry.get_by_client(dev.client_id)
            if info:
                online_sids.add(info.stable_id)

        for c in config.connections:
            src_sid = c.get("src_stable_id")
            dst_sid = c.get("dst_stable_id")
            if not src_sid or not dst_sid:
                continue
            # Only include if at least one side is offline
            if src_sid in online_sids and dst_sid in online_sids:
                continue
            entry = {
                "id": f"offline:{src_sid}:{c.get('src_port', 0)}|{dst_sid}:{c.get('dst_port', 0)}",
                "src_stable_id": src_sid,
                "src_port": c.get("src_port", 0),
                "dst_stable_id": dst_sid,
                "dst_port": c.get("dst_port", 0),
                "offline": True,
                "filtered": bool(c.get("filter") or c.get("mappings")),
            }
            if c.get("filter"):
                entry["filter"] = c["filter"]
            if c.get("mappings"):
                entry["mappings"] = c["mappings"]
            conns.append(entry)

        return Response.json(conns)

    # ================================================================
    # POST /api/connections — create a connection
    # ================================================================

    @server.route("POST", "/api/connections", exact=True)
    async def api_create_connection(req: Request) -> Response:
        data = req.json

        # Handle offline connection (stable IDs, no ALSA client)
        if data.get("src_stable_id") or data.get("dst_stable_id"):
            src_sid = data.get("src_stable_id", "")
            dst_sid = data.get("dst_stable_id", "")
            src_port = data.get("src_port", 0)
            dst_port = data.get("dst_port", 0)
            if not src_sid or not dst_sid:
                return Response.error("Missing stable IDs for offline connection")
            # Add to config connections
            entry = {
                "src_stable_id": src_sid, "src_port": src_port,
                "dst_stable_id": dst_sid, "dst_port": dst_port,
            }
            # Check not already saved
            existing = config.connections
            if not any(c.get("src_stable_id") == src_sid and c.get("dst_stable_id") == dst_sid
                       and c.get("src_port") == src_port and c.get("dst_port") == dst_port
                       for c in existing):
                existing.append(entry)
                config.set_connections(existing)
                config.save()
            await server.send_sse("connection-changed", {"action": "created"})
            config.set_mode("custom")
            return Response.json({"status": "created"}, 201)

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
        conn_id = f"{conn.src_client}:{conn.src_port}-{conn.dst_client}:{conn.dst_port}"

        # Check for saved filter/mapping data from previous disconnect
        saved = engine._disconnected.pop(conn_id, {})
        fe = engine.filter_engine

        saved_filter = saved.get("filter")
        saved_mappings = saved.get("mappings", [])
        needs_userspace = bool(saved_mappings)
        if saved_filter:
            midi_filter = MidiFilter.from_dict(saved_filter)
            needs_userspace = needs_userspace or not midi_filter.is_passthrough
        else:
            midi_filter = None

        if needs_userspace and fe:
            if midi_filter is None:
                midi_filter = MidiFilter()
        if needs_userspace and fe and midi_filter:
            # Restore via filter engine (userspace passthrough)
            fe.add_filter(conn.src_client, conn.src_port,
                          conn.dst_client, conn.dst_port, midi_filter)
            for md in saved_mappings:
                try:
                    mapping = MidiMapping.from_dict(md)
                    fe.add_mapping(conn_id, mapping)
                except (ValueError, KeyError):
                    pass
            engine._connections.add(conn)
        else:
            # Direct ALSA subscription
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

        # Handle offline connection IDs: "offline:src_sid:port|dst_sid:port"
        if conn_id.startswith("offline:"):
            parts = conn_id[len("offline:"):]
            try:
                src_part, dst_part = parts.split("|", 1)
                # src_part = "stable_id:port", dst_part = "stable_id:port"
                src_sid, src_port_s = src_part.rsplit(":", 1)
                dst_sid, dst_port_s = dst_part.rsplit(":", 1)
                src_port = int(src_port_s)
                dst_port = int(dst_port_s)
            except (ValueError, IndexError):
                return Response.error("Invalid offline connection ID")
            # Find saved filter/mapping data before removing
            saved_conn = None
            for c in config.connections + config.disconnected:
                if (c.get("src_stable_id") == src_sid and c.get("dst_stable_id") == dst_sid
                        and c.get("src_port") == src_port and c.get("dst_port") == dst_port):
                    saved_conn = c
                    break
            # Remove from saved connections
            config.data["connections"] = [
                c for c in config.connections
                if not (c.get("src_stable_id") == src_sid and c.get("dst_stable_id") == dst_sid
                        and c.get("src_port") == src_port and c.get("dst_port") == dst_port)
            ]
            disconn_entry = {
                "src_stable_id": src_sid, "src_port": src_port,
                "dst_stable_id": dst_sid, "dst_port": dst_port,
            }
            if saved_conn:
                if saved_conn.get("filter"):
                    disconn_entry["filter"] = saved_conn["filter"]
                if saved_conn.get("mappings"):
                    disconn_entry["mappings"] = saved_conn["mappings"]
            # Add to disconnected if not already there
            if not any(c.get("src_stable_id") == src_sid and c.get("dst_stable_id") == dst_sid
                       and c.get("src_port") == src_port and c.get("dst_port") == dst_port
                       for c in config.disconnected):
                config.data.setdefault("disconnected", []).append(disconn_entry)
            config.save()
            config.set_mode("custom")
            await server.send_sse("connection-changed", {"action": "deleted", "id": conn_id})
            return Response.json({"status": "deleted"})

        # Parse id: "src_client:src_port-dst_client:dst_port"
        try:
            src, dst = conn_id.split("-")
            src_client, src_port = map(int, src.split(":"))
            dst_client, dst_port = map(int, dst.split(":"))
        except (ValueError, IndexError):
            return Response.error("Invalid connection ID format")

        conn = Connection(src_client, src_port, dst_client, dst_port)

        # Save filter/mapping data before removing
        fe = engine.filter_engine
        saved_data = {}
        if fe:
            f = fe.get_filter(conn_id)
            if f:
                saved_data["filter"] = f.to_dict()
            mappings = fe.get_mappings(conn_id)
            if mappings:
                saved_data["mappings"] = [m.to_dict() for m in mappings]
            if fe.has_filter(conn_id):
                fe.remove_filter(conn_id)

        try:
            engine._seq.unsubscribe(conn.src_client, conn.src_port,
                                    conn.dst_client, conn.dst_port)
        except OSError:
            pass
        engine._connections.discard(conn)

        # Track as deliberately disconnected with saved config
        engine._disconnected[conn_id] = saved_data

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
            # Check if mappings still need userspace
            fc = fe.filtered_connections.get(conn_id)
            if fc and len(fc.mappings) > 0:
                # Keep in userspace for mappings, just update filter
                fe.update_filter(conn_id, midi_filter)
            elif fe.has_filter(conn_id):
                # No mappings — switch back to direct ALSA subscription
                fe.remove_filter(conn_id)
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
    # GET/POST/DELETE /api/connections/{id}/mappings — mapping CRUD
    # ================================================================

    @server.route("GET", "/api/mappings/", exact=False)
    async def api_get_mappings(req: Request) -> Response:
        conn_id = req.path_param("/api/mappings/")
        if not conn_id:
            return Response.error("Missing connection ID")

        fe = engine.filter_engine
        if not fe:
            return Response.error("Filter engine not available", 500)

        mappings = fe.get_mappings(conn_id)
        return Response.json([m.to_dict() for m in mappings])

    @server.route("POST", "/api/mappings/", exact=False)
    async def api_add_mapping(req: Request) -> Response:
        conn_id = req.path_param("/api/mappings/")
        if not conn_id:
            return Response.error("Missing connection ID")

        # Parse connection ID
        try:
            src, dst = conn_id.split("-")
            src_client, src_port = map(int, src.split(":"))
            dst_client, dst_port = map(int, dst.split(":"))
        except (ValueError, IndexError):
            return Response.error("Invalid connection ID format")

        conn = Connection(src_client, src_port, dst_client, dst_port)
        if conn not in engine.connections:
            return Response.not_found()

        fe = engine.filter_engine
        if not fe:
            return Response.error("Filter engine not available", 500)

        data = req.json
        try:
            mapping = MidiMapping.from_dict(data)
        except (ValueError, KeyError) as e:
            return Response.error(f"Invalid mapping: {e}")

        # Validate: CC→CC with same channel and same CC number is pointless
        if mapping.type == MappingType.CC_TO_CC:
            dst_ch = mapping.dst_channel if mapping.dst_channel is not None else mapping.src_channel
            dst_cc = mapping.dst_cc_num if mapping.dst_cc_num is not None else mapping.src_cc
            if mapping.src_channel == dst_ch and mapping.src_cc == dst_cc:
                return Response.error("Same channel and CC number — mapping has no effect")

        # Check for conflicting mappings (same source match)
        for existing in fe.get_mappings(conn_id):
            if existing.type != mapping.type:
                continue
            if existing.src_channel != mapping.src_channel:
                continue
            if mapping.type in (MappingType.CC_TO_CC,) and existing.src_cc == mapping.src_cc:
                return Response.error(f"A CC mapping for CC{mapping.src_cc} on this channel already exists")
            if mapping.type in (MappingType.NOTE_TO_CC, MappingType.NOTE_TO_CC_TOGGLE) and \
               existing.src_note == mapping.src_note:
                return Response.error(f"A note mapping for this note on this channel already exists")
            if mapping.type == MappingType.CHANNEL_MAP:
                return Response.error("A channel remap for this channel already exists")

        # Ensure connection is in userspace mode
        if not fe.has_filter(conn_id):
            # Remove direct ALSA subscription, create filtered connection
            try:
                engine._seq.unsubscribe(src_client, src_port, dst_client, dst_port)
            except OSError:
                pass
            fe.add_filter(src_client, src_port, dst_client, dst_port, MidiFilter())

        idx = fe.add_mapping(conn_id, mapping)
        config.set_mode("custom")
        await server.send_sse("connection-changed", {
            "action": "mapping-added", "id": conn_id,
        })
        return Response.json({"status": "added", "index": idx}, 201)

    @server.route("DELETE", "/api/mappings/", exact=False)
    async def api_delete_mapping(req: Request) -> Response:
        path = req.path_param("/api/mappings/")
        if not path:
            return Response.error("Missing connection ID")

        # Path: conn_id/index  e.g. "24:0-28:0/0"
        parts = path.rsplit("/", 1)
        if len(parts) != 2:
            return Response.error("Expected format: connection_id/mapping_index")

        conn_id = parts[0]
        try:
            index = int(parts[1])
        except ValueError:
            return Response.error("Invalid mapping index")

        fe = engine.filter_engine
        if not fe:
            return Response.error("Filter engine not available", 500)

        if not fe.remove_mapping(conn_id, index):
            return Response.not_found()

        # If no more mappings and filter is passthrough, switch back to direct
        fc = fe.filtered_connections.get(conn_id)
        if fc and not fc.needs_userspace:
            fe.remove_filter(conn_id)
            try:
                src, dst = conn_id.split("-")
                sc, sp = map(int, src.split(":"))
                dc, dp = map(int, dst.split(":"))
                engine._seq.subscribe(sc, sp, dc, dp)
            except (ValueError, OSError):
                pass

        config.set_mode("custom")
        await server.send_sse("connection-changed", {
            "action": "mapping-removed", "id": conn_id,
        })
        return Response.json({"status": "deleted"})

    # ================================================================
    # POST /api/connections/connect-all — restore all-to-all
    # ================================================================

    @server.route("POST", "/api/connections/connect-all")
    async def api_connect_all(req: Request) -> Response:
        engine.disconnect_all()
        engine._disconnected.clear()  # dict.clear()
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

        # Serialize current connections with stable IDs, filters, mappings
        registry = engine.device_registry
        fe = engine.filter_engine
        conns = []
        for c in engine.connections:
            conn_id = f"{c.src_client}:{c.src_port}-{c.dst_client}:{c.dst_port}"
            entry = {
                "src_client": c.src_client, "src_port": c.src_port,
                "dst_client": c.dst_client, "dst_port": c.dst_port,
            }
            src_info = registry.get_by_client(c.src_client)
            dst_info = registry.get_by_client(c.dst_client)
            if src_info:
                entry["src_stable_id"] = src_info.stable_id
            if dst_info:
                entry["dst_stable_id"] = dst_info.stable_id
            if fe:
                f = fe.get_filter(conn_id)
                if f:
                    entry["filter"] = f.to_dict()
                mappings = fe.get_mappings(conn_id)
                if mappings:
                    entry["mappings"] = [m.to_dict() for m in mappings]
            conns.append(entry)

        if not config.save_preset(name, conns):
            return Response.error("Too many presets (max 100)")

        # Also persist current device names
        config.data["device_names"] = registry.get_custom_names()
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

            # Apply preset connections using stable IDs
            from .midi_filter import MidiFilter as _MF, MidiMapping as _MM
            engine.disconnect_all()
            engine._disconnected.clear()
            registry = engine.device_registry
            fe = engine.filter_engine
            for c in preset.get("connections", []):
                try:
                    # Resolve stable IDs to current client IDs
                    src_stable = c.get("src_stable_id")
                    dst_stable = c.get("dst_stable_id")
                    if src_stable and dst_stable:
                        src_client = registry.client_for_stable_id(src_stable)
                        dst_client = registry.client_for_stable_id(dst_stable)
                    else:
                        src_client = c.get("src_client")
                        dst_client = c.get("dst_client")
                    if src_client is None or dst_client is None:
                        continue
                    sp, dp = c["src_port"], c["dst_port"]
                    conn = Connection(src_client, sp, dst_client, dp)
                    conn_id = f"{src_client}:{sp}-{dst_client}:{dp}"

                    # Check if needs userspace (filter/mappings)
                    filter_data = c.get("filter")
                    mappings_data = c.get("mappings", [])
                    needs_userspace = bool(mappings_data)
                    midi_filter = None
                    if filter_data:
                        midi_filter = _MF.from_dict(filter_data)
                        needs_userspace = needs_userspace or not midi_filter.is_passthrough

                    if needs_userspace and fe:
                        if midi_filter is None:
                            midi_filter = _MF()  # passthrough filter for mappings-only
                    if needs_userspace and fe and midi_filter:
                        fe.add_filter(src_client, sp, dst_client, dp, midi_filter)
                        for md in mappings_data:
                            try:
                                fe.add_mapping(conn_id, _MM.from_dict(md))
                            except (ValueError, KeyError):
                                pass
                    else:
                        engine._seq.subscribe(src_client, sp, dst_client, dp)
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
        registry = engine.device_registry
        conns = []
        for c in engine.connections:
            conn_id = f"{c.src_client}:{c.src_port}-{c.dst_client}:{c.dst_port}"
            entry = {
                "src_client": c.src_client, "src_port": c.src_port,
                "dst_client": c.dst_client, "dst_port": c.dst_port,
            }
            # Add stable IDs for persistence across reboots
            src_info = registry.get_by_client(c.src_client)
            dst_info = registry.get_by_client(c.dst_client)
            if src_info:
                entry["src_stable_id"] = src_info.stable_id
            if dst_info:
                entry["dst_stable_id"] = dst_info.stable_id
            if fe:
                f = fe.get_filter(conn_id)
                if f:
                    entry["filter"] = f.to_dict()
                mappings = fe.get_mappings(conn_id)
                if mappings:
                    entry["mappings"] = [m.to_dict() for m in mappings]
            conns.append(entry)
        config.set_connections(conns)

        # Save deliberately disconnected pairs with their filter/mapping config
        disconn = []
        for conn_id, saved_data in engine._disconnected.items():
            try:
                src, dst = conn_id.split("-")
                sc, sp = map(int, src.split(":"))
                dc, dp = map(int, dst.split(":"))
            except (ValueError, IndexError):
                continue
            entry = {"src_port": sp, "dst_port": dp}
            src_info = registry.get_by_client(sc)
            dst_info = registry.get_by_client(dc)
            if src_info:
                entry["src_stable_id"] = src_info.stable_id
            if dst_info:
                entry["dst_stable_id"] = dst_info.stable_id
            if saved_data:
                entry.update(saved_data)
            disconn.append(entry)
        config.data["disconnected"] = disconn

        # Persist all device names (custom + ALSA defaults) by stable ID
        names = dict(registry.get_custom_names())
        for dev in engine.devices:
            info = registry.get_by_client(dev.client_id)
            if info and info.stable_id not in names:
                names[info.stable_id] = info.name
        config.data["device_names"] = names

        if config.save():
            return Response.json({"status": "saved"})
        return Response.error("Failed to save config", 500)

    # ================================================================
    # POST /api/system/reboot — reboot the Pi
    # ================================================================

    @server.route("POST", "/api/system/reboot")
    async def api_reboot(req: Request) -> Response:
        import subprocess
        asyncio.get_event_loop().call_later(1, lambda: subprocess.Popen(["sudo", "reboot"]))
        return Response.json({"status": "rebooting"})

    # ================================================================
    # GET /api/system/update-check — check for newer release on GitHub
    # ================================================================

    @server.route("GET", "/api/system/update-check")
    async def api_update_check(req: Request) -> Response:
        import urllib.request
        import json as _json

        loop = asyncio.get_event_loop()

        def _check():
            url = "https://api.github.com/repos/wamdam/raspimidihub/releases/latest"
            rq = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(rq, timeout=10) as resp:
                data = _json.loads(resp.read())
            tag = data.get("tag_name", "")
            latest = tag.lstrip("v")
            body = data.get("body", "")
            # Find the .deb asset URL
            deb_url = ""
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name.startswith("raspimidihub_") and name.endswith("_all.deb"):
                    deb_url = asset.get("browser_download_url", "")
                    break
            return {"current": __version__, "latest": latest, "changelog": body,
                    "deb_url": deb_url, "update_available": latest != __version__}

        try:
            result = await loop.run_in_executor(None, _check)
            return Response.json(result)
        except Exception as e:
            log.warning("Update check failed: %s", e)
            return Response.json({"current": __version__, "latest": __version__,
                                  "changelog": "", "deb_url": "",
                                  "update_available": False, "offline": True})

    # ================================================================
    # POST /api/system/update — download and install latest .deb
    # ================================================================

    UPDATE_STATUS_FILE = Path("/run/raspimidihub/update-status")
    UPDATE_SCRIPT = Path("/usr/lib/raspimidihub/update.sh")

    @server.route("POST", "/api/system/update")
    async def api_update(req: Request) -> Response:
        import subprocess

        data = req.json
        deb_url = data.get("deb_url", "")
        if not deb_url or "github.com" not in deb_url:
            return Response.error("Invalid download URL")

        if not UPDATE_SCRIPT.is_file():
            return Response.error("Update script not found", 500)

        # Launch external updater script (survives service restart)
        subprocess.Popen(
            [str(UPDATE_SCRIPT), deb_url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return Response.json({"status": "started"})

    @server.route("GET", "/api/system/update-status")
    async def api_update_status(req: Request) -> Response:
        try:
            status = UPDATE_STATUS_FILE.read_text().strip()
        except FileNotFoundError:
            status = ""
        return Response.json({"status": status, "version": __version__})

    # ================================================================
    # POST /api/config/load — reload saved config from disk
    # ================================================================

    @server.route("POST", "/api/config/load")
    async def api_load_config(req: Request) -> Response:
        from .__main__ import _apply_saved_config

        config.load()
        if config.mode != "custom" or not config.connections:
            # No custom config — fall back to all-to-all
            engine.disconnect_all()
            engine.scan_devices()
            engine.connect_all()
            engine._update_monitor_subscriptions()
            config.set_mode("all-to-all")
        else:
            engine.disconnect_all()
            _apply_saved_config(engine, config)
            engine._update_monitor_subscriptions()

        await server.send_sse("connection-changed", {"action": "config-loaded"})
        return Response.json({"status": "loaded"})

    # ================================================================
    # GET /api/config/export — download full config as JSON
    # ================================================================

    @server.route("GET", "/api/config/export")
    async def api_export_config(req: Request) -> Response:
        import json as _json
        return Response(
            status=200,
            body=_json.dumps(config.data, indent=2).encode(),
            content_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="raspimidihub-config.json"',
            },
        )

    # ================================================================
    # POST /api/config/import — upload and apply a full config JSON
    # ================================================================

    @server.route("POST", "/api/config/import")
    async def api_import_config(req: Request) -> Response:
        from .__main__ import _apply_saved_config

        data = req.json
        if not isinstance(data, dict) or "version" not in data:
            return Response.error("Invalid config format")

        config._data = data
        config.save()

        # Apply the imported config
        if config.mode == "custom":
            engine.disconnect_all()
            _apply_saved_config(engine, config)
            engine._update_monitor_subscriptions()
        else:
            engine.disconnect_all()
            engine.scan_devices()
            engine.connect_all()
            engine._update_monitor_subscriptions()

        # Reload device names
        device_names = config.data.get("device_names", {})
        if device_names:
            engine.device_registry.load_custom_names(device_names)

        await server.send_sse("connection-changed", {"action": "config-loaded"})
        return Response.json({"status": "imported"})

    # ================================================================
    # Network API
    # ================================================================

    from .wifi import get_all_interfaces, configure_interface

    @server.route("GET", "/api/network")
    async def api_network(req: Request) -> Response:
        loop = asyncio.get_event_loop()
        interfaces = await loop.run_in_executor(None, get_all_interfaces)
        return Response.json(interfaces)

    @server.route("POST", "/api/network/", exact=False)
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

        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, configure_interface,
                                         iface, method, address, netmask, gateway)
        if ok:
            return Response.json({"status": "configured", "interface": iface})
        return Response.error("Failed to configure interface", 500)

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

        return Response.json({"status": "ap started", "ssid": wifi.ssid, "ip": wifi.ip})

    @server.route("POST", "/api/wifi/client")
    async def api_wifi_client(req: Request) -> Response:
        data = req.json
        ssid = data.get("ssid", "")
        password = data.get("password", "")
        if not ssid:
            return Response.error("SSID required")

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
            return Response.error("Connection failed, fell back to AP mode", 502)

    @server.route("GET", "/api/wifi/scan")
    async def api_wifi_scan(req: Request) -> Response:
        loop = asyncio.get_event_loop()
        networks = await loop.run_in_executor(None, wifi.scan_networks)
        return Response.json(networks)
