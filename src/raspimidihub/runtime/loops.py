"""Background asyncio loops kept running for the lifetime of the service.

Independent supervisors:

- `rate_meter`: snapshots per-port MIDI message rates from the engine
  every second, broadcasts them over SSE, and rolls server-side
  meters (SSE rate, latency probes, CPU%) into their /api/system fields.
- `loop_lag_meter`: probes asyncio scheduling lag — schedules a wake
  100 ms out, measures how late the loop actually serviced it. The
  single best signal for "is the server keeping up with itself?".
- `watchdog_ping`: pings systemd's `WATCHDOG=1` at the unit's
  WatchdogSec interval / 2.
- `wifi_watchdog`: when WiFi is in client mode, polls the connection
  every 30 s and falls back to AP mode after 3 consecutive failures.
"""

import asyncio
import logging
import time

log = logging.getLogger(__name__)

WIFI_CHECK_INTERVAL = 30
WIFI_FAIL_THRESHOLD = 3  # consecutive failures before fallback


async def rate_meter(engine, server) -> None:
    """Broadcast per-port MIDI message rates and CC observatory deltas
    every second, and snapshot all server-side meters (SSE rate,
    latency probes, CPU%) for /api/system."""
    while True:
        await asyncio.sleep(1.0)
        server.sample_sse_rate()
        server.sample_latencies()
        server.sample_cpu()
        rates = engine.snapshot_rates()
        if rates:
            await server.send_sse("midi-rates", rates)
        cc_changes = engine.cc_dest_snapshot_dirty()
        if cc_changes:
            await server.send_sse("cc-changes", cc_changes)


async def loop_lag_meter(server) -> None:
    """Schedule a wake-up 100 ms out and measure how late the asyncio
    loop actually serviced it. A healthy loop wakes 0-3 ms late;
    pinned-loop wakes show 50-500 ms. Reports the windowed max via
    server.record_latency('loop_lag', ms)."""
    interval = 0.1
    expected = time.monotonic() + interval
    while True:
        await asyncio.sleep(interval)
        now = time.monotonic()
        lag_ms = (now - expected) * 1000.0
        if lag_ms > 0:
            server.record_latency("loop_lag", lag_ms)
        expected = now + interval


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
