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
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Rate limiting
MAX_MUTATING_PER_SEC = 10
MAX_SSE_CONNECTIONS = 5

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
        self._captive_portal_ip: str | None = None

    def route(self, method: str, path: str, exact: bool = True):
        """Decorator to register a route handler."""
        def decorator(func):
            self.routes.append((method.upper(), path, exact, func))
            return func
        return decorator

    def enable_captive_portal(self, ip: str):
        """Enable captive portal redirects to the given IP."""
        self._captive_portal_ip = ip

    def disable_captive_portal(self):
        self._captive_portal_ip = None

    async def send_sse(self, event: str, data: dict):
        """Broadcast an SSE event to all connected clients."""
        msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        dead = []
        for q in self._sse_queues:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._sse_queues.remove(q)

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
                writer.write(msg.encode())
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            if queue in self._sse_queues:
                self._sse_queues.remove(queue)

    async def _serve_static(self, path: str) -> Response:
        """Serve a static file from the static directory."""
        # Security: prevent directory traversal
        clean = path.lstrip("/")
        if clean == "" or clean.endswith("/"):
            clean += "index.html"

        file_path = (STATIC_DIR / clean).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())):
            return Response.not_found()

        if not file_path.is_file():
            return Response.not_found()

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        body = file_path.read_bytes()
        return Response(body=body, content_type=content_type,
                        headers={"Cache-Control": "public, max-age=3600"})

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

    def _is_captive_portal_check(self, path: str) -> bool:
        """Detect OS captive portal check URLs."""
        captive_paths = {
            "/hotspot-detect.html",       # Apple
            "/library/test/success.html", # Apple
            "/generate_204",              # Android/Chrome
            "/connecttest.txt",           # Windows
            "/ncsi.txt",                  # Windows
            "/redirect",                  # Firefox
            "/canonical.html",            # Firefox
            "/success.txt",               # Firefox
        }
        return path in captive_paths

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

            # Captive portal handling — only for AP clients (192.168.4.x subnet)
            if self._captive_portal_ip and client_addr.startswith("192.168.4."):
                host = headers.get("host", "")
                if host and self._captive_portal_ip not in host and not path.startswith("/api/"):
                    # Redirect to our IP to trigger OS captive portal popup
                    resp = Response.redirect(f"http://{self._captive_portal_ip}/")
                    await self._write_response(writer, resp)
                    return

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
                except Exception as e:
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
        """Stop the HTTP server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            log.info("Web server stopped")

        # Close all SSE connections
        for q in self._sse_queues:
            q.put_nowait(None)
        self._sse_queues.clear()
