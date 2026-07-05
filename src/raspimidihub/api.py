"""REST API routes for RaspiMIDIHub.

Registers all /api/* handlers on the WebServer instance.
"""

import asyncio
import json
import logging
import os
import socket
import subprocess
from pathlib import Path

from . import __version__
from .bluetooth import BluetoothMidi
from .config import Config
from .midi_engine import Connection, MidiEngine
from .midi_filter import (
    ALL_CHANNELS,
    ALL_MSG_TYPES,
    MidiFilter,
    MidiMapping,
    validate_new_mapping,
)
from .network_midi import ERR_SESSION_NOT_FOUND
from .plugin_api import LayoutGrid, get_all_params, get_default_cc_map
from .update_flow import (
    NoInternetError,
    UpdateFetcher,
    download_newer_releases,
    list_stored_versions,
    read_status,
    write_status,
)
from .web import Request, Response, WebServer
from .wifi import WifiManager

INSTALL_DEB_SCRIPT = Path("/usr/local/bin/raspimidihub-install-deb")

log = logging.getLogger(__name__)


# --- Helpers ---

class _Autosaver:
    """Polls the engine's change counter and writes a debounced, rate-
    capped ping-pong autosave snapshot so a reboot — including a hard
    power cut — resumes the last edited state. The cadence: never more
    often than MIN_INTERVAL; after edits go quiet for DEBOUNCE it writes
    promptly; during a long continuous edit it still writes every
    MAX_WAIT so you can't lose an unbounded amount on a cut."""

    POLL = 3.0
    DEBOUNCE = 6.0
    MIN_INTERVAL = 15.0
    MAX_WAIT = 30.0

    def __init__(self, engine, config, snapshot):
        self._engine = engine
        self._config = config
        self._snapshot = snapshot
        self._last_seq = engine._change_seq
        self._last_write = 0.0
        self._running = True
        self._suspended = False
        # pid of an in-flight background autosave child (fork_write_autosave),
        # or None. Reaped non-blocking on the next poll; we never stack two.
        self._child_pid: int | None = None

    def _reap_child(self, block: bool) -> None:
        """Reap the background autosave child if present. block=False is
        the periodic non-blocking reap (clears _child_pid once the child
        exits); block=True waits for it (shutdown / before a durable
        write, so its rw/ro remount window can't overlap ours)."""
        if self._child_pid is None:
            return
        try:
            flags = 0 if block else os.WNOHANG
            reaped, _status = os.waitpid(self._child_pid, flags)
        except ChildProcessError:
            reaped = self._child_pid  # already gone
        if block or reaped == self._child_pid:
            self._child_pid = None

    async def run(self) -> None:
        import time as _t
        # Anchor MIN_INTERVAL to start-up so we don't write in the first
        # few seconds of boot while things settle.
        self._last_write = _t.monotonic()
        while self._running:
            await asyncio.sleep(self.POLL)
            try:
                self._reap_child(block=False)  # clear a finished prior child
                if self._child_pid is not None:
                    continue  # previous encode still running — don't stack forks
                seq = self._engine._change_seq
                if seq == self._last_seq:
                    continue  # nothing changed since the last autosave
                now = _t.monotonic()
                since_write = now - self._last_write
                if since_write < self.MIN_INTERVAL:
                    continue  # rate cap
                idle = now - self._engine._last_change_t
                if idle < self.DEBOUNCE and since_write < self.MAX_WAIT:
                    continue  # still actively editing and not yet overdue
                # Build the plain snapshot on the loop (cheap, shallow,
                # race-free vs hotplug), then fork: the GIL-heavy encode
                # runs in the child off the isolated core, so the loop
                # is free the instant fork() returns.
                self._snapshot()
                self._child_pid = self._config.fork_write_autosave()
                self._last_write = now
                self._last_seq = seq
            except Exception:
                log.exception("autosave loop error")

    def flush(self, force: bool = False) -> None:
        """Synchronous final autosave for the shutdown path — captures a
        clean stop even if the debounce hadn't fired. No-op if nothing
        changed since the last autosave, UNLESS `force` is set.

        `force=True` is used right after Load / Restore / Import: the
        live state *is* the new state and the user expects it to be the
        resume point, but those paths clear_dirty() (so _change_seq ==
        _last_seq and the debounced loop would never fire) — without a
        forced write a power cut just after a Load would resume the
        PRE-Load state."""
        try:
            if self._suspended:
                return  # factory reset cleared the snapshot; don't recreate it
            # Wait for any in-flight background child first so its rw/ro
            # remount window can't overlap this synchronous write.
            self._reap_child(block=True)
            if not force and self._engine._change_seq == self._last_seq:
                return
            self._snapshot()
            # Shutdown path: encode in-process. The loop is going away,
            # so the GIL hold doesn't matter, and an in-process write
            # can't be orphaned by the process exiting before a child
            # finishes.
            self._config.write_autosave()
            self._last_seq = self._engine._change_seq
            import time as _t
            self._last_write = _t.monotonic()
        except Exception:
            log.exception("autosave flush error")

    async def autosave_now(self) -> None:
        """Async force-autosave for the request handlers (Load / Restore
        / Import). The new state must be durable as the resume point
        before we return, so we fork the encode child and WAIT for it —
        but on a worker thread, where the waitpid blocks without holding
        the GIL, leaving the loop free while the child encodes off-core.
        Falls back to an in-process write if fork fails."""
        try:
            # Don't overlap a background child's remount window.
            self._reap_child(block=True)
            self._snapshot()
            await asyncio.to_thread(self._fork_and_wait)
            self._last_seq = self._engine._change_seq
            import time as _t
            self._last_write = _t.monotonic()
        except Exception:
            log.exception("autosave_now error")

    def _fork_and_wait(self) -> None:
        """Fork the encode child and block (on a worker thread) until it
        has durably written the slot. The waitpid is a GIL-releasing
        syscall, so the loop keeps running while the child encodes."""
        pid = self._config.fork_write_autosave()
        if pid is None:
            self._config.write_autosave()  # fork failed: in-process fallback
            return
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

    def stop(self) -> None:
        self._running = False

    def disable(self) -> None:
        """Permanently silence autosave (factory reset): stop the poll
        loop AND neuter the shutdown flush, so the just-cleared resume
        snapshot can't be recreated from the still-live old engine state
        before the reboot."""
        self._running = False
        self._suspended = True


def _parse_conn_id(conn_id: str) -> tuple[int, int, int, int]:
    """Parse 'src_client:src_port-dst_client:dst_port' → (sc, sp, dc, dp). Raises ValueError."""
    src, dst = conn_id.split("-")
    sc, sp = map(int, src.split(":"))
    dc, dp = map(int, dst.split(":"))
    return sc, sp, dc, dp


