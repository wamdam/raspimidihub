"""System info, stats, observatory, SSE-subscribe, panic, reboot and
factory-reset routes. Moved verbatim from the old api.py."""

import asyncio
import logging
import os
import socket
import subprocess
from pathlib import Path

from .. import __version__
from ..web import Request, Response
from ._ctx import ApiContext

log = logging.getLogger(__name__)


def parse_root_fs_mode(mounts_text: str) -> str | None:
    """Root-filesystem state from `/proc/mounts` content.

    Returns ``"read/write"`` or ``"readonly"``; ``None`` when there is
    no ``/`` mount entry. Pure in its input so tests can feed synthetic
    mount tables. The match is on the exact mountpoint ``/`` (field 2),
    so a ``/root`` or ``/boot`` entry never counts; the mode is the
    ``rw``/``ro`` option token, not a substring of the options string.
    """
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == "/":
            return "read/write" if "rw" in parts[3].split(",") else "readonly"
    return None


def register_system(ctx: ApiContext) -> None:
    """Register the system-level routes."""
    server = ctx.server
    engine = ctx.engine
    config = ctx.config
    autosaver = ctx.autosaver

    # ================================================================
    # GET /api/system — system info
    # ================================================================

    @server.route("GET", "/api/system", summary="Hub status: hostname, IPs, version, CPU/RAM/temp, per-core load, SSE + latency stats, ALSA port budget, MIDI 2.0 (UMP) capability.")
    async def api_system(req: Request) -> Response:

        from ..alsa_seq import probe_ump_support
        from ..wifi import default_ap_ssid
        _ump = probe_ump_support()
        hostname = socket.gethostname()
        # The AP SSID is what the user sees in the WiFi list and the
        # header badge mirrors it. Configured name wins; else the
        # RaspiMIDIHub-<MAC suffix> default.
        ap_ssid = config.wifi.get("ap_ssid") or default_ap_ssid()

        # IP addresses — the `ip` subprocesses run on a worker thread:
        # fork/exec/waitpid on the loop blocked the MIDI loop 10-150 ms
        # per interface under load (visible in the loop_lag tail).
        def _iface_ips() -> list:
            out = []
            for iface in os.listdir("/sys/class/net"):
                if iface == "lo":
                    continue
                try:
                    result = subprocess.run(
                        ["ip", "-4", "addr", "show", iface],
                        capture_output=True, text=True, timeout=2
                    )
                    for line in result.stdout.splitlines():
                        line = line.strip()
                        if line.startswith("inet "):
                            out.append({"interface": iface, "address": line.split()[1].split("/")[0]})
                except Exception:
                    continue
            return out

        try:
            ips = await asyncio.get_running_loop().run_in_executor(
                None, _iface_ips)
        except Exception:
            ips = []

        # CPU temp, RAM, uptime — read from /proc and /sys
        temp = ram = uptime = None
        try:
            temp = round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000, 1)
        except Exception:
            pass
        try:
            ram = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    ram["total_mb"] = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    ram["available_mb"] = int(line.split()[1]) // 1024
        except Exception:
            ram = {}
        try:
            uptime = int(float(Path("/proc/uptime").read_text().split()[0]))
        except Exception:
            pass
        load1 = None
        try:
            load1 = float(Path("/proc/loadavg").read_text().split()[0])
        except Exception:
            pass

        # Root-fs state (the rosetup hardening, manual ch. 14): steady
        # state is readonly; writers remount rw only for the brief
        # window of a save/backup/update. Surfacing it live makes a
        # failed remount-ro visible in the UI instead of only in
        # `mount` output.
        fs_mode = None
        try:
            fs_mode = parse_root_fs_mode(Path("/proc/mounts").read_text())
        except Exception:
            pass

        # ALSA port budget of the hub's own seq client. The kernel caps
        # a client at 254 ports and every filtered/mapped connection
        # holds two, so an approaching ceiling must be VISIBLE — at the
        # limit, creating filters fails (the 4.7.1 port leak presented
        # as "filter edits silently stop saving").
        alsa_ports = None
        try:
            own = engine._seq.client_id if engine._seq else None
            if own is not None:
                used = 0
                current = None
                for line in Path("/proc/asound/seq/clients").read_text().splitlines():
                    if line.startswith("Client "):
                        try:
                            current = int(line.split()[1])
                        except (IndexError, ValueError):
                            current = None
                    elif current == own and line.lstrip().startswith("Port "):
                        used += 1
                alsa_ports = {"used": used, "max": 254}
        except Exception:
            pass

        # Per-client SSE queue depth (0 = idle, 100 = saturated and
        # dropping oldest). A spike here means a slow tab is buffering
        # and the server is fanning out to it the wrong way — useful
        # for diagnosing "feels stuck" on a phone.
        sse_queue_depths = sorted(
            (q.qsize() for q in server._sse_queues), reverse=True
        )
        # Latency snapshot — windowed max ms over the last second for each
        # probed path. Missing keys mean no events of that kind happened
        # in the window (frontend renders "—" for those). Round to 1 dp.
        latency_max = {k: round(v, 1) for k, v in server._latency_max.items()}
        # Per-core busy% tagged with each core's role (loop / plugins /
        # system) so the UI can flag saturation of the isolated cores.
        from .. import cpu_affinity
        _loop_core = cpu_affinity.loop_core()
        _plugin_cores = cpu_affinity.plugin_cpus() if _loop_core is not None else set()
        cpu_cores = [
            {"core": c["core"], "pct": c["pct"],
             "role": ("loop" if c["core"] == _loop_core
                      else "plugins" if c["core"] in _plugin_cores
                      else "system")}
            for c in server._cpu_cores
        ]
        return Response.json({
            "hostname": hostname, "ap_ssid": ap_ssid, "version": __version__,
            "build_token": server._build_token,
            "ip_addresses": ips, "cpu_temp_c": temp, "ram": ram,
            "uptime_seconds": uptime, "load1": load1, "fs_mode": fs_mode,
            "cpu_percent": server._cpu_percent,
            "cpu_cores": cpu_cores,
            "sse_per_sec": server._sse_per_sec,
            "alsa_ports": alsa_ports,
            "sse_clients": len(server._sse_queues),
            "sse_queue_max": sse_queue_depths[0] if sse_queue_depths else 0,
            "sse_queue_depths": sse_queue_depths,
            "latency_max": latency_max,
            "config_fallback": config.fallback_active,
            "default_routing": config.default_routing,
            "config_dirty": engine.config_dirty,
            "midi2": {"alsa_lib": _ump.alsa_lib, "kernel": _ump.kernel,
                      "capable": _ump.capable},
        })

    # ================================================================
    # PATCH /api/system — update system settings
    # ================================================================

    @server.route("PATCH", "/api/system", summary="Update system settings (currently default_routing: all or none).")
    async def api_patch_system(req: Request) -> Response:
        data = req.json
        if "default_routing" in data:
            val = data["default_routing"]
            if val not in ("all", "none"):
                return Response.error("default_routing must be 'all' or 'none'")
            config.data["default_routing"] = val
            await config.asave()
        return Response.json({"status": "updated"})

    # ================================================================
    # Perf stats — timing distributions for the latency/jitter suite
    # ================================================================

    @server.route("GET", "/api/stats", summary="Perf timing distributions (jitter/lag percentiles) plus a CPU/temp context snapshot, for the latency suite.")
    async def api_stats(req: Request) -> Response:
        """Timing distributions (percentiles/histograms) for the perf
        harness: clock-tick jitter, loop lag, plugin note-send jitter,
        net-MIDI RX jitter, cross-Pi clock offset. Plus a context snapshot
        (per-core CPU, temp, server monotonic clock) so the harness can
        correlate spikes with load and attribute them to operations."""
        from .. import cpu_affinity, perf_stats
        _loop_core = cpu_affinity.loop_core()
        _plugin_cores = cpu_affinity.plugin_cpus() if _loop_core is not None else set()
        cpu_cores = [
            {"core": c["core"], "pct": c["pct"],
             "role": ("loop" if c["core"] == _loop_core
                      else "plugins" if c["core"] in _plugin_cores else "system")}
            for c in server._cpu_cores
        ]
        try:
            temp = round(int(Path("/sys/class/thermal/thermal_zone0/temp")
                             .read_text().strip()) / 1000, 1)
        except (OSError, ValueError):
            temp = None
        return Response.json({
            "metrics": perf_stats.snapshot_all(),
            "bucket_edges_ms": perf_stats.bucket_edges_ms(),
            "server_monotonic_ms": round(perf_stats.monotonic_ms(), 3),
            "context": {
                "cpu_cores": cpu_cores,
                "cpu_percent": server._cpu_percent,
                "cpu_temp_c": temp,
            },
        })

    @server.route("POST", "/api/stats/reset", summary="Zero all perf metrics before a measurement window.")
    async def api_stats_reset(req: Request) -> Response:
        """Zero all perf metrics — the harness calls this before each
        measurement window so a reading attributes only to that window."""
        from .. import perf_stats
        perf_stats.reset_all()
        return Response.json({"status": "reset"})

    # ================================================================
    # GET /api/observatory — current CC values per destination + held notes
    # ================================================================

    @server.route("GET", "/api/observatory", summary="Live snapshot of current CC values per destination and currently-held notes.")
    async def api_observatory(req: Request) -> Response:
        return Response.json({
            "cc": engine.cc_dest_snapshot(),
            "active_notes": engine.active_notes_snapshot(),
            # Kernel input-FIFO health of the main seq client.
            # `fifo_overflows` counts overflow episodes (kernel dropped
            # queued events + wiped the pending queue — the loop was
            # too slow to drain); a rising count during a performance
            # is the signature of lost note-ons/note-offs.
            "alsa": engine.alsa_buffer_info(),
        })

    @server.route("POST", "/api/debug/midi-activity",
                  summary="Toggle the unthrottled midi-activity SSE stream (debug: lifts the 10 events/sec per-port cap so the MIDI monitor shows every event, e.g. a whole chord).")
    async def api_debug_midi_activity(req: Request) -> Response:
        data = req.json or {}
        enabled = bool(data.get("unthrottled", False))
        server._midi_activity_unthrottled = enabled
        return Response.json({"status": "ok", "unthrottled": enabled})

    @server.route("GET", "/api/debug/stalls",
                  summary="Recent event-loop stall episodes with fingerprints: for each lag above the threshold, the loop thread's frozen frame + kernel wait channel, the thread that burned the most CPU during the window (the GIL hog), and per-thread frames — the forensics behind the loop_lag percentiles.")
    async def api_debug_stalls(req: Request) -> Response:
        sensor = getattr(server, "stall_sensor", None)
        if sensor is None:
            return Response.json({"threshold_ms": None, "episodes": []})
        return Response.json(sensor.episodes())

    # POST /api/sse/subscribe — set this connection's subscription set.
    # Body: {conn_id, events: [str], instances: [instance_id],
    #        label?: str, ...feature extensions}.
    # The conn_id is the UUID the server sent as the `connection`
    # event right after the SSE handshake. Calling subscribe replaces
    # the existing subscription wholesale — the frontend's
    # SubscriptionManager unions all active hooks' contributions and
    # sends the merged set, so this endpoint is the single point of
    # truth for "what should this client receive".
    #
    # Feature modules can add keys to the body (e.g. spectator.py
    # consumes `label` and `spectate_target`); those are handed off
    # via subscribe_extensions registered on the WebServer instance.
    @server.route("POST", "/api/sse/subscribe", summary="Set this SSE connection's subscription (event types + plugin instance ids); identified by conn_id.")
    async def api_sse_subscribe(req: Request) -> Response:
        body = req.json
        conn_id = body.get("conn_id", "")
        if not conn_id:
            return Response.error("conn_id required")
        conn = server._sse_connections.get(conn_id)
        if conn is None:
            return Response.error("connection not found", 404)
        events = body.get("events") or []
        instances = body.get("instances") or []
        conn.events = set(events)
        conn.instances = set(instances)
        for ext in getattr(server, "_subscribe_extensions", ()):
            try:
                ext(conn, body)
            except Exception:  # noqa: BLE001 — best-effort
                pass
        return Response.json({"status": "ok"})

    # ================================================================
    # POST /api/panic — silence all notes across every destination
    # ================================================================

    @server.route("POST", "/api/panic", summary="Silence all notes on every destination (all-notes-off; hard=true resets more aggressively).")
    async def api_panic(req: Request) -> Response:
        data = req.json or {}
        hard = bool(data.get("hard", False))
        await asyncio.to_thread(engine.panic, hard)
        await server.send_sse("panic", {"hard": hard})
        return Response.json({"status": "panic", "hard": hard})

    # ================================================================
    # POST /api/system/reboot — reboot the Pi
    # ================================================================

    @server.route("POST", "/api/system/reboot", summary="Reboot the Pi.")
    async def api_reboot(req: Request) -> Response:
        asyncio.get_running_loop().call_later(1, lambda: subprocess.Popen(["sudo", "reboot"]))
        return Response.json({"status": "rebooting"})

    # ================================================================
    # POST /api/system/factory-reset — wipe to defaults, keep backups +
    # WiFi, then reboot clean. Recoverable via Settings → Backup.
    # ================================================================

    @server.route("POST", "/api/system/factory-reset", summary="Wipe config to defaults (keeps backups and WiFi), then reboot clean.")
    async def api_factory_reset(req: Request) -> Response:
        # Silence autosave first: the shutdown flush would otherwise
        # recreate the resume snapshot from the still-live old engine
        # state and undo the reset on the next boot.
        autosaver.disable()
        ok = await config.afactory_reset(keep_wifi=True)
        if not ok:
            return Response.error("Factory reset failed — see the hub log.")
        # Reboot so the appliance comes up clean from the reset config.
        asyncio.get_running_loop().call_later(1, lambda: subprocess.Popen(["sudo", "reboot"]))
        return Response.json({"status": "reset"})

