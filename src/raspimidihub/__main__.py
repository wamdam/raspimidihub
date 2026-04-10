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
from .plugin_host import PluginHost
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
        13: "Pitch Bend", 36: "Clock", 37: "Start", 38: "Continue",
        39: "Stop", 130: "SysEx",
    }

    def on_midi_event(ev):
        # Only process known MIDI events, not system/subscription events
        if ev.type not in _EVENT_NAMES:
            return
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

        asyncio.ensure_future(server.send_sse("midi-activity", data))

    engine.on_midi_event(on_midi_event)

    try:
        # Store config ref before start() so _scan_and_connect uses saved config
        if config_ok:
            engine._config = config

        # Wire plugin host to engine
        engine._plugin_host = plugin_host

        # Discover available plugins
        plugin_host.discover_plugins()

        engine.start()

        # Load custom device names from config
        device_names = config.data.get("device_names", {})
        if device_names:
            engine.device_registry.load_custom_names(device_names)

        # Restore plugin instances from config
        saved_plugins = config.data.get("plugins", [])
        if saved_plugins:
            plugin_host.restore_instances(saved_plugins)
            # Rescan so plugin ALSA clients appear in the matrix
            engine._schedule_rescan()

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
            except Exception:
                log.warning("WiFi AP setup failed (no wlan0?), continuing without AP")

        notify_systemd("READY=1")
        log.info("Service ready (web on port %d)", port)

        # Set up watchdog pinger
        watchdog_usec = os.environ.get("WATCHDOG_USEC")
        if watchdog_usec:
            interval = int(watchdog_usec) / 1_000_000 / 2
            asyncio.ensure_future(_watchdog_ping(interval))

        # WiFi client mode watchdog — fall back to AP if connection lost
        asyncio.ensure_future(_wifi_watchdog(wifi, config, server))

        # MIDI rate meter — snapshot and broadcast every second
        asyncio.ensure_future(_rate_meter(engine, server))

        await engine.run_event_loop()
    except KeyboardInterrupt:
        log.info("Interrupted")
    except Exception:
        log.exception("Fatal error")
        led.set_fast_blink()
        raise
    finally:
        await server.stop()
        plugin_host.stop_all()
        engine.stop()
        led.set_off()
        led.restore_default_trigger()
        log.info("Shutdown complete")


