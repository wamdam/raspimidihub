"""REST API for RaspiMIDIHub.

register_api() builds the shared ApiContext (autosave, MIDI-Learn,
captive-portal wiring) and hands each feature domain to its
register_<domain>() function:

    system.py         /api/system, /api/stats, /api/observatory,
                      /api/sse/subscribe, /api/panic, reboot,
                      factory-reset
    devices.py        /api/devices/*
    connections.py    /api/connections/*, /api/mappings/*, connect-all
    updates.py        /api/system/check-update, install, reinstall,
                      versions, update-status
    config_routes.py  /api/config/*, /api/backups/*
    network.py        /api/network/*, /api/bluetooth/*,
                      /api/network-midi/*
    wifi_routes.py    /api/wifi/*
    plugins.py        /api/plugins/*, /api/cc-learn/*

Route ORDER: web.py matches first route hit per method (exact then
prefix), but the route set has no prefix route whose path is a prefix
of a later same-method route (verified), so registering the domains
as groups here is behaviour-identical to the old monolith's
interleaved order. The manifest (/docs, /api/routes.json) sorts by
path anyway.
"""

import asyncio
import logging

from ..bluetooth import BluetoothMidi
from ..config import Config
from ..midi_engine import MidiEngine
from ..web import WebServer
from ..wifi import WifiManager
from ._autosaver import _Autosaver
from ._captive import register_captive
from ._ctx import ApiContext
from .config_routes import register_config_routes
from .connections import register_connections
from .devices import register_devices
from .network import register_network
from .plugins import register_plugins
from .system import register_system
from .updates import register_updates
from .wifi_routes import register_wifi

log = logging.getLogger(__name__)


def register_api(server: WebServer, engine: MidiEngine, config: Config,
                 wifi: WifiManager | None = None,
                 bluetooth: BluetoothMidi | None = None,
                 network_midi=None):
    """Register all API routes on the web server."""

    ctx = ApiContext(server=server, engine=engine, config=config,
                     wifi=wifi, bluetooth=bluetooth,
                     network_midi=network_midi)

    # Wire the dirty-tracker SSE side so mark_dirty / clear_dirty can fan
    # out a config-dirty event from any thread (CC-driven param mutations
    # come from worker threads). The plugin_host._on_dirty_cb hook is
    # wired in __main__ AFTER engine._plugin_host is attached — register_api
    # runs before that, so doing it here would no-op.
    engine._dirty_loop = asyncio.get_running_loop()
    engine._dirty_sse_cb = server.send_sse

    # Debounced rolling autosave: resume the last edited state on boot,
    # incl. after a hard power cut. Polls engine._change_seq; writes a
    # ping-pong snapshot once edits settle, rate-capped. flush() is used
    # by the shutdown path so a clean stop loses nothing. The snapshot
    # itself is ApiContext.snapshot — shared by manual Save, the
    # autosaver, and the shutdown flush so all three persist an
    # identical snapshot.
    autosaver = _Autosaver(engine, config, ctx.snapshot)
    engine._autosaver = autosaver
    ctx.autosaver = autosaver
    asyncio.get_running_loop().create_task(autosaver.run())

    # MIDI Learn — armed state for the CC binding popup. Keyed by
    # learn_id (UUID). Values: {instance_id, param, timeout_task}.
    # The first inbound CONTROLLER event after arming fires SSE
    # cc_learn_result and drops the entry. 30 s timeout fires SSE
    # cc_learn_timeout and also drops the entry. Learn observes
    # every CC on any source — not gated by routing to the plugin —
    # so a user binding Arp 1 → Rate can move ANY knob on ANY
    # controller routed to the Pi to capture it.
    cc_learn_loop = asyncio.get_running_loop()

    from ..alsa_seq import MidiEventType as _MidiEventType

    def _cc_learn_observe(ev) -> None:
        if not ctx.cc_learn_armed:
            return
        if ev.type != int(_MidiEventType.CONTROLLER):
            return
        if ev.dest.port != engine._monitor_port:
            return
        cc_ch = ev.data.control.channel
        cc_num = ev.data.control.param
        for learn_id, entry in list(ctx.cc_learn_armed.items()):
            entry.get("timeout_task") and entry["timeout_task"].cancel()
            ctx.cc_learn_armed.pop(learn_id, None)
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

    # Domain registration (order documented in the module docstring).
    register_captive(ctx)
    register_system(ctx)
    register_devices(ctx)
    register_connections(ctx)
    register_updates(ctx)
    register_config_routes(ctx)
    register_network(ctx)
    if wifi is None:
        # Legacy behaviour preserved verbatim from the monolith: the
        # plugins routes sat AFTER the wifi block's `if wifi is None:
        # return` guard, so register_api() without a WifiManager never
        # registered them. The appliance always has a WifiManager, so
        # this path is latent — kept exactly as it was.
        return
    register_wifi(ctx)
    register_plugins(ctx)
