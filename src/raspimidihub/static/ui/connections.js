/**
 * Shared connection helpers for the routing views.
 *
 * The matrix (pages/matrix.js) carries its own inline copies of the
 * connection-lookup logic; this module exists so the rack view
 * (pages/rack.js) can reuse the *same* semantics without importing —
 * and thus coupling to — the matrix component. Keep the two in sync:
 * the id formats here MUST match what the server emits and what the
 * matrix builds, or a connection drawn in one view won't be found in
 * the other.
 *
 * Routing-graph port semantics (the confusing part, documented once):
 *   - A port with `is_input === true` is a *source* you route FROM
 *     (the device's MIDI output — e.g. a plugin port named "OUT").
 *   - A port with `is_output === true` is a *destination* you route TO
 *     (the device's MIDI input — e.g. a plugin port named "IN").
 * A connection's `src` is always an is_input port; its `dst` an
 * is_output port. The rack draws a cable from the source's OUT jack to
 * the destination's IN jack.
 */

// Build the O(1) lookup keyed identically to the matrix: live
// connections by client:port pairs, saved-but-offline ones by
// stable_id pairs (a device replug changes client_id but not
// stable_id, so offline edges survive the gap).
export function buildConnMap(connections) {
    const map = {};
    for (const c of connections) {
        if (c.offline) {
            map[`offline:${c.src_stable_id}:${c.src_port}|${c.dst_stable_id}:${c.dst_port}`] = c;
        } else {
            map[`${c.src_client}:${c.src_port}-${c.dst_client}:${c.dst_port}`] = c;
        }
    }
    return map;
}

// `src` is a source descriptor (is_input port), `dst` a destination
// descriptor (is_output port); both carry client_id, port_id,
// stable_id, online. Prefers the live edge, falls back to the offline
// (stable_id) edge — same precedence as the matrix.
export function getConn(connMap, src, dst) {
    const active = connMap[`${src.client_id}:${src.port_id}-${dst.client_id}:${dst.port_id}`];
    if (active) return active;
    if (src.stable_id && dst.stable_id) {
        return connMap[`offline:${src.stable_id}:${src.port_id}|${dst.stable_id}:${dst.port_id}`];
    }
    return null;
}

export function connIsOffline(src, dst) {
    return !src.online || !dst.online;
}

export function connIsFiltered(conn) {
    return !!(conn && (conn.filtered || (conn.mappings && conn.mappings.length > 0)));
}

// Deterministic cable colour, one hue per *source* port. Hashing on
// stable_id (not client_id) keeps a cable the same colour across a
// replug / reboot — client_id is reassigned by ALSA each session.
export function cableColor(stableId, portId) {
    const s = (stableId || '') + ':' + portId;
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return `hsl(${h % 360} 75% 60%)`;
}
