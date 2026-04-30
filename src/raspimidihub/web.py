"""Minimal async HTTP server using only the Python standard library.

Provides routing, static file serving, JSON API, SSE, security headers,
and rate limiting — without any external dependencies.
"""

import asyncio
import json
import logging
import mimetypes
import os
import time
import urllib.parse
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Rate limiting
# Rate limit for mutating requests. 120/sec is roughly 2x animation-frame
# rate — covers a worst-case fast drag where every other rAF tick fits a
# round-trip. The client also serialises one PATCH at a time, so on a
# realistic LAN we won't actually hit this; it's the floor where
# misbehaving clients start getting 429'd.
MAX_MUTATING_PER_SEC = 120
# SSE connections allowed across all clients. Each browser tab opens
# several EventSources (global event bus + transport-start + device-detail
# MIDI monitor + ...), so a single laptop with the matrix open and a
# plugin panel open can use ~3-4 by itself. Headroom for several phones.
MAX_SSE_CONNECTIONS = 30

# Events that carry an `instance_id` field and are filtered by the
# client's per-instance subscription set; everything else is filtered
# by the event-type set.
_PER_INSTANCE_EVENTS = frozenset({"plugin-param", "plugin-display"})


@dataclass
class SSEConnection:
    """Per-SSE-connection state. The client receives a UUID as its
    first event; subsequent /api/sse/subscribe calls reference that
    UUID so the server can update this connection's subscription.

    `events` and `instances` are the client's currently-active
    subscription set. send_sse() consults them to decide whether to
    fan an event out to this client. Empty sets = receive nothing
    (intentional — every view must declare its interest)."""
    conn_id: str
    queue: "asyncio.Queue"
    events: set[str]
    instances: set[str]


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
    "Referrer-Policy": "no-referrer",
}


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: bytes
    client_addr: str = ""

    @property
    def json(self) -> dict:
        return json.loads(self.body) if self.body else {}

    def path_param(self, prefix: str) -> str:
        """Extract path suffix after prefix, e.g. /api/presets/foo -> foo"""
        return self.path[len(prefix):].strip("/")


class Response:
    def __init__(self, status: int = 200, body: bytes = b"",
                 content_type: str = "text/plain", headers: dict | None = None):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.headers = headers or {}

    @staticmethod
    def json(data, status: int = 200) -> "Response":
        body = json.dumps(data, ensure_ascii=False).encode()
        return Response(status=status, body=body, content_type="application/json")

    @staticmethod
    def text(text: str, status: int = 200) -> "Response":
        return Response(status=status, body=text.encode(), content_type="text/plain")

    @staticmethod
    def html(text: str, status: int = 200) -> "Response":
        return Response(status=status, body=text.encode(), content_type="text/html; charset=utf-8")

    @staticmethod
    def redirect(url: str, status: int = 302) -> "Response":
        return Response(status=status, headers={"Location": url})

    @staticmethod
    def not_found() -> "Response":
        return Response.json({"error": "Not found"}, 404)

    @staticmethod
    def error(msg: str, status: int = 400) -> "Response":
        return Response.json({"error": msg}, status)


# Route type: (method, path_prefix, exact_match, handler)
Route = tuple[str, str, bool, callable]


