/**
 * Connection matrix + its sub-components (cells, headers, rate meter).
 */

import { useState, useRef } from '../lib/hooks.module.js';
import { html } from '../ui/common.js';
import { IconDIN, PluginIcon } from '../ui/icons.js';

let _blockClick = false;

export function MatrixCell({ on, filtered, onTap, onLongPress, offline }) {
    const [s] = useState(() => ({ timer: null }));

    const startTimer = () => {
        _blockClick = false;
        s.timer = setTimeout(() => { _blockClick = true; s.timer = null; onLongPress(); }, 500);
    };
    const cancelTimer = () => {
        if (s.timer) { clearTimeout(s.timer); s.timer = null; }
    };

    let cls = on ? (filtered ? 'on filtered' : 'on') : '';
    if (offline) cls += ' offline-cell';

    return html`<td
        onTouchStart=${startTimer}
        onTouchEnd=${cancelTimer}
        onTouchMove=${cancelTimer}
        onMouseDown=${startTimer}
        onMouseUp=${cancelTimer}
        onMouseLeave=${cancelTimer}
        onClick=${(e) => {
            if (_blockClick) { _blockClick = false; e.preventDefault(); return; }
            onTap();
        }}
        onContextMenu=${(e) => { e.preventDefault(); onLongPress(); }}>
        <div class="cb ${cls}"></div>
    </td>`;
}

export function MatrixHeader({ item, label, isPlugin, pluginType, sendsClock, multiClock, online, stableId, onTap, onLongPress, midiRate }) {
    const timerRef = useRef(null);
    const didLong = useRef(false);
    const start = () => { didLong.current = false; timerRef.current = setTimeout(() => { didLong.current = true; onLongPress(); }, 500); };
    const end = () => { if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; } };
    const click = (e) => { if (!didLong.current) onTap(); };
    const ctx = (e) => { e.preventDefault(); onLongPress(); };
    return html`<th class="row-header ${online ? '' : 'offline'} ${isPlugin ? 'plugin-row' : ''}" style="cursor:pointer"
        onclick=${click} onContextMenu=${ctx}
        onTouchStart=${start} onTouchEnd=${end} onTouchCancel=${end}>${isPlugin ? html`<${PluginIcon} type=${pluginType} />` : html`<span class="dev-icon din" style="display:inline-flex;vertical-align:middle;margin-right:3px">${IconDIN}</span>`} ${label}${sendsClock ? html`<span class="clock-icon ${multiClock ? 'clock-warn' : ''}" title="${multiClock ? 'Multiple clock sources!' : 'Sending clock'}"></span>` : ''}
        <${RateMeter} rate=${midiRate} /></th>`;
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

export function ConnectionMatrix({ devices, connections, onToggle, onFilterOpen, onRemoveDevice, showToast, clockSources, midiRates, onDeviceOpen, onAddPlugin }) {
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
        if (short.length > 20) short = short.slice(0, 19) + '\u2026';
        return short;
    };
    const showName = (item) => {
        const name = item.multi ? `${item.dev_name}: ${item.port_name}` : item.dev_name;
        const origDev = item.dev_default_name && item.dev_default_name !== item.dev_name;
        const origPort = item.multi && item.port_default_name && item.port_default_name !== item.port_name;
        const orig = origDev || origPort
            ? origPort ? `${item.dev_default_name}: ${item.port_default_name}` : item.dev_default_name
            : null;
        const clock = clockSources && clockSources[item.client_id];
        showToast(html`<span>${name}</span>${orig ? html` <span style="color:var(--text-dim);font-weight:normal;font-size:12px">(${orig})</span>` : ''}${clock ? html` <span style="font-size:12px">${multiClock ? '\u26a0 Clock (multiple!)' : '\u23f1 Clock'}</span>` : ''}`);
    };

    const clockClientIds = clockSources ? Object.keys(clockSources).map(Number) : [];
    const multiClock = clockClientIds.length > 1;

    if (inputs.length === 0 || outputs.length === 0) {
        return html`<div class="card"><p style="color:var(--text-dim)">No MIDI devices connected</p></div>`;
    }

    return html`
        <div class="matrix">
            <table>
                <thead>
                    <tr>
                        <th class="corner-header"><span class="from-label">FROM \u2193</span><span class="to-label">TO \u2192</span></th>
                        ${outputs.map(o => html`<th class="${o.online ? '' : 'offline'} ${o.is_plugin ? 'plugin-col' : ''}" style="cursor:pointer"
                            title="${o.multi ? o.dev_name + ': ' + o.port_name : o.dev_name}"
                            onclick=${() => o.online && o.client_id ? onDeviceOpen(o.client_id) : (o.stable_id && onRemoveDevice && confirm('Remove ' + o.dev_name + '?') && onRemoveDevice(o.stable_id))}
                            onContextMenu=${(e) => { e.preventDefault(); if (o.online) showName(o); }}><span>${label(o)}</span></th>`)}
                    </tr>
                </thead>
                <tbody>
                    ${inputs.map(inp => {
                        const sendsClock = clockClientIds.includes(inp.client_id);
                        return html`
                        <tr>
                            <${MatrixHeader} item=${inp} label=${label(inp)} isPlugin=${inp.is_plugin} pluginType=${inp.plugin_type}
                                sendsClock=${sendsClock} multiClock=${multiClock}
                                online=${inp.online} stableId=${inp.stable_id}
                                onTap=${() => inp.online && inp.client_id ? onDeviceOpen(inp.client_id) : (inp.stable_id && onRemoveDevice && confirm('Remove ' + inp.dev_name + '?') && onRemoveDevice(inp.stable_id))}
                                onLongPress=${() => inp.online && showName(inp)}
                                midiRate=${midiRates && midiRates[inp.client_id + ':' + inp.port_id]} />
                            ${outputs.map(out => {
                                if (isSelf(inp, out)) return html`<td class="self"></td>`;
                                const offline = isOffline(inp, out);
                                const conn = getConn(inp, out);
                                const on = !!conn;
                                const filtered = conn && (conn.filtered || (conn.mappings && conn.mappings.length > 0));
                                return html`<${MatrixCell} on=${on} filtered=${filtered} offline=${offline}
                                    onTap=${() => onToggle(inp, out, !on)}
                                    onLongPress=${() => { if (on) onFilterOpen(conn); }} />`;
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
            Long-press or right-click a connection for filters & mappings
        </p>
    `;
}
