import { h, render } from './lib/preact.module.js';
import { useState, useEffect, useCallback } from './lib/hooks.module.js';
import htm from './lib/htm.module.js';

const html = htm.bind(h);

// --- API helpers ---
async function api(path, opts = {}) {
    const res = await fetch(`/api${path}`, {
        headers: { 'Content-Type': 'application/json', ...opts.headers },
        ...opts,
    });
    return res.json();
}

// --- SSE ---
function useSSE(onEvent) {
    useEffect(() => {
        const es = new EventSource('/api/events');
        const handler = (type) => (e) => {
            try { onEvent(type, JSON.parse(e.data)); }
            catch {}
        };
        for (const ev of ['device-connected','device-disconnected','connection-changed','midi-activity']) {
            es.addEventListener(ev, handler(ev));
        }
        return () => es.close();
    }, []);
}

// --- Icons (inline SVG) ---
const IconRouting = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h4l4 6-4 6H4"/><path d="M20 6h-4l-4 6 4 6h4"/></svg>`;
const IconPreset = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>`;
const IconStatus = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4m0 12v4m-8-10H2m20 0h-2m-2.93-6.07l-1.41 1.41m-7.32 7.32l-1.41 1.41m12.14 0l-1.41-1.41M6.34 6.34L4.93 4.93"/><circle cx="12" cy="12" r="4"/></svg>`;
const IconSettings = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2m0 18v2m-9-11h2m16 0h2m-3.64-6.36l-1.42 1.42M6.06 17.94l-1.42 1.42m0-12.72l1.42 1.42m11.88 11.88l1.42 1.42"/></svg>`;

// --- Toast ---
function Toast({ message }) {
    if (!message) return null;
    return html`<div class="toast">${message}</div>`;
}

// --- Filter Panel ---
const MSG_TYPES = ['note', 'cc', 'pc', 'pitchbend', 'aftertouch', 'sysex', 'clock'];
const MSG_LABELS = { note: 'Notes', cc: 'CC', pc: 'Program', pitchbend: 'Pitch Bend', aftertouch: 'Aftertouch', sysex: 'SysEx', clock: 'Clock/RT' };

function FilterPanel({ connId, filter, onClose, onApply }) {
    const [channelMask, setChannelMask] = useState(filter ? filter.channel_mask : 0xFFFF);
    const [msgTypes, setMsgTypes] = useState(new Set(filter ? filter.msg_types : MSG_TYPES));

    const toggleChannel = (ch) => setChannelMask(m => m ^ (1 << ch));
    const toggleAllChannels = () => setChannelMask(m => m === 0xFFFF ? 0 : 0xFFFF);
    const toggleMsgType = (t) => setMsgTypes(s => { const n = new Set(s); n.has(t) ? n.delete(t) : n.add(t); return n; });

    const apply = async () => {
        await onApply(connId, channelMask, [...msgTypes]);
        onClose();
    };
    const clear = async () => {
        await onApply(connId, 0xFFFF, MSG_TYPES);
        onClose();
    };

    return html`
        <div class="filter-overlay" onclick=${(e) => e.target.className === 'filter-overlay' && onClose()}>
            <div class="filter-panel">
                <h3>Filter: ${connId}</h3>
                <div class="card">
                    <h3 style="cursor:pointer" onclick=${toggleAllChannels}>MIDI Channels</h3>
                    <div class="channel-grid">
                        ${Array.from({length: 16}, (_, i) => html`
                            <button class="ch-btn ${channelMask & (1 << i) ? 'on' : ''}"
                                onclick=${() => toggleChannel(i)}>${i + 1}</button>
                        `)}
                    </div>
                </div>
                <div class="card">
                    <h3>Message Types</h3>
                    <div class="msg-types">
                        ${MSG_TYPES.map(t => html`
                            <label class="msg-toggle">
                                <input type="checkbox" checked=${msgTypes.has(t)} onchange=${() => toggleMsgType(t)} />
                                <span>${MSG_LABELS[t]}</span>
                            </label>
                        `)}
                    </div>
                </div>
                <div class="btn-group">
                    <button class="btn btn-primary" onclick=${apply}>Apply Filter</button>
                    <button class="btn btn-secondary" onclick=${clear}>Clear Filter</button>
                </div>
            </div>
        </div>
    `;
}

