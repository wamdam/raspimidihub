/**
 * Settings page: system info, network/wifi cards, default-routing,
 * MIDI bar toggle, software update, reload, reboot.
 */

import { useState, useEffect } from '../lib/hooks.module.js';
import { html, api } from '../ui/common.js';
import { UPDATE_LABELS } from '../state/constants.js';
import { getSoundsEnabled, setSoundsEnabled } from '../components/common.js';

function NetworkCard({ iface, showToast }) {
    const [method, setMethod] = useState(iface.method || 'auto');
    const [address, setAddress] = useState(iface.address || '');
    const [netmask, setNetmask] = useState(iface.netmask || '255.255.255.0');
    const [gateway, setGateway] = useState(iface.gateway || '');
    const [saving, setSaving] = useState(false);

    const save = async () => {
        setSaving(true);
        const body = { method };
        if (method === 'manual') { body.address = address; body.netmask = netmask; body.gateway = gateway; }
        const res = await api(`/network/${iface.interface}`, { method: 'POST', body: JSON.stringify(body) });
        setSaving(false);
        if (res.error) showToast(res.error);
        else showToast(`${iface.interface} configured`);
    };

    return html`
        <div class="card">
            <h3>${iface.interface} ${iface.up ? html`<span style="color:var(--success);font-size:12px">\u25cf</span>` : html`<span style="color:var(--text-dim);font-size:12px">\u25cb</span>`}</h3>
            ${iface.address && html`<p style="font-size:13px;color:var(--text-dim);margin-bottom:8px">${iface.address}/${iface.netmask}${iface.gateway ? ` gw ${iface.gateway}` : ''}</p>`}
            <div class="form-group">
                <label>Mode</label>
                <select value=${method} onChange=${e => setMethod(e.target.value)}>
                    <option value="auto">DHCP</option>
                    <option value="manual">Static IP</option>
                </select>
            </div>
            ${method === 'manual' && html`
                <div class="form-group">
                    <label>IP Address</label>
                    <input value=${address} onInput=${e => setAddress(e.target.value)} placeholder="10.1.1.2" />
                </div>
                <div style="display:flex;gap:8px">
                    <div class="form-group" style="flex:1">
                        <label>Netmask</label>
                        <input value=${netmask} onInput=${e => setNetmask(e.target.value)} placeholder="255.255.255.0" />
                    </div>
                    <div class="form-group" style="flex:1">
                        <label>Gateway</label>
                        <input value=${gateway} onInput=${e => setGateway(e.target.value)} placeholder="optional" />
                    </div>
                </div>
            `}
            <button class="btn btn-primary btn-block" onclick=${save}>${saving ? 'Applying...' : 'Apply'}</button>
        </div>
    `;
}

