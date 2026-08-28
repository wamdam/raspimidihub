"""Shared registration context for the api/ domain modules.

One ApiContext per register_api() call: the objects every domain
handler needs (server / engine / config / the optional feature
managers) plus the small pieces of shared *mutable* state the old
monolith kept as closures (the in-flight update task, the MIDI-Learn
armed map, the /api/plugins/instances cache). snapshot() serialises
the live engine state into config.data — shared by manual Save, the
autosaver, and the shutdown flush so all three persist an identical
snapshot.
"""

from dataclasses import dataclass, field

from ..bluetooth import BluetoothMidi
from ..config import Config
from ..midi_engine import MidiEngine
from ..web import WebServer
from ..wifi import WifiManager
from ._autosaver import _Autosaver
from ._conn import _parse_conn_id, _serialize_connection


@dataclass
class ApiContext:
    server: WebServer
    engine: MidiEngine
    config: Config
    wifi: WifiManager | None = None
    bluetooth: BluetoothMidi | None = None
    network_midi: object | None = None
    # Filled in by register_api() during wiring.
    autosaver: _Autosaver | None = None

    # One in-flight update orchestrator at a time (single-slot list so
    # the handlers can rebind it without a nonlocal).
    in_flight_update: list = field(default_factory=lambda: [None])
    # MIDI-Learn armed state: learn_id -> {instance_id, param,
    # timeout_task} (see the wiring comment in __init__).
    cc_learn_armed: dict = field(default_factory=dict)
    # 500 ms TTL cache for GET /api/plugins/instances (see plugins.py).
    instances_cache: dict = field(
        default_factory=lambda: {"body": None, "ts": 0.0})

    def snapshot(self) -> None:
        """Serialize the live engine state into config.data. Shared by
        manual Save, the autosaver, and the shutdown flush so all three
        persist an identical snapshot (timed for /api/stats)."""
        from .. import perf_stats
        with perf_stats.time_op("op_autosave_snapshot"):
            self._snapshot_impl()

    def _snapshot_impl(self) -> None:
        engine = self.engine
        config = self.config
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

    def invalidate_instances_cache(self) -> None:
        """Drop the cached /api/plugins/instances body so the next GET
        rebuilds from live state. Called after any mutation that changes
        the list (create, delete, rename, status change)."""
        self.instances_cache["body"] = None
        self.instances_cache["ts"] = 0.0
