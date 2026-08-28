"""Connection (de)serialisation helpers shared across API domains.

Moved verbatim from the old api.py.
"""

from ..midi_filter import MidiFilter, MidiMapping


def _parse_conn_id(conn_id: str) -> tuple[int, int, int, int]:
    """Parse 'src_client:src_port-dst_client:dst_port' → (sc, sp, dc, dp). Raises ValueError."""
    src, dst = conn_id.split("-")
    sc, sp = map(int, src.split(":"))
    dc, dp = map(int, dst.split(":"))
    return sc, sp, dc, dp


def _get_filter_data(fe, conn_id: str) -> dict:
    """Serialize filter + mappings for a connection. Returns dict with 'filter'/'mappings' keys."""
    data = {}
    if not fe:
        return data
    f = fe.get_filter(conn_id)
    if f:
        data["filter"] = f.to_dict()
    mappings = fe.get_mappings(conn_id)
    if mappings:
        data["mappings"] = [m.to_dict() for m in mappings]
    return data


def _serialize_connection(conn, registry, fe) -> dict:
    """Serialize a Connection with stable IDs and filter/mapping data."""
    conn_id = f"{conn.src_client}:{conn.src_port}-{conn.dst_client}:{conn.dst_port}"
    entry = {
        "src_client": conn.src_client, "src_port": conn.src_port,
        "dst_client": conn.dst_client, "dst_port": conn.dst_port,
    }
    src_info = registry.get_by_client(conn.src_client)
    dst_info = registry.get_by_client(conn.dst_client)
    if src_info:
        entry["src_stable_id"] = src_info.stable_id
    if dst_info:
        entry["dst_stable_id"] = dst_info.stable_id
    entry.update(_get_filter_data(fe, conn_id))
    return entry


def _restore_userspace(engine, fe, conn, saved_data: dict):
    """Restore a connection with saved filter/mapping data. Returns True if userspace, False if ALSA."""
    conn_id = f"{conn.src_client}:{conn.src_port}-{conn.dst_client}:{conn.dst_port}"
    saved_filter = saved_data.get("filter")
    saved_mappings = saved_data.get("mappings", [])
    needs_userspace = bool(saved_mappings)
    midi_filter = None
    if saved_filter:
        midi_filter = MidiFilter.from_dict(saved_filter)
        needs_userspace = needs_userspace or not midi_filter.is_passthrough

    if needs_userspace and fe:
        if midi_filter is None:
            midi_filter = MidiFilter()
        fe.add_filter(conn.src_client, conn.src_port,
                      conn.dst_client, conn.dst_port, midi_filter)
        for md in saved_mappings:
            try:
                fe.add_mapping(conn_id, MidiMapping.from_dict(md))
            except (ValueError, KeyError):
                pass
        engine._connections.add(conn)
        return True
    else:
        engine._seq.subscribe(conn.src_client, conn.src_port,
                              conn.dst_client, conn.dst_port)
        engine._connections.add(conn)
        return False


def _matches_saved(c: dict, src_sid: str, dst_sid: str, src_port: int, dst_port: int) -> bool:
    """Check if a saved config entry matches the given stable IDs and ports."""
    return (c.get("src_stable_id") == src_sid and c.get("dst_stable_id") == dst_sid
            and c.get("src_port") == src_port and c.get("dst_port") == dst_port)