function UpgradeCard({ showToast, onUpdatingChange }) {
    const [info, setInfo] = useState(null);
    const [checking, setChecking] = useState(false);
    const [updating, _setUpdating] = useState(false);
    const setUpdating = (v) => { _setUpdating(v); if (onUpdatingChange) onUpdatingChange(v); };
    const [status, setStatus] = useState('');
    const [showLog, setShowLog] = useState(false);
    const [showAll, setShowAll] = useState(false);

    const check = async () => {
        setChecking(true);
        const res = await api('/system/update-check');
        setInfo(res);
        setChecking(false);
    };
    useEffect(() => { check(); }, []);

    const installVersion = async (ver, debUrl) => {
        if (!debUrl) return;
        const action = ver === info.latest ? 'Update' : 'Install';
        if (!confirm(`${action} v${ver}? The service will restart.`)) return;
        setUpdating(true);
        setStatus('starting');
        const res = await api('/system/update', { method: 'POST', body: JSON.stringify({ deb_url: debUrl }) });
        if (res.error) { showToast('Update failed: ' + res.error); setUpdating(false); setStatus(''); return; }

        const startVersion = info.current;
        const poll = setInterval(async () => {
            try {
                const s = await fetch('/api/system/update-status').then(r => r.json()).catch(() => null);
                if (s && s.status) setStatus(s.status);
                if (s && s.status === 'done') setStatus('restarting');
                if (s && s.status && s.status.startsWith('error')) {
                    showToast(s.status); setUpdating(false); clearInterval(poll); return;
                }
                if (s && s.version && s.version !== startVersion) {
                    clearInterval(poll); location.reload(); return;
                }
            } catch (e) {}
        }, 1500);
    };

    const statusLabel = UPDATE_LABELS[status] || (status.startsWith('error') ? status : status);

    return html`
        <div class="card">
            <h3>Software Update</h3>
            ${!info ? html`
                <p style="color:var(--text-dim)">${checking ? 'Checking for updates...' : ''}</p>
            ` : html`
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <span style="font-size:13px">Current: <b>v${info.current}</b></span>
                    ${info.update_available
                        ? html`<span style="font-size:13px;color:var(--success)">Available: <b>v${info.latest}</b></span>`
                        : html`<span style="font-size:13px;color:var(--text-dim)">Up to date</span>`}
                </div>
                ${info.update_available && info.changelog && html`
                    <div style="margin-bottom:8px">
                        <button style="background:none;border:none;color:var(--accent);font-size:12px;cursor:pointer;padding:0"
                            onclick=${() => setShowLog(!showLog)}>${showLog ? '\u25bc' : '\u25b6'} Changelog</button>
                        ${showLog && html`<pre style="font-size:11px;color:var(--text-dim);white-space:pre-wrap;margin-top:4px;max-height:200px;overflow-y:auto;background:var(--bg);padding:8px;border-radius:6px">${info.changelog}</pre>`}
                    </div>
                `}
                ${info.update_available
                    ? html`<button class="btn btn-success btn-block" onclick=${() => installVersion(info.latest, info.deb_url)} disabled=${updating}>
                        ${'Install v' + info.latest}</button>`
                    : html`<button class="btn btn-secondary btn-block" onclick=${check} disabled=${checking}>
                        ${checking ? 'Checking...' : 'Check for updates'}</button>`}
                ${updating && html`<p style="font-size:13px;color:var(--warn);margin-top:8px;text-align:center;font-weight:500">${statusLabel || 'Starting...'}</p>`}
                ${info.offline && html`<p style="font-size:11px;color:var(--text-dim);margin-top:4px">No internet connection — connect to a network to check for updates.</p>`}

                ${info.all_versions && info.all_versions.length > 0 && html`
                    <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--surface2)">
                        <button style="background:none;border:none;color:var(--accent);font-size:12px;cursor:pointer;padding:0"
                            onclick=${() => setShowAll(!showAll)}>${showAll ? '\u25bc' : '\u25b6'} All versions</button>
                        ${showAll && html`
                            <div style="margin-top:8px">
                                ${info.all_versions.map(v => html`
                                    <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--surface2)">
                                        <span style="font-size:13px">
                                            v${v.version}
                                            ${v.version === info.current ? html` <span style="color:var(--text-dim);font-size:11px">(current)</span>` : ''}
                                            ${v.prerelease ? html` <span style="color:var(--warn);font-size:11px">pre</span>` : ''}
                                        </span>
                                        ${v.version !== info.current && html`
                                            <button class="btn btn-secondary" style="padding:4px 12px;font-size:12px"
                                                onclick=${() => installVersion(v.version, v.deb_url)} disabled=${updating}>Install</button>
                                        `}
                                    </div>
                                `)}
                            </div>
                        `}
                    </div>
                `}
            `}
        </div>
    `;
}