def _get_filter_data(fe, conn_id: str) -> dict:
    """Serialize filter + mappings for a connection. Returns dict with 'filter'/'mappings' keys."""
    data = {}
    if not fe:
        return data
    f = fe.get_filter(conn_id)
    if f:
        data["filter"] = f.to_dict()
    mappings = fe.get_mappings(conn_id)
    if mappings:
        data["mappings"] = [m.to_dict() for m in mappings]
    return data


def _serialize_connection(conn, registry, fe) -> dict:
    """Serialize a Connection with stable IDs and filter/mapping data."""
    conn_id = f"{conn.src_client}:{conn.src_port}-{conn.dst_client}:{conn.dst_port}"
    entry = {
        "src_client": conn.src_client, "src_port": conn.src_port,
        "dst_client": conn.dst_client, "dst_port": conn.dst_port,
    }
    src_info = registry.get_by_client(conn.src_client)
    dst_info = registry.get_by_client(conn.dst_client)
    if src_info:
        entry["src_stable_id"] = src_info.stable_id
    if dst_info:
        entry["dst_stable_id"] = dst_info.stable_id
    entry.update(_get_filter_data(fe, conn_id))
    return entry


def _restore_userspace(engine, fe, conn, saved_data: dict):
    """Restore a connection with saved filter/mapping data. Returns True if userspace, False if ALSA."""
    conn_id = f"{conn.src_client}:{conn.src_port}-{conn.dst_client}:{conn.dst_port}"
    saved_filter = saved_data.get("filter")
    saved_mappings = saved_data.get("mappings", [])
    needs_userspace = bool(saved_mappings)
    midi_filter = None
    if saved_filter:
        midi_filter = MidiFilter.from_dict(saved_filter)
        needs_userspace = needs_userspace or not midi_filter.is_passthrough

    if needs_userspace and fe:
        if midi_filter is None:
            midi_filter = MidiFilter()
        fe.add_filter(conn.src_client, conn.src_port,
                      conn.dst_client, conn.dst_port, midi_filter)
        for md in saved_mappings:
            try:
                fe.add_mapping(conn_id, MidiMapping.from_dict(md))
            except (ValueError, KeyError):
                pass
        engine._connections.add(conn)
        return True
    else:
        engine._seq.subscribe(conn.src_client, conn.src_port,
                              conn.dst_client, conn.dst_port)
        engine._connections.add(conn)
        return False


def _matches_saved(c: dict, src_sid: str, dst_sid: str, src_port: int, dst_port: int) -> bool:
    """Check if a saved config entry matches the given stable IDs and ports."""
    return (c.get("src_stable_id") == src_sid and c.get("dst_stable_id") == dst_sid
            and c.get("src_port") == src_port and c.get("dst_port") == dst_port)


# --- Captive portal landing -----------------------------------------------
# OS captive-portal probes (Android / iOS / Firefox) all hit known
# endpoints. We serve the same tiny landing for every one — pure HTML,
# no JS, no SSE. A captive webview that fetches this stays inert; the
# user taps the link to open the SPA in their normal browser, where
# SSE legitimately belongs.
#
# Microsoft endpoints (connecttest.txt / ncsi.txt) keep their original
# success responses because Windows' NCSI uses them for "do I have
# internet" without ever showing a captive browser — there's nothing
# to land on, so changing them just risks breaking Windows.

_CAPTIVE_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RaspiMIDIHub</title>
<style>
*{box-sizing:border-box}
body{margin:0;padding:24px;min-height:100vh;
     font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
     background:#1a1a2e;color:#eaeaea;
     display:flex;flex-direction:column;align-items:center;justify-content:center;
     text-align:center}