// --- Matrix cell with long-press + right-click for filters ---
function MatrixCell({ on, filtered, onTap, onLongPress }) {
    const timer = { current: null };
    const didLongPress = { current: false };
    const isTouch = { current: false };

    const start = (e) => {
        if (e.type === 'touchstart') isTouch.current = true;
        if (e.type === 'mousedown' && isTouch.current) return; // skip mouse after touch
        didLongPress.current = false;
        timer.current = setTimeout(() => {
            didLongPress.current = true;
            onLongPress();
        }, 500);
    };
    const cancel = () => {
        if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    };
    const end = (e) => {
        if (e.type === 'mouseup' && isTouch.current) { isTouch.current = false; return; }
        cancel();
        if (!didLongPress.current) onTap();
        e.preventDefault();
    };
    const rightClick = (e) => {
        e.preventDefault();
        onLongPress();
    };

    return html`<td
        onTouchStart=${start} onTouchEnd=${end} onTouchMove=${cancel}
        onMouseDown=${start} onMouseUp=${end} onMouseLeave=${cancel}
        onContextMenu=${rightClick}>
        <div class="cb ${on ? (filtered ? 'on filtered' : 'on') : ''}"></div>
    </td>`;
}

// --- Connection Matrix ---
function ConnectionMatrix({ devices, connections, onToggle, onFilterOpen }) {
    const inputs = [];
    const outputs = [];
    for (const dev of devices) {
        for (const p of dev.ports) {
            if (p.is_input) inputs.push({ ...p, client_id: dev.client_id, dev_name: dev.name });
            if (p.is_output) outputs.push({ ...p, client_id: dev.client_id, dev_name: dev.name });
        }
    }

    const connMap = {};
    for (const c of connections) {
        connMap[`${c.src_client}:${c.src_port}-${c.dst_client}:${c.dst_port}`] = c;
    }

    const getConn = (inp, out) => connMap[`${inp.client_id}:${inp.port_id}-${out.client_id}:${out.port_id}`];
    const isSelf = (inp, out) => inp.client_id === out.client_id;

    const label = (item) => {
        const parts = item.dev_name.split(' ');
        return parts.length > 2 ? parts.slice(0,2).join(' ') : item.dev_name;
    };

    if (inputs.length === 0 || outputs.length === 0) {
        return html`<div class="card"><p style="color:var(--text-dim)">No MIDI devices connected</p></div>`;
    }

    return html`
        <div class="matrix">
            <table>
                <thead>
                    <tr>
                        <th class="corner-header"><span class="from-label">FROM \u2193</span><span class="to-label">TO \u2192</span></th>
                        ${outputs.map(o => html`<th title="${o.dev_name}: ${o.name}">${label(o)}</th>`)}
                    </tr>
                </thead>
                <tbody>
                    ${inputs.map(inp => html`
                        <tr>
                            <th class="row-header" title="${inp.dev_name}: ${inp.name}">${label(inp)}</th>
                            ${outputs.map(out => {
                                if (isSelf(inp, out)) return html`<td class="self"></td>`;
                                const conn = getConn(inp, out);
                                const on = !!conn;
                                const filtered = conn && conn.filtered;
                                return html`<${MatrixCell} on=${on} filtered=${filtered}
                                    onTap=${() => onToggle(inp, out, !on)}
                                    onLongPress=${() => { if (on) onFilterOpen(conn); }} />`;
                            })}
                        </tr>
                    `)}
                </tbody>
            </table>
        </div>
        <p style="font-size:11px;color:var(--text-dim);text-align:center;margin-top:4px">
            Long-press a connection to set filters
        </p>
    `;
}