function WiFiCard({ showToast }) {
    const [wifi, setWifi] = useState(null);
    const [wantMode, setWantMode] = useState(null); // null = show current, 'ap' or 'client' = show switch form
    const [apPassword, setApPassword] = useState('');
    const [clientSsid, setClientSsid] = useState('');
    const [clientPassword, setClientPassword] = useState('');
    const [networks, setNetworks] = useState([]);
    const [scanning, setScanning] = useState(false);
    const [switching, setSwitching] = useState(false);

    const refresh = () => api('/wifi').then(w => { setWifi(w); setWantMode(null); }).catch(() => {});
    useEffect(() => { refresh(); }, []);

    const scanNetworks = async () => {
        setScanning(true);
        const nets = await api('/wifi/scan');
        setNetworks(nets || []);
        setScanning(false);
    };

    const switchToAp = async () => {
        setSwitching(true);
        const body = {};
        if (apPassword) body.password = apPassword;
        await api('/wifi/ap', { method: 'POST', body: JSON.stringify(body) });
        setSwitching(false);
        showToast('Switched to AP mode');
        refresh();
    };
    const switchToClient = async () => {
        if (!clientSsid) return;
        setSwitching(true);
        showToast('Connecting...');
        const res = await api('/wifi/client', {
            method: 'POST',
            body: JSON.stringify({ ssid: clientSsid, password: clientPassword }),
        });
        setSwitching(false);
        if (res.error) showToast('Connection failed: ' + res.error);
        else showToast('Connected to ' + clientSsid);
        refresh();
    };

    const isAp = wifi && wifi.mode === 'ap';
    const isClient = wifi && wifi.mode === 'client';

    return html`
        <div class="card">
            <h3>WiFi</h3>
            ${!wifi ? html`<p style="color:var(--text-dim)">Loading...</p>` : html`
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;padding:10px;background:var(--bg);border-radius:6px">
                    <span style="font-size:20px">${isAp ? '\uD83D\uDCE1' : '\uD83D\uDD17'}</span>
                    <div style="flex:1">
                        <div style="font-size:15px;font-weight:600">${isAp ? 'Access Point' : 'Client'}: ${wifi.ssid || '-'}</div>
                        <div style="font-size:12px;color:var(--text-dim)">${wifi.ip || 'No IP'}</div>
                    </div>
                    <span style="font-size:11px;padding:3px 8px;border-radius:4px;font-weight:600;${isAp
                        ? 'background:var(--accent2);color:#fff'
                        : 'background:var(--success);color:#fff'}">${isAp ? 'AP' : 'WiFi'}</span>
                </div>

                ${wantMode === null && html`
                    <div class="btn-group">
                        ${isClient && html`<button class="btn btn-secondary" onclick=${() => setWantMode('ap')}>Switch to AP</button>`}
                        ${isAp && html`<button class="btn btn-secondary" onclick=${() => { setWantMode('client'); scanNetworks(); }}>Join WiFi</button>`}
                        ${isAp && html`<button class="btn btn-secondary" onclick=${() => setWantMode('ap-settings')}>AP Settings</button>`}
                    </div>
                `}

                ${wantMode === 'ap-settings' && html`
                    <div class="form-group">
                        <label>AP Password (min 8 chars)</label>
                        <input type="password" value=${apPassword} onInput=${e => setApPassword(e.target.value)} placeholder="Leave empty to keep current" />
                    </div>
                    <div class="btn-group">
                        <button class="btn btn-secondary" onclick=${() => setWantMode(null)}>Cancel</button>
                        <button class="btn btn-primary" onclick=${switchToAp} disabled=${switching}>${switching ? 'Applying...' : 'Apply'}</button>
                    </div>
                `}

                ${wantMode === 'ap' && html`
                    <p style="font-size:13px;color:var(--text-dim);margin-bottom:8px">Switch back to access point mode?</p>
                    <div class="form-group">
                        <label>AP Password (min 8 chars)</label>
                        <input type="password" value=${apPassword} onInput=${e => setApPassword(e.target.value)} placeholder="Leave empty to keep current" />
                    </div>
                    <div class="btn-group">
                        <button class="btn btn-secondary" onclick=${() => setWantMode(null)}>Cancel</button>
                        <button class="btn btn-primary" onclick=${switchToAp} disabled=${switching}>${switching ? 'Switching...' : 'Switch to AP'}</button>
                    </div>
                `}

                ${wantMode === 'client' && html`
                    <div class="form-group">
                        <label>WiFi Network</label>
                        <div style="display:flex;gap:8px">
                            <select style="flex:1" value=${clientSsid} onChange=${e => setClientSsid(e.target.value)}>
                                <option value="">Select network...</option>
                                ${networks.map(n => html`<option value=${n.ssid}>${n.ssid} (${n.signal}%${n.security ? ' ' + n.security : ''})</option>`)}
                            </select>
                            <button class="btn btn-secondary" style="min-width:48px;padding:8px" onclick=${scanNetworks}>
                                ${scanning ? '...' : '\u21bb'}
                            </button>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Password</label>
                        <input type="password" value=${clientPassword} onInput=${e => setClientPassword(e.target.value)} />
                    </div>
                    <div class="btn-group">
                        <button class="btn btn-secondary" onclick=${() => setWantMode(null)}>Cancel</button>
                        <button class="btn btn-primary" onclick=${switchToClient} disabled=${switching || !clientSsid}>${switching ? 'Connecting...' : 'Connect'}</button>
                    </div>
                    <p style="font-size:11px;color:var(--text-dim);margin-top:6px;text-align:center">After connecting, find this device at <b>http://raspimidihub.local</b></p>
                `}
            `}
        </div>
    `;
}

