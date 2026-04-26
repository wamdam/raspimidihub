"""RaspiMIDIHub entry point.

Usage: python3 -m raspimidihub
"""

import asyncio
import logging
import os
import signal
import sys

from . import __version__
from .api import register_api
from .config import Config
from .led import LedController
from .midi_engine import MidiEngine
from .plugin_host import PluginHost
from .runtime.loops import (
    loop_lag_meter,
    pending_param_flusher,
    rate_meter,
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

    # Register API routes
    register_api(server, engine, config, wifi)

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

        # Latency probe: lets the engine record userspace-routed
        # midi-in→midi-out into the same window as loop_lag and
        # midi_in_sse_out, all visible in /api/system → Settings.
        engine._latency_cb = server.record_latency
        plugin_host._latency_cb = server.record_latency

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
                )
            except Exception:
                log.warning("WiFi AP setup failed (no wlan0?), continuing without AP")

        notify_systemd("READY=1")
        log.info("Service ready (web on port %d)", port)

        # Set up watchdog pinger
        watchdog_usec = os.environ.get("WATCHDOG_USEC")
        if watchdog_usec:
            interval = int(watchdog_usec) / 1_000_000 / 2
            asyncio.ensure_future(watchdog_ping(interval, notify_systemd))

        # WiFi client mode watchdog — fall back to AP if connection lost
        asyncio.ensure_future(wifi_watchdog(wifi, config, server))

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
        plugin_host.stop_all()
        engine.stop()
        led.set_off()
        led.restore_default_trigger()
        log.info("Shutdown complete")


def main() -> None:
    setup_logging()

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