// --- Routing Page ---
function RoutingPage({ devices, connections, refresh, showToast }) {
    const [filterConn, setFilterConn] = useState(null);

    const onToggle = async (inp, out, connect) => {
        if (connect) {
            await api('/connections', {
                method: 'POST',
                body: JSON.stringify({
                    src_client: inp.client_id, src_port: inp.port_id,
                    dst_client: out.client_id, dst_port: out.port_id,
                }),
            });
        } else {
            const id = `${inp.client_id}:${inp.port_id}-${out.client_id}:${out.port_id}`;
            await api(`/connections/${id}`, { method: 'DELETE' });
        }
        refresh();
    };

    const onFilterApply = async (connId, channelMask, msgTypes) => {
        await api(`/connections/${connId}`, {
            method: 'PATCH',
            body: JSON.stringify({ channel_mask: channelMask, msg_types: msgTypes }),
        });
        refresh();
        showToast('Filter applied');
    };

    const connectAll = async () => {
        await api('/connections/connect-all', { method: 'POST' });
        refresh();
        showToast('All devices connected');
    };
    const disconnectAll = async () => {
        await api('/connections/', { method: 'DELETE' });
        refresh();
        showToast('All connections removed');
    };
    const saveConfig = async () => {
        await api('/config/save', { method: 'POST' });
        showToast('Configuration saved');
    };

    return html`
        ${filterConn && html`<${FilterPanel}
            connId=${filterConn.id}
            filter=${filterConn.filter || null}
            onClose=${() => setFilterConn(null)}
            onApply=${onFilterApply} />`}
        <div class="btn-group">
            <button class="btn btn-success" onclick=${connectAll}>Connect All</button>
            <button class="btn btn-danger" onclick=${disconnectAll}>Disconnect All</button>
        </div>
        <${ConnectionMatrix} devices=${devices} connections=${connections} onToggle=${onToggle} onFilterOpen=${(conn) => setFilterConn(conn)} />
        <button class="btn btn-primary btn-block" onclick=${saveConfig}>Save Configuration</button>
    `;
}

// --- Presets Page ---
function PresetsPage({ refresh, showToast }) {
    const [presets, setPresets] = useState([]);
    const [newName, setNewName] = useState('');

    const loadPresets = async () => {
        const data = await api('/presets');
        setPresets(data);
    };
    useEffect(() => { loadPresets(); }, []);

    const save = async () => {
        if (!newName.trim()) return;
        await api('/presets', { method: 'POST', body: JSON.stringify({ name: newName.trim() }) });
        setNewName('');
        loadPresets();
        showToast('Preset saved');
    };
    const activate = async (name) => {
        await api(`/presets/${encodeURIComponent(name)}/activate`, { method: 'POST' });
        refresh();
        showToast(`Preset "${name}" activated`);
    };
    const del = async (name) => {
        await api(`/presets/${encodeURIComponent(name)}`, { method: 'DELETE' });
        loadPresets();
        showToast('Preset deleted');
    };
    const exportPreset = async (name) => {
        const data = await api(`/presets/${encodeURIComponent(name)}/export`);
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `${name}.json`;
        a.click();
    };
    const importPreset = () => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const text = await file.text();
            const data = JSON.parse(text);
            await api('/presets/import', { method: 'POST', body: JSON.stringify(data) });
            loadPresets();
            showToast('Preset imported');
        };
        input.click();
    };

    return html`
        <div class="card">
            <h3>Save Current Routing</h3>
            <div style="display:flex;gap:8px">
                <input class="form-group" style="flex:1;margin:0;min-height:48px;padding:10px 12px;background:var(--bg);border:1px solid var(--surface2);border-radius:6px;color:var(--text);font-size:14px"
                    placeholder="Preset name" value=${newName} onInput=${e => setNewName(e.target.value)}
                    onKeyDown=${e => e.key === 'Enter' && save()} />
                <button class="btn btn-primary" onclick=${save}>Save</button>
            </div>
        </div>
        <div class="card">
            <h3>Presets</h3>
            ${presets.length === 0 && html`<p style="color:var(--text-dim)">No presets saved</p>`}
            ${presets.map(name => html`
                <div class="preset-item">
                    <span class="name">${name}</span>
                    <button class="btn btn-success" onclick=${() => activate(name)}>Load</button>
                    <button class="btn btn-secondary" onclick=${() => exportPreset(name)}>Export</button>
                    <button class="btn btn-danger" onclick=${() => del(name)}>Del</button>
                </div>
            `)}
        </div>
        <button class="btn btn-secondary btn-block" onclick=${importPreset}>Import Preset</button>
    `;
}

