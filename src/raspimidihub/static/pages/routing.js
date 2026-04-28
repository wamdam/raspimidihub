/**
 * Routing page: connection matrix + save/load/import/export config
 * + add-plugin overlay + global Panic.
 */

import { useState, useEffect } from '../lib/hooks.module.js';
import { html, api } from '../ui/common.js';
import { useSSESubscription } from '../ui/sse-subscriptions.js';
import { PluginIcon } from '../ui/icons.js';
import { ConnectionMatrix } from './matrix.js';
import { FilterPanel } from '../panels/filterpanel.js';

export function RoutingPage({ devices, connections, refresh, showToast, clockSources, clockQuarters, midiRates, onDeviceOpen, clipboard, setClipboard, showContextMenu }) {
    // The matrix shows live MIDI activity, clock pulses, message rates,
    // and CC observatory; all of those need their respective events.
    // App already subscribes to device/connection lifecycle.
    useSSESubscription(
        ['midi-activity', 'midi-rates', 'clock-quarter', 'cc-changes',
         'transport-start'],
        [],
    );
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

    // ----- Phase 6: clipboard + context menu actions -----------------
    //
    // The menu lives at App level (one popover for the whole app). We
    // build per-target item lists here and pass them into the matrix as
    // callbacks; the matrix triggers via long-press / right-click.

    const copyConnection = (conn) => {
        // Shallow-copy the filter + mappings the server already gave us
        // on the connection object. No extra fetch needed.
        const payload = {
            filter: conn.filter ? { ...conn.filter } : null,
            mappings: (conn.mappings || []).map(m => ({ ...m })),
        };
        setClipboard({ kind: 'connection', payload });
        const n = (conn.mappings || []).length;
        showToast(`Copied connection (${conn.filter ? 'filter' : 'no filter'}, ${n} mapping${n === 1 ? '' : 's'})`);
    };

    const pasteConnection = async (inp, out, existingConn) => {
        if (!clipboard || clipboard.kind !== 'connection') return;
        const { filter, mappings } = clipboard.payload;

        // POST /api/connections returns {status: "created"} with no id —
        // the codebase builds connection ids deterministically from the
        // src/dst pair. Mirror that here so we always have an id to
        // PATCH the filter and POST the mappings against.
        const offline = !inp.online || !out.online;
        const connId = existingConn ? existingConn.id : (offline
            ? `offline:${inp.stable_id}:${inp.port_id}|${out.stable_id}:${out.port_id}`
            : `${inp.client_id}:${inp.port_id}-${out.client_id}:${out.port_id}`);

        if (existingConn) {
            // Replace, not merge: wipe target mappings so paste mirrors
            // the source. Roadmap §3 open question #1 — replace wins
            // for simplicity.
            for (let i = (existingConn.mappings || []).length - 1; i >= 0; i--) {
                await api(`/mappings/${connId}/${i}`, { method: 'DELETE' });
            }
        } else {
            const body = offline
                ? { src_stable_id: inp.stable_id, src_port: inp.port_id, dst_stable_id: out.stable_id, dst_port: out.port_id }
                : { src_client: inp.client_id, src_port: inp.port_id, dst_client: out.client_id, dst_port: out.port_id };
            const created = await api('/connections', { method: 'POST', body: JSON.stringify(body) });
            if (created && created.error) {
                showToast('Paste failed: ' + created.error);
                return;
            }
        }

        if (filter) {
            await api(`/connections/${connId}`, {
                method: 'PATCH',
                body: JSON.stringify({
                    channel_mask: filter.channel_mask,
                    msg_types: filter.msg_types,
                }),
            });
        }
        for (const m of mappings) {
            await api(`/mappings/${connId}`, { method: 'POST', body: JSON.stringify(m) });
        }
        refresh();
        showToast(`Pasted (${mappings.length} mapping${mappings.length === 1 ? '' : 's'})`);
    };

    const cellMenuItems = (inp, out, conn) => {
        const isCompat = clipboard && clipboard.kind === 'connection';
        if (conn) {
            return [
                { label: 'Edit', action: () => onFilterOpen(conn) },
                { label: 'Copy', action: () => copyConnection(conn) },
                { label: 'Paste', action: () => pasteConnection(inp, out, conn),
                  disabled: !isCompat },
                { divider: true },
                { label: 'Remove', action: () => onToggle(inp, out, false), danger: true },
            ];
        }
        // Empty cell: don't even render Edit / Remove.
        return [
            { label: 'Add connection', action: () => onToggle(inp, out, true) },
            { label: 'Paste', action: () => pasteConnection(inp, out, null),
              disabled: !isCompat },
        ];
    };

    const onFilterOpen = (conn) => setFilterConnId(conn.id);
    const onDeviceOpenForMenu = (clientId) => onDeviceOpen(clientId);
    const onRemoveDevice = async (sid) => {
        await api('/devices/' + encodeURIComponent(sid), { method: 'DELETE' });
        refresh();
    };

    // ----- Plugin clipboard (Copy / Paste-as-new) ---------------------
    //
    // The instance id lives on item.stable_id with the format
    // "plugin-{instance_id}" — strip the prefix to call the plugin API.
    const pluginInstanceId = (item) =>
        (item.stable_id || '').startsWith('plugin-')
            ? item.stable_id.slice('plugin-'.length)
            : null;

    const copyPlugin = async (item) => {
        const id = pluginInstanceId(item);
        if (!id) { showToast('Not a plugin'); return; }
        const data = await api(`/plugins/instances/${id}`);
        if (!data || data.error) {
            showToast('Copy failed: ' + ((data && data.error) || 'unknown'));
            return;
        }
        setClipboard({
            kind: 'plugin',
            payload: { type: data.type, params: data.params || {} },
        });
        showToast(`Copied plugin (${data.type})`);
    };

    const pasteAsNewPlugin = async () => {
        if (!clipboard || clipboard.kind !== 'plugin') return;
        const { type, params } = clipboard.payload;
        // POST returns the full new instance dict including id (unlike
        // POST /connections which returns just status — see paste-
        // connection above).
        const created = await api('/plugins/instances', {
            method: 'POST', body: JSON.stringify({ type }),
        });
        if (!created || created.error || !created.id) {
            showToast('Paste failed: ' + ((created && created.error) || 'no id'));
            return;
        }
        if (params && Object.keys(params).length > 0) {
            await api(`/plugins/instances/${created.id}`, {
                method: 'PATCH', body: JSON.stringify({ params }),
            });
        }
        refresh();
        showToast(`Pasted as new ${type}`);
    };

    const deletePlugin = async (item) => {
        const id = pluginInstanceId(item);
        if (!id) return;
        if (!confirm(`Delete plugin "${item.dev_name}"?`)) return;
        const res = await api(`/plugins/instances/${id}`, { method: 'DELETE' });
        if (res && res.error) { showToast('Delete failed: ' + res.error); return; }
        refresh();
        showToast(`Deleted ${item.dev_name}`);
    };

    // ----- Mapping clipboard (Copy / Paste-with-bump) -----------------

    const copyMapping = (mapping) => {
        setClipboard({ kind: 'mapping', payload: { ...mapping } });
        showToast('Copied mapping');
    };

    // Generate paste candidates: the original first, then bumped
    // variants of the relevant destination field. The server's dup-
    // detection error message contains "already exists" — we use that
    // as the marker to retry vs. give up. Other errors (pointless
    // mapping, invalid shape) abort the loop immediately since
    // bumping wouldn't help.
    const mappingPasteCandidates = function* (mapping) {
        yield { ...mapping };
        const t = mapping.type;
        if (t === 'cc_to_cc') {
            const start = mapping.dst_cc_num != null ? mapping.dst_cc_num : mapping.src_cc;
            for (let off = 1; off < 128; off++) {
                yield { ...mapping, dst_cc_num: (start + off) % 128 };
            }
        } else if (t === 'note_to_cc' || t === 'note_to_cc_toggle') {
            const start = mapping.dst_cc != null ? mapping.dst_cc : 0;
            for (let off = 1; off < 128; off++) {
                yield { ...mapping, dst_cc: (start + off) % 128 };
            }
        } else if (t === 'channel_map') {
            const start = mapping.dst_channel != null ? mapping.dst_channel : 0;
            for (let off = 1; off < 16; off++) {
                yield { ...mapping, dst_channel: (start + off) % 16 };
            }
        }
    };

    const pasteMapping = async () => {
        if (!filterConn || !clipboard || clipboard.kind !== 'mapping') return;
        let bumped = false;
        for (const candidate of mappingPasteCandidates(clipboard.payload)) {
            const res = await api(`/mappings/${filterConn.id}`, {
                method: 'POST', body: JSON.stringify(candidate),
            });
            if (!res.error) {
                refresh();
                showToast(bumped ? 'Pasted (bumped to free slot)' : 'Pasted mapping');
                return;
            }
            // Only retry for duplicates — other errors won't be fixed
            // by bumping. The server's _duplicate_error_message always
            // contains "already exists".
            if (!res.error.toLowerCase().includes('already exists')) {
                showToast('Paste failed: ' + res.error);
                return;
            }
            bumped = true;
        }
        showToast('Paste failed: no free slot in destination range');
    };

    const renameHardware = async (item) => {
        const next = prompt(`Rename "${item.dev_name}":`, item.dev_name);
        if (!next || next === item.dev_name) return;
        const res = await api(`/devices/${item.client_id}/rename`, {
            method: 'POST', body: JSON.stringify({ name: next.trim() }),
        });
        if (res && res.error) { showToast('Rename failed: ' + res.error); return; }
        refresh();
        showToast(`Renamed to "${next.trim()}"`);
    };

    const headerMenuItems = (item) => {
        // Offline hardware: keep the existing "remove?" confirmation
        // available without forcing the user to tap-then-confirm. Offline
        // plugins shouldn't exist (instances live as long as we keep
        // them), so they get the full plugin menu.
        if (!item.online && !item.is_plugin) {
            return [
                { label: 'Remove', danger: true,
                  action: () => item.stable_id && onRemoveDevice && onRemoveDevice(item.stable_id) },
            ];
        }
        if (item.is_plugin) {
            const isCompat = clipboard && clipboard.kind === 'plugin';
            return [
                { label: 'Edit', action: () => onDeviceOpenForMenu(item.client_id) },
                { label: 'Copy', action: () => copyPlugin(item) },
                { label: 'Paste as new', action: () => pasteAsNewPlugin(),
                  disabled: !isCompat },
                { divider: true },
                { label: 'Delete', danger: true, action: () => deletePlugin(item) },
            ];
        }
        // Online hardware: just rename (per spec — "hardware is physical").
        return [
            { label: 'Rename', action: () => renameHardware(item) },
        ];
    };

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
            onMappingCopy=${copyMapping}
            onMappingPaste=${pasteMapping}
            clipboard=${clipboard}
            showContextMenu=${showContextMenu}
            srcClientId=${filterConn.src_client} />`}
        <${ConnectionMatrix} devices=${devices} connections=${connections} onToggle=${onToggle}
            onRemoveDevice=${onRemoveDevice}
            showToast=${showToast} clockSources=${clockSources} clockQuarters=${clockQuarters} midiRates=${midiRates}
            onDeviceOpen=${onDeviceOpen} onAddPlugin=${() => { loadPluginTypes(); setShowAddPlugin(true); }}
            getCellMenuItems=${cellMenuItems} getHeaderMenuItems=${headerMenuItems}
            showContextMenu=${showContextMenu} />
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
