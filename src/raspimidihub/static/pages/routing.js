/**
 * Routing page: connection matrix + save/load/import/export config
 * + add-plugin overlay + global Panic.
 */

import { useState, useEffect } from '../lib/hooks.module.js';
import { html, api } from '../ui/common.js';
import { PluginIcon } from '../ui/icons.js';
import { ConnectionMatrix } from './matrix.js';
import { FilterPanel } from '../panels/filterpanel.js';

export function RoutingPage({ devices, connections, refresh, showToast, clockSources, clockQuarters, midiRates, onDeviceOpen }) {
    const [filterConnId, setFilterConnId] = useState(null);
    const [showAddPlugin, setShowAddPlugin] = useState(false);
    const [pluginTypes, setPluginTypes] = useState({});
    const loadPluginTypes = () => { api('/plugins').then(setPluginTypes).catch(() => {}); };
    const addPlugin = async (typeName) => {
        await api('/plugins/instances', { method: 'POST', body: JSON.stringify({ type: typeName }) });
        showToast('Virtual device created');
        setShowAddPlugin(false);
        refresh();
    };
    const filterConn = filterConnId ? connections.find(c => c.id === filterConnId) || null : null;

    const onToggle = async (inp, out, connect) => {
        const offline = !inp.online || !out.online;
        if (connect) {
            const body = offline
                ? { src_stable_id: inp.stable_id, src_port: inp.port_id, dst_stable_id: out.stable_id, dst_port: out.port_id }
                : { src_client: inp.client_id, src_port: inp.port_id, dst_client: out.client_id, dst_port: out.port_id };
            await api('/connections', {
                method: 'POST',
                body: JSON.stringify(body),
            });
        } else {
            const conn = connections.find(c =>
                (c.offline && c.src_stable_id === inp.stable_id && c.dst_stable_id === out.stable_id
                    && c.src_port === inp.port_id && c.dst_port === out.port_id)
                || (!c.offline && c.src_client === inp.client_id && c.src_port === inp.port_id
                    && c.dst_client === out.client_id && c.dst_port === out.port_id));
            const id = conn ? conn.id : `${inp.client_id}:${inp.port_id}-${out.client_id}:${out.port_id}`;
            await api(`/connections/${encodeURIComponent(id)}`, { method: 'DELETE' });
        }
        refresh();
    };

    const onFilterApply = async (connId, channelMask, msgTypes) => {
        await api(`/connections/${connId}`, {
            method: 'PATCH',
            body: JSON.stringify({ channel_mask: channelMask, msg_types: msgTypes }),
        });
        refresh();
    };

    const onMappingAdd = async (mappingData) => {
        if (!filterConn) return;
        const res = await api(`/mappings/${filterConn.id}`, {
            method: 'POST',
            body: JSON.stringify(mappingData),
        });
        if (res.error) { showToast(res.error); return; }
        refresh();
        showToast('Mapping added');
    };

    const onMappingDelete = async (index) => {
        if (!filterConn) return;
        await api(`/mappings/${filterConn.id}/${index}`, { method: 'DELETE' });
        refresh();
        showToast('Mapping removed');
    };

    const onMappingSave = async (index, mappingData) => {
        if (!filterConn) return;
        await api(`/mappings/${filterConn.id}/${index}`, { method: 'DELETE' });
        await api(`/mappings/${filterConn.id}`, {
            method: 'POST',
            body: JSON.stringify(mappingData),
        });
        refresh();
        showToast('Mapping updated');
    };

    const [saving, setSaving] = useState(false);
    const saveConfig = async () => {
        setSaving(true);
        await api('/config/save', { method: 'POST' });
        setSaving(false);
        showToast('Configuration saved');
    };
    const [loading, setLoading] = useState(false);
    const loadConfig = async () => {
        setLoading(true);
        await api('/config/load', { method: 'POST' });
        setLoading(false);
        refresh();
        showToast('Configuration loaded');
    };
    // Panic state machine: 'idle' → tap → 'soft' → tap → 'hard' (briefly, then back to idle)
    // Incoming MIDI Start resets to 'idle'. Hard auto-decays after 600ms.
    const [panicState, setPanicState] = useState('idle');
    const panic = async () => {
        const goingHard = panicState === 'soft';
        setPanicState(goingHard ? 'hard' : 'soft');
        try {
            await api('/panic', { method: 'POST', body: JSON.stringify({ hard: goingHard }) });
            showToast(goingHard ? 'Panic — all sound off' : 'Panic — all notes off');
        } catch {}
        if (goingHard) {
            setTimeout(() => setPanicState('idle'), 600);
        }
    };
    useEffect(() => {
        const es = new EventSource('/api/events');
        const reset = () => setPanicState('idle');
        es.addEventListener('transport-start', reset);
        return () => es.close();
    }, []);

    return html`
        ${filterConn && html`<${FilterPanel}
            connId=${filterConn.id}
            filter=${filterConn.filter || null}
            mappings=${filterConn.mappings || []}
            onClose=${() => setFilterConnId(null)}
            onApply=${onFilterApply}
            onMappingAdd=${onMappingAdd}
            onMappingDelete=${onMappingDelete}
            onMappingSave=${onMappingSave}
            srcClientId=${filterConn.src_client} />`}
        <${ConnectionMatrix} devices=${devices} connections=${connections} onToggle=${onToggle} onFilterOpen=${(conn) => setFilterConnId(conn.id)}
            onRemoveDevice=${async (sid) => { await api('/devices/' + encodeURIComponent(sid), { method: 'DELETE' }); refresh(); }}
            showToast=${showToast} clockSources=${clockSources} clockQuarters=${clockQuarters} midiRates=${midiRates}
            onDeviceOpen=${onDeviceOpen} onAddPlugin=${() => { loadPluginTypes(); setShowAddPlugin(true); }} />
        <div class="btn-group">
            <button class="btn btn-primary" onclick=${saveConfig} disabled=${saving || loading}>${saving ? 'Saving...' : 'Save Config'}</button>
            <button class="btn btn-secondary" onclick=${loadConfig} disabled=${saving || loading}>${loading ? 'Loading...' : 'Load Config'}</button>
        </div>
        <div class="btn-group" style="margin-top:4px">
            <button class="btn btn-secondary" onclick=${() => { const a = document.createElement('a'); a.href = '/api/config/export'; a.download = 'raspimidihub-config.json'; a.click(); }}>Export Config</button>
            <button class="btn btn-secondary" onclick=${() => {
                const inp = document.createElement('input'); inp.type = 'file'; inp.accept = '.json';
                inp.onchange = async () => { const text = await inp.files[0].text(); const data = JSON.parse(text);
                    await api('/config/import', { method: 'POST', body: JSON.stringify(data) }); refresh(); showToast('Config imported'); };
                inp.click();
            }}>Import Config</button>
        </div>
        <div class="btn-group" style="margin-top:4px">
            <button class="btn btn-panic ${panicState === 'soft' ? 'btn-panic-soft' : ''} ${panicState === 'hard' ? 'btn-panic-hard' : ''}" onclick=${panic}>
                ${panicState === 'soft' ? 'Press again for full Sound Off' : 'Panic — All Notes Off'}
            </button>
        </div>
        ${showAddPlugin && html`
            <div class="filter-overlay" onclick=${(e) => e.target.className === 'filter-overlay' && setShowAddPlugin(false)}>
                <div class="filter-panel" style="max-height:70vh">
                    <div class="panel-header"><div class="panel-handle"></div></div>
                    <div class="panel-header">
                        <h3>Add Virtual Device</h3>
                        <button class="panel-close" onclick=${() => setShowAddPlugin(false)}>\u2715</button>
                    </div>
                    ${Object.entries(pluginTypes).filter(([t]) => !t.startsWith('_')).map(([type, info]) => html`
                        <div class="device" style="cursor:pointer;padding:12px 0;display:flex;align-items:center;gap:10px" onclick=${() => addPlugin(type)}>
                            <${PluginIcon} type=${type} />
                            <div style="flex:1">
                                <div style="font-weight:600;margin-bottom:2px;color:#4dd9c0">${info.name}</div>
                                <div style="font-size:12px;color:var(--text-dim)">${info.description}</div>
                            </div>
                            <span style="color:var(--accent);font-size:13px;font-weight:600">Add</span>
                        </div>
                    `)}
                </div>
            </div>
        `}
    `;
}
