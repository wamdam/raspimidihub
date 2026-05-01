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

import { html } from '../ui/common.js';
import { useTapMenu } from '../ui/contextmenu.js';
import { IconDIN, PluginIcon } from '../ui/icons.js';

export function MatrixCell({ on, filtered, getMenuItems, showContextMenu, offline }) {
    const trigger = useTapMenu(showContextMenu, getMenuItems);
    let cls = on ? (filtered ? 'on filtered' : 'on') : '';
    if (offline) cls += ' offline-cell';
    return html`<td onClick=${trigger.onClick} onContextMenu=${trigger.onContextMenu}>
        <div class="cb ${cls}"></div>
    </td>`;
}

export function MatrixHeader({ item, label, isPlugin, pluginType, sendsClock, clockBlocked, multiEffective, clockBeat, online, getMenuItems, showContextMenu, midiRate }) {
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
    return html`<th class="row-header ${online ? '' : 'offline'} ${isPlugin ? 'plugin-row' : ''}" style="cursor:pointer"
        onClick=${trigger.onClick} onContextMenu=${trigger.onContextMenu}>${isPlugin ? html`<${PluginIcon} type=${pluginType} />` : html`<span class="dev-icon din" style="display:inline-flex;vertical-align:middle;margin-right:3px">${IconDIN}</span>`} ${label}${sendsClock ? html`<span key=${clockBeat || 0} class="clock-icon ${cls}" title="${title}"></span>` : ''}
        <${RateMeter} rate=${midiRate} /></th>`;
}

export function ColumnHeader({ item, label, getMenuItems, showContextMenu }) {
    const trigger = useTapMenu(showContextMenu, getMenuItems);
    return html`<th class="${item.online ? '' : 'offline'} ${item.is_plugin ? 'plugin-col' : ''}" style="cursor:pointer"
        title="${item.multi ? item.dev_name + ': ' + item.port_name : item.dev_name}"
        onClick=${trigger.onClick} onContextMenu=${trigger.onContextMenu}><span>${label}</span></th>`;
}

export function RateMeter({ rate }) {
    if (!rate) return null;
    const max = 1000;
    const pct = Math.min(100, (rate / max) * 100);
    const color = pct < 50 ? 'var(--success)' : pct < 80 ? '#f0ad4e' : 'var(--accent)';
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
            const extra = { client_id: dev.client_id, dev_name: dev.name, dev_default_name: dev.default_name || dev.name, port_name: p.name, port_default_name: p.default_name || p.name, online: dev.online !== false, stable_id: dev.stable_id, is_plugin: !!dev.is_plugin, plugin_type: dev.plugin_type };
            if (p.is_input) inputs.push({ ...p, ...extra, multi: inCount > 1 });
            if (p.is_output) outputs.push({ ...p, ...extra, multi: outCount > 1 });
        }
    }
    const byName = (a, b) => (b.is_plugin - a.is_plugin) || a.dev_name.localeCompare(b.dev_name);
    inputs.sort(byName);
    outputs.sort(byName);

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

    // label(): short text shown in matrix row/column headers
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

    return html`
        <div class="matrix">
            <table>
                <thead>
                    <tr>
                        <th class="corner-header"><span class="from-label">FROM ↓</span><span class="to-label">TO →</span></th>
                        ${outputs.map(o => html`<${ColumnHeader} key=${o.client_id + ':' + o.port_id} item=${o}
                            label=${label(o)}
                            getMenuItems=${() => getHeaderMenuItems ? getHeaderMenuItems(o, 'output') : []}
                            showContextMenu=${showContextMenu} />`)}
                    </tr>
                </thead>
                <tbody>
                    ${inputs.map(inp => {
                        const sendsClock = clockClientIds.includes(inp.client_id);
                        return html`
                        <tr>
                            <${MatrixHeader} item=${inp} label=${label(inp)} isPlugin=${inp.is_plugin} pluginType=${inp.plugin_type}
                                sendsClock=${sendsClock}
                                clockBlocked=${!!blockedById[inp.client_id]}
                                multiEffective=${multiEffective}
                                clockBeat=${clockQuarters && clockQuarters[inp.client_id]}
                                online=${inp.online}
                                getMenuItems=${() => getHeaderMenuItems ? getHeaderMenuItems(inp, 'input') : []}
                                showContextMenu=${showContextMenu}
                                midiRate=${midiRates && midiRates[inp.client_id + ':' + inp.port_id]} />
                            ${outputs.map(out => {
                                if (isSelf(inp, out)) return html`<td class="self"></td>`;
                                const offline = isOffline(inp, out);
                                const conn = getConn(inp, out);
                                const on = !!conn;
                                const filtered = conn && (conn.filtered || (conn.mappings && conn.mappings.length > 0));
                                return html`<${MatrixCell} on=${on} filtered=${filtered} offline=${offline}
                                    getMenuItems=${() => getCellMenuItems ? getCellMenuItems(inp, out, conn) : []}
                                    showContextMenu=${showContextMenu} />`;
                            })}
                        </tr>
                    `;})}
                    ${onAddPlugin && html`<tr>
                        <th class="row-header" style="padding:4px 6px">
                            <button style="background:var(--accent);color:#fff;border:none;border-radius:4px;padding:5px 12px;font-size:12px;font-weight:600;cursor:pointer;width:100%" onclick=${onAddPlugin}>Add</button>
                        </th>
                        ${outputs.map(() => html`<td></td>`)}
                    </tr>`}
                </tbody>
            </table>
        </div>
        <p style="font-size:11px;color:var(--text-dim);text-align:center;margin-top:4px">
            Tap a connection or device for filters, mappings, and copy/paste.
        </p>
    `;
}
