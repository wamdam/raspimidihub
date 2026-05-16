/**
 * Routing page: connection matrix + save/load/import/export config
 * + add-plugin overlay + global Panic.
 */

import { useState, useEffect } from '../lib/hooks.module.js';
import { html, api } from '../ui/common.js';
import { useSSESubscription } from '../ui/sse-subscriptions.js';
import { useSharedUiState } from '../lib/shared-ui-state.js';
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
    // filterConnId and showAddPlugin drive the two big in-page
    // overlays (filter panel, add-plugin modal). Mirroring them via
    // useSharedUiState lets a spectator see when the source opens
    // those panels. The lists rendered inside them (plugin types,
    // BT devices) are read-only API state and stay component-local
    // — the spectator's view shows the modal frame but its lists
    // will be empty unless the spectator separately fetches.
    const [filterConnId, setFilterConnId] = useSharedUiState('filterConnId', null);
    const [showAddPlugin, setShowAddPlugin] = useSharedUiState('showAddPlugin', false);
    const [pluginTypes, setPluginTypes] = useState({});
    const loadPluginTypes = () => { api('/plugins').then(setPluginTypes).catch(() => {}); };
    const addPlugin = async (typeName) => {
        await api('/plugins/instances', { method: 'POST', body: JSON.stringify({ type: typeName }) });
        showToast('Virtual device created');
        setShowAddPlugin(false);
        refresh();
    };
    // Bluetooth MIDI: state + handlers for the Add Device overlay's
    // BT section. `btAvailable === false` hides the section entirely
    // (Pi-OS variants without bluez / bluealsa). Scan results merge
    // with the paired-devices list so a found-but-not-yet-paired
    // device shows alongside already-paired ones.
    const [btAvailable, setBtAvailable] = useState(false);
    // When unavailable, the API returns a reason — `dbus-next-missing`
    // is the common one on Pis upgraded via the old dpkg-i path
    // (python3-dbus-next is a Recommends since the BLE-MIDI bridge
    // was added; dpkg ignores Recommends so it lands missing). We
    // show a banner with the apt command that fixes it.
    const [btReason, setBtReason] = useState(null);
    const [btDevices, setBtDevices] = useState([]);
    const [btScanning, setBtScanning] = useState(false);
    const [btConnecting, setBtConnecting] = useState(null);
    // Default to MIDI-only — a BLE scan picks up dozens of unrelated
    // peripherals (random-MAC trackers, watches, sensors) which is
    // overwhelming when looking for a synth. Toggle reveals them all
    // for the rare case where a known BLE-MIDI device doesn't
    // advertise the MIDI UUID until after first connection.
    const [btShowAll, setBtShowAll] = useState(false);
    const loadBt = () => { api('/bluetooth').then(r => {
        setBtAvailable(!!r.available);
        setBtReason(r.available ? null : (r.reason || null));
        setBtDevices(r.devices || []);
    }).catch(() => {}); };
    const btScan = async () => {
        setBtScanning(true);
        try {
            const found = await api('/bluetooth/scan', { method: 'POST' });
            setBtDevices(prev => {
                const known = new Set(prev.map(d => d.address));
                const merged = [...prev];
                for (const d of found || []) { if (!known.has(d.address)) merged.push(d); }
                return merged;
            });
        } catch (e) { showToast('BT scan failed'); }
        setBtScanning(false);
    };
    const btConnect = async (address) => {
        // Single /connect call — the backend's BLE-MIDI bridge handles
        // the D-Bus Connect itself and waits for GATT services to
        // resolve. /pair via bluetoothctl was a) often the wrong thing
        // (most BLE-MIDI peripherals don't bond) and b) added ~10s
        // before the real connect even started.
        setBtConnecting(address);
        try {
            const r = await api('/bluetooth/connect', { method: 'POST', body: JSON.stringify({ address }) });
            if (r && r.error) {
                showToast(r.error || 'BT connect failed');
            } else {
                showToast('Bluetooth device connected');
                setShowAddPlugin(false);
                refresh();
            }
        } catch (e) { showToast('BT connect failed'); }
        setBtConnecting(null);
    };
    const btDisconnect = async (address) => {
        await api('/bluetooth/disconnect', { method: 'POST', body: JSON.stringify({ address }) });
        showToast('Bluetooth device disconnected');
        loadBt();
        refresh();
    };
    const btForget = async (address, name) => {
        if (!confirm('Forget ' + (name || address) + '?')) return;
        await api('/bluetooth/' + encodeURIComponent(address), { method: 'DELETE' });
        showToast('Bluetooth device removed');
        loadBt();
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
        } else if (t === 'note_to_note') {
            const start = mapping.dst_note != null ? mapping.dst_note : 60;
            for (let off = 1; off < 128; off++) {
                yield { ...mapping, dst_note: (start + off) % 128 };
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

    const headerMenuItems = (item, _role, fullLabel) => {
        // The matrix row/column labels are abbreviated to leave room
        // for cells. The full label gets surfaced as a styled header
        // at the top of this menu so the user can verify which row /
        // column they tapped before committing to a destructive
        // action (Remove / Delete).
        const headerItem = fullLabel
            ? [{ header: true, label: fullLabel }, { divider: true }]
            : [];
        // Offline hardware: keep the existing "remove?" confirmation
        // available without forcing the user to tap-then-confirm. Offline
        // plugins shouldn't exist (instances live as long as we keep
        // them), so they get the full plugin menu.
        if (!item.online && !item.is_plugin) {
            const items = [];
            // Offline BT devices — paired but not currently connected.
            // Surface a Reconnect right here so the user doesn't have to
            // dig into Add Device → Bluetooth list.
            if (item.is_bluetooth && item.stable_id && item.stable_id.startsWith('bt-')) {
                const addr = item.stable_id.slice(3);
                items.push({
                    label: 'Reconnect',
                    action: async () => {
                        showToast('Reconnecting…');
                        try {
                            const r = await api('/bluetooth/connect', { method: 'POST', body: JSON.stringify({ address: addr }) });
                            if (r && r.error) showToast(r.error || 'Reconnect failed');
                            else { showToast('Reconnected'); refresh(); }
                        } catch (e) { showToast('Reconnect failed'); }
                    },
                });
            }
            items.push({ label: 'Remove', danger: true,
                action: () => item.stable_id && onRemoveDevice && onRemoveDevice(item.stable_id) });
            return [...headerItem, ...items];
        }
        if (item.is_plugin) {
            const isCompat = clipboard && clipboard.kind === 'plugin';
            return [
                ...headerItem,
                { label: 'Edit', action: () => onDeviceOpenForMenu(item.client_id) },
                { label: 'Copy', action: () => copyPlugin(item) },
                { label: 'Paste as new', action: () => pasteAsNewPlugin(),
                  disabled: !isCompat },
                { divider: true },
                { label: 'Delete', danger: true, action: () => deletePlugin(item) },
            ];
        }
        // Online hardware: Edit (opens device-detail panel for MIDI
        // monitor + test sender) and Rename. Hardware can't be deleted
        // here — unplug to remove.
        return [
            ...headerItem,
            { label: 'Edit', action: () => onDeviceOpenForMenu(item.client_id) },
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
        <${ConnectionMatrix} devices=${devices} connections=${connections}
            showToast=${showToast} clockSources=${clockSources} clockQuarters=${clockQuarters} midiRates=${midiRates}
            onAddPlugin=${() => { loadPluginTypes(); loadBt(); setShowAddPlugin(true); }}
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
                <div class="filter-panel" style="max-height:80vh;overflow-y:auto">
                    <div class="panel-header"><div class="panel-handle"></div></div>
                    <div class="panel-header">
                        <h3>Add Device</h3>
                        <button class="panel-close" onclick=${() => setShowAddPlugin(false)}>\u2715</button>
                    </div>
                    ${(() => {
                        // Group addable types by SURFACE_KIND so the
                        // panel matches the runtime taxonomy: Plugins
                        // (routing-graph), Controllers (play-surface),
                        // Play (step-sequencer surfaces), Bluetooth
                        // (live scan, rendered below the grouped list).
                        // ui_demo and other underscore-prefixed types
                        // are dev-only and stay hidden.
                        const sections = [
                            { key: 'plugin',     label: 'Plugins' },
                            { key: 'controller', label: 'Controllers' },
                            { key: 'play',       label: 'Play' },
                        ];
                        const entries = Object.entries(pluginTypes)
                            .filter(([t]) => !t.startsWith('_'));
                        const renderRow = ([type, info]) => html`
                            <div class="device" style="cursor:pointer;padding:12px 0;display:flex;align-items:center;gap:10px" onclick=${() => addPlugin(type)}>
                                <${PluginIcon} type=${type} />
                                <div style="flex:1">
                                    <div style="font-weight:600;margin-bottom:2px;color:#4dd9c0">${info.name}</div>
                                    <div style="font-size:12px;color:var(--text-dim)">${info.description}</div>
                                </div>
                                <span style="color:var(--accent);font-size:13px;font-weight:600">Add</span>
                            </div>`;
                        return sections.map((sec, i) => {
                            const rows = entries.filter(
                                ([, info]) => (info.kind || 'plugin') === sec.key,
                            );
                            if (rows.length === 0) return null;
                            const margin = i === 0
                                ? 'margin:12px 0 8px'
                                : 'margin:20px 0 8px;border-top:1px solid var(--surface2);padding-top:16px';
                            return html`
                                <div style="font-size:11px;text-transform:uppercase;color:var(--text-dim);letter-spacing:1px;${margin};font-weight:600">${sec.label}</div>
                                ${rows.map(renderRow)}
                            `;
                        });
                    })()}
                    ${!btAvailable && btReason === 'dbus-next-missing' && html`
                        <div style="margin-top:20px;padding:12px;background:var(--bg);border:1px solid var(--surface2);border-radius:6px;font-size:12px;color:var(--text-dim);line-height:1.5">
                            <div style="font-weight:600;color:var(--text);margin-bottom:6px">Bluetooth MIDI unavailable</div>
                            The BLE-MIDI bridge needs <code>python3-dbus-next</code>, which is an optional package
                            that wasn't installed when this Pi was upgraded. Click below to fetch it; the Pi will
                            briefly join WiFi to reach apt, install it, and return to the AP.
                            <button class="btn btn-secondary btn-block" style="margin-top:10px;font-size:13px"
                                onclick=${async () => {
                                    try {
                                        const r = await api('/system/reinstall', { method: 'POST' });
                                        if (r && r.error) showToast(r.error);
                                        else showToast('Reinstalling — watch Settings for progress');
                                    } catch (e) { showToast('Reinstall failed to start'); }
                                }}>
                                Reinstall to enable Bluetooth
                            </button>
                            <div style="font-size:11px;color:var(--text-dim);margin-top:6px">
                                Or, from a terminal: <code>sudo apt install python3-dbus-next</code>
                            </div>
                        </div>
                    `}
                    ${btAvailable && html`
                        <div style="font-size:11px;text-transform:uppercase;color:var(--text-dim);letter-spacing:1px;margin:20px 0 8px;font-weight:600;border-top:1px solid var(--surface2);padding-top:16px">Bluetooth MIDI</div>
                        <button class="btn btn-secondary btn-block" style="margin-bottom:8px;font-size:13px"
                            onclick=${btScan} disabled=${btScanning}>
                            ${btScanning ? 'Scanning\u2026' : 'Scan for BLE-MIDI Devices'}
                        </button>
                        ${(() => {
                            // The scan returns every BLE peripheral in
                            // range. Default view filters to entries
                            // that advertise the MIDI service UUID OR
                            // are already paired with us (some devices
                            // only expose MIDI post-pair).
                            const midiOnly = btDevices.filter(
                                d => d.midi || d.paired || d.connected);
                            const nonMidiCount = btDevices.length - midiOnly.length;
                            const visible = btShowAll ? btDevices : midiOnly;
                            return html`
                                ${nonMidiCount > 0 && html`
                                    <div style="display:flex;align-items:center;justify-content:space-between;font-size:11px;color:var(--text-dim);margin-bottom:8px">
                                        <span>${midiOnly.length} MIDI-capable device${midiOnly.length === 1 ? '' : 's'}</span>
                                        <label style="display:inline-flex;align-items:center;gap:5px;cursor:pointer">
                                            <input type="checkbox" checked=${btShowAll}
                                                onchange=${e => setBtShowAll(e.target.checked)} />
                                            <span>Show all (${nonMidiCount} other)</span>
                                        </label>
                                    </div>
                                `}
                                ${visible.length === 0 && !btScanning && html`
                                    <div style="font-size:13px;color:var(--text-dim);text-align:center;padding:8px 0">No Bluetooth MIDI devices found</div>
                                `}
                                ${visible.map(d => html`
                                    <div class="device" style="padding:10px 0;display:flex;align-items:center;gap:10px">
                                        <span style="font-size:18px;color:#4488ff">\u16d2</span>
                                        <div style="flex:1">
                                            <div style="font-weight:600;margin-bottom:2px;color:#4488ff">${d.name || d.address}</div>
                                            <div style="font-size:11px;color:var(--text-dim)">${d.address}${d.midi ? ' \u2022 MIDI' : ''}${d.paired ? ' \u2022 paired' : ''}${d.connected ? ' \u2022 connected' : ''}</div>
                                        </div>
                                        ${d.connected ? html`
                                            <button style="background:none;border:1px solid var(--text-dim);color:var(--text-dim);border-radius:4px;padding:4px 10px;font-size:12px;cursor:pointer"
                                                onclick=${() => btDisconnect(d.address)}>Disconnect</button>
                                            <button style="background:none;border:1px solid var(--accent);color:var(--accent);border-radius:4px;padding:4px 10px;font-size:12px;cursor:pointer"
                                                onclick=${() => btForget(d.address, d.name)}>Forget</button>
                                        ` : html`
                                            <button style="background:var(--accent);color:#fff;border:none;border-radius:4px;padding:5px 12px;font-size:12px;font-weight:600;cursor:pointer"
                                                onclick=${() => btConnect(d.address)} disabled=${btConnecting === d.address}>
                                                ${btConnecting === d.address ? 'Connecting\u2026' : 'Connect'}
                                            </button>
                                        `}
                                    </div>
                                `)}
                            `;
                        })()}
                    `}
                </div>
            </div>
        `}
    `;
}
