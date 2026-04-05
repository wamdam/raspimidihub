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
        # Push SSE event (fire-and-forget)
        asyncio.ensure_future(server.send_sse("device-connected", {
            "devices": [d.name for d in engine.devices]
        }))

    engine.on_change(on_change)

    try:
        engine.start()

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