// --- Device Detail Page (MIDI Monitor) ---
function DeviceDetailPage({ device, onClose, showToast }) {
    const [editName, setEditName] = useState(device.name);
    const [events, setEvents] = useState([]);
    const maxEvents = 100;

    useEffect(() => {
        const es = new EventSource('/api/events');
        const handler = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data.src_client === device.client_id) {
                    const line = formatMidiEvent(data);
                    setEvents(prev => [{ ...data, line, ts: Date.now() }, ...prev].slice(0, maxEvents));
                }
            } catch {}
        };
        es.addEventListener('midi-activity', handler);
        return () => es.close();
    }, [device.client_id]);

    const formatMidiEvent = (d) => {
        let s = d.event;
        if (d.channel != null) s += ` ch${d.channel}`;
        if (d.note != null) s += ` note=${d.note} vel=${d.velocity}`;
        if (d.cc != null) s += ` cc=${d.cc} val=${d.value}`;
        return s;
    };

    const rename = async () => {
        if (!editName.trim() || editName === device.name) return;
        await api(`/devices/${device.client_id}/rename`, {
            method: 'POST',
            body: JSON.stringify({ name: editName.trim() }),
        });
        showToast('Device renamed');
    };

    return html`
        <div>
            <button class="btn btn-secondary" onclick=${onClose} style="margin-bottom:var(--gap)">\u2190 Back</button>
            <div class="card">
                <h3>Device Info</h3>
                <div class="stat-grid">
                    <div class="stat"><div class="label">Default Name</div><div class="value">${device.default_name || device.name}</div></div>
                    <div class="stat"><div class="label">Client ID</div><div class="value">${device.client_id}</div></div>
                    ${device.vid ? html`<div class="stat"><div class="label">USB ID</div><div class="value">${device.vid}:${device.pid}</div></div>` : ''}
                    ${device.usb_path ? html`<div class="stat"><div class="label">USB Path</div><div class="value">${device.usb_path}</div></div>` : ''}
                    ${device.stable_id ? html`<div class="stat"><div class="label">Stable ID</div><div class="value" style="font-size:11px">${device.stable_id}</div></div>` : ''}
                </div>
                <div style="display:flex;gap:8px;margin-top:12px">
                    <input style="flex:1;padding:10px 12px;background:var(--bg);border:1px solid var(--surface2);border-radius:6px;color:var(--text);font-size:14px;min-height:48px"
                        value=${editName} onInput=${e => setEditName(e.target.value)}
                        onKeyDown=${e => e.key === 'Enter' && rename()} />
                    <button class="btn btn-primary" onclick=${rename}>Rename</button>
                </div>
            </div>
            <div class="card">
                <h3>Ports</h3>
                ${device.ports.map(p => html`
                    <div class="device">
                        <div class="dot" style="background:${p.is_input ? 'var(--success)' : 'var(--accent)'}"></div>
                        <span class="name">${p.name}</span>
                        <span class="ports">${p.is_input ? 'IN' : ''}${p.is_input && p.is_output ? '/' : ''}${p.is_output ? 'OUT' : ''}</span>
                    </div>
                `)}
            </div>
            <div class="card">
                <h3>MIDI Monitor</h3>
                <div class="midi-monitor">
                    ${events.length === 0 ? html`<p style="color:var(--text-dim)">Waiting for MIDI events...</p>` : ''}
                    ${events.map(e => html`
                        <div class="midi-event">${e.line}</div>
                    `)}
                </div>
            </div>
        </div>
    `;
}

