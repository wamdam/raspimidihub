/**
 * Connection matrix + its sub-components (cells, headers, rate meter).
 *
 * Phase 6: every interaction is a context menu. Single tap (or right-
 * click) on a cell, plugin/hardware header, or mapping row opens a
 * popover with all the actions for that target. There is NO separate
 * "primary tap" behaviour any more — the old tap-toggles-connection,
 * tap-opens-detail, tap-confirms-remove dual modes are gone.
 *
 * Cells, row headers, and column headers all use the shared
 * `useTapMenu` from ui/contextmenu.js — they receive a `getMenuItems()`
 * callback from the parent and a `showContextMenu(x, y, items)` to
 * surface the popover.
 */

import { useState } from '../lib/hooks.module.js';
import { html } from '../ui/common.js';
import { useTapMenu } from '../ui/contextmenu.js';
import { IconDIN, IconBluetooth, IconNetwork, PluginIcon } from '../ui/icons.js';
import { touchTs, pruneByPrefix } from '../ui/storage.js';

// Collapse state of per-hub network groups: per-browser display
// state (like density / sounds), one small localStorage key per hub.
const NET_COLLAPSE_PREFIX = 'raspimidihub:netCollapse:';
pruneByPrefix(NET_COLLAPSE_PREFIX, { maxCount: 20 });

function isHubCollapsed(hub) {
    try {
        const o = JSON.parse(localStorage.getItem(NET_COLLAPSE_PREFIX + hub) || 'null');
        return !!(o && o.collapsed);
    } catch { return false; }
}

function setHubCollapsed(hub, collapsed) {
    try {
        localStorage.setItem(NET_COLLAPSE_PREFIX + hub,
            JSON.stringify(touchTs({ collapsed })));
    } catch {}
}

// Row-header column is always narrow so the matrix gets maximum
// horizontal room. Labels middle-truncate to fit the budget; tap
// the row to open the context menu where the full name is shown at
// the top for unambiguous identification.
const ROW_HEADER_WIDTH = 96;
const ROW_HEADER_CHARS = 9; // fits "Velo…ar 1" at 12px sans-serif

function midEllipsis(text, chars) {
    if (!text || text.length <= chars) return text || '';
    if (chars <= 2) return text.slice(0, 1) + '…';
    const remain = chars - 1; // 1 char for the ellipsis itself
    const head = Math.ceil(remain / 2);
    const tail = remain - head;
    return tail > 0
        ? text.slice(0, head) + '…' + text.slice(-tail)
        : text.slice(0, head) + '…';
}

export function MatrixCell({ on, filtered, getMenuItems, showContextMenu, offline }) {
    const trigger = useTapMenu(showContextMenu, getMenuItems);
    let cls = on ? (filtered ? 'on filtered' : 'on') : '';
    if (offline) cls += ' offline-cell';
    return html`<td onClick=${trigger.onClick} onContextMenu=${trigger.onContextMenu}>
        <div class="cb ${cls}"></div>
    </td>`;
}

