"""MIDI device routes: list, delete, and per-device actions
(rename, rename-port, force-midi1, identify, clock-source, send).
Moved verbatim from the old api.py."""

import logging

from ..web import Request, Response
from ._ctx import ApiContext

log = logging.getLogger(__name__)


def register_devices(ctx: ApiContext) -> None:
    """Register the /api/devices routes."""
    server = ctx.server
    engine = ctx.engine
    config = ctx.config
    network_midi = ctx.network_midi

    # ================================================================
    # GET /api/devices — list MIDI devices
    # ================================================================

    @server.route("GET", "/api/devices", summary="List MIDI devices and ports (online plus saved-offline), with names, flags, and plugin/export info.")
    async def api_devices(req: Request) -> Response:
        # Use the CACHED device list, not a fresh scan_devices() — a full
        # ALSA re-enumeration here is ~150 ms on a busy rig and the UI
        # fetches /api/devices on every connection-changed SSE, so a
        # scan-per-fetch stalled the loop (and jittered MIDI) on every
        # cable add. The cache is kept current by hotplug-driven rescans.
        devices = engine.devices
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
            if dev.is_ump:
                # force_midi1 masks the hub's *use* of the capability
                # (badge, hi-res paths, MIDI-CI); topology stays visible.
                forced = bool(info and info.stable_id
                              in config.midi2.get("force_midi1", []))
                entry["midi2"] = {
                    "protocol": dev.midi2_protocol and not forced,
                    "capable": dev.midi2_protocol,
                    "forced_midi1": forced,
                    "endpoint_name": dev.endpoint_name,
                    "product_id": dev.product_id,
                    "function_blocks": dev.function_blocks,
                }
            if info:
                ci = engine.ci_info(info.stable_id)
                if ci:
                    entry["midi_ci"] = ci
                entry["stable_id"] = info.stable_id
                entry["vid"] = info.vid
                entry["pid"] = info.pid
                entry["usb_path"] = info.usb_path
                entry["is_plugin"] = info.is_plugin
                if info.is_bluetooth:
                    entry["is_bluetooth"] = True
                # Hardware only — plugins never feed the bus from
                # this gate (their feeds_clock_bus class attribute
                # already governs them).
                if not info.is_plugin:
                    entry["clock_blocked"] = registry.is_clock_blocked(info.stable_id)
                if info.is_network:
                    entry["is_network"] = True
                    entry["remote_hub"] = info.remote_hub
                else:
                    entry["exported"] = (
                        info.stable_id in config.network_midi.get("exported", []))
            entry["online"] = True
            # Add plugin instance info if this is a virtual device
            if info and info.is_plugin and engine._plugin_host:
                # stable_id is "plugin-{instance_id}"
                inst_id = info.stable_id.removeprefix("plugin-")
                inst_data = engine._plugin_host.get_instance_data(inst_id)
                if inst_data:
                    entry["plugin_type"] = inst_data["type"]
                    entry["plugin_instance_id"] = inst_id
                    entry["plugin_type_name"] = inst_data.get("name", inst_data["type"])
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
            offline_entry = {
                "client_id": None,
                "stable_id": sid,
                "name": name,
                "default_name": name,
                "ports": ports,
                "online": False,
                # Carry the BT flag through to offline entries so the
                # matrix's "Reconnect" context-menu item shows up for
                # paired-but-disconnected BLE-MIDI devices.
                "is_bluetooth": sid.startswith("bt-"),
                # Same idea for mirrored network devices (peer hub
                # offline): the matrix tints + groups them by prefix.
                "is_network": sid.startswith("net-"),
            }
            if offline_entry["is_network"] and network_midi:
                offline_entry["remote_hub"] = \
                    network_midi.hub_name_for_stable_id(sid)
            result.append(offline_entry)

        return Response.json(result)

    # ================================================================
    # DELETE /api/devices/{stable_id} — remove an offline device from saved config
    # ================================================================

    @server.route("DELETE", "/api/devices/", exact=False, summary="Remove a saved offline device and its connections/name from the config.")
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

        await config.asave()
        await server.send_sse("connection-changed", {"action": "device-removed"})
        return Response.json({"status": "removed"})

    # ================================================================
    # POST /api/devices/{client_id}/rename — rename a device
    # ================================================================

    @server.route("POST", "/api/devices/", exact=False, summary="Per-device actions: rename, rename-port, clock-source toggle, force-midi1 toggle, identify (MIDI-CI), or send a test MIDI message.")
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
            await config.asave()
            # Also bust the plugin-instances list cache — the resolved
            # display_name comes from custom_names so a rename here
            # changes what /api/plugins/instances returns.
            ctx.invalidate_instances_cache()
            # plugin-changed SSE so subscribers (Settings → Plugin
            # Control Mappings, the bottom-nav controller picker, ...)
            # refresh their cached label. Plugin renames go through
            # this path, not the /api/plugins/instances PATCH route.
            if info.is_plugin:
                await server.send_sse(
                    "plugin-changed",
                    {"instance_id": info.stable_id, "client_id": client_id})
            return Response.json({"status": "renamed", "name": name})

        # POST /api/devices/{client_id}/force-midi1 — treat a MIDI 2.0
        # capable device as MIDI 1.0 (escape hatch for devices that
        # misbehave under UMP). Body: {enabled: bool}. Persisted in
        # config.midi2.force_midi1 by stable_id.
        if path.endswith("/force-midi1"):
            try:
                client_id = int(path[:-len("/force-midi1")])
            except ValueError:
                return Response.error("Invalid client ID")
            data = req.json
            enabled = bool(data.get("enabled", True))
            info = engine.device_registry.get_by_client(client_id)
            if info is None:
                return Response.not_found()
            forced = set(config.midi2.get("force_midi1", []))
            if enabled:
                forced.add(info.stable_id)
            else:
                forced.discard(info.stable_id)
            config.data.setdefault("midi2", {})["force_midi1"] = sorted(forced)
            await config.asave()
            await server.send_sse("device-connected", {"client_id": client_id})
            return Response.json({"status": "ok", "forced_midi1": enabled})

        # POST /api/devices/{client_id}/identify — re-run MIDI-CI
        # discovery against this device (results arrive via the usual
        # device refresh SSE once the device answers).
        if path.endswith("/identify"):
            try:
                client_id = int(path[:-len("/identify")])
            except ValueError:
                return Response.error("Invalid client ID")
            info = engine.device_registry.get_by_client(client_id)
            if info is None:
                return Response.not_found()
            engine.reidentify(info.stable_id)
            return Response.json({"status": "identifying"})

        # POST /api/devices/{client_id}/clock-source — toggle whether
        # this device's MIDI Clock / Start / Stop feeds the global
        # ClockBus. Body: {enabled: bool}. enabled=False adds the
        # device's stable_id to the engine's clock-blocked set;
        # enabled=True removes it. Persisted as `device_clock_blocked`
        # so the choice survives reboots.
        if path.endswith("/clock-source"):
            try:
                client_id = int(path[:-len("/clock-source")])
            except ValueError:
                return Response.error("Invalid client ID")

            data = req.json
            enabled = bool(data.get("enabled", True))

            registry = engine.device_registry
            info = registry.get_by_client(client_id)
            if info is None:
                return Response.not_found()
            if info.is_plugin:
                return Response.error(
                    "Plugins gate clock via feeds_clock_bus, not this toggle", 400)

            registry.set_clock_blocked(info.stable_id, blocked=not enabled)
            config.data["device_clock_blocked"] = registry.get_clock_blocked()
            await config.asave()
            engine.mark_dirty()
            return Response.json({
                "status": "ok",
                "stable_id": info.stable_id,
                "clock_blocked": not enabled,
            })

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
            await config.asave()
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
                from ..alsa_seq import MidiEventType, SndSeqEvent
                ev = SndSeqEvent()
                ev.type = MidiEventType.CONTROLLER
                ev.data.control.channel = channel
                ev.data.control.param = cc
                ev.data.control.value = value
                engine._seq.send_event_coalesced(ev, client_id, port)
                return Response.json({"status": "sent", "type": "cc"})
            else:
                return Response.error("Unknown type. Use: note_on, note_off, cc")

        return Response.not_found()

