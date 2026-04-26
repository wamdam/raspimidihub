"""Minimal async HTTP server using only the Python standard library.

Provides routing, static file serving, JSON API, SSE, security headers,
and rate limiting — without any external dependencies.
"""

import asyncio
import json
import logging
import mimetypes
import time
import urllib.parse
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
        self._sse_queues: list[asyncio.Queue] = []
        self._rate_counts: dict[str, list[float]] = defaultdict(list)
        self._server: asyncio.AbstractServer | None = None
    def route(self, method: str, path: str, exact: bool = True):
        """Decorator to register a route handler."""
        def decorator(func):
            self.routes.append((method.upper(), path, exact, func))
            return func
        return decorator

    async def send_sse(self, event: str, data: dict):
        """Broadcast an SSE event to all connected clients.

        If a client's queue is full (slow / backgrounded tab), drop its
        oldest queued event and try again. This keeps the client
        subscribed instead of silently disconnecting it from broadcast
        for the lifetime of the connection — which used to leave one
        phone updating while the others sat stale until refresh.
        """
        msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        for q in self._sse_queues:
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
                    # Still full somehow (race) — skip this event for this client
                    # rather than dropping the client.
                    pass

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

    async def _handle_sse(self, request: Request, writer: asyncio.StreamWriter):
        """Handle SSE connection with direct writer access."""
        if len(self._sse_queues) >= MAX_SSE_CONNECTIONS:
            resp = Response.error("Too many SSE connections", 429)
            await self._write_response(writer, resp)
            return

        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
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

        try:
            while True:
                msg = await queue.get()
                # None is the shutdown sentinel pushed by WebServer.stop()
                if msg is None:
                    break
                writer.write(msg.encode())
                await asyncio.wait_for(writer.drain(), timeout=5.0)
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError,
                OSError, asyncio.TimeoutError):
            pass
        finally:
            if queue in self._sse_queues:
                self._sse_queues.remove(queue)
            try:
                writer.close()
            except Exception:
                pass

    async def _serve_static(self, path: str) -> Response:
        """Serve a static file from the static directory.

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

        if not file_path.is_file():
            # SPA fallback for extensionless paths — serve index.html so
            # client-side routing can take over. Anything with a "."
            # in the last segment (asset paths like /missing.png) gets
            # the real 404 it deserves.
            last_segment = clean.rsplit("/", 1)[-1]
            if "." not in last_segment:
                fallback = (STATIC_DIR / "index.html").resolve()
                if fallback.is_file():
                    body = fallback.read_bytes()
                    return Response(body=body, content_type="text/html",
                                    headers={"Cache-Control": "no-cache, must-revalidate"})
            return Response.not_found()

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        body = file_path.read_bytes()
        return Response(body=body, content_type=content_type,
                        headers={"Cache-Control": "no-cache, must-revalidate"})

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
                await self._handle_sse(request, writer)
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
                # Try static files
                resp = await self._serve_static(path)
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