export function MatrixHeader({ item, label, isPlugin, pluginType, isBluetooth, isNetwork, sendsClock, clockBlocked, multiEffective, clockBeat, online, getMenuItems, showContextMenu, midiRate }) {
    const trigger = useTapMenu(showContextMenu, getMenuItems);
    // Three-state clock icon:
    //   blocked       → desaturated + faint  (still pulses so the user
    //                   can confirm the device is firing, but clearly
    //                   not driving anything)
    //   multiEffective → orange clock-warn   (≥2 unblocked senders)
    //   else          → green                (the sole effective
    //                   sender, or the only sender period)
    // Re-key the icon on each quarter-note SSE so the one-shot CSS
    // animation replays in time with the source.
    const cls = clockBlocked ? 'clock-blocked'
              : multiEffective ? 'clock-warn'
              : '';
    const title = clockBlocked ? 'Sending clock (blocked from system clock)'
                : multiEffective ? 'Multiple clock sources!'
                : 'Sending clock';

    // Row-header column is always capped narrow so the matrix gets
    // maximum horizontal room. The full label is surfaced as a header
    // in the tap menu (see getHeaderMenuItems in routing.js), so the
    // abbreviation never costs the user identification.
    const displayLabel = label ? midEllipsis(label, ROW_HEADER_CHARS) : '';
    const devIcon = isBluetooth ? html`<${IconBluetooth} />`
                  : isNetwork ? html`<${IconNetwork} />`
                  : html`<${IconDIN} />`;
    const iconCls = isBluetooth ? 'bt' : isNetwork ? 'net' : 'din';
    return html`<th class="row-header ${online ? '' : 'offline'} ${isPlugin ? 'plugin-row' : ''} ${isBluetooth ? 'bt-row' : ''} ${isNetwork ? 'net-row' : ''}" style="cursor:pointer;max-width:${ROW_HEADER_WIDTH}px"
        title="${label || ''}"
        onClick=${trigger.onClick} onContextMenu=${trigger.onContextMenu}>${isPlugin ? html`<${PluginIcon} type=${pluginType} />` : html`<span class="dev-icon ${iconCls}" style="display:inline-flex;vertical-align:middle;margin-right:3px">${devIcon}</span>`} <span class="row-header-label">${displayLabel}</span>${item.midi2 && item.midi2.capable ? html`<span class="midi2-badge${item.midi2.protocol ? '' : ' forced'}" title="${item.midi2.protocol ? 'MIDI 2.0 device' : 'MIDI 2.0 device — forced to MIDI 1.0'}">2.0</span>` : ''}${sendsClock ? html`<span key=${clockBeat || 0} class="clock-icon ${cls}" title="${title}"></span>` : ''}
        <${RateMeter} rate=${midiRate} /></th>`;
}

export function ColumnHeader({ item, label, getMenuItems, showContextMenu }) {
    const trigger = useTapMenu(showContextMenu, getMenuItems);
    return html`<th class="${item.online ? '' : 'offline'} ${item.is_plugin ? 'plugin-col' : ''} ${item.is_bluetooth ? 'bt-col' : ''} ${item.is_network ? 'net-col' : ''}" style="cursor:pointer"
        title="${item.multi ? item.dev_name + ': ' + item.port_name : item.dev_name}"
        onClick=${trigger.onClick} onContextMenu=${trigger.onContextMenu}><span>${label}</span></th>`;
}

export function RateMeter({ rate }) {
    if (!rate) return null;
    const max = 1000;
    const pct = Math.min(100, (rate / max) * 100);
    const color = pct < 50 ? 'var(--success)' : pct < 80 ? 'var(--warn-soft)' : 'var(--accent)';
    return html`<div class="rate-meter" title="${rate} msg/s">
        <div class="rate-bar" style="width:${pct}%;background:${color}"></div>
    </div>`;
}

