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
from .midi_engine import MidiEngine, Connection
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
        13: "Pitch Bend", 36: "Clock", 37: "Start", 38: "Continue",
        39: "Stop", 130: "SysEx",
    }

    def on_midi_event(ev):
        key = f"{ev.source.client}:{ev.source.port}"
        now = _time.monotonic()
        if now - _last_activity.get(key, 0) < _ACTIVITY_THROTTLE:
            return
        _last_activity[key] = now

        ev_name = _EVENT_NAMES.get(ev.type, f"type:{ev.type}")
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

        asyncio.ensure_future(server.send_sse("midi-activity", data))

    engine.on_midi_event(on_midi_event)

    try:
        engine.start()

        # Load custom device names from config
        device_names = config.data.get("device_names", {})
        if device_names:
            engine.device_registry.load_custom_names(device_names)

        # Apply saved config or fall back to all-to-all
        if config_ok and config.mode == "custom" and config.connections:
            log.info("Restoring saved routing configuration...")
            _apply_saved_config(engine, config)
        else:
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
            loop = asyncio.get_event_loop()
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
                server.enable_captive_portal("192.168.4.1")
            except Exception:
                log.warning("WiFi AP setup failed (no wlan0?), continuing without AP")

        notify_systemd("READY=1")
        log.info("Service ready (web on port %d)", port)

        # Set up watchdog pinger
        watchdog_usec = os.environ.get("WATCHDOG_USEC")
        if watchdog_usec:
            interval = int(watchdog_usec) / 1_000_000 / 2
            asyncio.ensure_future(_watchdog_ping(interval))

        await engine.run_event_loop()
    except KeyboardInterrupt:
        log.info("Interrupted")
    except Exception:
        log.exception("Fatal error")
        led.set_fast_blink()
        raise
    finally:
        await server.stop()
        engine.stop()
        led.set_off()
        led.restore_default_trigger()
        log.info("Shutdown complete")


def _apply_saved_config(engine: MidiEngine, config: Config) -> None:
    """Apply saved connections and filters from config on startup."""
    from .midi_filter import MidiFilter

    engine.scan_devices()
    saved_conns = config.connections
    applied = 0
    pending = 0

    for c in saved_conns:
        try:
            src_client = c["src_client"]
            src_port = c["src_port"]
            dst_client = c["dst_client"]
            dst_port = c["dst_port"]
        except KeyError:
            continue

        # Check if both devices are currently present
        current_clients = {d.client_id for d in engine.devices}
        if src_client not in current_clients or dst_client not in current_clients:
            pending += 1
            continue

        conn = Connection(src_client, src_port, dst_client, dst_port)

        # Check for filter
        filter_data = c.get("filter")
        if filter_data:
            midi_filter = MidiFilter.from_dict(filter_data)
            if not midi_filter.is_passthrough and engine.filter_engine:
                engine.filter_engine.add_filter(
                    src_client, src_port, dst_client, dst_port, midi_filter
                )
                engine._connections.add(conn)
                applied += 1
                continue

        # Direct ALSA subscription
        try:
            engine._seq.subscribe(src_client, src_port, dst_client, dst_port)
            engine._connections.add(conn)
            applied += 1
        except OSError as e:
            log.warning("Failed to restore connection %d:%d -> %d:%d: %s",
                        src_client, src_port, dst_client, dst_port, e)

    log.info("Config restored: %d connections applied, %d pending (devices not present)",
             applied, pending)


async def _watchdog_ping(interval: float) -> None:
    """Periodically ping the systemd watchdog."""
    while True:
        notify_systemd("WATCHDOG=1")
        await asyncio.sleep(interval)


def main() -> None:
    setup_logging()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: loop.stop())

    try:
        loop.run_until_complete(async_main())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
