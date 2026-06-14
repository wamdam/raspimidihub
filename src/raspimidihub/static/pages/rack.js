/**
 * Rack view — a second routing surface alongside the matrix.
 *
 * Devices are drawn as 19" rack units (label + IN/OUT jacks), grouped
 * into hardware / plugins / one sub-rack per network peer hub. Cables
 * hang between jacks; you patch by tapping a jack then its counterpart,
 * or by dragging one onto the other. Filters/mappings, context menus,
 * clipboard and connect/disconnect all reuse the exact same callbacks
 * the matrix uses (passed down from RoutingPage) — this component only
 * owns presentation + the patching gestures.
 *
 * Split of responsibilities (important — see also rack-engine.js):
 *   - Preact (this file) renders the STATIC structure: groups, unit
 *     faceplates, jacks, the empty SVG cable layer. It re-renders only
 *     on structural change (device/connection/collapse), never on a
 *     MIDI-activity tick.
 *   - The imperative engine owns everything dynamic: drawing cables,
 *     port-activity LEDs, the patch gestures, peek/spread, ripple. It
 *     mutates classes directly on the Preact-rendered jacks. Because
 *     this component's render output does NOT depend on midiRates /
 *     clock, an activity tick produces identical vnodes → Preact's diff
 *     is a no-op → the engine's classes are never clobbered.
 */

import { useRef, useEffect, useState, useMemo } from '../lib/hooks.module.js';
import { html } from '../ui/common.js';
import { DeviceIcon } from '../ui/icons.js';
import { touchTs } from '../ui/storage.js';
import { createRackEngine } from '../ui/rack-engine.js';

// Collapse persistence. Network hubs reuse the matrix's key so the two
// views share one collapsed/expanded state per hub; the local groups
// get their own rack-only prefix.
const NET_COLLAPSE_PREFIX = 'raspimidihub:netCollapse:';
const GROUP_COLLAPSE_PREFIX = 'raspimidihub:rackCollapse:';
function isCollapsed(key) {
    try { const o = JSON.parse(localStorage.getItem(key) || 'null'); return !!(o && o.collapsed); }
    catch { return false; }
}
function setCollapsedLS(key, v) {
    try { localStorage.setItem(key, JSON.stringify(touchTs({ collapsed: v }))); } catch {}
}

// Per-device key used in data-jack + cable resolution: client_id when
// online, stable_id when offline (a replug changes client_id, so saved
// edges must key off stable_id — mirrors the matrix's connMap).
function deviceKey(d) {
    return d.client_id != null ? 'c' + d.client_id : 's:' + d.stable_id;
}

// Build the ordered group list from the device set. Hardware first
// (the rack metaphor — real gear mounted at the top), then plugins,
// then one sub-rack per network peer hub (alphabetical).
function buildGroups(devices) {
    const hardware = [], plugins = [], byHub = {};
    for (const d of devices) {
        if (d.is_plugin) plugins.push(d);
        else if (d.is_network) (byHub[d.remote_hub || ''] = byHub[d.remote_hub || ''] || []).push(d);
        else hardware.push(d);
    }
    const groups = [];
    if (hardware.length) groups.push({ id: 'hardware', title: 'HARDWARE', kind: 'hw', collapseKey: GROUP_COLLAPSE_PREFIX + 'hardware', devices: hardware });
    if (plugins.length) groups.push({ id: 'plugins', title: 'PLUGINS & CONTROLLER', kind: 'plugin', collapseKey: GROUP_COLLAPSE_PREFIX + 'plugins', devices: plugins });
    for (const hub of Object.keys(byHub).sort()) {
        groups.push({ id: 'net:' + hub, title: hub.toUpperCase(), sub: 'Network MIDI · ' + byHub[hub].length + (byHub[hub].length === 1 ? ' device' : ' devices'),
            kind: 'net', net: true, collapseKey: NET_COLLAPSE_PREFIX + hub, devices: byHub[hub] });
    }
    return groups;
}

// Descriptor a jack/cable endpoint needs: enough for onToggle (which
// branches on online to pick stable_id vs client_id) and for the
// filter/menu callbacks.
function portDesc(d, p) {
    return { client_id: d.client_id, port_id: p.port_id, stable_id: d.stable_id,
        online: d.online !== false, dev_name: d.name, dev_default_name: d.default_name,
        port_name: p.name, multi: d.ports.length > 1 };
}