def _apply_saved_config(engine: MidiEngine, config: Config) -> None:
    """Apply saved connections, filters, and mappings from config on startup."""
    from .midi_filter import MidiFilter, MidiMapping

    engine.scan_devices()
    registry = engine.device_registry
    saved_conns = config.connections
    applied = 0
    pending = 0

    for c in saved_conns:
        try:
            src_port = c["src_port"]
            dst_port = c["dst_port"]
        except KeyError:
            continue

        # Resolve client IDs: prefer stable IDs, fall back to raw client IDs
        src_stable = c.get("src_stable_id")
        dst_stable = c.get("dst_stable_id")

        if src_stable:
            src_client = registry.client_for_stable_id(src_stable)
        else:
            src_client = c.get("src_client")

        if dst_stable:
            dst_client = registry.client_for_stable_id(dst_stable)
        else:
            dst_client = c.get("dst_client")

        if src_client is None or dst_client is None:
            pending += 1
            continue

        # Check if both devices are currently present
        current_clients = {d.client_id for d in engine.devices}
        if src_client not in current_clients or dst_client not in current_clients:
            pending += 1
            continue

        conn = Connection(src_client, src_port, dst_client, dst_port)
        conn_id = f"{src_client}:{src_port}-{dst_client}:{dst_port}"

        filter_data = c.get("filter")
        mappings_data = c.get("mappings", [])
        needs_userspace = bool(mappings_data)

        if filter_data:
            midi_filter = MidiFilter.from_dict(filter_data)
            needs_userspace = needs_userspace or not midi_filter.is_passthrough
        else:
            midi_filter = MidiFilter()

        if needs_userspace and engine.filter_engine:
            # Remove any direct ALSA subscription that might exist
            try:
                engine._seq.unsubscribe(src_client, src_port, dst_client, dst_port)
            except OSError:
                pass
            engine.filter_engine.add_filter(
                src_client, src_port, dst_client, dst_port, midi_filter
            )
            # Restore mappings
            for md in mappings_data:
                try:
                    mapping = MidiMapping.from_dict(md)
                    engine.filter_engine.add_mapping(conn_id, mapping)
                except (ValueError, KeyError):
                    log.warning("Skipping invalid mapping on %s", conn_id)
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

    # Restore disconnected dict with saved filter/mapping data
    for c in config.disconnected:
        src_stable = c.get("src_stable_id")
        dst_stable = c.get("dst_stable_id")
        src_client = registry.client_for_stable_id(src_stable) if src_stable else None
        dst_client = registry.client_for_stable_id(dst_stable) if dst_stable else None
        if src_client is not None and dst_client is not None:
            sp = c.get("src_port", 0)
            dp = c.get("dst_port", 0)
            conn_id = f"{src_client}:{sp}-{dst_client}:{dp}"
            saved_data = {}
            if "filter" in c:
                saved_data["filter"] = c["filter"]
            if "mappings" in c:
                saved_data["mappings"] = c["mappings"]
            engine._disconnected[conn_id] = saved_data

    # Handle device pairs not in saved config: apply default_routing
    known_pairs = set()
    for c in saved_conns:
        src_stable = c.get("src_stable_id")
        dst_stable = c.get("dst_stable_id")
        if src_stable and dst_stable:
            known_pairs.add((src_stable, c.get("src_port", 0), dst_stable, c.get("dst_port", 0)))
    for c in config.disconnected:
        src_stable = c.get("src_stable_id")
        dst_stable = c.get("dst_stable_id")
        if src_stable and dst_stable:
            known_pairs.add((src_stable, c.get("src_port", 0), dst_stable, c.get("dst_port", 0)))

    if config.default_routing == "all":
        # Connect any new device pairs not covered by saved config
        for src_dev in engine.devices:
            for dst_dev in engine.devices:
                if src_dev.client_id == dst_dev.client_id:
                    continue
                for src_port in src_dev.input_ports:
                    for dst_port in dst_dev.output_ports:
                        src_info = registry.get_by_client(src_dev.client_id)
                        dst_info = registry.get_by_client(dst_dev.client_id)
                        if src_info and dst_info:
                            key = (src_info.stable_id, src_port.port_id, dst_info.stable_id, dst_port.port_id)
                            if key in known_pairs:
                                continue
                        conn = Connection(src_dev.client_id, src_port.port_id, dst_dev.client_id, dst_port.port_id)
                        if conn not in engine._connections:
                            try:
                                engine._seq.subscribe(src_dev.client_id, src_port.port_id,
                                                      dst_dev.client_id, dst_port.port_id)
                                engine._connections.add(conn)
                            except OSError:
                                pass

    log.info("Config restored: %d connections applied, %d pending (devices not present)",
             applied, pending)


async def _rate_meter(engine, server) -> None:
    """Broadcast per-port MIDI message rates every second."""
    while True:
        await asyncio.sleep(1.0)
        rates = engine.snapshot_rates()
        if rates:
            await server.send_sse("midi-rates", rates)


async def _watchdog_ping(interval: float) -> None:
    """Periodically ping the systemd watchdog."""
    while True:
        notify_systemd("WATCHDOG=1")
        await asyncio.sleep(interval)


WIFI_CHECK_INTERVAL = 30
WIFI_FAIL_THRESHOLD = 3  # consecutive failures before fallback


async def _wifi_watchdog(wifi, config, server) -> None:
    """Monitor client WiFi connection, fall back to AP if lost."""
    fail_count = 0
    while True:
        await asyncio.sleep(WIFI_CHECK_INTERVAL)
        if wifi.mode != "client":
            fail_count = 0
            continue
        if wifi.check_client_connected():
            fail_count = 0
        else:
            fail_count += 1
            log.warning("WiFi client connection check failed (%d/%d)",
                        fail_count, WIFI_FAIL_THRESHOLD)
            if fail_count >= WIFI_FAIL_THRESHOLD:
                log.warning("WiFi connection lost, falling back to AP mode")
                wifi_cfg = config.wifi
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, wifi.start_ap,
                    wifi_cfg.get("ap_ssid", ""),
                    wifi_cfg.get("ap_password", "midihub1"),
                )
                fail_count = 0


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