// --- Status Page ---
function StatusPage({ devices, onDeviceSelect }) {
    const [sys, setSys] = useState(null);
    useEffect(() => { api('/system').then(setSys); }, []);

    if (!sys) return html`<div class="loading">Loading...</div>`;

    const uptime = sys.uptime_seconds;
    const uptimeStr = uptime != null
        ? `${Math.floor(uptime/3600)}h ${Math.floor((uptime%3600)/60)}m`
        : '?';

    return html`
        <div class="card">
            <h3>System</h3>
            <div class="stat-grid">
                <div class="stat"><div class="label">Hostname</div><div class="value">${sys.hostname}</div></div>
                <div class="stat"><div class="label">Version</div><div class="value">${sys.version}</div></div>
                <div class="stat"><div class="label">CPU Temp</div><div class="value">${sys.cpu_temp_c != null ? sys.cpu_temp_c + '\u00b0C' : '?'}</div></div>
                <div class="stat"><div class="label">Uptime</div><div class="value">${uptimeStr}</div></div>
                <div class="stat"><div class="label">RAM</div><div class="value">${sys.ram.available_mb || '?'} / ${sys.ram.total_mb || '?'} MB</div></div>
                ${(sys.ip_addresses || []).map(ip => html`
                    <div class="stat"><div class="label">${ip.interface}</div><div class="value">${ip.address}</div></div>
                `)}
            </div>
        </div>
        <div class="card">
            <h3>Connected Devices (${devices.length})</h3>
            ${devices.map(d => html`
                <div class="device" style="cursor:pointer" onclick=${() => onDeviceSelect(d)}>
                    <div class="dot"></div>
                    <span class="name">${d.name}</span>
                    <span class="ports">${d.ports.length} port${d.ports.length !== 1 ? 's' : ''} \u203a</span>
                </div>
            `)}
            ${devices.length === 0 && html`<p style="color:var(--text-dim)">No devices connected</p>`}
        </div>
    `;
}

// --- Settings Page ---
function SettingsPage({ showToast }) {
    const [wifi, setWifi] = useState(null);
    const [apPassword, setApPassword] = useState('');
    const [clientSsid, setClientSsid] = useState('');
    const [clientPassword, setClientPassword] = useState('');

    useEffect(() => { api('/wifi').then(setWifi).catch(() => {}); }, []);

    const switchToAp = async () => {
        const body = {};
        if (apPassword) body.password = apPassword;
        await api('/wifi/ap', { method: 'POST', body: JSON.stringify(body) });
        api('/wifi').then(setWifi);
        showToast('Switched to AP mode');
    };
    const switchToClient = async () => {
        if (!clientSsid) return;
        const res = await api('/wifi/client', {
            method: 'POST',
            body: JSON.stringify({ ssid: clientSsid, password: clientPassword }),
        });
        if (res.error) showToast('Connection failed: ' + res.error);
        else showToast('Connected to ' + clientSsid);
        api('/wifi').then(setWifi);
    };
    const rebootPi = async () => {
        if (confirm('Reboot the Raspberry Pi?')) {
            showToast('Rebooting...');
            fetch('/api/system/reboot', { method: 'POST' }).catch(() => {});
        }
    };

    return html`
        <div class="card">
            <h3>WiFi Status</h3>
            ${wifi ? html`
                <div class="stat-grid">
                    <div class="stat"><div class="label">Mode</div><div class="value">${wifi.mode}</div></div>
                    <div class="stat"><div class="label">SSID</div><div class="value">${wifi.ssid || '-'}</div></div>
                    <div class="stat"><div class="label">IP</div><div class="value">${wifi.ip || '-'}</div></div>
                </div>
            ` : html`<p style="color:var(--text-dim)">WiFi info unavailable</p>`}
        </div>
        <div class="card">
            <h3>Access Point Mode</h3>
            <div class="form-group">
                <label>AP Password (min 8 chars)</label>
                <input type="password" value=${apPassword} onInput=${e => setApPassword(e.target.value)} placeholder="Leave empty to keep current" />
            </div>
            <button class="btn btn-primary btn-block" onclick=${switchToAp}>Switch to AP Mode</button>
        </div>
        <div class="card">
            <h3>Client Mode (Join WiFi)</h3>
            <div class="form-group">
                <label>WiFi SSID</label>
                <input value=${clientSsid} onInput=${e => setClientSsid(e.target.value)} placeholder="Network name" />
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" value=${clientPassword} onInput=${e => setClientPassword(e.target.value)} />
            </div>
            <button class="btn btn-primary btn-block" onclick=${switchToClient}>Connect</button>
        </div>
        <div class="card">
            <h3>System</h3>
            <button class="btn btn-danger btn-block" onclick=${rebootPi}>Reboot Pi</button>
        </div>
    `;
}