// The device name is already in the faceplate header, so strip it (and
// the factory name) from the port label: "LCXL3 1 MIDI In" → "MIDI In".
// Single-port devices whose port just echoes the device name collapse
// to an empty label (the header carries the identity).
function portShortLabel(dev, port) {
    let s = (port.name || '').trim();
    for (const pre of [dev.name, dev.default_name]) {
        if (pre && s.toLowerCase().startsWith(pre.toLowerCase())) {
            s = s.slice(pre.length).replace(/^[\s:_-]+/, '').trim();
        }
    }
    return s;
}

function PortRow({ dkey, dev, port }) {
    const plabel = portShortLabel(dev, port);
    // is_input  → device is a source you route FROM → render an OUT jack
    // is_output → device is a destination you route TO → render an IN jack
    // IN on the far left, OUT on the far right, label centred between.
    // A jack the port doesn't have renders as a hidden ghost so the
    // left/right slots (and the centred label) stay aligned across rows.
    const inJack = port.is_output
        ? html`<div class="jackbox in-box"><div class="jack in" data-jack="${dkey}:${port.port_id}:in"></div><span class="j-sub">IN</span></div>`
        : html`<div class="jackbox in-box ghost"><div class="jack"></div><span class="j-sub">IN</span></div>`;
    const outJack = port.is_input
        ? html`<div class="jackbox out-box"><span class="j-sub">OUT</span><div class="jack out" data-jack="${dkey}:${port.port_id}:out"></div></div>`
        : html`<div class="jackbox out-box ghost"><span class="j-sub">OUT</span><div class="jack"></div></div>`;
    return html`<div class="pmod">
        ${inJack}
        <span class="p-label" title="${port.name || ''}">${plabel}</span>
        ${outJack}
    </div>`;
}

function Unit({ dev }) {
    const dkey = deviceKey(dev);
    const cls = 'unit mounted'
        + (dev.is_plugin ? ' plugin' : '')
        + (dev.is_network ? ' remote' : '')
        + (dev.online === false ? ' offline' : '');
    return html`<div class=${cls} data-dkey=${dkey} data-client=${dev.client_id == null ? '' : dev.client_id}>
        <div class="u-head"><span class="u-icon"><${DeviceIcon} device=${dev} /></span>
            <span class="u-name">${dev.name}</span>
            <span class="u-clock" title="Sending clock"></span></div>
        <div class="u-ports">
            ${dev.ports.map(p => html`<${PortRow} key=${p.port_id} dkey=${dkey} dev=${dev} port=${p} />`)}
        </div>
    </div>`;
}