export function SettingsPage({ showToast, showMidiBar, toggleMidiBar }) {
    const [ifaces, setIfaces] = useState([]);
    const [sys, setSys] = useState(null);
    const [defaultRouting, setDefaultRouting] = useState('all');
    const [isUpgrading, setIsUpgrading] = useState(false);
    const [soundsOn, setSoundsOn] = useState(getSoundsEnabled());
    useEffect(() => { api('/network').then(setIfaces).catch(() => {}); }, []);
    useEffect(() => {
        let cancelled = false;
        const tick = () => {
            api('/system').then(s => {
                if (cancelled) return;
                setSys(s);
                setDefaultRouting(s.default_routing || 'all');
            }).catch(() => {});
        };
        tick();
        // Re-poll while Settings is open so the SSE/sec + load gauges
        // tick live. 2s is slow enough not to add noticeable load,
        // fast enough to feel responsive.
        const id = setInterval(tick, 2000);
        return () => { cancelled = true; clearInterval(id); };
    }, []);

    const changeDefaultRouting = async (val) => {
        setDefaultRouting(val);
        await api('/system', { method: 'PATCH', body: JSON.stringify({ default_routing: val }) });
        showToast('Default routing: ' + (val === 'all' ? 'all-to-all' : 'none'));
    };

    const rebootPi = async () => {
        if (confirm('Reboot the Raspberry Pi?')) {
            showToast('Rebooting...');
            fetch('/api/system/reboot', { method: 'POST' }).catch(() => {});
        }
    };

    const uptimeStr = sys && sys.uptime_seconds != null
        ? `${Math.floor(sys.uptime_seconds/3600)}h ${Math.floor((sys.uptime_seconds%3600)/60)}m`
        : '?';

    return html`
        ${sys && html`
            <div class="card">
                <h3>System</h3>
                <div class="stat-grid">
                    <div class="stat"><div class="label">Hostname</div><div class="value">${sys.hostname}</div></div>
                    <div class="stat"><div class="label">Version</div><div class="value">${sys.version}</div></div>
                    <div class="stat"><div class="label">CPU Temp</div><div class="value">${sys.cpu_temp_c != null ? sys.cpu_temp_c + '\u00b0C' : '?'}</div></div>
                    <div class="stat"><div class="label">Uptime</div><div class="value">${uptimeStr}</div></div>
                    ${sys.load1 != null && html`<div class="stat"><div class="label">Load (1m)</div><div class="value">${sys.load1}</div></div>`}
                    <div class="stat"><div class="label">RAM</div><div class="value">${sys.ram.available_mb || '?'} / ${sys.ram.total_mb || '?'} MB</div></div>
                    ${sys.sse_per_sec != null && html`<div class="stat" title="Broadcast events/sec the server pushes to every connected browser. ×N is the number of currently subscribed clients - every event fans out to each, so total socket writes/sec is roughly events × clients.">
                        <div class="label">SSE / sec</div>
                        <div class="value">${sys.sse_per_sec}${sys.sse_clients ? html` <span style="color:var(--text-dim);font-size:11px">× ${sys.sse_clients} ${sys.sse_clients === 1 ? 'client' : 'clients'}</span>` : ''}</div>
                    </div>`}
                    ${sys.sse_queue_depths && sys.sse_queue_depths.length > 0 && html`<div class="stat" title="Per-client SSE outbox depths (max 100). Non-zero means a tab is buffering and the server is fanning ahead of it - usually a phone with the screen off.">
                        <div class="label">SSE backlog</div>
                        <div class="value">${sys.sse_queue_depths.join(' / ')}</div>
                    </div>`}
                    ${(sys.ip_addresses || []).map(ip => html`
                        <div class="stat"><div class="label">${ip.interface}</div><div class="value">${ip.address}</div></div>
                    `)}
                </div>
            </div>
        `}
        <${WiFiCard} showToast=${showToast} />
        ${ifaces.filter(i => i.interface !== 'wlan0').map(i => html`
            <${NetworkCard} iface=${i} showToast=${showToast} />
        `)}
        <div class="card">
            <h3>MIDI Routing</h3>
            <div class="form-group">
                <label>New devices</label>
                <select value=${defaultRouting} onChange=${e => changeDefaultRouting(e.target.value)}>
                    <option value="all">Connect all (default)</option>
                    <option value="none">Disconnected (manual)</option>
                </select>
            </div>
            <p style="font-size:11px;color:var(--text-dim)">When a new device is plugged in, should it be connected to all other devices automatically?</p>
        </div>
        <div class="card">
            <h3>Display</h3>
            <label class="msg-toggle">
                <input type="checkbox" checked=${showMidiBar} onchange=${toggleMidiBar} />
                <span>MIDI activity bar</span>
            </label>
            <label class="msg-toggle">
                <input type="checkbox" checked=${soundsOn}
                    onchange=${e => { setSoundsEnabled(e.target.checked); setSoundsOn(e.target.checked); }} />
                <span>Knob / wheel tick sounds</span>
            </label>
        </div>
        <${UpgradeCard} showToast=${showToast} onUpdatingChange=${setIsUpgrading} />
        <div class="card">
            <button class="btn btn-secondary btn-block" style="margin-bottom:8px" onclick=${() => location.reload()} disabled=${isUpgrading}>Reload App</button>
            <button class="btn btn-danger btn-block" onclick=${rebootPi} disabled=${isUpgrading}>${isUpgrading ? 'Upgrade in progress...' : 'Reboot Pi'}</button>
        </div>
    `;
}