class WebServer:
    """Async HTTP server with routing, static files, SSE, and security headers."""

    def __init__(self, host: str = "0.0.0.0", port: int = 80):
        self.host = host
        self.port = port
        self.routes: list[Route] = []
        # Per-connection SSE state. Each entry tracks the client's
        # current subscription set (event types + plugin instance ids).
        # send_sse() filters per-recipient against this — a backgrounded
        # phone tab on a view that subscribes to nothing receives zero
        # plugin-param noise. There is NO backward-compat fallback:
        # connections that haven't called /api/sse/subscribe have empty
        # sets and receive nothing. Every view explicitly declares its
        # interest via the useSSESubscription() hook.
        self._sse_connections: dict[str, SSEConnection] = {}
        # Kept for shutdown fan-out only — points to the same queue
        # objects held in _sse_connections.
        self._sse_queues: list[asyncio.Queue] = []
        # SSE traffic meter — incremented per broadcast (one per send_sse,
        # not per recipient), sampled to _sse_per_sec each second by
        # runtime.loops.rate_meter so /api/system can report it cheaply.
        self._sse_count_window = 0
        self._sse_per_sec = 0
        # Latency probes — caller records per-event ms via record_latency,
        # rate_meter snapshots the windowed max into _latency_max once a
        # second so /api/system reads cheaply. Tracking only the running
        # max (not every sample) keeps overhead at ~1 dict lookup +
        # 1 compare per recorded event.
        self._latency_window: dict[str, float] = {}
        self._latency_max: dict[str, float] = {}
        # Process CPU sampling — captures /proc/self/stat utime+stime in
        # jiffies, computes delta vs prior snapshot, expressed as
        # percent-of-one-core (100 = one core pinned; >100 means
        # multi-thread is summing).
        self._cpu_percent = 0.0
        self._cpu_last_snapshot: tuple[float, int] | None = None
        # Per-restart cache-bust token. Substituted into index.html's
        # entry script + stylesheet hrefs (?v=...) so two deploys of
        # the same package version still bust browser caches — without
        # this, an in-place upgrade serves identical URLs and stale
        # tabs keep running old JS.
        self._build_token = format(int(time.time()), "x")
        self._rate_counts: dict[str, list[float]] = defaultdict(list)
        self._server: asyncio.AbstractServer | None = None
    def route(self, method: str, path: str, exact: bool = True):
        """Decorator to register a route handler."""
        def decorator(func):
            self.routes.append((method.upper(), path, exact, func))
            return func
        return decorator

    async def send_sse(self, event: str, data: dict):
        """Broadcast an SSE event to clients subscribed to it.

        Per-connection filter: events of type `plugin-param` or
        `plugin-display` are delivered only to clients whose
        `instances` set contains `data['instance_id']`. All other
        events are delivered to clients whose `events` set contains
        `event`. A client that hasn't subscribed at all (empty sets)
        receives nothing — every view must explicitly declare its
        interest via /api/sse/subscribe.

        If a client's queue is full (slow / backgrounded tab), drop
        its oldest queued event and try again — the client stays
        subscribed; the freshest event wins.
        """
        msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        self._sse_count_window += 1
        per_instance = event in _PER_INSTANCE_EVENTS
        instance_id = data.get("instance_id") if per_instance else None
        for conn in self._sse_connections.values():
            if per_instance:
                if instance_id is None or instance_id not in conn.instances:
                    continue
            else:
                if event not in conn.events:
                    continue
            q = conn.queue
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()  # drop oldest so the freshest event wins
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    pass

    def sample_sse_rate(self) -> None:
        """Roll the broadcast-event counter into _sse_per_sec. Called once
        per second from runtime.loops.rate_meter so /api/system can read
        the latest value without doing any work itself."""
        self._sse_per_sec = self._sse_count_window
        self._sse_count_window = 0

    def record_latency(self, name: str, ms: float) -> None:
        """Record a single latency sample. Stored as a running max in the
        current 1-second window — cheap (one get + one compare) and
        bounded (no growing list). The actionable signal users care
        about is the worst case anyway."""
        cur = self._latency_window.get(name, 0.0)
        if ms > cur:
            self._latency_window[name] = ms

    def sample_latencies(self) -> None:
        """Roll the latency window into _latency_max. Called once per
        second from runtime.loops.rate_meter."""
        self._latency_max = self._latency_window
        self._latency_window = {}

    def sample_cpu(self) -> None:
        """Sample process CPU usage as percent-of-one-core. /proc/self/stat
        fields 14 (utime) and 15 (stime) are jiffies consumed in user /
        kernel mode; delta over wall-clock × 100 / Hz = % of one core."""
        try:
            with open("/proc/self/stat") as f:
                fields = f.read().split()
            jiffies = int(fields[13]) + int(fields[14])
        except (OSError, IndexError, ValueError):
            return
        now = time.monotonic()
        if self._cpu_last_snapshot is not None:
            t0, j0 = self._cpu_last_snapshot
            dt = now - t0
            if dt > 0:
                hz = os.sysconf("SC_CLK_TCK") or 100
                self._cpu_percent = round(100.0 * (jiffies - j0) / hz / dt, 1)
        self._cpu_last_snapshot = (now, jiffies)

    def _check_rate_limit(self, client: str) -> bool:
        """Returns True if request should be rate-limited."""
        now = time.monotonic()
        times = self._rate_counts[client]
        # Prune old entries
        self._rate_counts[client] = [t for t in times if now - t < 1.0]
        if len(self._rate_counts[client]) >= MAX_MUTATING_PER_SEC:
            return True
        self._rate_counts[client].append(now)
        return False

    async def _handle_sse(self, request: Request, reader: asyncio.StreamReader,
                          writer: asyncio.StreamWriter):
        """Handle SSE connection with direct writer access. The first
        message sent is `event: connection` carrying a UUID; the
        client uses it as conn_id when calling /api/sse/subscribe.

        We also park a reader task that watches for peer-EOF and pushes
        the shutdown sentinel into the queue when it fires. Without this,
        a browser tab close (which sends TCP FIN) sits in CLOSE_WAIT
        until the next heartbeat write tries to drain a half-closed
        socket — up to 30 s of zombie connection per tab close. SSE is
        one-way (server→client), so any inbound bytes signal the peer
        is gone."""
        if len(self._sse_connections) >= MAX_SSE_CONNECTIONS:
            resp = Response.error("Too many SSE connections", 429)
            await self._write_response(writer, resp)
            return

        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        conn_id = uuid.uuid4().hex
        conn = SSEConnection(conn_id=conn_id, queue=queue,
                             events=set(), instances=set())
        self._sse_connections[conn_id] = conn
        self._sse_queues.append(queue)

        # Write SSE headers
        header = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/event-stream\r\n"
            "Cache-Control: no-cache\r\n"
            "Connection: keep-alive\r\n"
            "X-Content-Type-Options: nosniff\r\n"
            "\r\n"
        )
        writer.write(header.encode())
        await writer.drain()

        # Hand the client its conn_id immediately so the
        # SubscriptionManager can call /api/sse/subscribe.
        intro = f"event: connection\ndata: {json.dumps({'conn_id': conn_id})}\n\n"
        writer.write(intro.encode())
        await writer.drain()

        # Peer-EOF watcher: any inbound byte (or EOF) on an SSE socket
        # means the browser closed the tab / refreshed / lost the page.
        # Push the shutdown sentinel so the writer loop unblocks and
        # the finally clause cleans up the connection.
        async def _watch_peer():
            try:
                while True:
                    chunk = await reader.read(4096)
                    if not chunk:
                        break  # EOF — peer closed
            except (ConnectionResetError, BrokenPipeError, OSError,
                    asyncio.CancelledError):
                pass
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        watcher = asyncio.create_task(_watch_peer())

        try:
            while True:
                msg = await queue.get()
                # None is the shutdown sentinel pushed by WebServer.stop()
                if msg is None:
                    break
                # Batch: while we were waiting in queue.get(), more events
                # may have piled in. Drain them all into a single write +
                # drain instead of paying the StreamWriter / TCP-flush cost
                # per event.
                msgs = [msg]
                while True:
                    try:
                        m = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if m is None:
                        writer.write("".join(msgs).encode())
                        await asyncio.wait_for(writer.drain(), timeout=5.0)
                        msgs = None
                        break
                    msgs.append(m)
                if msgs is None:
                    break
                writer.write("".join(msgs).encode())
                await asyncio.wait_for(writer.drain(), timeout=5.0)
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError,
                OSError, asyncio.TimeoutError):
            pass
        finally:
            watcher.cancel()
            self._sse_connections.pop(conn_id, None)
            if queue in self._sse_queues:
                self._sse_queues.remove(queue)
            try:
                writer.close()
            except Exception:
                pass

    async def _serve_static(self, path: str, if_none_match: str | None = None) -> Response:
        """Serve a static file from the static directory.

        Sends an ETag based on file size + mtime; honours If-None-Match
        with a 304 Not Modified so already-loaded modules avoid
        re-downloading the body on every revalidation pass. The
        no-cache + must-revalidate headers force the browser to
        revalidate, but the round-trip itself is now cheap.

        index.html gets `__VERSION__` substituted with the live package
        version on every serve — that lets the entry script + stylesheet
        load with `?v={version}` query strings, so a fresh deploy busts
        all the per-module sub-imports automatically (the modules are
        re-fetched under a new URL space).

        SPA fallback: paths without a file extension (e.g. /controller,
        /routing/d/42) fall through to index.html so the JS router can
        handle them on the client side. Real 404s only fire for paths
        that look like asset requests (have an extension)."""
        # Security: prevent directory traversal
        clean = path.lstrip("/")
        if clean == "" or clean.endswith("/"):
            clean += "index.html"

        file_path = (STATIC_DIR / clean).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())):
            return Response.not_found()

        is_index = False
        if not file_path.is_file():
            # SPA fallback for extensionless paths — serve index.html so
            # client-side routing can take over. Anything with a "."
            # in the last segment (asset paths like /missing.png) gets
            # the real 404 it deserves.
            last_segment = clean.rsplit("/", 1)[-1]
            if "." not in last_segment:
                fallback = (STATIC_DIR / "index.html").resolve()
                if fallback.is_file():
                    file_path = fallback
                    is_index = True
            if not file_path.is_file():
                return Response.not_found()
        elif file_path.name == "index.html":
            is_index = True

        try:
            stat = file_path.stat()
        except OSError:
            return Response.not_found()

        # ETag: file size + mtime ns. Cheap to compute, stable across
        # restarts unless the file changes; weak ETag is fine here since
        # we never want byte-exact match guarantees.
        etag = f'W/"{stat.st_size:x}-{stat.st_mtime_ns:x}"'
        if if_none_match and if_none_match == etag:
            return Response(status=304, body=b"",
                            headers={"ETag": etag,
                                     "Cache-Control": "no-cache, must-revalidate"})

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        body = file_path.read_bytes()
        if is_index:
            from . import __version__
            stamp = f"{__version__}-{self._build_token}"
            body = body.replace(b"__VERSION__", stamp.encode())
            # index.html: no-store so browsers (mobile Safari especially,
            # which restores from bf-cache aggressively) always refetch
            # on reload. Other assets stay on no-cache+revalidate so
            # ETag 304s remain cheap. Without this, "Reload App" on a
            # phone can restore the old page from memory and the
            # version-stamped JS URLs in it never refresh.
            return Response(body=body, content_type=content_type,
                            headers={"Cache-Control": "no-store"})
        return Response(body=body, content_type=content_type,
                        headers={"ETag": etag,
                                 "Cache-Control": "no-cache, must-revalidate"})

    def _match_route(self, method: str, path: str) -> tuple[callable, bool] | None:
        """Find matching route handler. Returns (handler, exact_match)."""
        for route_method, route_path, exact, handler in self.routes:
            if route_method != method and route_method != "*":
                continue
            if exact and path == route_path:
                return handler, True
            if not exact and path.startswith(route_path):
                return handler, False
        return None

    async def _handle_request(self, reader: asyncio.StreamReader,
                               writer: asyncio.StreamWriter):
        """Handle a single HTTP request."""
        try:
            # Read request line
            request_line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not request_line:
                return

            line = request_line.decode("utf-8", errors="replace").strip()
            parts = line.split(" ")
            if len(parts) < 3:
                return

            method, raw_path, _ = parts[0], parts[1], parts[2]

            # Parse path and query string
            parsed = urllib.parse.urlparse(raw_path)
            path = urllib.parse.unquote(parsed.path)
            query = dict(urllib.parse.parse_qsl(parsed.query))

            # Read headers
            headers = {}
            while True:
                header_line = await asyncio.wait_for(reader.readline(), timeout=10)
                if header_line in (b"\r\n", b"\n", b""):
                    break
                key, _, value = header_line.decode("utf-8", errors="replace").partition(":")
                headers[key.strip().lower()] = value.strip()

            # Read body
            body = b""
            content_length = int(headers.get("content-length", 0))
            if content_length > 0:
                body = await asyncio.wait_for(reader.readexactly(content_length), timeout=30)

            # Build request
            peer = writer.get_extra_info("peername")
            client_addr = peer[0] if peer else ""
            request = Request(
                method=method.upper(),
                path=path,
                query=query,
                headers=headers,
                body=body,
                client_addr=client_addr,
            )

            # SSE endpoint (special handling — keeps connection open)
            if path == "/api/events" and method == "GET":
                await self._handle_sse(request, reader, writer)
                return

            # Rate limiting for mutating requests
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                if self._check_rate_limit(client_addr):
                    resp = Response.error("Rate limit exceeded", 429)
                    await self._write_response(writer, resp)
                    return

            # Route matching
            match = self._match_route(method, path)
            if match:
                handler, _ = match
                try:
                    resp = await handler(request)
                except json.JSONDecodeError:
                    resp = Response.error("Invalid JSON", 400)
                except Exception:
                    log.exception("Handler error for %s %s", method, path)
                    resp = Response.error("Internal server error", 500)
            elif method == "GET":
                # Try static files (pass If-None-Match for ETag/304)
                resp = await self._serve_static(path, headers.get("if-none-match"))
            else:
                resp = Response.not_found()

            await self._write_response(writer, resp)

        except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            log.exception("Request handling error")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _write_response(self, writer: asyncio.StreamWriter, resp: Response):
        """Write an HTTP response."""
        status_text = {
            200: "OK", 201: "Created", 204: "No Content",
            301: "Moved Permanently", 302: "Found",
            400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed",
            429: "Too Many Requests", 500: "Internal Server Error",
        }.get(resp.status, "Unknown")

        lines = [f"HTTP/1.1 {resp.status} {status_text}"]

        if resp.body:
            lines.append(f"Content-Type: {resp.content_type}")
            lines.append(f"Content-Length: {len(resp.body)}")

        # Security headers
        for key, value in SECURITY_HEADERS.items():
            lines.append(f"{key}: {value}")

        # Custom headers
        for key, value in resp.headers.items():
            lines.append(f"{key}: {value}")

        lines.append("Connection: close")
        lines.append("")
        lines.append("")

        header_bytes = "\r\n".join(lines).encode()
        writer.write(header_bytes + resp.body)
        await writer.drain()

    async def start(self):
        """Start the HTTP server."""
        self._server = await asyncio.start_server(
            self._handle_request, self.host, self.port,
        )
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        log.info("Web server listening on %s", addrs)

    async def stop(self):
        """Stop the HTTP server.

        SSE connections must be signalled to close *before* awaiting
        wait_closed(), otherwise wait_closed() hangs forever waiting for
        the long-poll connections to drain.
        """
        # Tell every SSE handler to exit its read loop
        for q in self._sse_queues:
            try:
                q.put_nowait(None)
            except Exception:
                pass
        self._sse_queues.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            log.info("Web server stopped")