export function RackView({ devices, connections, clockSources, clockQuarters, midiRates,
                           onToggle, onAddPlugin, getCellMenuItems, getHeaderMenuItems, showContextMenu }) {
    const rootRef = useRef(null);
    const svgRef = useRef(null);
    const engineRef = useRef(null);
    const ctxRef = useRef(null);
    const [collapseVer, setCollapseVer] = useState(0);   // bumps on a group toggle

    // The structural model (groups, port map, signature) only depends on
    // the device/connection set and the collapse state — NOT on MIDI
    // activity. devices/connections keep a stable reference across
    // activity ticks (app.js updates them only on device/connection SSE
    // events), so this memo does not recompute on a midi-rates tick.
    const model = useMemo(() => {
        const groups = buildGroups(devices);
        const portMap = {};
        for (const d of devices) {
            const dkey = deviceKey(d);
            for (const p of d.ports) {
                if (p.is_input) portMap[`${dkey}:${p.port_id}:out`] = portDesc(d, p);
                if (p.is_output) portMap[`${dkey}:${p.port_id}:in`] = portDesc(d, p);
            }
        }
        // structKey changes exactly when the drawn cables/jacks would —
        // device identity/online/ports, connection set + filtered flag,
        // and group collapse. Used to gate the (expensive) cable redraw.
        const structKey = JSON.stringify({
            d: devices.map(d => [deviceKey(d), d.name, d.online, d.is_plugin, d.is_network, d.remote_hub,
                d.ports.map(p => [p.port_id, p.name, p.is_input, p.is_output])]),
            c: connections.map(c => [c.id || `${c.src_client}:${c.src_port}-${c.dst_client}:${c.dst_port}`,
                !!c.offline, !!c.filtered, (c.mappings || []).length]),
            g: groups.map(g => isCollapsed(g.collapseKey)),
        });
        return { groups, portMap, structKey };
    }, [devices, connections, collapseVer]);

    // ctx: latest data + callbacks the engine reads at draw/event time.
    // Reassigned every render (cheap) so connect/menu callbacks — which
    // close over the current connections — never go stale.
    const ctx = {
        devices, connections, portMap: model.portMap, deviceKey,
        midiRates, clockQuarters, clockSources,
        onToggle, getCellMenuItems, getHeaderMenuItems, showContextMenu,
    };
    ctxRef.current = ctx;
    if (engineRef.current) engineRef.current.ctx = ctx;

    // Mount the engine once; tear down document listeners on unmount.
    useEffect(() => {
        const engine = createRackEngine();
        engine.ctx = ctxRef.current;
        engineRef.current = engine;
        engine.mount({ rootEl: rootRef.current, svgEl: svgRef.current });
        engine.drawCables();
        return () => { engine.destroy(); engineRef.current = null; };
    }, []);

    // Redraw cables ONLY when the structure changes (the heavy path:
    // full SVG rebuild + forced layout). drawCables() refreshes activity
    // for the new jacks itself.
    useEffect(() => { engineRef.current && engineRef.current.drawCables(); }, [model.structKey]);

    // Activity is cheap (class toggles, no SVG rebuild) and runs on every
    // MIDI tick — this is what keeps the LEDs/clock live without paying
    // the redraw cost each tick.
    useEffect(() => { engineRef.current && engineRef.current.updateActivity(); },
        [midiRates, clockQuarters, clockSources]);

    const toggleGroup = (g) => { setCollapsedLS(g.collapseKey, !isCollapsed(g.collapseKey)); setCollapseVer(v => v + 1); };

    // The units/groups subtree is memoised on structKey, so an activity
    // tick (which re-renders RackView) reuses the exact same vnode
    // reference and Preact skips diffing the whole rack DOM — the
    // engine's imperatively-set jack classes are never touched.
    const unitsContent = useMemo(() => model.groups.map(g => {
        const collapsed = isCollapsed(g.collapseKey);
        const extConns = connections.filter(c => {
            const inG = (cid, sid) => g.devices.some(d => (c.offline ? d.stable_id === sid : d.client_id === cid));
            return inG(c.src_client, c.src_stable_id) !== inG(c.dst_client, c.dst_stable_id);
        }).length;
        return html`
            <div class="gpanel mounted slim ${g.kind} ${collapsed ? 'collapsed' : ''}" data-group=${g.id}>
                <span class="g-collapse" onclick=${() => toggleGroup(g)}>
                    <span class="arrow">▼</span>
                    ${g.net ? html`<span class="g-icon"><${DeviceIcon} device=${{ is_network: true }} /></span>` : ''}
                    <span class="g-title">${g.title}</span>
                    ${g.sub ? html`<span class="g-sub">${g.sub}</span>` : ''}
                </span>
                <span class="g-spacer"></span>
                <span class="g-led" data-gled=${g.id}></span>
                ${collapsed && extConns ? html`<span class="g-badge">● ${extConns}</span>` : ''}
                <div class="jack g-jack" data-ganchor=${g.id}></div>
            </div>
            ${!collapsed ? g.devices.map(d => html`<${Unit} key=${deviceKey(d)} dev=${d} />`) : ''}
        `;
    }), [model.structKey]);

    // Always render the shell (with refs) — even with zero devices — so
    // the engine's mount effect never sees a null container. The first
    // app render can briefly have no devices (they arrive async).
    return html`
        <div class="rack-view" ref=${rootRef}>
            <div class="rail left"></div>
            <div class="rail right"></div>
            <div class="rack-units">
                ${!devices.length ? html`<p style="color:var(--text-dim);text-align:center;padding:24px 0">No MIDI devices connected</p>` : ''}
                ${unitsContent}
                <div class="rack-add">
                    <button class="btn-rack-add" onclick=${onAddPlugin}>+ Add Device</button>
                </div>
            </div>
            <svg class="rack-cables" ref=${svgRef}></svg>
        </div>
        <p style="font-size:11px;color:var(--text-dim);text-align:center;margin-top:4px">
            Tap a jack then its counterpart to patch (or drag). Hold a jack to highlight its cables. Tap a cable for filters; long-press a device for its menu.
        </p>
    `;
}
