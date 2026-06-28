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
        server.sample_cpu_cores()
        rates = engine.snapshot_rates()
        if rates:
            await server.send_sse("midi-rates", rates)
        cc_changes = engine.cc_dest_snapshot_dirty()
        if cc_changes:
            await server.send_sse("cc-changes", cc_changes)


async def pending_param_flusher(plugin_host) -> None:
    """Drain the plugin host's trailing-edge param coalescer at 20 Hz
    and the display coalescer at 10 Hz. Plugin threads submit the
    latest value per (instance, name); these loops fan them out to
    SSE on the asyncio thread, with the latest value always winning.
    String-typed param values (DropButtonRow drops.action cycling and
    similar state transitions) bypass the queue entirely via
    emit_now(), so every transition still reaches the UI immediately."""
    tick = 0
    while True:
        await asyncio.sleep(0.05)
        plugin_host.flush_pending_params()
        tick += 1
        if tick % 2 == 0:
            plugin_host.flush_pending_displays()


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


async def sse_heartbeat(server, interval: float = 30.0) -> None:
    """Push a comment line into every SSE outbox every `interval` seconds.

    Two reasons:
    - Browsers (and intermediate proxies) drop idle SSE streams. A
      keepalive every 30 s holds them open even when the client
      subscribed to events that don't fire often.
    - Without a write attempt, _handle_sse's queue.get() would block
      forever on a dead socket — the writer.drain() failure that
      triggers cleanup never fires. With the per-view subscription
      model, a connection on Settings receives no events at all, so
      dead-socket detection used to wait until the client reconnected.
      The heartbeat write surfaces dead sockets within one interval
      and lets _sse_connections shed them.

    The line `:hb` is an SSE comment — browsers ignore it; servers
    write it through the existing per-conn queue + drain machinery.
    """
    msg = ":hb\n\n"
    while True:
        await asyncio.sleep(interval)
        for conn in list(server._sse_connections.values()):
            try:
                conn.queue.put_nowait(msg)
            except asyncio.QueueFull:
                # Outbox is saturated — the connection isn't draining
                # anyway, so the next failed write will surface the
                # dead socket. Skip silently.
                pass


async def cpu_isolation_guard(interval: float = 15.0) -> None:
    """Keep the isolated loop core for the loop alone: periodically sweep
    any thread that drifted onto it (e.g. a python-zeroconf thread we
    can't pin at the source) back onto the housekeeping cores. Threads we
    own pin themselves at start, so this is a safety net for the rest.
    No-op off the isolated appliance."""
    import threading

    from .. import cpu_affinity
    loop_tid = threading.get_native_id()
    while True:
        try:
            cpu_affinity.enforce_isolation(loop_tid)
        except Exception:
            log.exception("cpu_isolation_guard sweep failed")
        await asyncio.sleep(interval)


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