// --- Main App ---
function App() {
    const [tab, setTab] = useState('routing');
    const [devices, setDevices] = useState([]);
    const [connections, setConnections] = useState([]);
    const [toast, setToast] = useState('');
    const [configFallback, setConfigFallback] = useState(false);
    const [selectedDevice, setSelectedDevice] = useState(null);

    const refresh = useCallback(async () => {
        const [devs, conns] = await Promise.all([api('/devices'), api('/connections')]);
        setDevices(devs);
        setConnections(conns);
    }, []);

    useEffect(() => {
        refresh();
        api('/system').then(s => setConfigFallback(s.config_fallback));
    }, []);

    useSSE((type, data) => {
        if (type === 'device-connected' || type === 'device-disconnected' || type === 'connection-changed') {
            refresh();
        }
    });

    const showToast = (msg) => {
        setToast(msg);
        setTimeout(() => setToast(''), 2500);
    };

    // Device detail view overrides the current tab
    if (selectedDevice) {
        return html`
            <div class="header">
                <h1>RaspiMIDIHub</h1>
                <span class="status ${devices.length > 0 ? 'ok' : ''}">${devices.length} device${devices.length !== 1 ? 's' : ''}</span>
            </div>
            <div class="main">
                <${DeviceDetailPage} device=${selectedDevice}
                    onClose=${() => { setSelectedDevice(null); refresh(); }}
                    showToast=${showToast} />
            </div>
            <${Toast} message=${toast} />
        `;
    }

    let page;
    switch (tab) {
        case 'routing':
            page = html`<${RoutingPage} devices=${devices} connections=${connections} refresh=${refresh} showToast=${showToast} />`;
            break;
        case 'presets':
            page = html`<${PresetsPage} refresh=${refresh} showToast=${showToast} />`;
            break;
        case 'status':
            page = html`<${StatusPage} devices=${devices} onDeviceSelect=${setSelectedDevice} />`;
            break;
        case 'settings':
            page = html`<${SettingsPage} showToast=${showToast} />`;
            break;
    }

    return html`
        <div class="header">
            <h1>RaspiMIDIHub</h1>
            <span class="status ${devices.length > 0 ? 'ok' : ''}">${devices.length} device${devices.length !== 1 ? 's' : ''}</span>
        </div>
        ${configFallback && html`<div class="banner">Config unreadable — using default all-to-all routing. Save to fix.</div>`}
        <div class="main">${page}</div>
        <nav class="bottom-nav">
            <button class=${tab === 'routing' ? 'active' : ''} onclick=${() => setTab('routing')}>${IconRouting}<span>Routing</span></button>
            <button class=${tab === 'presets' ? 'active' : ''} onclick=${() => setTab('presets')}>${IconPreset}<span>Presets</span></button>
            <button class=${tab === 'status' ? 'active' : ''} onclick=${() => setTab('status')}>${IconStatus}<span>Status</span></button>
            <button class=${tab === 'settings' ? 'active' : ''} onclick=${() => setTab('settings')}>${IconSettings}<span>Settings</span></button>
        </nav>
        <${Toast} message=${toast} />
    `;
}

render(html`<${App} />`, document.getElementById('app'));