h1{font-size:1.6rem;font-weight:600;margin:0 0 8px}
.tag{color:#9aa0aa;font-size:0.9rem;margin:0 0 24px}
.lead{font-size:1rem;margin:0 0 14px}
.addr{display:flex;align-items:center;gap:8px;margin:8px 0;
      background:#16213e;border-radius:10px;padding:10px 12px;max-width:100%}
.addr code{font-size:1rem;color:#eaeaea;word-break:break-all}
.copy{flex:none;border:0;border-radius:8px;background:#e94560;color:#fff;
      font-size:1rem;padding:8px 12px;cursor:pointer}
.copy:active{transform:scale(0.95)}
.foot{color:#6a6f78;font-size:0.78rem;margin-top:24px;line-height:1.4}
</style>
</head>
<body>
<h1>RaspiMIDIHub</h1>
<p class="tag">Connected to the access point.</p>
<p class="lead">Open one of these in your browser:</p>
<div class="addr"><code id="a1">http://192.168.4.1/</code><button class="copy" onclick="cp('a1',this)">Copy</button></div>
<div class="addr"><code id="a2">http://__MDNS__.local/</code><button class="copy" onclick="cp('a2',this)">Copy</button></div>
<p class="foot">Paste an address into your browser's address bar.<br>
The name works from any device on this network; the IP works if .local isn't supported.</p>
<script>
function cp(id,b){var el=document.getElementById(id),t=el.textContent.trim(),ok=false;
try{var r=document.createRange();r.selectNodeContents(el);var s=getSelection();
s.removeAllRanges();s.addRange(r);ok=document.execCommand('copy');s.removeAllRanges();}catch(e){}
if(!ok&&navigator.clipboard){navigator.clipboard.writeText(t);ok=true;}
b.textContent=ok?'Copied':'Copy';setTimeout(function(){b.textContent='Copy';},1200);}
</script>
</body>
</html>
"""

_CAPTIVE_LANDING_PATHS = (
    "/generate_204",                   # Android
    "/hotspot-detect.html",            # iOS / macOS
    "/library/test/success.html",      # iOS variant
    "/redirect",                        # Firefox
    "/canonical.html",                  # Firefox
)
# Microsoft NCSI: keep the original success body, no captive needed.
_CAPTIVE_PASSTHROUGH = {
    "/connecttest.txt": "Microsoft Connect Test",
    "/ncsi.txt": "Microsoft NCSI",
}


def register_api(server: WebServer, engine: MidiEngine, config: Config,
                  wifi: WifiManager | None = None,
                  bluetooth: BluetoothMidi | None = None,
                  network_midi=None):
    """Register all API routes on the web server."""

    # Wire the dirty-tracker SSE side so mark_dirty / clear_dirty can fan
    # out a config-dirty event from any thread (CC-driven param mutations
    # come from worker threads). The plugin_host._on_dirty_cb hook is
    # wired in __main__ AFTER engine._plugin_host is attached — register_api
    # runs before that, so doing it here would no-op.
    engine._dirty_loop = asyncio.get_event_loop()
    engine._dirty_sse_cb = server.send_sse

    # Serialize the live engine state into config.data. Shared by manual
    # Save, the autosaver, and the shutdown flush so all three persist an
    # identical snapshot.
    def _snapshot_into_config() -> None:
        from . import perf_stats
        with perf_stats.time_op("op_autosave_snapshot"):
            _snapshot_into_config_impl()

    def _snapshot_into_config_impl() -> None:
        fe = engine.filter_engine
        registry = engine.device_registry
        config.set_connections(
            [_serialize_connection(c, registry, fe) for c in engine.connections])
        disconn = []
        for conn_id, saved_data in engine._disconnected.items():
            try:
                sc, sp, dc, dp = _parse_conn_id(conn_id)
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
        names = dict(registry.get_custom_names())
        for dev in engine.devices:
            info = registry.get_by_client(dev.client_id)
            if info and info.stable_id not in names:
                names[info.stable_id] = info.name
        config.data["device_names"] = names
        if engine._plugin_host:
            config.data["plugins"] = engine._plugin_host.serialize_instances()

    # Debounced rolling autosave: resume the last edited state on boot,
    # incl. after a hard power cut. Polls engine._change_seq; writes a
    # ping-pong snapshot once edits settle, rate-capped. flush() is used
    # by the shutdown path so a clean stop loses nothing.
    autosaver = _Autosaver(engine, config, _snapshot_into_config)
    engine._autosaver = autosaver
    asyncio.get_event_loop().create_task(autosaver.run())

    # MIDI Learn — armed state for the CC binding popup. Keyed by
    # learn_id (UUID). Values: {instance_id, param, timeout_task}.
    # The first inbound CONTROLLER event after arming fires SSE
    # cc_learn_result and drops the entry. 30 s timeout fires SSE
    # cc_learn_timeout and also drops the entry. Learn observes
    # every CC on any source — not gated by routing to the plugin —
    # so a user binding Arp 1 → Rate can move ANY knob on ANY
    # controller routed to the Pi to capture it.
    cc_learn_armed: dict[str, dict] = {}
    cc_learn_loop = asyncio.get_event_loop()

    from .alsa_seq import MidiEventType as _MidiEventType

    def _cc_learn_observe(ev) -> None:
        if not cc_learn_armed:
            return
        if ev.type != int(_MidiEventType.CONTROLLER):
            return
        if ev.dest.port != engine._monitor_port:
            return
        cc_ch = ev.data.control.channel
        cc_num = ev.data.control.param
        for learn_id, entry in list(cc_learn_armed.items()):
            entry.get("timeout_task") and entry["timeout_task"].cancel()
            cc_learn_armed.pop(learn_id, None)
            asyncio.run_coroutine_threadsafe(
                server.send_sse("cc_learn_result", {
                    "learn_id": learn_id,
                    "instance_id": entry["instance_id"],
                    "param": entry["param"],
                    "ch": cc_ch,
                    "cc": cc_num,
                }),
                cc_learn_loop,
            )

    engine.on_midi_event(_cc_learn_observe)

    # Captive-portal probe access log. The phone's OS hits one of these
    # endpoints periodically to decide whether the network has internet;
    # if the response is slow or missing, the OS marks the network "no
    # internet" and after a few failures de-associates. This log makes
    # phone-disconnect post-mortem possible: grep for "captive:" and
    # the time delta + client IP correlate against hostapd's own log.
    import time as _t_cap

    def _captive_handler(path: str, body: str, status: int, content_type: str):
        async def handler(req: Request) -> Response:
            t0 = _t_cap.monotonic()
            if status == 204:
                resp = Response(status=204)
            elif content_type == "html":
                resp = Response.html(body)
            else:
                resp = Response.text(body)
            log.info("captive: %s %s %d %.1fms",
                     req.client_addr or "?", path, status,
                     (_t_cap.monotonic() - t0) * 1000.0)
            return resp
        return handler

    # OS probes that should trigger the captive flow → serve the tiny
    # landing with a link to the SPA. No JS/SSE here.
    # Substitute the hub's actual mDNS name (raspimidihub-<id>) into the
    # landing so users learn the new address on first connect.
    _captive_html = _CAPTIVE_LANDING_HTML.replace("__MDNS__", socket.gethostname())
    for p in _CAPTIVE_LANDING_PATHS:
        server.route("GET", p, summary="OS captive-portal probe: serves the "
                     "tiny landing page linking to the app.")(_captive_handler(
                         p, _captive_html, 200, "html"))
    # Windows NCSI: keep the legacy success bodies so it stays out of
    # the captive flow entirely (it has no captive UI to land on).
    for p, body in _CAPTIVE_PASSTHROUGH.items():
        server.route("GET", p, summary="Windows NCSI probe: returns the legacy "
                     "success body (stays out of the captive flow).")(
                         _captive_handler(p, body, 200, "text"))

    # ================================================================
    # GET /api/system — system info
    # ================================================================

    @server.route("GET", "/api/system", summary="Hub status: hostname, IPs, version, CPU/RAM/temp, per-core load, SSE + latency stats, ALSA port budget, MIDI 2.0 (UMP) capability.")
    async def api_system(req: Request) -> Response:
        import subprocess

        from .alsa_seq import probe_ump_support
        from .wifi import default_ap_ssid
        _ump = probe_ump_support()
        hostname = socket.gethostname()
        # The AP SSID is what the user sees in the WiFi list and the
        # header badge mirrors it. Configured name wins; else the
        # RaspiMIDIHub-<MAC suffix> default.
        ap_ssid = config.wifi.get("ap_ssid") or default_ap_ssid()

        # IP addresses
        ips = []
        try:
            for iface in os.listdir("/sys/class/net"):
                if iface == "lo":
                    continue
                result = subprocess.run(
                    ["ip", "-4", "addr", "show", iface],
                    capture_output=True, text=True, timeout=2
                )
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("inet "):
                        ips.append({"interface": iface, "address": line.split()[1].split("/")[0]})
        except Exception:
            pass

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
        from . import cpu_affinity
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
            "uptime_seconds": uptime, "load1": load1,
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
        from . import cpu_affinity, perf_stats
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
        from . import perf_stats
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
        })

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

    @server.route("POST", "/api/devices/", exact=False, summary="Per-device actions: rename, rename-port, clock-source toggle, force-midi1 toggle, or send a test MIDI message.")
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
            _invalidate_instances_cache()
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
                from .alsa_seq import MidiEventType, SndSeqEvent
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
        from . import perf_stats
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
        from . import perf_stats
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
        # Gather live engine state, then persist + drop a rolling backup
        # checkpoint (with an auto diff summary) in the same rw window.
        _snapshot_into_config()
        if await config.asave(make_backup=True):
            engine.clear_dirty()
            return Response.json({"status": "saved"})
        return Response.error("Failed to save config", 500)

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
        import subprocess
        asyncio.get_event_loop().call_later(1, lambda: subprocess.Popen(["sudo", "reboot"]))
        return Response.json({"status": "rebooting"})

    # ================================================================
    # POST /api/system/factory-reset — wipe to defaults, keep backups +
    # WiFi, then reboot clean. Recoverable via Settings → Backup.
    # ================================================================

    @server.route("POST", "/api/system/factory-reset", summary="Wipe config to defaults (keeps backups and WiFi), then reboot clean.")
    async def api_factory_reset(req: Request) -> Response:
        import subprocess
        # Silence autosave first: the shutdown flush would otherwise
        # recreate the resume snapshot from the still-live old engine
        # state and undo the reset on the next boot.
        autosaver.disable()
        ok = await config.afactory_reset(keep_wifi=True)
        if not ok:
            return Response.error("Factory reset failed — see the hub log.")
        # Reboot so the appliance comes up clean from the reset config.
        asyncio.get_event_loop().call_later(1, lambda: subprocess.Popen(["sudo", "reboot"]))
        return Response.json({"status": "reset"})

    # ================================================================
    # Phase 5.5 update flow: orchestrator-backed check & install
    #
    # Check: WiFi dance → fetch release list + download newer debs →
    # back to AP. Stored debs sit in /var/lib/raspimidihub/updates so
    # the user can downgrade offline.
    #
    # Install: peeks the deb's Depends. If every dep is already
    # satisfied (typical for downgrades) the install runs offline, no
    # WiFi dance. If any dep is missing (typical for upgrades that
    # add new packages, e.g. python3-dbus-next for BLE-MIDI) the
    # install is wrapped in UpdateFetcher.run() so the same dance
    # used by the check makes apt come back online for the dep fetch.
    # `apt install <path.deb>` then resolves and pulls anything
    # missing transparently.
    #
    # All kickoffs return immediately (the orchestrator runs as a
    # backgrounded asyncio task) — otherwise switching WiFi tears
    # down the AP and would kill the held-open HTTP request from a
    # phone. The UI polls GET /api/system/update-status and silently
    # absorbs fetches that fail during the AP outage.
    # ================================================================

    # One in-flight orchestrator task at a time; second click returns
    # 409 so the UI can ignore it without erroring out.
    in_flight_check: list = [None]

    @server.route("POST", "/api/system/check-update", summary="Check GitHub for a newer release and download it (runs in the background).")
    async def api_check_update(req: Request) -> Response:
        if wifi is None:
            return Response.error("WiFi manager unavailable", 503)
        if in_flight_check[0] and not in_flight_check[0].done():
            return Response.error("Update check already running", 409)

        fetcher = UpdateFetcher(wifi, config)

        include_pre = bool(
            config.data.get("updates", {}).get("include_prereleases", False))

        async def run_orchestrator():
            try:
                await fetcher.run(
                    lambda: download_newer_releases(
                        __version__, include_prereleases=include_pre),
                    version_label="check",
                )
            except NoInternetError:
                # _abort already wrote the actionable status — UI sees it.
                pass
            except Exception as e:
                log.exception("check-update failed")
                write_status({"step": "error", "message": str(e)})

        write_status({"step": "starting", "version": "check"})
        in_flight_check[0] = asyncio.get_event_loop().create_task(run_orchestrator())
        return Response.json({"status": "started"})

    @server.route("GET", "/api/system/versions", summary="List downloaded release debs (newest first) plus the running version.")
    async def api_system_versions(req: Request) -> Response:
        """List stored debs (newest first) plus the running version so
        the UI can mark which one's currently installed. Also returns
        the prerelease-channel toggle so the Settings card can render
        its state without a separate fetch."""
        return Response.json({
            "running": __version__,
            "stored": list_stored_versions(),
            "include_prereleases": bool(
                config.data.get("updates", {}).get("include_prereleases", False)),
        })

    @server.route("POST", "/api/system/include-prereleases", summary="Toggle whether update checks consider GitHub pre-releases.")
    async def api_set_include_prereleases(req: Request) -> Response:
        """Toggle whether `download_newer_releases` considers GitHub
        releases marked as prerelease (alpha / beta tags). Persists in
        config.data["updates"]["include_prereleases"]; takes effect on
        the next check-update click — does not retroactively download
        previously-skipped prereleases."""
        enabled = bool(req.json.get("enabled", False))
        updates_cfg = config.data.setdefault("updates", {})
        updates_cfg["include_prereleases"] = enabled
        await config.asave()
        return Response.json({"status": "ok", "include_prereleases": enabled})

    def _deb_unmet_deps(deb_path: str) -> list[str]:
        """Return the list of Depends in the deb that aren't satisfied
        on the current system. Empty list = the install can run fully
        offline."""
        try:
            depends_raw = subprocess.run(
                ["dpkg-deb", "-f", deb_path, "Depends"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except Exception:
            return []  # can't tell — let apt sort it out
        if not depends_raw:
            return []
        # dpkg's Depends syntax: "pkg1 (>= 1.0), pkg2 | pkg3, pkg4".
        # We're looking for any clause where NONE of the alternatives
        # is installed; version constraints are best-effort (we just
        # check pkg presence — apt will reject version mismatches
        # later, but those only happen on a corrupted system).
        unmet: list[str] = []
        for clause in depends_raw.split(","):
            alts = [a.strip().split()[0] for a in clause.split("|") if a.strip()]
            if not alts:
                continue
            # Strip ${...} substvars resolved at build time.
            alts = [a for a in alts if not a.startswith("${")]
            if not alts:
                continue
            satisfied = False
            for alt in alts:
                rc = subprocess.run(
                    ["dpkg-query", "-W", "-f=${Status}", alt],
                    capture_output=True, text=True, timeout=5,
                ).stdout
                if "install ok installed" in rc:
                    satisfied = True
                    break
            if not satisfied:
                unmet.append(clause.strip())
        return unmet

    @server.route("POST", "/api/system/install", summary="Install a previously-downloaded release deb. Body: {version}.")
    async def api_system_install(req: Request) -> Response:
        """Install a previously-downloaded deb. Body: {version: "X.Y.Z"}.

        If the deb has unmet deps, the install runs through
        UpdateFetcher so a transient WiFi switch happens automatically
        and apt can fetch them. Otherwise the install runs offline —
        no AP outage, no dance. Returns immediately (the install is
        backgrounded) because dpkg restarts raspimidihub.service mid-
        flight."""
        version = req.json.get("version", "")
        if not version:
            return Response.error("version required")
        match = next((v for v in list_stored_versions()
                      if v["version"] == version), None)
        if match is None:
            return Response.error(f"Version {version} not in storage", 404)
        if not INSTALL_DEB_SCRIPT.is_file():
            return Response.error("Install script missing", 500)

        unmet = _deb_unmet_deps(match["deb_path"])
        log.info("install %s: unmet deps = %r", version, unmet)

        if not unmet:
            # Offline-capable path: run the install script directly.
            write_status({"step": "installing", "version": version})
            subprocess.Popen(
                [str(INSTALL_DEB_SCRIPT), match["deb_path"]],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return Response.json({
                "status": "started", "version": version, "online": False,
            })

        # Online-required path: wrap the install in the UpdateFetcher
        # so the same WiFi dance used by check-update kicks in.
        if wifi is None:
            return Response.error(
                "Install needs network for new deps but WiFi manager "
                "is unavailable", 503)
        if in_flight_check[0] and not in_flight_check[0].done():
            return Response.error(
                "Update flow already running", 409)

        async def install_work():
            # The install script is blocking; run it in the executor
            # so the orchestrator's status pump keeps moving. The
            # script itself updates the status JSON ("installing" /
            # "done" / "error-install"), so we just need to await it.
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [str(INSTALL_DEB_SCRIPT), match["deb_path"]],
                    capture_output=True),
            )

        fetcher = UpdateFetcher(wifi, config)

        async def run_orchestrator():
            try:
                await fetcher.run(install_work, version_label=version)
            except NoInternetError:
                # _abort already wrote the actionable status.
                pass
            except Exception as e:
                log.exception("install %s failed", version)
                write_status({"step": "error-install",
                              "version": version, "message": str(e)})

        write_status({"step": "starting", "version": version})
        in_flight_check[0] = asyncio.get_event_loop().create_task(
            run_orchestrator())
        return Response.json({
            "status": "started", "version": version, "online": True,
            "unmet_deps": unmet,
        })

    @server.route("POST", "/api/system/reinstall", summary="Reinstall the currently-running version (apt reinstall).")
    async def api_system_reinstall(req: Request) -> Response:
        """Reinstall the currently-running version with apt's
        Recommends pulled in. Used to recover from upgrades that came
        via the old `dpkg -i` path: those skip Recommends, so the
        BLE-MIDI bridge silently has no python3-dbus-next on it.
        Always routes through UpdateFetcher because the whole point
        is to fetch missing optional packages — needs network."""
        match = next((v for v in list_stored_versions()
                      if v["version"] == __version__), None)
        if match is None:
            return Response.error(
                f"No stored deb for the running version ({__version__}). "
                "Run check-for-updates first to download it.", 404)
        if not INSTALL_DEB_SCRIPT.is_file():
            return Response.error("Install script missing", 500)
        if wifi is None:
            return Response.error("WiFi manager unavailable", 503)
        if in_flight_check[0] and not in_flight_check[0].done():
            return Response.error("Update flow already running", 409)

        async def reinstall_work():
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [str(INSTALL_DEB_SCRIPT), match["deb_path"], "--reinstall"],
                    capture_output=True),
            )

        fetcher = UpdateFetcher(wifi, config)

        async def run_orchestrator():
            try:
                await fetcher.run(reinstall_work, version_label=__version__)
            except NoInternetError:
                pass
            except Exception as e:
                log.exception("reinstall failed")
                write_status({"step": "error-install",
                              "version": __version__, "message": str(e)})

        write_status({"step": "starting", "version": __version__})
        in_flight_check[0] = asyncio.get_event_loop().create_task(
            run_orchestrator())
        return Response.json({"status": "started", "version": __version__})

    @server.route("GET", "/api/system/update-status", summary="Live state of the current update flow (the UI polls this for progress).")
    async def api_update_status(req: Request) -> Response:
        """Live state of the most recent update flow. UI polls this for
        progress + post-mortem error messages. Always returns running
        version so the UI can detect a successful self-restart after
        an install."""
        return Response.json({"status": read_status(), "version": __version__})

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
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, engine._plugin_host.restore_instances, saved_plugins)
            _invalidate_instances_cache()
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

    # ================================================================
    # Network API
    # ================================================================

    from .wifi import configure_interface, get_all_interfaces

    @server.route("GET", "/api/network", summary="List network interfaces and their IPv4 configuration.")
    async def api_network(req: Request) -> Response:
        loop = asyncio.get_event_loop()
        interfaces = await loop.run_in_executor(None, get_all_interfaces)
        return Response.json(interfaces)

    @server.route("GET", "/api/network/usb-tether", summary="Report USB-tether (phone internet-sharing) status.")
    async def api_usb_tether(req: Request) -> Response:
        from .usb_tether import detect_tether
        loop = asyncio.get_event_loop()
        state = await loop.run_in_executor(None, detect_tether)
        return Response.json(state)

    @server.route("POST", "/api/network/", exact=False, summary="Configure an interface's IPv4 (auto/DHCP or manual static).")
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
        # A 169.254.x.x link-local is never a valid static IP. It's the
        # fallback eth0 carries when the cable is unplugged; refusing it
        # here stops a stale form prefill from clobbering the real static
        # address with the link-local.
        if method == "manual" and address.startswith("169.254."):
            return Response.error(
                "link-local (169.254.x.x) cannot be used as a static IP")

        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, configure_interface,
                                         iface, method, address, netmask, gateway)
        if ok:
            return Response.json({"status": "configured", "interface": iface})
        return Response.error("Failed to configure interface", 500)

    # ================================================================
    # Bluetooth MIDI API
    # ================================================================
    # The only static gate is whether a manager object exists at all
    # (the import succeeded). Everything else — radio powered, bluealsa
    # on PATH, dbus-next importable — is re-checked *live on each GET*
    # via availability(), not frozen at startup. This matters because
    # the radio can settle to `Powered: yes` slightly after we boot
    # (notably the Pi 3 B+, whose BCM firmware-patch path is slower):
    # a one-shot check at startup could catch it mid-power-on, cache
    # `no-bt-radio`, and hide the BT UI for the whole process lifetime
    # even though the radio came up fine moments later. Re-checking per
    # request lets the UI self-heal — the next time the Add overlay
    # re-fetches /api/bluetooth, it sees the now-powered radio. The
    # check is read-only when the radio is already powered (it only
    # issues `power on` from the *off* state, so it never disturbs a
    # live BLE-MIDI link), but it shells out to bluetoothctl with up to
    # ~5s of timeouts, so run it off-loop to keep routing/SSE smooth.
    # Bare GET /api/bluetooth always returns a payload so the UI can
    # render an "unsupported on this hardware" hint without polling 404s.

    if bluetooth:
        async def _bt_availability() -> dict:
            return await asyncio.to_thread(bluetooth.availability)

        @server.route("GET", "/api/bluetooth", summary="List paired Bluetooth-MIDI devices and radio availability.")
        async def api_bluetooth_status(req: Request) -> Response:
            avail = await _bt_availability()
            if not avail["available"]:
                return Response.json({
                    "available": False,
                    "reason": avail.get("reason"),
                    "devices": [],
                })
            devices = await bluetooth.get_paired_devices()
            return Response.json({"available": True, "devices": devices})

        @server.route("POST", "/api/bluetooth/scan", summary="Scan for nearby Bluetooth-MIDI devices (~10s).")
        async def api_bluetooth_scan(req: Request) -> Response:
            devices = await bluetooth.scan(timeout=10)
            return Response.json(devices)

        from .device_id import invalidate_bluealsa_macs_cache

        @server.route("POST", "/api/bluetooth/pair", summary="Pair a Bluetooth-MIDI device by address.")
        async def api_bluetooth_pair(req: Request) -> Response:
            address = req.json.get("address", "")
            if not address:
                return Response.error("address required")
            ok = await bluetooth.pair(address)
            invalidate_bluealsa_macs_cache()
            if ok:
                # Brief settle + kick a device-connected SSE so the
                # matrix re-fetches /api/devices and picks up the
                # new BLE-MIDI port.
                await asyncio.sleep(2)
                await server.send_sse("device-connected", {})
                return Response.json({"status": "paired"})
            return Response.error("Pairing failed", 502)

        @server.route("POST", "/api/bluetooth/connect", summary="Connect a paired Bluetooth-MIDI device by address.")
        async def api_bluetooth_connect(req: Request) -> Response:
            address = req.json.get("address", "")
            if not address:
                return Response.error("address required")
            ok = await bluetooth.connect(address)
            invalidate_bluealsa_macs_cache()
            if ok:
                # Hotplug detection on the ALSA seq fd already fires
                # device-connected when bluetoothd publishes its seq
                # client, so we don't need to sit on a sleep here.
                # Send one anyway as a belt-and-braces nudge.
                await server.send_sse("device-connected", {})
                return Response.json({"status": "connected"})
            return Response.error("Connection failed", 502)

        @server.route("POST", "/api/bluetooth/disconnect", summary="Disconnect a Bluetooth-MIDI device by address.")
        async def api_bluetooth_disconnect(req: Request) -> Response:
            address = req.json.get("address", "")
            if not address:
                return Response.error("address required")
            await bluetooth.disconnect(address)
            invalidate_bluealsa_macs_cache()
            await server.send_sse("device-disconnected", {})
            return Response.json({"status": "disconnected"})

        @server.route("DELETE", "/api/bluetooth/", exact=False, summary="Forget (unpair) a Bluetooth-MIDI device by address.")
        async def api_bluetooth_forget(req: Request) -> Response:
            address = req.path_param("/api/bluetooth/")
            if not address:
                return Response.error("address required")
            await bluetooth.forget(address)
            invalidate_bluealsa_macs_cache()
            await server.send_sse("device-disconnected", {})
            return Response.json({"status": "removed"})
    else:
        @server.route("GET", "/api/bluetooth", summary="List paired Bluetooth-MIDI devices and radio availability.")
        async def api_bluetooth_unavailable(req: Request) -> Response:
            return Response.json({
                "available": False,
                "reason": "no-bluetooth-manager",
                "devices": [],
            })

    # ================================================================
    # Network MIDI API (RTP-MIDI hub-to-hub link + standard clients)
    # ================================================================
    # Gated like Bluetooth: routes exist only when python3-zeroconf is
    # importable; the bare GET always answers so the Settings page can
    # render an "unsupported" hint without polling 404s. All settings
    # here are appliance settings (wifi pattern): mutate config +
    # asave() immediately, no dirty/asterisk.

    nm_avail = network_midi.availability() if network_midi else \
        {"available": False, "reason": "no-network-midi-manager"}
    if network_midi and nm_avail["available"]:
        @server.route("GET", "/api/network-midi", summary="Network-MIDI (RTP) status: exports, discovered sessions, mirrors, and peers.")
        async def api_network_midi(req: Request) -> Response:
            return Response.json(network_midi.status())

        @server.route("POST", "/api/network-midi/enable", summary="Enable or disable network-MIDI (RTP) on the hub.")
        async def api_network_midi_enable(req: Request) -> Response:
            enabled = bool(req.json.get("enabled"))
            config.data.setdefault("network_midi", {})["enabled"] = enabled
            await config.asave()
            # config.json holds the setting, but the autosave slot is
            # what boot resumes from — and a settings-only change never
            # bumps the engine change-seq, so the debounced autosaver
            # would never refresh it. Force a resume-snapshot now so the
            # toggle survives a reboot (same rule as Load/Restore/Import).
            await autosaver.autosave_now()
            await network_midi.set_enabled(enabled)
            return Response.json({"status": "saved", "enabled": enabled})

        @server.route("POST", "/api/network-midi/export", summary="Export (or stop exporting) a device over network-MIDI by stable_id.")
        async def api_network_midi_export(req: Request) -> Response:
            stable_id = req.json.get("stable_id", "")
            exported = bool(req.json.get("exported"))
            if not stable_id:
                return Response.error("stable_id required")
            if exported:
                ok, reason = network_midi.is_exportable(stable_id)
                if not ok:
                    return Response.error(reason)
            cfg = config.data.setdefault("network_midi", {})
            current = cfg.setdefault("exported", [])
            if exported and stable_id not in current:
                current.append(stable_id)
            elif not exported and stable_id in current:
                current.remove(stable_id)
            await config.asave()
            await autosaver.autosave_now()  # keep the resume snapshot in sync
            await network_midi.set_export(stable_id, exported)
            return Response.json({"status": "saved"})

        @server.route("POST", "/api/network-midi/mirror", summary="Mirror a discovered network-MIDI session as a local device.")
        async def api_network_midi_mirror(req: Request) -> Response:
            key = req.json.get("service") or req.json.get("stable_id", "")
            svc = network_midi.service_for(key)
            if svc is None:
                return Response.error(
                    f"Session not found ({ERR_SESSION_NOT_FOUND}).")
            cfg = config.data.setdefault("network_midi", {})
            if svc.is_hub:
                # Hub sessions auto-mirror; "mirror" = clear the opt-out.
                disabled = cfg.setdefault("mirror_disabled", [])
                if svc.service in disabled:
                    disabled.remove(svc.service)
            else:
                added = cfg.setdefault("mirrored_foreign", [])
                if svc.service not in added:
                    added.append(svc.service)
            await config.asave()
            await autosaver.autosave_now()  # keep the resume snapshot in sync
            # The config entry above records the *intent* (the policy
            # retries when the peer re-advertises); a failure here means
            # it isn't live yet, so report the diagnostic code rather
            # than claim success.
            err = await network_midi.set_mirrored(svc.service, True)
            if err:
                return Response.error(
                    f"Could not mirror this device ({err}). "
                    f"See the hub log for details.")
            await server.send_sse("device-connected", {})
            return Response.json({"status": "mirrored"})

        @server.route("POST", "/api/network-midi/unmirror", summary="Stop mirroring a network-MIDI session.")
        async def api_network_midi_unmirror(req: Request) -> Response:
            key = req.json.get("service") or req.json.get("stable_id", "")
            svc = network_midi.service_for(key)
            if svc is None:
                return Response.error(
                    f"Session not found ({ERR_SESSION_NOT_FOUND}).")
            cfg = config.data.setdefault("network_midi", {})
            if svc.is_hub:
                disabled = cfg.setdefault("mirror_disabled", [])
                if svc.service not in disabled:
                    disabled.append(svc.service)
            else:
                added = cfg.setdefault("mirrored_foreign", [])
                if svc.service in added:
                    added.remove(svc.service)
            await config.asave()
            await autosaver.autosave_now()  # keep the resume snapshot in sync
            await network_midi.set_mirrored(svc.service, False)
            await server.send_sse("device-disconnected", {})
            return Response.json({"status": "unmirrored"})

        @server.route("POST", "/api/network-midi/peers", summary="Add a manual network-MIDI peer host (discovery fallback).")
        async def api_network_midi_peer_add(req: Request) -> Response:
            host = (req.json.get("host") or "").strip()
            if not host:
                return Response.error("host required")
            cfg = config.data.setdefault("network_midi", {})
            peers = cfg.setdefault("manual_peers", [])
            if host not in peers:
                peers.append(host)
                await config.asave()
                await autosaver.autosave_now()  # keep resume snapshot in sync
            return Response.json({"status": "added"})

        @server.route("DELETE", "/api/network-midi/peers/", exact=False, summary="Remove a manual network-MIDI peer host.")
        async def api_network_midi_peer_remove(req: Request) -> Response:
            host = req.path_param("/api/network-midi/peers/")
            if not host:
                return Response.error("host required")
            cfg = config.data.setdefault("network_midi", {})
            peers = cfg.setdefault("manual_peers", [])
            if host in peers:
                peers.remove(host)
                await config.asave()
                await autosaver.autosave_now()  # keep resume snapshot in sync
            return Response.json({"status": "removed"})
    else:
        @server.route("GET", "/api/network-midi", summary="Network-MIDI (RTP) status: exports, discovered sessions, mirrors, and peers.")
        async def api_network_midi_unavailable(req: Request) -> Response:
            return Response.json({
                "available": False,
                "reason": nm_avail.get("reason"),
                "exports": [],
            })

    # ================================================================
    # WiFi API
    # ================================================================

    if wifi is None:
        return

    @server.route("GET", "/api/wifi", summary="WiFi status: mode, SSID, IP, saved home-WiFi SSID, AP band/country, 5 GHz support.")
    async def api_wifi_status(req: Request) -> Response:
        # Expose the saved update-WiFi SSID (NOT the password) so the
        # Settings UI can show "Update WiFi: HomeWiFi - change?" without
        # the user re-entering it on every visit. wifi_mode_pref drives
        # the AP-only / WiFi-for-updates / WiFi-always radio.
        from .wifi import WifiManager
        loop = asyncio.get_event_loop()
        band_5ghz_supported = await loop.run_in_executor(
            None, WifiManager.radio_supports_5ghz)
        resolved_country = await loop.run_in_executor(
            None, WifiManager._resolve_country, config.wifi.get("ap_country", ""))
        return Response.json({
            "mode": wifi.mode,
            "ssid": wifi.ssid,
            "ip": wifi.ip,
            "saved_client_ssid": config.wifi.get("client_ssid", ""),
            "wifi_mode_pref": config.wifi.get("wifi_mode_pref", "ap_only"),
            "ap_band": config.wifi.get("ap_band", "2.4"),
            "ap_country": config.wifi.get("ap_country", ""),
            "resolved_country": resolved_country,
            "band_5ghz_supported": band_5ghz_supported,
        })

    # ----- Home WiFi credentials --------------------------------------
    #
    # The Pi's "home WiFi" is the network it can briefly join (or stay on
    # permanently) to reach the public internet. Saved as a pair of
    # SSID + password in the persistent config; the actual mode flip is
    # decided by `wifi_mode_pref` and the apply-mode endpoint, NOT by
    # saving credentials. So this endpoint is data-only — no live
    # network changes.
    @server.route("POST", "/api/wifi/credentials", summary="Save or forget home-WiFi credentials (data only; no live mode change).")
    async def api_wifi_credentials(req: Request) -> Response:
        data = req.json
        cfg_wifi = config.wifi

        if data.get("action") == "forget":
            cfg_wifi["client_ssid"] = ""
            cfg_wifi["client_password"] = ""
            # Two of the three modes need credentials. Without them only
            # ap_only is meaningful, so demote silently.
            if cfg_wifi.get("wifi_mode_pref") in ("wifi_for_updates", "wifi_always"):
                cfg_wifi["wifi_mode_pref"] = "ap_only"
            await config.asave()
            await autosaver.autosave_now()  # keep the resume snapshot in sync
            return Response.json({"status": "forgotten"})

        ssid = data.get("ssid", "").strip()
        if not ssid:
            return Response.error("SSID required")
        cfg_wifi["client_ssid"] = ssid
        # Empty password = keep existing (so the user can change SSID
        # without re-typing the password).
        if "password" in data and data["password"] != "":
            cfg_wifi["client_password"] = data["password"]
        await config.asave()
        await autosaver.autosave_now()  # keep the resume snapshot in sync
        return Response.json({"status": "saved", "ssid": ssid})

    @server.route("POST", "/api/wifi/ap-password", summary="Change the access-point password (existing connections survive).")
    async def api_wifi_ap_password(req: Request) -> Response:
        """Change the AP password without flipping modes. Existing
        connections survive (PSK is checked at association, not per
        packet); new connections need the new password."""
        password = req.json.get("password", "")
        if len(password) < 8:
            return Response.error("Password must be at least 8 characters")
        try:
            wifi.set_ap_password(password)
        except ValueError as e:
            return Response.error(str(e))
        config.wifi["ap_password"] = password
        await config.asave()
        await autosaver.autosave_now()  # keep the resume snapshot in sync
        return Response.json({"status": "saved"})

    @server.route("POST", "/api/wifi/ap-radio", summary="Set the AP radio band (2.4/5 GHz) and country, restarting the AP to apply.")
    async def api_wifi_ap_radio(req: Request) -> Response:
        """Set the AP radio band (2.4 / 5 GHz) and regulatory country,
        then restart the AP to apply. Restarting drops wlan0, which would
        kill a phone's held-open request, so the restart runs as a
        backgrounded task — same pattern as apply-mode. 5 GHz on a
        2.4-only radio is rejected up front; a 5 GHz bring-up that fails
        later still self-heals to 2.4 inside start_ap."""
        data = req.json
        band = str(data.get("band", "")).strip()
        country = str(data.get("country", "")).strip().upper()
        if band not in ("2.4", "5"):
            return Response.error("band must be '2.4' or '5'")
        if country and not (len(country) == 2 and country.isalpha()):
            return Response.error(
                "country must be a 2-letter ISO code (or empty for auto)")
        loop = asyncio.get_event_loop()
        if band == "5":
            from .wifi import WifiManager
            if not await loop.run_in_executor(
                    None, WifiManager.radio_supports_5ghz):
                return Response.error(
                    "This Pi's radio does not support 5 GHz", 400)
        cfg_wifi = config.wifi
        cfg_wifi["ap_band"] = band
        cfg_wifi["ap_country"] = country
        await config.asave()
        await autosaver.autosave_now()  # appliance setting — keep resume snapshot
        # Only restart when actually in AP mode; in client mode the new
        # band applies the next time the AP comes up.
        if wifi.mode != "ap":
            return Response.json({"status": "saved", "switched": False})
        ap_ssid = cfg_wifi.get("ap_ssid", "")
        ap_password = cfg_wifi.get("ap_password", "midihub1")

        async def restart():
            try:
                await loop.run_in_executor(
                    None, wifi.start_ap, ap_ssid, ap_password, band, country)
            except Exception:
                log.exception("ap-radio restart failed")

        loop.create_task(restart())
        return Response.json({"status": "saved", "switched": True, "band": band})

    # The mode-pref is the only thing that drives the live wlan0 state.
    # Apply saves the pref and triggers the underlying mode flip (if
    # any) as a backgrounded asyncio task — same reason as
    # /api/system/check-update: switching to client mode tears down the
    # AP and would kill any held-open HTTP request from a phone.
    @server.route("POST", "/api/wifi/apply-mode", summary="Set the WiFi mode (ap_only / wifi_for_updates / wifi_always) and flip wlan0 if needed.")
    async def api_wifi_apply_mode(req: Request) -> Response:
        pref = req.json.get("pref", "")
        if pref not in ("ap_only", "wifi_for_updates", "wifi_always"):
            return Response.error("invalid pref")
        cfg_wifi = config.wifi
        saved_ssid = cfg_wifi.get("client_ssid", "")
        if pref in ("wifi_for_updates", "wifi_always") and not saved_ssid:
            return Response.error(
                "Save home WiFi credentials before selecting this mode")

        cfg_wifi["wifi_mode_pref"] = pref
        await config.asave()
        # Appliance setting (not a MIDI edit), so it never bumps the dirty
        # counter — without forcing the autosave here, boot would prefer a
        # staler resume snapshot and the mode would revert to ap_only on the
        # next restart/update. Mirrors the network_midi endpoints.
        await autosaver.autosave_now()

        # Decide whether the live wlan0 mode needs to change. Only two
        # of the four (current_mode, target_pref) combinations are
        # disruptive: AP→client (going to wifi_always) and client→AP
        # (leaving wifi_always).
        target_live = "client" if pref == "wifi_always" else "ap"
        if wifi.mode == target_live:
            return Response.json({"status": "saved", "switched": False})

        loop = asyncio.get_event_loop()
        ap_ssid = cfg_wifi.get("ap_ssid", "")
        ap_password = cfg_wifi.get("ap_password", "midihub1")
        client_password = cfg_wifi.get("client_password", "")

        async def switch():
            try:
                if target_live == "client":
                    await wifi.start_client_with_fallback(
                        saved_ssid, client_password, ap_ssid, ap_password)
                else:
                    await loop.run_in_executor(
                        None, wifi.start_ap, ap_ssid, ap_password,
                        cfg_wifi.get("ap_band", "2.4"),
                        cfg_wifi.get("ap_country", ""))
            except Exception:
                log.exception("apply-mode switch failed")

        loop.create_task(switch())
        return Response.json({"status": "saved", "switched": True,
                              "target_mode": target_live})

    @server.route("GET", "/api/wifi/scan", summary="Scan for nearby WiFi networks.")
    async def api_wifi_scan(req: Request) -> Response:
        loop = asyncio.get_event_loop()
        networks = await loop.run_in_executor(None, wifi.scan_networks)
        return Response.json(networks)

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

    # 500 ms TTL cache for the list endpoint. The contents only change
    # on plugin add / remove / rename — but those mutations explicitly
    # invalidate the cache (see _invalidate_instances_cache below) so
    # the dropdown always reflects the latest state immediately. The
    # cache exists to protect the server from a buggy / stale-cached
    # frontend re-fetching /plugins/instances on every render (we've
    # been bitten by that loop). Pre-encoded bytes mean cache hits
    # skip json.dumps too.
    import time as _time
    _instances_cache = {"body": None, "ts": 0.0}

    def _invalidate_instances_cache():
        """Drop the cached body so the next GET rebuilds from live state.
        Called after any mutation that changes the list (create, delete,
        rename, status change)."""
        _instances_cache["body"] = None
        _instances_cache["ts"] = 0.0

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
        if _instances_cache["body"] is not None and now - _instances_cache["ts"] < 0.5:
            return Response(
                status=200, body=_instances_cache["body"],
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
        _instances_cache["body"] = body
        _instances_cache["ts"] = now
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
            loop = asyncio.get_event_loop()
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

        _invalidate_instances_cache()
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
        loop = asyncio.get_event_loop()
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
            _invalidate_instances_cache()
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

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, engine._plugin_host.stop_instance, instance_id)

        # Drop only this client's subscriptions; leave everything else
        # alone so clock and MIDI through other plugins keep flowing.
        if gone_client_id >= 0:
            engine.handle_plugin_removed(gone_client_id)
        else:
            engine.handle_plugin_added()  # fall back to a plain refresh

        _invalidate_instances_cache()
        engine.mark_dirty()
        await server.send_sse("plugin-changed", {"instance_id": instance_id})
        return Response.json({"status": "deleted"})
