"""Routing connection + MIDI mapping routes. Moved verbatim from the
old api.py."""

import logging

from ..midi_engine import Connection
from ..midi_filter import (
    ALL_CHANNELS,
    ALL_MSG_TYPES,
    MidiFilter,
    MidiMapping,
    validate_new_mapping,
)
from ..web import Request, Response
from ._conn import _get_filter_data, _matches_saved, _parse_conn_id, _restore_userspace
from ._ctx import ApiContext

log = logging.getLogger(__name__)


def register_connections(ctx: ApiContext) -> None:
    """Register the /api/connections and /api/mappings routes."""
    server = ctx.server
    engine = ctx.engine
    config = ctx.config

    # ================================================================
    # GET /api/connections — list active + offline connections
    # ================================================================

    @server.route("GET", "/api/connections", summary="List active and saved-offline routing connections, including filter/mapping state.")
    async def api_connections(req: Request) -> Response:
        conns = []
        fe = engine.filter_engine
        for c in sorted(engine.connections,
                        key=lambda c: (c.src_client, c.src_port, c.dst_client, c.dst_port)):
            conn_id = f"{c.src_client}:{c.src_port}-{c.dst_client}:{c.dst_port}"
            entry = {
                "id": conn_id,
                "src_client": c.src_client, "src_port": c.src_port,
                "dst_client": c.dst_client, "dst_port": c.dst_port,
                "filtered": False,
            }
            fd = _get_filter_data(fe, conn_id)
            entry.update(fd)
            if "filter" in fd or "mappings" in fd:
                entry["filtered"] = True
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

    @server.route("POST", "/api/connections", exact=True, summary="Create a routing connection (live client:port, or a saved offline stable-id edge).")
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
            if not any(_matches_saved(c, src_sid, dst_sid, src_port, dst_port)
                       for c in config.connections):
                config.connections.append(entry)
                config.set_connections(config.connections)
                await config.asave()
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

        # Check for saved filter/mapping data from previous disconnect
        saved = engine._disconnected.pop(
            f"{conn.src_client}:{conn.src_port}-{conn.dst_client}:{conn.dst_port}", {})

        # Time the synchronous connect work (how long it blocks the loop)
        # so a REAL hardware cable-add self-measures in /api/stats — the
        # perf harness can only synthesise cheap plugin↔plugin connects.
        from .. import perf_stats
        try:
            with perf_stats.time_op("op_add_connection"):
                _restore_userspace(engine, engine.filter_engine, conn, saved)
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
        engine.mark_dirty()
        return Response.json({"status": "created"}, 201)

    # ================================================================
    # DELETE /api/connections/{id} — remove a connection
    # ================================================================

    @server.route("DELETE", "/api/connections/", exact=False, summary="Remove a connection (or all if no id); preserves its filter/mapping for later reconnect.")
    async def api_delete_connection(req: Request) -> Response:
        conn_id = req.path_param("/api/connections/")
        if not conn_id:
            # DELETE /api/connections — disconnect all
            engine.disconnect_all()
            config.set_mode("custom")
            engine.mark_dirty()
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
            match = lambda c: _matches_saved(c, src_sid, dst_sid, src_port, dst_port)
            saved_conn = next((c for c in config.connections + config.disconnected if match(c)), None)
            # Remove from saved connections
            config.data["connections"] = [c for c in config.connections if not match(c)]
            disconn_entry = {
                "src_stable_id": src_sid, "src_port": src_port,
                "dst_stable_id": dst_sid, "dst_port": dst_port,
            }
            if saved_conn:
                for k in ("filter", "mappings"):
                    if saved_conn.get(k):
                        disconn_entry[k] = saved_conn[k]
            # Add to disconnected if not already there
            if not any(match(c) for c in config.disconnected):
                config.data.setdefault("disconnected", []).append(disconn_entry)
            await config.asave()
            config.set_mode("custom")
            await server.send_sse("connection-changed", {"action": "deleted", "id": conn_id})
            return Response.json({"status": "deleted"})

        try:
            src_client, src_port, dst_client, dst_port = _parse_conn_id(conn_id)
        except (ValueError, IndexError):
            return Response.error("Invalid connection ID format")

        conn = Connection(src_client, src_port, dst_client, dst_port)

        # Save filter/mapping data before removing
        fe = engine.filter_engine
        saved_data = _get_filter_data(fe, conn_id)
        if fe and fe.has_filter(conn_id):
            fe.remove_filter(conn_id)

        # Release any held notes on this edge before tearing down the
        # subscription so the destination doesn't end up with stuck notes.
        engine.release_edge_notes(conn)

        try:
            engine._seq.unsubscribe(conn.src_client, conn.src_port,
                                    conn.dst_client, conn.dst_port)
        except OSError:
            pass
        engine._connections.discard(conn)

        # Track as deliberately disconnected with saved config
        engine._disconnected[conn_id] = saved_data

        config.set_mode("custom")
        engine.mark_dirty()
        await server.send_sse("connection-changed", {
            "action": "deleted",
            "id": conn_id,
        })
        return Response.json({"status": "deleted"})

    # ================================================================
    # PATCH /api/connections/{id} — update filter on a connection
    # ================================================================

    @server.route("PATCH", "/api/connections/", exact=False, summary="Update a connection's channel / message-type filter (switches to userspace routing as needed).")
    async def api_patch_connection(req: Request) -> Response:
        conn_id = req.path_param("/api/connections/")
        if not conn_id:
            return Response.error("Missing connection ID")

        try:
            src_client, src_port, dst_client, dst_port = _parse_conn_id(conn_id)
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
                try:
                    fe.add_filter(src_client, src_port, dst_client, dst_port, midi_filter)
                except OSError:
                    # Port creation failed — restore the direct
                    # subscription so the connection keeps flowing, and
                    # tell the UI instead of silently dropping the edit.
                    log.exception("add_filter failed for %s", conn_id)
                    engine._seq.subscribe(src_client, src_port, dst_client, dst_port)
                    return Response.error("Failed to apply filter", 500)
            else:
                fe.update_filter(conn_id, midi_filter)

        config.set_mode("custom")
        await server.send_sse("connection-changed", {
            "action": "filter-updated",
            "id": conn_id,
            "filter": midi_filter.to_dict(),
        })
        engine.mark_dirty()
        return Response.json({"status": "updated", "filter": midi_filter.to_dict()})

    # ================================================================
    # GET/POST/DELETE /api/connections/{id}/mappings — mapping CRUD
    # ================================================================

    @server.route("GET", "/api/mappings/", exact=False, summary="List the MIDI mappings on a connection.")
    async def api_get_mappings(req: Request) -> Response:
        conn_id = req.path_param("/api/mappings/")
        if not conn_id:
            return Response.error("Missing connection ID")

        fe = engine.filter_engine
        if not fe:
            return Response.error("Filter engine not available", 500)

        mappings = fe.get_mappings(conn_id)
        return Response.json([m.to_dict() for m in mappings])

    @server.route("POST", "/api/mappings/", exact=False, summary="Add a MIDI mapping to a connection (converts it to userspace-filtered if needed).")
    async def api_add_mapping(req: Request) -> Response:
        conn_id = req.path_param("/api/mappings/")
        if not conn_id:
            return Response.error("Missing connection ID")

        try:
            src_client, src_port, dst_client, dst_port = _parse_conn_id(conn_id)
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

        err = validate_new_mapping(fe.get_mappings(conn_id), mapping)
        if err:
            return Response.error(err)

        # Ensure connection is in userspace mode. Converting a direct
        # ALSA link to a userspace-filtered one (new ports + routing
        # thread) is the heavy part — time it so a real filter change
        # self-measures its loop-blocking cost in /api/stats.
        from .. import perf_stats
        with perf_stats.time_op("op_change_filter"):
            if not fe.has_filter(conn_id):
                # Remove direct ALSA subscription, create filtered connection
                try:
                    engine._seq.unsubscribe(src_client, src_port, dst_client, dst_port)
                except OSError:
                    pass
                fe.add_filter(src_client, src_port, dst_client, dst_port, MidiFilter())
            idx = fe.add_mapping(conn_id, mapping)
        config.set_mode("custom")
        engine.mark_dirty()
        await server.send_sse("connection-changed", {
            "action": "mapping-added", "id": conn_id,
        })
        return Response.json({"status": "added", "index": idx}, 201)

    @server.route("DELETE", "/api/mappings/", exact=False, summary="Remove a mapping (path conn_id/index) from a connection.")
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
                sc, sp, dc, dp = _parse_conn_id(conn_id)
                engine._seq.subscribe(sc, sp, dc, dp)
            except (ValueError, OSError):
                pass

        config.set_mode("custom")
        engine.mark_dirty()
        await server.send_sse("connection-changed", {
            "action": "mapping-removed", "id": conn_id,
        })
        return Response.json({"status": "deleted"})

    # ================================================================
    # POST /api/connections/connect-all — restore all-to-all
    # ================================================================

    @server.route("POST", "/api/connections/connect-all", summary="Reset routing to all-to-all: reconnect every source to every destination.")
    async def api_connect_all(req: Request) -> Response:
        engine.disconnect_all()
        engine._disconnected.clear()  # dict.clear()
        engine.scan_devices()
        conns = engine.connect_all()
        config.set_mode("all-to-all")
        engine.mark_dirty()
        await server.send_sse("connection-changed", {"action": "connected-all"})
        return Response.json({"status": "connected", "count": len(conns)})

