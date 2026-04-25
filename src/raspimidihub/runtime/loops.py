"""Background asyncio loops kept running for the lifetime of the service.

Three independent supervisors:

- `rate_meter`: snapshots per-port MIDI message rates from the engine
  every second and broadcasts them over SSE.
- `watchdog_ping`: pings systemd's `WATCHDOG=1` at the unit's
  WatchdogSec interval / 2.
- `wifi_watchdog`: when WiFi is in client mode, polls the connection
  every 30 s and falls back to AP mode after 3 consecutive failures.
"""

import asyncio
import logging

log = logging.getLogger(__name__)

WIFI_CHECK_INTERVAL = 30
WIFI_FAIL_THRESHOLD = 3  # consecutive failures before fallback


async def rate_meter(engine, server) -> None:
    """Broadcast per-port MIDI message rates and CC observatory deltas
    every second."""
    while True:
        await asyncio.sleep(1.0)
        rates = engine.snapshot_rates()
        if rates:
            await server.send_sse("midi-rates", rates)
        cc_changes = engine.cc_snapshot_dirty()
        if cc_changes:
            await server.send_sse("cc-changes", cc_changes)


async def watchdog_ping(interval: float, notify_fn) -> None:
    """Periodically tell systemd we're alive. `notify_fn` is the
    sd_notify wrapper from __main__."""
    while True:
        notify_fn("WATCHDOG=1")
        await asyncio.sleep(interval)


async def wifi_watchdog(wifi, config, server) -> None:
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
