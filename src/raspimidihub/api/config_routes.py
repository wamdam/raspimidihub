"""Config save/load/export/import + rolling-backup routes. Moved
verbatim from the old api.py."""

import asyncio
import json
import logging

from ..web import Request, Response
from ._ctx import ApiContext

log = logging.getLogger(__name__)


def register_config_routes(ctx: ApiContext) -> None:
    """Register the /api/config and /api/backups routes."""
    server = ctx.server
    engine = ctx.engine
    config = ctx.config
    autosaver = ctx.autosaver

    # ================================================================
    # POST /api/config/save — explicitly save current config
    # ================================================================

    @server.route("POST", "/api/config/save", summary="Commit the current state to config.json plus a rolling backup (the deliberate Save).")
    async def api_save_config(req: Request) -> Response:
        # A deliberate Save commits session aliases: re-recognized
        # devices migrate from their saved (old) IDs to their canonical
        # ones. Connections/device names rebuild from the registry in
        # the snapshot below; the clock-block list is re-read here.
        if engine.device_registry.commit_aliases():
            config.data["device_clock_blocked"] = \
                engine.device_registry.get_clock_blocked()
        ctx.snapshot()
        # Gather live engine state, then persist + drop a rolling backup
        # checkpoint (with an auto diff summary) in the same rw window.
        if await config.asave(make_backup=True):
            engine.clear_dirty()
            return Response.json({"status": "saved"})
        return Response.error("Failed to save config", 500)

    # ================================================================
    # POST /api/config/load — reload saved config from disk
    # ================================================================

    async def _apply_current_config() -> None:
        """Apply whatever is in config.data to the live engine — restore
        plugin instances, then diff routing onto the matrix. Shared by
        Load (manual save) and backup Restore."""
        # Boot-like identity semantics for a deliberately loaded config:
        # every online device becomes eligible for re-recognition again,
        # so e.g. an old backup whose port-bound IDs no longer match
        # still binds to the devices that are sitting right there.
        engine.device_registry.reset_presence()
        if engine._plugin_host:
            engine._plugin_host.stop_all()
            saved_plugins = config.data.get("plugins", [])
            if saved_plugins:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, engine._plugin_host.restore_instances, saved_plugins)
            ctx.invalidate_instances_cache()
        # Pick up restored plugins' new ALSA client IDs AND run identity
        # resolution against the just-loaded config's references, so
        # apply_edge_diff below can resolve stable IDs (incl. re-bound
        # ones) to live clients.
        engine.scan_devices()
        if config.mode != "custom" or not config.connections:
            # No custom config — fall back to all-to-all
            engine.disconnect_all()
            engine.scan_devices()
            engine.connect_all()
            engine._update_monitor_subscriptions()
            config.set_mode("all-to-all")
        else:
            # Smooth switch: diff current routing against the saved set,
            # only touch the edges that actually changed. Untouched edges
            # (clock, transport, anything still in the saved config) keep
            # flowing without a millisecond of interruption.
            engine._disconnected.clear()
            engine.apply_edge_diff(config.connections)
            # Mirror saved disconnected edges into the engine's tracking
            # dict so hotplug-restore still re-applies them when the
            # devices come back online.
            registry = engine._device_registry
            for c in config.disconnected:
                src_stable = c.get("src_stable_id")
                dst_stable = c.get("dst_stable_id")
                src_client = (registry.client_for_stable_id(src_stable)
                              if src_stable else None)
                dst_client = (registry.client_for_stable_id(dst_stable)
                              if dst_stable else None)
                if src_client is None or dst_client is None:
                    continue
                sp = c.get("src_port", 0)
                dp = c.get("dst_port", 0)
                conn_id = f"{src_client}:{sp}-{dst_client}:{dp}"
                saved_data = {}
                if "filter" in c:
                    saved_data["filter"] = c["filter"]
                if "mappings" in c:
                    saved_data["mappings"] = c["mappings"]
                engine._disconnected[conn_id] = saved_data
            engine._update_monitor_subscriptions()

    @server.route("POST", "/api/config/load", summary="Load the last deliberate Save (the committed checkpoint), discarding uncommitted edits.")
    async def api_load_config(req: Request) -> Response:
        # Load the last DELIBERATE save (not the autosave) — reverting to
        # the user's committed checkpoint is the whole point of "Load".
        await config.aload_manual()
        await _apply_current_config()
        engine.clear_dirty()
        # The loaded config IS the resume point now — force an autosave
        # so a power cut right after Load doesn't resume the pre-Load
        # state (Load clears dirty, so the debounced loop won't fire).
        await autosaver.autosave_now()
        await server.send_sse("connection-changed", {"action": "config-loaded"})
        return Response.json({"status": "loaded"})

    # ================================================================
    # Backups — list / restore / download rolling save checkpoints
    # ================================================================

    @server.route("GET", "/api/backups", summary="List rolling backup checkpoints and current autosave status.")
    async def api_backups_list(req: Request) -> Response:
        return Response.json({"backups": config.list_backups(),
                              "autosave": config.autosave_status()})

    @server.route("POST", "/api/backups/", exact=False, summary="Restore a rolling backup by seq (path .../restore); leaves the config dirty to Save.")
    async def api_backups_action(req: Request) -> Response:
        # Path: /api/backups/<seq>/restore
        tail = req.path.split("/api/backups/")[1].strip("/")
        parts = tail.split("/")
        if len(parts) != 2 or parts[1] != "restore":
            return Response.error("Not found", 404)
        try:
            seq = int(parts[0])
        except ValueError:
            return Response.error("Bad backup id", 400)
        data = config.backup_data(seq)
        if not data:
            return Response.error("Backup not found", 404)
        if engine._plugin_host:
            engine._plugin_host.stop_all()
        config._data = data
        await _apply_current_config()
        # A restored backup diverges from the on-disk deliberate save, so
        # leave the config dirty — the user can Save to commit it.
        engine.mark_dirty()
        # The restored state is the resume point now — force an autosave
        # so a power cut right after Restore resumes it, not the prior
        # live state.
        await autosaver.autosave_now()
        await server.send_sse("connection-changed", {"action": "config-loaded"})
        return Response.json({"status": "restored", "seq": seq})

    @server.route("GET", "/api/backups/", exact=False, summary="Download a rolling backup as JSON (path .../download).")
    async def api_backup_download(req: Request) -> Response:
        # Path: /api/backups/<seq>/download
        tail = req.path.split("/api/backups/")[1].strip("/")
        parts = tail.split("/")
        if len(parts) != 2 or parts[1] != "download":
            return Response.error("Not found", 404)
        try:
            seq = int(parts[0])
        except ValueError:
            return Response.error("Bad backup id", 400)
        data = config.backup_data(seq)
        if not data:
            return Response.error("Backup not found", 404)
        return Response(
            status=200,
            body=json.dumps(data, indent=2).encode(),
            content_type="application/json",
            headers={
                "Content-Disposition":
                    f'attachment; filename="raspimidihub-backup-{seq:05d}.json"',
            },
        )

    # ================================================================
    # GET /api/config/export — download full config as JSON
    # ================================================================

    @server.route("GET", "/api/config/export", summary="Download the full config as a JSON file.")
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

    @server.route("POST", "/api/config/import", summary="Upload and apply a full config JSON, replacing the current state.")
    async def api_import_config(req: Request) -> Response:
        data = req.json
        if not isinstance(data, dict) or "version" not in data:
            return Response.error("Invalid config format")

        config._data = data
        # Boot-like identity semantics for the imported config (see
        # _apply_current_config): all devices re-recognizable.
        engine.device_registry.reset_presence()
        await config.asave()
        # Apply the imported config
        if config.mode == "custom":
            engine.disconnect_all()
            engine.apply_saved_config()
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

        # Restore plugin instances from imported config
        if engine._plugin_host:
            engine._plugin_host.stop_all()
            saved_plugins = config.data.get("plugins", [])
            if saved_plugins:
                engine._plugin_host.restore_instances(saved_plugins)
                engine._schedule_rescan()

        engine.clear_dirty()
        # Imported config is the resume point now — force an autosave so
        # a power cut right after Import resumes it, not the prior state.
        await autosaver.autosave_now()
        await server.send_sse("connection-changed", {"action": "config-loaded"})
        return Response.json({"status": "imported"})

