"""Spectator-mode mirroring service.

The spectator feature lets a browser tab or OBS Browser Source render
the same UI as another connected device, driven by a per-source
broadcast channel. The implementation is intentionally factored into
its own module so the core SSE machinery (web.py) and the general
API surface (api.py) don't have to grow spectator-specific concerns.

Public surface
--------------
- ``SpectatorService(server)`` — instantiate alongside ``WebServer`` and
  call ``register_routes()`` once. It hooks itself into the WebServer
  via two callbacks:
    * ``event_filter(event, data)`` — if the broadcast event belongs
      to this feature, returns a per-recipient predicate; web.py uses
      it inside ``send_sse``. Returns ``None`` for foreign events so
      the default filter applies.
    * ``on_disconnect(conn_id)`` — called from ``WebServer._handle_sse``
      when an SSE connection closes; lets us clean up watcher slots
      and notify spectators that their source is gone.
- ``apply_subscribe_extension(conn, body)`` — extension point called
  from ``/api/sse/subscribe`` so the existing subscribe endpoint can
  honour ``label`` and ``spectate_target`` keys without that handler
  having to know what they mean.

Core integration points (intentionally kept visible in the host code)
---------------------------------------------------------------------
- ``WebServer.send_sse`` calls into ``event_filter``.
- ``WebServer._handle_sse`` calls ``on_disconnect``.
- ``/api/sse/subscribe`` calls ``apply_subscribe_extension``.
- ``SSEConnection.label`` is the one general-purpose field this
  service relies on existing on the connection record. Everything
  else lives in this module's own per-conn state map.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .web import Request, Response, SSEConnection, WebServer


# Event-type strings exposed on the wire. Kept inside this module so
# nothing outside has to know they exist.
EVENT_STATE = "spectator-state"
EVENT_WATCH_START = "spectator-watch-start"
EVENT_WATCH_STOP = "spectator-watch-stop"
EVENT_SOURCE_GONE = "spectator-source-gone"


@dataclass
class _ConnState:
    """Per-connection spectator state. Kept outside SSEConnection so
    the core connection record stays clean."""
    spectate_target: str | None = None
    last_state: dict = field(default_factory=dict)
    viewport: dict | None = None
    last_seen: float = 0.0


class SpectatorService:
    """Owns per-connection spectator state, the watchers_of map, the
    state-fan-out filter, and the four ``/api/spectator/*`` routes."""

    def __init__(self, server: WebServer) -> None:
        self._server = server
        # conn_id -> per-conn spectator state.
        self._state: dict[str, _ConnState] = defaultdict(_ConnState)
        # source conn_id -> set of spectator conn_ids watching it.
        # Empty→non-empty transitions emit spectator-watch-start to the
        # source; non-empty→empty emits spectator-watch-stop.
        self._watchers_of: dict[str, set[str]] = defaultdict(set)

    # ---- Hooks called by web.py / api.py ----------------------------

    def event_filter(self, event: str, data: dict) -> Callable | None:
        """Called from ``WebServer.send_sse``. If this event belongs to
        the spectator feature, return a per-recipient predicate; else
        return None so the default events-set filter applies.

        Spectator-state is the only fan-out event we own: it's
        delivered only to connections whose ``spectate_target`` equals
        ``data['conn_id']`` (the source that produced the state).
        """
        if event != EVENT_STATE:
            return None
        target = data.get("conn_id")
        state = self._state

        def predicate(conn: SSEConnection) -> bool:
            s = state.get(conn.conn_id)
            return bool(s and s.spectate_target == target)
        return predicate

    def on_disconnect(self, conn_id: str) -> None:
        """Called from ``WebServer._handle_sse`` when an SSE connection
        closes. Releases the watcher slot if the disconnected client
        was a spectator, and notifies any spectators of this client
        that their source is gone."""
        # If we were spectating something, release that watcher slot.
        s = self._state.get(conn_id)
        if s and s.spectate_target:
            self._update_target(conn_id, None)
        # If anyone was spectating us as a source, tell them.
        watchers = self._watchers_of.pop(conn_id, None)
        if watchers:
            msg = {"conn_id": conn_id}
            for sid in watchers:
                other = self._state.get(sid)
                if other is not None:
                    other.spectate_target = None
                asyncio.create_task(
                    self._send_direct(sid, EVENT_SOURCE_GONE, msg))
        # Forget our own state entry.
        self._state.pop(conn_id, None)

    def apply_subscribe_extension(self, conn: SSEConnection,
                                  body: dict) -> None:
        """Called from ``/api/sse/subscribe`` after the default
        events/instances are applied. Honours optional ``label`` and
        ``spectate_target`` keys. label is on SSEConnection itself
        (the one general-purpose field this service uses); the
        spectate_target lives in our own per-conn state map."""
        if "label" in body:
            label = body.get("label") or ""
            if isinstance(label, str):
                conn.label = label[:64]
        if "spectate_target" in body:
            target = body.get("spectate_target")
            if not target:
                self._update_target(conn.conn_id, None)
            elif isinstance(target, str) \
                    and target in self._server._sse_connections:
                self._update_target(conn.conn_id, target)
            else:
                # Target conn_id doesn't exist — drop any prior
                # spectate so we don't leak a watcher slot.
                self._update_target(conn.conn_id, None)

    # ---- HTTP routes -----------------------------------------------

    def register_routes(self) -> None:
        """Register the four ``/api/spectator/*`` handlers on the
        WebServer instance. Call once at startup."""
        server = self._server

        @server.route("GET", "/api/spectator/clients", summary="List connected spectator clients and their watch targets.")
        async def _clients(req):  # noqa: ARG001
            return self._clients()

        @server.route("POST", "/api/spectator/state", summary="Update this spectator's state (watch target, label).")
        async def _state(req):
            return await self._state_post(req)

        @server.route("GET", "/api/spectator/snapshot/", exact=False, summary="Get the current UI snapshot for a spectate target.")
        async def _snapshot(req):
            return self._snapshot(req)

    # ---- Internals -------------------------------------------------

    def _update_target(self, spectator_id: str,
                       new_target: str | None) -> None:
        """Move a spectator's watch target, maintaining the
        ``watchers_of`` map and firing watch-start / watch-stop edge
        events to the source when its watcher-count transitions 0↔1.
        """
        s = self._state[spectator_id]
        old_target = s.spectate_target
        if old_target == new_target:
            return
        s.spectate_target = new_target
        # Old source: drop us; if it emptied, tell the source.
        if old_target:
            watchers = self._watchers_of.get(old_target)
            if watchers and spectator_id in watchers:
                watchers.discard(spectator_id)
                if not watchers:
                    self._watchers_of.pop(old_target, None)
                    asyncio.create_task(self._send_direct(
                        old_target, EVENT_WATCH_STOP,
                        {"conn_id": old_target}))
        # New source: add us; if it was empty, tell the source.
        if new_target:
            watchers = self._watchers_of[new_target]
            was_empty = not watchers
            watchers.add(spectator_id)
            if was_empty:
                asyncio.create_task(self._send_direct(
                    new_target, EVENT_WATCH_START,
                    {"conn_id": new_target}))

    async def _send_direct(self, conn_id: str, event: str,
                           data: dict) -> None:
        """Push an SSE event to a single recipient's queue, bypassing
        the subscription filter. Used for the watch lifecycle events
        which target a specific recipient by conn_id. Routes through
        the WebServer's send_sse_direct helper, which exists as a
        plain utility on web.py (not spectator-specific)."""
        await self._server.send_sse_direct(conn_id, event, data)

    def _clients(self) -> Response:
        from .web import Response  # avoid circular import at module load
        now = time.monotonic()
        result = []
        for cid, conn in self._server._sse_connections.items():
            s = self._state.get(cid)
            # Skip connections that are themselves spectators.
            if s and s.spectate_target:
                continue
            last_seen = s.last_seen if s else 0
            viewport = s.viewport if s else None
            result.append({
                "conn_id": cid,
                "label": conn.label or "",
                "last_seen": round(last_seen, 3) if last_seen else 0,
                "age_sec": round(now - last_seen, 1) if last_seen else None,
                "viewport": viewport,
            })
        result.sort(key=lambda x: -(x["last_seen"] or 0))
        return Response.json({"clients": result})

    async def _state_post(self, req: Request) -> Response:
        from .web import Response
        body = req.json
        conn_id = body.get("conn_id", "")
        if not conn_id:
            return Response.error("conn_id required")
        if conn_id not in self._server._sse_connections:
            return Response.error("connection not found", 404)
        kind = body.get("kind", "")
        if not isinstance(kind, str) or not kind:
            return Response.error("kind required")
        value = body.get("value")
        s = self._state[conn_id]
        s.last_seen = time.monotonic()
        if kind == "viewport" and isinstance(value, dict):
            s.viewport = {
                "w": int(value.get("w", 0) or 0),
                "h": int(value.get("h", 0) or 0),
            }
        # Touch is fire-and-forget — replaying a stale touch frame
        # after a reconnect would look weird; everything else is
        # cached for late-joining spectators.
        if kind != "touch":
            s.last_state[kind] = value
        await self._server.send_sse(EVENT_STATE, {
            "conn_id": conn_id,
            "kind": kind,
            "value": value,
        })
        return Response.json({"status": "ok"})

    def _snapshot(self, req: Request) -> Response:
        from .web import Response
        target = req.path_param("/api/spectator/snapshot/")
        if not target:
            return Response.error("conn_id required")
        conn = self._server._sse_connections.get(target)
        s = self._state.get(target) if conn else None
        if conn is None:
            return Response.json({"state": {}, "exists": False})
        return Response.json({
            "state": dict(s.last_state) if s else {},
            "exists": True,
            "label": conn.label or "",
            "viewport": s.viewport if s else None,
        })
