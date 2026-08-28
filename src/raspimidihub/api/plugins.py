"""Plugin instance + MIDI-Learn (CC binding) routes. Moved verbatim
from the old api.py."""

import asyncio
import json
import logging
import time as _time

from ..plugin_api import LayoutGrid, get_all_params, get_default_cc_map
from ..web import Request, Response
from ._ctx import ApiContext

log = logging.getLogger(__name__)


def register_plugins(ctx: ApiContext) -> None:
    """Register the /api/plugins and /api/cc-learn routes.

    The list endpoint (below) keeps a 500 ms TTL cache for the light
    instance rows. The contents only change on plugin add / remove /
    rename — but those mutations explicitly invalidate the cache (via
    ctx.invalidate_instances_cache) so the dropdown always reflects the
    latest state immediately. The cache exists to protect the server
    from a buggy / stale-cached frontend re-fetching /plugins/instances
    on every render (we've been bitten by that loop). Pre-encoded bytes
    mean cache hits skip json.dumps too."""
    server = ctx.server
    engine = ctx.engine
    cc_learn_armed = ctx.cc_learn_armed
    instances_cache = ctx.instances_cache

    # ================================================================
    # PLUGINS — Virtual Instruments
    # ================================================================

    @server.route("GET", "/api/plugins", summary="List available plugin types.")
    async def api_plugins_list(req: Request) -> Response:
        """List available plugin types."""
        if not engine._plugin_host:
            return Response.json({})
        return Response.json(engine._plugin_host.list_types())

    @server.route("POST", "/api/cc-learn/start", summary="Arm MIDI Learn for one plugin (instance, param).")
    async def api_cc_learn_start(req: Request) -> Response:
        """Arm MIDI Learn for one (instance, param). Body:
        {instance_id, param}. Returns {learn_id}. The next inbound
        CONTROLLER event on any routed source fires SSE
        cc_learn_result with {learn_id, ch, cc}. Auto-cancels after
        30 s with cc_learn_timeout."""
        if not engine._plugin_host:
            return Response.error("Plugin host not available", 503)
        body = req.json or {}
        instance_id = body.get("instance_id", "")
        param = body.get("param", "")
        if not instance_id or not param:
            return Response.error("instance_id and param required", 400)
        if engine._plugin_host.get_instance(instance_id) is None:
            return Response.error("Instance not found", 404)
        import uuid
        learn_id = uuid.uuid4().hex
        entry = {"instance_id": instance_id, "param": param, "timeout_task": None}

        async def _timeout() -> None:
            try:
                await asyncio.sleep(30.0)
            except asyncio.CancelledError:
                return
            if cc_learn_armed.pop(learn_id, None) is not None:
                await server.send_sse("cc_learn_timeout", {"learn_id": learn_id})

        entry["timeout_task"] = asyncio.create_task(_timeout())
        cc_learn_armed[learn_id] = entry
        return Response.json({"learn_id": learn_id})

    @server.route("POST", "/api/cc-learn/cancel", summary="Cancel an armed MIDI Learn.")
    async def api_cc_learn_cancel(req: Request) -> Response:
        """Cancel an armed Learn. Body: {learn_id}."""
        body = req.json or {}
        learn_id = body.get("learn_id", "")
        entry = cc_learn_armed.pop(learn_id, None)
        if entry is None:
            return Response.json({"status": "not-armed"})
        if entry.get("timeout_task"):
            entry["timeout_task"].cancel()
        return Response.json({"status": "cancelled"})

    @server.route("GET", "/api/plugins/cc-mappings", summary="Flat list of every per-instance CC binding across all plugins.")
    async def api_plugins_cc_mappings(req: Request) -> Response:
        """Flat list of every per-instance CC binding across all plugins.

        Powers the Settings → Plugin Control Mappings sub-page (and any
        client-side collision lookup). Returns one row per binding
        from BOTH systems:

          - `kind: "param"` — a plugin param's cc_map entry
            (Arpeggiator's Rate, CC LFO's Freq, ...). ch can be null
            ("any channel"); cc can be null (cleared / no binding).
          - `kind: "cell"` — a controller cell's symmetric (channel,
            cc). Non-XY cells emit one row; XY-pad cells emit two
            (axis = "x" and axis = "y"). Effective binding =
            user override from cell_bindings, falling back to the
            LayoutCell's factory default.

        The frontend dispatches click-to-edit on `kind` — cell rows
        open the CellBinding popup, param rows open CcBinding."""
        if not engine._plugin_host:
            return Response.json({"mappings": []})
        # Resolve user-facing names via the device registry (same path
        # /api/plugins/instances uses). Plugin renames live in
        # custom_names, not in PluginInstance.name, so without this
        # the table would freeze at spawn-time labels.
        registry = engine.device_registry
        rows = []
        for inst in engine._plugin_host.get_instances():
            cls = type(inst.plugin)
            label_for = {p.name: p.label for p in get_all_params(cls.params)
                         if getattr(p, "name", None)}
            display_name = inst.name
            client_id = inst.alsa_client.client_id if inst.alsa_client else None
            if client_id is not None:
                info = registry.get_by_client(client_id)
                if info is not None and info.custom_name:
                    display_name = info.custom_name
            # 1) Plugin-param rows (cc_map).
            for param, binding in inst.plugin.cc_map.items():
                rows.append({
                    "kind": "param",
                    "instance_id": inst.id,
                    "instance_name": display_name,
                    "plugin_type": inst.plugin_type,
                    "param": param,
                    "param_label": label_for.get(param, param),
                    "ch": binding.get("ch"),
                    "cc": binding.get("cc"),
                })
            # 2) Controller-cell rows. Walk every LayoutGrid in the
            #    schema; for each cell, compute the effective binding
            #    from cell_bindings overrides + the LayoutCell factory
            #    defaults. XY pads expand into two rows (x / y).
            for top in cls.params:
                grid = top if isinstance(top, LayoutGrid) else None
                if grid is None or not grid.bindings_param:
                    continue
                cell_bindings = inst.plugin._param_values.get(
                    grid.bindings_param) or {}
                cell_labels = (inst.plugin._param_values.get(
                    grid.labels_param) if grid.labels_param else {}) or {}
                for cell in grid.cells:
                    cname = cell.param.name
                    ov = cell_bindings.get(cname) or {}
                    label = cell_labels.get(cname) or cell.param.label or cname
                    is_xy = cell.param.__class__.__name__ == "XYPad"
                    if is_xy:
                        fx_ch = cell.channel if cell.channel is not None else 0
                        fx_cc = cell.cc if cell.cc is not None else 0
                        fy_ch = cell.channel_y if cell.channel_y is not None else fx_ch
                        fy_cc = cell.cc_y if cell.cc_y is not None else 0
                        x_ch = ov.get("channel") if ov.get("channel") is not None else fx_ch
                        x_cc = ov.get("cc") if ov.get("cc") is not None else fx_cc
                        y_ch = ov.get("channel_y") if ov.get("channel_y") is not None else fy_ch
                        y_cc = ov.get("cc_y") if ov.get("cc_y") is not None else fy_cc
                        rows.append({
                            "kind": "cell",
                            "axis": "x",
                            "instance_id": inst.id,
                            "instance_name": display_name,
                            "plugin_type": inst.plugin_type,
                            "param": cname,
                            "param_label": f"{label} (X)",
                            "ch": x_ch,
                            "cc": x_cc,
                        })
                        rows.append({
                            "kind": "cell",
                            "axis": "y",
                            "instance_id": inst.id,
                            "instance_name": display_name,
                            "plugin_type": inst.plugin_type,
                            "param": cname,
                            "param_label": f"{label} (Y)",
                            "ch": y_ch,
                            "cc": y_cc,
                        })
                    else:
                        f_ch = cell.channel if cell.channel is not None else 0
                        f_cc = cell.cc if cell.cc is not None else 0
                        cur_ch = ov.get("channel") if ov.get("channel") is not None else f_ch
                        cur_cc = ov.get("cc") if ov.get("cc") is not None else f_cc
                        rows.append({
                            "kind": "cell",
                            "instance_id": inst.id,
                            "instance_name": display_name,
                            "plugin_type": inst.plugin_type,
                            "param": cname,
                            "param_label": label,
                            "ch": cur_ch,
                            "cc": cur_cc,
                        })
        return Response.json({"mappings": rows})

    @server.route("GET", "/api/plugins/icon/", exact=False, summary="Serve a plugin type's icon.svg.")
    async def api_plugin_icon(req: Request) -> Response:
        """Serve a plugin's icon.svg."""
        plugin_type = req.path.split("/api/plugins/icon/")[1].rstrip("/")
        if not engine._plugin_host or not plugin_type:
            return Response.not_found()
        icon_path = engine._plugin_host._plugins_dir / plugin_type / "icon.svg"
        if not icon_path.is_file():
            return Response.not_found()
        try:
            svg = icon_path.read_text()
            return Response(status=200, body=svg.encode(), content_type="image/svg+xml")
        except OSError:
            return Response.not_found()

    @server.route("GET", "/api/plugins/instances", summary="List running plugin instances (light rows).")
    async def api_plugins_instances(req: Request) -> Response:
        """List running plugin instances. Returns a *light* row per
        instance (id, type, name, status) — full data including
        params_schema is only ever needed for the currently selected
        one, fetched via /api/plugins/instances/<id>. The full payload
        used to be ~kB per Controller; with 4 controllers and a re-
        rendering frontend, listing them was the dominant CPU cost on
        the asyncio loop."""
        if not engine._plugin_host:
            return Response.json([])
        now = _time.monotonic()
        if instances_cache["body"] is not None and now - instances_cache["ts"] < 0.5:
            return Response(
                status=200, body=instances_cache["body"],
                content_type="application/json",
            )
        # Resolve user-facing name via the device registry's custom_names.
        # Plugin instance.name is just the spawn-time default and isn't
        # persisted; renames go through device_names (keyed by stable_id)
        # so that's the source of truth for "what the user calls this".
        registry = engine.device_registry
        types = engine._plugin_host._plugin_types
        rows = []
        for inst in engine._plugin_host.get_instances():
            display_name = inst.name
            client_id = inst.alsa_client.client_id if inst.alsa_client else None
            if client_id is not None:
                info = registry.get_by_client(client_id)
                if info is not None and info.custom_name:
                    display_name = info.custom_name
            cls = types.get(inst.plugin_type)
            rows.append({
                "id": inst.id,
                "type": inst.plugin_type,
                "name": display_name,
                "status": "crashed" if inst.crashed else ("running" if inst.running else "stopped"),
                # Surface kind drives which top-level UI panel hosts the
                # instance (Controller / Play / matrix-only). None
                # serialises to JSON null. See PluginBase.SURFACE_KIND.
                "kind": getattr(cls, "SURFACE_KIND", None) if cls else None,
            })
        body = json.dumps(rows).encode()
        instances_cache["body"] = body
        instances_cache["ts"] = now
        return Response(status=200, body=body, content_type="application/json")

    @server.route("POST", "/api/plugins/instances", summary="Create a plugin instance. Body: {type, name?}.")
    async def api_plugins_create(req: Request) -> Response:
        """Create a new plugin instance. Body: {type, name?}"""
        if not engine._plugin_host:
            return Response.error("Plugin host not available", 503)
        body = req.json
        plugin_type = body.get("type", "")
        name = body.get("name", "")
        try:
            loop = asyncio.get_running_loop()
            instance = await loop.run_in_executor(
                None, engine._plugin_host.create_instance, plugin_type, name)
        except ValueError as e:
            return Response.error(str(e), 400)
        except Exception as e:
            return Response.error(f"Failed to create instance: {e}", 500)

        # Register the new ALSA client without tearing down existing
        # subscriptions — keeps clock and MIDI flowing through the
        # other plugins. Incremental: add just this client (no full ALSA
        # re-enumeration / bluetoothctl / sysfs), so it doesn't stall the
        # loop or delay a received master clock (~34ms before).
        engine.handle_plugin_added(new_client_id=instance.alsa_client.client_id
                                   if instance.alsa_client else None)

        ctx.invalidate_instances_cache()
        engine.mark_dirty()
        await server.send_sse("plugin-changed", {"instance_id": instance.id})
        data = engine._plugin_host.get_instance_data(instance.id)
        return Response.json(data, status=201)

    @server.route("POST", "/api/plugins/instances/", exact=False, summary="POST a sub-resource on an instance (.../sysex streams a raw .syx out the OUT port).")
    async def api_plugins_instance_post(req: Request) -> Response:
        """POST sub-resources on a plugin instance. Currently just
        `.../sysex` — body is the raw .syx payload, gets streamed out
        the OUT port via send_sysex() (chunked + paced). Bytes are
        not persisted; one upload = one send."""
        # Path format: /api/plugins/instances/<id>/<action>
        suffix = req.path[len("/api/plugins/instances/"):].strip("/")
        parts = suffix.split("/")
        if len(parts) != 2 or parts[1] != "sysex":
            return Response.error("Not found", 404)
        instance_id = parts[0]
        if not engine._plugin_host:
            return Response.error("Plugin host not available", 503)
        instance = engine._plugin_host.get_instance(instance_id)
        if instance is None:
            return Response.error("Instance not found", 404)
        payload = req.body
        if not payload:
            return Response.error("Empty payload", 400)
        # Run the chunked send off the asyncio loop — large dumps with
        # 5ms gaps between 256-byte chunks can take ~1s for a 50KB
        # bank, which would otherwise stall every other request.
        import time as _t
        t0 = _t.monotonic()
        loop = asyncio.get_running_loop()
        sent = await loop.run_in_executor(
            None, instance.plugin.send_sysex, payload)
        elapsed_ms = (_t.monotonic() - t0) * 1000.0
        return Response.json({"sent": sent, "ms": round(elapsed_ms, 1)})

    @server.route("GET", "/api/plugins/instances/", exact=False, summary="Get one plugin instance's config and params.")
    async def api_plugins_instance_get(req: Request) -> Response:
        """Get a single plugin instance config + params."""
        if not engine._plugin_host:
            return Response.error("Plugin host not available", 503)
        instance_id = req.path.split("/api/plugins/instances/")[1].rstrip("/")
        data = engine._plugin_host.get_instance_data(instance_id)
        if data is None:
            return Response.error("Instance not found", 404)
        return Response.json(data)

    @server.route("PUT", "/api/plugins/instances/", exact=False, summary="Set a user CC binding on a plugin param.")
    async def api_plugins_cc_map_put(req: Request) -> Response:
        """Set a user CC binding on a plugin param.

        Path: /api/plugins/instances/<id>/cc-map/<param>
        Body: {"ch": int | null, "cc": int | null}

        ch=null = any channel; cc=null = cleared (the param stops
        accepting any CC; the cleared state is durable across
        restart so the seed default doesn't reappear). Broadcasts
        the new binding via SSE so other open panels stay in sync.
        """
        if not engine._plugin_host:
            return Response.error("Plugin host not available", 503)
        suffix = req.path[len("/api/plugins/instances/"):].strip("/")
        parts = suffix.split("/")
        if len(parts) != 3 or parts[1] != "cc-map":
            return Response.error("Not found", 404)
        instance_id, _, param = parts
        instance = engine._plugin_host.get_instance(instance_id)
        if instance is None:
            return Response.error("Instance not found", 404)
        body = req.json or {}
        ch = body.get("ch")
        cc = body.get("cc")
        if ch is not None and not (isinstance(ch, int) and 0 <= ch <= 15):
            return Response.error("ch must be null or 0..15", 400)
        if cc is not None and not (isinstance(cc, int) and 0 <= cc <= 127):
            return Response.error("cc must be null or 0..127", 400)
        instance.plugin.cc_map[param] = {"ch": ch, "cc": cc}
        engine.mark_dirty()
        await server.send_sse("cc_map_changed", {
            "instance_id": instance_id, "param": param, "ch": ch, "cc": cc,
        })
        return Response.json({"status": "updated"})

    @server.route("PATCH", "/api/plugins/instances/", exact=False, summary="Update a plugin instance's params or name.")
    async def api_plugins_instance_patch(req: Request) -> Response:
        """Update plugin params or name. Body: {params?, name?}"""
        if not engine._plugin_host:
            return Response.error("Plugin host not available", 503)
        instance_id = req.path.split("/api/plugins/instances/")[1].rstrip("/")
        instance = engine._plugin_host.get_instance(instance_id)
        if instance is None:
            return Response.error("Instance not found", 404)

        body = req.json
        if "name" in body:
            engine._plugin_host.rename_instance(instance_id, body["name"])
            ctx.invalidate_instances_cache()
            engine.mark_dirty()
            # plugin-changed is the catch-all "instance metadata
            # moved" signal — listeners that mirror the
            # /api/plugins/instances or /api/plugins/cc-mappings
            # result (the Settings → Plugin Control Mappings table,
            # the bottom-nav controller picker, ...) refetch on
            # this event. Rename touches inst.name which both
            # endpoints carry; without the broadcast they'd hold a
            # stale label until the next manual refresh.
            await server.send_sse("plugin-changed", {"instance_id": instance_id})
        if "params" in body:
            engine._plugin_host.set_params(instance_id, body["params"])
            # set_params -> per-param notify -> _on_param_change closure
            # already calls mark_dirty via _on_dirty_cb. No second call here.

        # Don't return get_instance_data here — frontend doesn't read the
        # body on a successful PATCH, but the schema serialization is
        # several ms per call. With rAF-coalesced PATCHes during a knob
        # drag plus inbound CC mirroring, this used to pin the asyncio
        # loop at ~80% CPU and make the controller page feel sluggish.
        # SSE plugin-param events deliver the canonical post-write state.
        return Response.json({"status": "updated", "id": instance_id})

    @server.route("DELETE", "/api/plugins/instances/", exact=False, summary="Remove a plugin instance, or reset one param's CC binding to its default.")
    async def api_plugins_instance_delete(req: Request) -> Response:
        """Stop and remove a plugin instance — or, when the path is the
        cc-map sub-resource (/api/plugins/instances/<id>/cc-map/<param>),
        reset that single param's binding to the plugin's default_cc."""
        if not engine._plugin_host:
            return Response.error("Plugin host not available", 503)
        suffix = req.path[len("/api/plugins/instances/"):].strip("/")
        parts = suffix.split("/")
        # cc-map sub-resource: reset a single binding to the seed default
        if len(parts) == 3 and parts[1] == "cc-map":
            instance_id, _, param = parts
            instance = engine._plugin_host.get_instance(instance_id)
            if instance is None:
                return Response.error("Instance not found", 404)
            cls = type(instance.plugin)
            seed = get_default_cc_map(cls.params)
            if param in seed:
                instance.plugin.cc_map[param] = dict(seed[param])
            else:
                instance.plugin.cc_map.pop(param, None)
            new_binding = instance.plugin.cc_map.get(param, {"ch": None, "cc": None})
            engine.mark_dirty()
            await server.send_sse("cc_map_changed", {
                "instance_id": instance_id, "param": param,
                "ch": new_binding.get("ch"), "cc": new_binding.get("cc"),
            })
            return Response.json({"status": "reset", "binding": new_binding})
        instance_id = suffix
        instance = engine._plugin_host.get_instance(instance_id)
        if instance is None:
            return Response.error("Instance not found", 404)

        gone_client_id = instance.alsa_client.client_id if instance.alsa_client else -1

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, engine._plugin_host.stop_instance, instance_id)

        # Drop only this client's subscriptions; leave everything else
        # alone so clock and MIDI through other plugins keep flowing.
        if gone_client_id >= 0:
            engine.handle_plugin_removed(gone_client_id)
        else:
            engine.handle_plugin_added()  # fall back to a plain refresh

        ctx.invalidate_instances_cache()
        engine.mark_dirty()
        await server.send_sse("plugin-changed", {"instance_id": instance_id})
        return Response.json({"status": "deleted"})