export function ConnectionMatrix({ devices, connections, showToast, clockSources, clockQuarters, midiRates, onAddPlugin, getCellMenuItems, getHeaderMenuItems, showContextMenu }) {
    const inputs = [];
    const outputs = [];
    for (const dev of devices) {
        const inCount = dev.ports.filter(p => p.is_input).length;
        const outCount = dev.ports.filter(p => p.is_output).length;
        for (const p of dev.ports) {
            const extra = { client_id: dev.client_id, dev_name: dev.name, dev_default_name: dev.default_name || dev.name, port_name: p.name, port_default_name: p.default_name || p.name, online: dev.online !== false, stable_id: dev.stable_id, is_plugin: !!dev.is_plugin, plugin_type: dev.plugin_type, is_bluetooth: !!dev.is_bluetooth, is_network: !!dev.is_network, remote_hub: dev.remote_hub || '', midi2: dev.midi2 || null };
            if (p.is_input) inputs.push({ ...p, ...extra, multi: inCount > 1 });
            if (p.is_output) outputs.push({ ...p, ...extra, multi: outCount > 1 });
        }
    }
    // Three tiers: plugins, local hardware, then network devices
    // grouped per remote hub (the per-hub group rows below rely on
    // same-hub ports being contiguous).
    const tier = (x) => x.is_plugin ? 0 : x.is_network ? 2 : 1;
    const byName = (a, b) => (tier(a) - tier(b))
        || a.remote_hub.localeCompare(b.remote_hub)
        || a.dev_name.localeCompare(b.dev_name);
    inputs.sort(byName);
    outputs.sort(byName);

    // Per-hub collapse: hiding a hub removes its rows AND columns;
    // the group row itself stays as the re-expand handle.
    const [, setCollapseVer] = useState(0);
    const netHubs = [...new Set(inputs.concat(outputs)
        .filter(x => x.is_network).map(x => x.remote_hub))];
    const hubCollapsed = {};
    for (const hub of netHubs) hubCollapsed[hub] = isHubCollapsed(hub);
    const toggleHub = (hub) => {
        setHubCollapsed(hub, !hubCollapsed[hub]);
        setCollapseVer(v => v + 1);
    };
    const hubDeviceCount = {};
    for (const d of devices) {
        if (d.is_network) {
            const h = d.remote_hub || '';
            hubDeviceCount[h] = (hubDeviceCount[h] || 0) + 1;
        }
    }
    const visibleOutputs = outputs.filter(
        o => !o.is_network || !hubCollapsed[o.remote_hub]);

    const connMap = {};
    for (const c of connections) {
        if (c.offline) {
            connMap[`offline:${c.src_stable_id}:${c.src_port}|${c.dst_stable_id}:${c.dst_port}`] = c;
        } else {
            connMap[`${c.src_client}:${c.src_port}-${c.dst_client}:${c.dst_port}`] = c;
        }
    }

    const getConn = (inp, out) => {
        const active = connMap[`${inp.client_id}:${inp.port_id}-${out.client_id}:${out.port_id}`];
        if (active) return active;
        if (inp.stable_id && out.stable_id) {
            return connMap[`offline:${inp.stable_id}:${inp.port_id}|${out.stable_id}:${out.port_id}`];
        }
        return null;
    };
    const isSelf = (inp, out) => inp.client_id && inp.client_id === out.client_id;
    const isOffline = (inp, out) => !inp.online || !out.online;

    // label(): short text shown in matrix row/column headers.
    // BLE-MIDI devices used to get a leading ᛒ rune; now the
    // bluetooth icon in the row/column header carries that signal.
    const label = (item) => {
        if (item.multi && item.port_name !== item.port_default_name) {
            return item.port_name;
        }
        let short = item.dev_name;
        if (item.multi) short += ` p${item.port_id + 1}`;
        if (short.length > 20) short = short.slice(0, 19) + '…';
        return short;
    };

    const clockClientIds = clockSources ? Object.keys(clockSources).map(Number) : [];
    // Per-device clock-veto map (built once per render). Hardware whose
    // user has unticked "Drive system clock" sets clock_blocked: true
    // in /api/devices, so we know to dim its icon and exclude it from
    // the "multi clock" warning count.
    const blockedById = {};
    for (const d of devices) {
        if (d.client_id != null && d.clock_blocked) blockedById[d.client_id] = true;
    }
    const effectiveSenderCount = clockClientIds.filter(id => !blockedById[id]).length;
    const multiEffective = effectiveSenderCount > 1;

    if (inputs.length === 0 || outputs.length === 0) {
        return html`<div class="card"><p style="color:var(--text-dim)">No MIDI devices connected</p></div>`;
    }

    // Row list with per-hub group headers spliced in before each
    // network hub's first input row. Collapsed hubs contribute the
    // group row only (their input rows AND output columns are hidden).
    const rows = [];
    let lastHub = null;
    for (const inp of inputs) {
        const hub = inp.is_network ? inp.remote_hub : null;
        if (hub !== null && hub !== lastHub) rows.push({ groupHub: hub });
        lastHub = hub;
        if (hub === null || !hubCollapsed[hub]) rows.push({ inp });
    }

    return html`
        <div class="matrix" data-spectator-scroll="matrix">
            <table>
                <thead>
                    <tr>
                        <th class="corner-header"><span class="from-label">FROM ↓</span><span class="to-label">TO →</span></th>
                        ${visibleOutputs.map(o => html`<${ColumnHeader} key=${o.client_id + ':' + o.port_id} item=${o}
                            label=${label(o)}
                            getMenuItems=${() => getHeaderMenuItems ? getHeaderMenuItems(o, 'output', label(o)) : []}
                            showContextMenu=${showContextMenu} />`)}
                    </tr>
                </thead>
                <tbody>
                    ${rows.map(row => {
                        if (row.groupHub !== undefined) {
                            const hub = row.groupHub;
                            const n = hubDeviceCount[hub] || 0;
                            return html`<tr key=${'net:' + hub} class="net-group">
                                <th class="net-group-header" colspan=${visibleOutputs.length + 1}
                                    onclick=${() => toggleHub(hub)}
                                    title="${hubCollapsed[hub] ? 'Show' : 'Hide'} the devices mirrored from ${hub}">
                                    <span class="net-chevron">${hubCollapsed[hub] ? '▶' : '▼'}</span>
                                    <span class="dev-icon net" style="display:inline-flex;vertical-align:middle;margin-right:3px"><${IconNetwork} /></span>
                                    @${hub} <span class="net-count">· ${n} device${n === 1 ? '' : 's'}</span>
                                </th>
                            </tr>`;
                        }
                        const inp = row.inp;
                        const sendsClock = clockClientIds.includes(inp.client_id);
                        // Stable per-port identity. Without a key here Preact
                        // matches rows by position, so when a device is added
                        // or removed the surviving rows shift up/down into
                        // slots that previously held a different device — and
                        // any component state inside (notably PluginIcon's
                        // async-fetched SVG) gets carried over to the wrong
                        // row, painting the wrong icon next to a fresh label.
                        const rowKey = inp.client_id + ':' + inp.port_id;
                        return html`
                        <tr key=${rowKey}>
                            <${MatrixHeader} item=${inp} label=${label(inp)} isPlugin=${inp.is_plugin} pluginType=${inp.plugin_type}
                                isBluetooth=${inp.is_bluetooth}
                                isNetwork=${inp.is_network}
                                sendsClock=${sendsClock}
                                clockBlocked=${!!blockedById[inp.client_id]}
                                multiEffective=${multiEffective}
                                clockBeat=${clockQuarters && clockQuarters[inp.client_id]}
                                online=${inp.online}
                                getMenuItems=${() => getHeaderMenuItems ? getHeaderMenuItems(inp, 'input', label(inp)) : []}
                                showContextMenu=${showContextMenu}
                                midiRate=${midiRates && midiRates[inp.client_id + ':' + inp.port_id]} />
                            ${visibleOutputs.map(out => {
                                const cellKey = out.client_id + ':' + out.port_id;
                                if (isSelf(inp, out)) return html`<td key=${cellKey} class="self"></td>`;
                                const offline = isOffline(inp, out);
                                const conn = getConn(inp, out);
                                const on = !!conn;
                                const filtered = conn && (conn.filtered || (conn.mappings && conn.mappings.length > 0));
                                return html`<${MatrixCell} key=${cellKey} on=${on} filtered=${filtered} offline=${offline}
                                    getMenuItems=${() => getCellMenuItems ? getCellMenuItems(inp, out, conn) : []}
                                    showContextMenu=${showContextMenu} />`;
                            })}
                        </tr>
                    `;})}
                    ${onAddPlugin && html`<tr>
                        <th class="row-header" style="padding:4px 6px">
                            <button style="background:var(--accent);color:#fff;border:none;border-radius:4px;padding:5px 12px;font-size:12px;font-weight:600;cursor:pointer;width:100%" onclick=${onAddPlugin}>Add</button>
                        </th>
                        ${visibleOutputs.map(() => html`<td></td>`)}
                    </tr>`}
                </tbody>
            </table>
        </div>
        <p style="font-size:11px;color:var(--text-dim);text-align:center;margin-top:4px">
            Tap a connection or device for filters, mappings, and copy/paste.
        </p>
    `;
}
