"""RaspiMIDIHub entry point.

Usage: python3 -m raspimidihub
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys

from . import __version__
from .api import register_api
from .config import Config
from .led import LedController
from .midi_engine import MidiEngine
from .plugin_host import PluginHost
from .runtime.loops import (
    link_local_maintainer,
    loop_lag_meter,
    pending_param_flusher,
    rate_meter,
    sse_heartbeat,
    watchdog_ping,
    wifi_watchdog,
)
from .web import WebServer
from .wifi import WifiManager

log = logging.getLogger("raspimidihub")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def pin_to_isolated_cpu() -> None:
    """Pin THIS process to the kernel-isolated CPU 3 (raspimidihub-system-prepare
    adds isolcpus=3 nohz_full=3 rcu_nocbs=3 to the kernel cmdline).

    Done at the Python-process level rather than as a systemd cgroup
    AllowedCPUs= because the latter propagates to every child process —
    including the daemonized hostapd / dnsmasq — and a hostapd pinned
    to a nohz_full core can't beacon at the right cadence, breaking
    the AP. Subprocesses raspimidihub spawns inherit affinity {3}, so
    the wifi.py spawn paths explicitly prefix `taskset -c 0-2 …` to
    place those daemons on the non-isolated cores.

    Safe no-op when the kernel didn't isolate CPU 3 (e.g. dev machine
    or pre-prepare deployment) — we just verify the target CPU is in
    the current allowed set; if not, we leave affinity alone."""
    target = {3}
    try:
        allowed = os.sched_getaffinity(0)
        if not target.issubset(allowed):
            log.info("CPU %s not in allowed set %s — skipping affinity pin",
                     sorted(target), sorted(allowed))
            return
        os.sched_setaffinity(0, target)
        log.info("Pinned to CPU %s (isolated core)", sorted(target))
    except (AttributeError, OSError) as e:
        log.info("Affinity pin not available: %s", e)


def notify_systemd(status: str) -> None:
    """Send sd_notify status if running under systemd."""
    import socket

    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr[0] == "@":
        addr = "\0" + addr[1:]
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.sendto(status.encode(), addr)
        sock.close()
    except OSError:
        pass


async def async_main() -> None:
    log.info("RaspiMIDIHub v%s starting", __version__)

    led = LedController()
    engine = MidiEngine()
    config = Config()
    wifi = WifiManager()
    plugin_host = PluginHost()

    # Load config
    config.init_runtime_copy()
    config_ok = config.load()

    # Determine web server port (80 requires root, fallback to 8080)
    port = 80 if os.geteuid() == 0 else 8080
    server = WebServer(port=port)

    # Bluetooth MIDI: unblock the radio (rfkill may have it blocked
    # at boot on some Pi-OS variants), spin up the BlueZ wrapper +
    # BLE-MIDI bridge. Both are no-ops if the host has no BT
    # hardware / dbus-next isn't installed.
    from .ble_midi_bridge import BleMidiBridge
    from .bluetooth import BluetoothMidi
    try:
        subprocess.run(["rfkill", "unblock", "bluetooth"],
                       capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    bt = BluetoothMidi()
    ble_bridge = BleMidiBridge()
    bt.ble_bridge = ble_bridge
    engine._ble_bridge = ble_bridge  # so device scans see BLE clients

    # Network MIDI: exported devices become RTP-MIDI sessions, peer
    # hubs' exports get mirrored into the matrix. No-op (available:
    # false) when python3-zeroconf isn't installed.
    from .network_midi import NetworkMidiManager
    network_midi = NetworkMidiManager(engine, config, server)
    engine._network_midi = network_midi  # device scans see mirror clients

    # Register API routes
    register_api(server, engine, config, wifi, bt, network_midi)

    # Spectator-mode mirroring service. Owns its own routes, per-conn
    # state map, and watcher tracking; plugs into the WebServer via
    # an SSE filter (for the spectator-state event), a subscribe
    # extension (to consume label/spectate_target), and a disconnect
    # handler (to clean up watcher slots). web.py / api.py stay free
    # of any spectator-specific branches.
    from .spectator import SpectatorService
    spectator = SpectatorService(server)
    server.add_sse_filter(spectator.event_filter)
    server.add_disconnect_handler(spectator.on_disconnect)
    server.add_subscribe_extension(spectator.apply_subscribe_extension)
    spectator.register_routes()

    # Wire up LED and SSE to hotplug events
    def on_change():
        led.set_hotplug_blink(duration=2.0)
        asyncio.ensure_future(server.send_sse("device-connected", {
            "devices": [d.name for d in engine.devices]
        }))

    engine.on_change(on_change)

    # MIDI event monitoring — throttled SSE for activity indicators + monitor
    import time as _time
    _last_activity: dict[str, float] = {}  # "client:port" -> last event time
    _ACTIVITY_THROTTLE = 0.1  # 10 updates/sec max per port

    _EVENT_NAMES = {
        6: "Note On", 7: "Note Off", 8: "Key Pressure",
        10: "CC", 11: "Program Change", 12: "Channel Pressure",
        13: "Pitch Bend", 36: "Clock", 30: "Start", 31: "Continue",
        32: "Stop", 130: "SysEx",
    }

    # Per-source clock counter so the UI can pulse the matrix indicator at
    # quarter-note rate (24 PPQ → emit once every 24 clocks per source).
    _clock_counts: dict[str, int] = {}

    def on_midi_event(ev):
        # Only process known MIDI events, not system/subscription events
        if ev.type not in _EVENT_NAMES:
            return
        # The engine's ALSA seq client receives copies of source events
        # at MULTIPLE ports: the monitor port (always) plus any filter
        # read-ports for routes that have a userspace MidiFilter
        # attached. Counting those copies as separate events made the
        # clock-quarter counter tick 2× per real source clock for any
        # device that had a filtered connection — visual pulsed at 8th
        # rate, ClockBus-driven plugin sync ran double-time. Restrict
        # all activity bookkeeping to the monitor port — exactly the
        # one delivery per source the engine itself uses for its own
        # rate / latency / clock-bus accounting.
        if ev.dest.port != engine.monitor_port:
            return
        # Clock: gentle heartbeat per beat; other MIDI: sharp blink
        if ev.type == 36:  # CLOCK
            led.clock_pulse()
            ckey = f"{ev.source.client}:{ev.source.port}"
            c = _clock_counts.get(ckey, 0) + 1
            if c >= 24:
                c = 0
                asyncio.ensure_future(server.send_sse("clock-quarter", {
                    "src_client": ev.source.client,
                    "src_port": ev.source.port,
                }))
            _clock_counts[ckey] = c
            # Don't broadcast a midi-activity for clock — clock-quarter
            # already drives the visual pulse, and clock at 24 PPQN ×
            # active sources is a noticeable share of SSE traffic.
            return
        elif ev.type == 30:  # START — re-phase that source's quarter counter
            _clock_counts[f"{ev.source.client}:{ev.source.port}"] = 0
        else:
            led.midi_blink()
        key = f"{ev.source.client}:{ev.source.port}"
        now = _time.monotonic()
        if now - _last_activity.get(key, 0) < _ACTIVITY_THROTTLE:
            return
        _last_activity[key] = now

        ev_name = _EVENT_NAMES[ev.type]
        data = {
            "src_client": ev.source.client,
            "src_port": ev.source.port,
            "event": ev_name,
            "channel": ev.channel + 1 if ev.type in (6,7,8,10,11,12,13) else None,
        }
        # Add note/CC specific data
        if ev.type in (6, 7, 8):  # Note events
            data["note"] = ev.data.note.note
            data["velocity"] = ev.data.note.velocity
        elif ev.type == 10:  # CC
            data["cc"] = ev.data.control.param
            data["value"] = ev.data.control.value
        # Carry the routing destinations of this (src_client, src_port)
        # so the device-detail MIDI monitor on a downstream device
        # (e.g. Mixer 8 receiving from LCXL3) can match incoming events
        # by destination, not just by source. Only the live engine
        # connections — offline / disconnected entries don't deliver
        # MIDI so they shouldn't pollute the receiver's monitor.
        dsts = set()
        for conn in engine.connections:
            if (conn.src_client == ev.source.client
                    and conn.src_port == ev.source.port):
                dsts.add(conn.dst_client)
        if dsts:
            data["dst_clients"] = sorted(dsts)

        # Latency probe: from "engine handed us this event" to "SSE
        # message put on every client queue". Captures asyncio
        # scheduling delay between ensure_future and the coroutine
        # actually running, so loop saturation shows up here too.
        t0 = _time.monotonic()
        async def _send_with_lat(d=data, t=t0):
            await server.send_sse("midi-activity", d)
            server.record_latency("midi_in_sse_out", (_time.monotonic() - t) * 1000.0)
        asyncio.ensure_future(_send_with_lat())

    engine.on_midi_event(on_midi_event)

    def on_transport_start():
        asyncio.ensure_future(server.send_sse("transport-start", {}))

    engine.on_transport_start(on_transport_start)

    try:
        # Store config ref before start() so _scan_and_connect uses saved config
        if config_ok:
            engine._config = config

        # Wire plugin host to engine
        engine._plugin_host = plugin_host
        # Plug the dirty-tracker into the plugin host's central param-change
        # signal. Has to happen AFTER engine._plugin_host is set; register_api
        # already configured engine._dirty_sse_cb earlier.
        plugin_host._on_dirty_cb = engine.mark_dirty

        # Latency probe: lets the engine record userspace-routed
        # midi-in→midi-out into the same window as loop_lag and
        # midi_in_sse_out, all visible in /api/system → Settings.
        engine._latency_cb = server.record_latency
        plugin_host._latency_cb = server.record_latency

        # Clock heartbeat → SSE. Fires on every quarter (24 ticks at
        # 24 PPQN) plus on transport changes (start / continue / stop)
        # so the frontend's always-running drop-button rings stay in
        # sync with the music AND freeze when the transport stops.
        # ClockBus runs in the asyncio thread (engine.run_event_loop
        # dispatches to it), so ensure_future is safe directly. At
        # 120 BPM that's 2 SSE / s while playing, 0 while stopped.
        def _on_quarter(tick: int, tpb: int, running: bool) -> None:
            asyncio.ensure_future(server.send_sse(
                "clock-position",
                {"tick": tick, "ticks_per_bar": tpb, "running": running}))
        plugin_host.clock_bus._on_quarter_callback = _on_quarter

        # Discover available plugins
        plugin_host.discover_plugins()

        # Wire plugin display outputs to SSE (called from plugin threads)
        _loop = asyncio.get_event_loop()
        def _on_plugin_display(instance_id, name, value):
            _loop.call_soon_threadsafe(
                asyncio.ensure_future,
                server.send_sse("plugin-display", {
                    "instance_id": instance_id, "name": name, "value": value,
                })
            )
        plugin_host._on_display_callback = _on_plugin_display

        # Wire plugin param changes to SSE (for CC automation UI).
        # No logging here — this fires for every CC mirrored from the
        # plugin host (incl. controllers reflecting an external fader),
        # so an INFO log per call generated 30+ journald writes/sec
        # under heavy MIDI input. Use DEBUG if you need to trace it.
        def _on_plugin_param_change(instance_id, name, value):
            _loop.call_soon_threadsafe(
                asyncio.ensure_future,
                server.send_sse("plugin-param", {
                    "instance_id": instance_id, "name": name, "value": value,
                })
            )
        plugin_host._on_param_change_callback = _on_plugin_param_change

        engine.start()

        # Load custom device names from config
        device_names = config.data.get("device_names", {})
        if device_names:
            engine.device_registry.load_custom_names(device_names)

        # Load per-device clock-source veto from config. List of
        # stable_ids whose Clock / Start / Stop won't feed the bus.
        engine.device_registry.load_clock_blocked(
            config.data.get("device_clock_blocked", []))

        # Restore plugin instances from config BEFORE the initial scan so plugin
        # ALSA clients are visible when saved connections are applied.
        saved_plugins = config.data.get("plugins", [])
        if saved_plugins:
            plugin_host.restore_instances(saved_plugins)

        # Initial device scan + apply saved config (connections, filters, mappings).
        # Runs here (not in engine.start) so plugins are already registered.
        engine._scan_and_connect()

        if not config_ok:
            led.set_fast_blink()
        else:
            led.set_steady()

        # Start web server
        await server.start()

        # One-time migration: drop a leftover NM `link-local=enabled` on
        # eth0 from pre-5.0.3 units (we now assign the link-local directly
        # with `ip`). Idempotent; no-op on clean profiles.
        try:
            from .wifi import cleanup_eth_link_local_nm_leftover
            await asyncio.get_event_loop().run_in_executor(
                None, cleanup_eth_link_local_nm_leftover)
        except Exception:
            log.warning("eth0 link-local NM cleanup skipped", exc_info=True)

        # Start WiFi AP if configured
        wifi_cfg = config.wifi
        if wifi_cfg.get("mode") == "client" and wifi_cfg.get("client_ssid"):
            log.info("WiFi: starting client mode")
            asyncio.get_event_loop()
            await wifi.start_client_with_fallback(
                wifi_cfg["client_ssid"], wifi_cfg.get("client_password", ""),
                wifi_cfg.get("ap_ssid", ""), wifi_cfg.get("ap_password", "midihub1"),
            )
        else:
            try:
                wifi.start_ap(
                    ssid=wifi_cfg.get("ap_ssid", ""),
                    password=wifi_cfg.get("ap_password", "midihub1"),
                    band=wifi_cfg.get("ap_band", "2.4"),
                    country=wifi_cfg.get("ap_country", ""),
                )
            except Exception:
                log.warning("WiFi AP setup failed (no wlan0?), continuing without AP")

        # Re-attach BLE-MIDI bridges for devices BlueZ still has
        # connected from before this process restarted, AND initiate
        # connect for paired-but-disconnected ones (BLE peripherals
        # don't auto-reconnect from the host side). Late-arrival case
        # (WIDI powered up after boot) is handled by the explicit
        # Connect button in the Add Device → Bluetooth panel — no
        # background polling.
        asyncio.ensure_future(bt.restore_connected_bridges())

        # Bring up network MIDI (if enabled in config): exports restore
        # for online devices, discovery browser starts. After the
        # initial scan so exported devices resolve to ALSA clients.
        asyncio.ensure_future(network_midi.start())

        notify_systemd("READY=1")
        log.info("Service ready (web on port %d)", port)

        # Set up watchdog pinger
        watchdog_usec = os.environ.get("WATCHDOG_USEC")
        if watchdog_usec:
            interval = int(watchdog_usec) / 1_000_000 / 2
            asyncio.ensure_future(watchdog_ping(interval, notify_systemd))

        # WiFi client mode watchdog — fall back to AP if connection lost
        asyncio.ensure_future(wifi_watchdog(wifi, config, server))

        # Keep eth0's link-local present regardless of the Network MIDI
        # toggle, so a direct hub-to-hub cable always has its 169.254.x
        # address and discovery works the moment Network MIDI is enabled
        # on both ends (no longer gated on the feature being on).
        asyncio.ensure_future(link_local_maintainer())

        # MIDI rate meter — snapshot and broadcast every second
        asyncio.ensure_future(rate_meter(engine, server))

        # asyncio loop-lag probe — single best signal for "server
        # keeping up with itself", visible as Loop lag in Settings.
        asyncio.ensure_future(loop_lag_meter(server))

        # Drain the plugin host's trailing-edge param coalescer at 20 Hz
        # so SSE plugin-param traffic stays UI-paced even under a
        # streaming hardware fader fanned out across multiple Controller
        # plugins listening on the same CC range.
        asyncio.ensure_future(pending_param_flusher(plugin_host))

        # SSE keep-alive: pushes a comment every 30 s so dead sockets
        # surface (the per-view subscription model means a connection
        # on a quiet view receives no events otherwise, and the dead
        # socket would never be detected until reconnect).
        asyncio.ensure_future(sse_heartbeat(server))

        try:
            await engine.run_event_loop()
        except asyncio.CancelledError:
            # Consume the cancellation here so the cleanup awaits below
            # don't immediately re-raise CancelledError. The task is still
            # cancelled overall — runner() in main() catches that.
            log.info("Shutdown signal received")
    except KeyboardInterrupt:
        log.info("Interrupted")
    except Exception:
        log.exception("Fatal error")
        led.set_fast_blink()
        raise
    finally:
        # Bound each cleanup step so a stuck await doesn't deadlock systemd
        # past TERMTimeoutSec.
        try:
            await asyncio.wait_for(server.stop(), timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            log.warning("Web server stop timed out")
        # BY to all RTP-MIDI participants + mDNS goodbye, so peers
        # drop the sessions instead of timing them out.
        try:
            await asyncio.wait_for(network_midi.stop(), timeout=2.0)
        except (Exception, asyncio.CancelledError):
            log.warning("Network MIDI stop failed", exc_info=True)
        # Flush a final autosave BEFORE tearing down plugins, so a clean
        # stop (deploy / reboot) resumes the exact in-memory state and the
        # snapshot still sees live plugin instances. Power cuts skip this
        # (no SIGTERM) — the periodic autosave covers those.
        try:
            autosaver = getattr(engine, "_autosaver", None)
            if autosaver is not None:
                autosaver.stop()
                autosaver.flush()
        except Exception:
            log.warning("Final autosave flush failed", exc_info=True)
        plugin_host.stop_all()
        engine.stop()
        led.set_off()
        led.restore_default_trigger()
        log.info("Shutdown complete")


def main() -> None:
    setup_logging()
    pin_to_isolated_cpu()

    async def runner() -> None:
        # Cancel the main task on SIGTERM/SIGINT so async_main's `finally`
        # block runs cleanly. Replaces the older `loop.stop()` pattern,
        # which raced background tasks and exited with a RuntimeError —
        # which systemd then mis-treated as a crash and auto-restarted.
        main_task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, main_task.cancel)
        try:
            await async_main()
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
