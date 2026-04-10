import { h, render } from './lib/preact.module.js';
import { useState, useEffect, useCallback, useRef } from './lib/hooks.module.js';
import htm from './lib/htm.module.js';
import { PluginConfigPanel, renderParamList, tickFeedback, PluginWheel, PluginFader, PluginRadio, PluginNoteSelect, PluginToggle } from './plugin-controls.js';

const html = htm.bind(h);

// --- Reusable hooks ---
function useEscapeClose(close) {
    useEffect(() => {
        const handler = (e) => { if (e.key === 'Escape') close(); };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, []);
}

// --- API helpers ---
async function api(path, opts = {}) {
    const res = await fetch(`/api${path}`, {
        headers: { 'Content-Type': 'application/json', ...opts.headers },
        ...opts,
    });
    return res.json();
}

// --- SSE ---
function useSSE(onEvent, onConnChange) {
    useEffect(() => {
        const es = new EventSource('/api/events');
        const handler = (type) => (e) => {
            try { onEvent(type, JSON.parse(e.data)); }
            catch {}
        };
        for (const ev of ['device-connected','device-disconnected','connection-changed','midi-activity','midi-rates','plugin-display']) {
            es.addEventListener(ev, handler(ev));
        }
        es.onopen = () => onConnChange(true);
        es.onerror = () => onConnChange(false);
        return () => es.close();
    }, []);
}

// --- Icons (inline SVG) ---
const IconRouting = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h4l4 6-4 6H4"/><path d="M20 6h-4l-4 6 4 6h4"/></svg>`;
const IconPreset = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>`;
const IconStatus = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4m0 12v4m-8-10H2m20 0h-2m-2.93-6.07l-1.41 1.41m-7.32 7.32l-1.41 1.41m12.14 0l-1.41-1.41M6.34 6.34L4.93 4.93"/><circle cx="12" cy="12" r="4"/></svg>`;
const IconSettings = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2m0 18v2m-9-11h2m16 0h2m-3.64-6.36l-1.42 1.42M6.06 17.94l-1.42 1.42m0-12.72l1.42 1.42m11.88 11.88l1.42 1.42"/></svg>`;

// DIN MIDI connector icon (5-pin) for hardware devices
const IconDIN = html`<svg viewBox="0 0 20 20" class="dev-icon din"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="6" cy="8" r="1.2" fill="currentColor"/><circle cx="14" cy="8" r="1.2" fill="currentColor"/><circle cx="10" cy="13" r="1.2" fill="currentColor"/><circle cx="7" cy="12" r="1.2" fill="currentColor"/><circle cx="13" cy="12" r="1.2" fill="currentColor"/></svg>`;

// Plugin icon: fetched from /api/plugins/icon/{type} and injected inline for currentColor
const _iconCache = {};
function PluginIcon({ type }) {
    const [svg, setSvg] = useState(_iconCache[type] || null);
    useEffect(() => {
        if (_iconCache[type]) { setSvg(_iconCache[type]); return; }
        fetch(`/api/plugins/icon/${type}`).then(r => r.ok ? r.text() : '').then(t => {
            if (t) { _iconCache[type] = t; setSvg(t); }
        }).catch(() => {});
    }, [type]);
    if (!svg) return null;
    return html`<span class="dev-icon plugin" dangerouslySetInnerHTML=${{ __html: svg }}></span>`;
}

function DeviceIcon({ device }) {
    if (device.is_plugin && device.plugin_type) return html`<${PluginIcon} type=${device.plugin_type} />`;
    return IconDIN;
}

// --- Toast ---
function Toast({ message }) {
    if (!message) return null;
    return html`<div class="toast">${message}</div>`;
}

// --- MIDI Activity Bar ---
function MidiBar({ events }) {
    const now = Date.now();
    const entries = Object.values(events).filter(e => now - e.ts < 2000).sort((a, b) => b.ts - a.ts);
    const truncName = (n) => n.length > 8 ? n.slice(0, 7) + '\u2026' : n;
    const countStr = (e) => e.count > 1 ? ' x' + e.count : '';
    if (entries.length === 0) return html`<div class="midi-bar"><span class="midi-bar-empty">\u00b7\u00b7\u00b7</span></div>`;
    const left = entries[0];
    const right = entries.length > 1 ? entries[1] : null;
    return html`<div class="midi-bar">
        <span class="midi-bar-l"><b>In:</b> <span class="midi-bar-name">${truncName(left.name)}</span> ${left.detail}${countStr(left)}</span>
        ${right && html`<span class="midi-bar-r"><b>In:</b> <span class="midi-bar-name">${truncName(right.name)}</span>\u2002${right.detail}${countStr(right)}</span>`}
    </div>`;
}

// --- Filter Panel ---
const MSG_TYPES = ['note', 'cc', 'pc', 'pitchbend', 'aftertouch', 'sysex', 'clock'];
const MSG_LABELS = { note: 'Notes', cc: 'CC', pc: 'Program', pitchbend: 'Pitch Bend', aftertouch: 'Aftertouch', sysex: 'SysEx', clock: 'Clock/RT' };

const MAPPING_TYPES = [
    { value: 'note_to_cc', label: 'Note \u2192 CC' },
    { value: 'note_to_cc_toggle', label: 'Note \u2192 CC (toggle)' },
    { value: 'cc_to_cc', label: 'CC \u2192 CC' },
    { value: 'channel_map', label: 'Channel Remap' },
];

// --- Animated panel close ---
function animateClose(panelEl, onDone) {
    if (!panelEl) { onDone(); return; }
    panelEl.classList.add('closing');
    panelEl.addEventListener('animationend', onDone, { once: true });
    setTimeout(onDone, 250); // fallback
}

// --- Swipe-down dismiss hook ---
const _swipeIgnore = '.wheel-container, .fader-track, .metal-toggle, .piano, .piano-key, .mini-wheel, .curve-canvas-wrap, .step-head';
function useSwipeDismiss(onDismiss) {
    const [s] = useState(() => ({ startY: 0, el: null, ignore: false }));
    const onTouchStart = (e) => {
        s.startY = e.touches[0].clientY;
        s.el = e.currentTarget;
        s.ignore = !!e.target.closest(_swipeIgnore);
    };
    const onTouchEnd = (e) => {
        if (s.ignore) return;
        const dy = e.changedTouches[0].clientY - s.startY;
        if (dy > 80 && s.el && s.el.scrollTop <= 0) onDismiss();
    };
    return { onTouchStart, onTouchEnd };
}

// --- Mapping description helper ---
function mappingDesc(m) {
    const sch = m.src_channel != null ? `CH${m.src_channel + 1} ` : '';
    const dch = m.dst_channel != null ? `CH${m.dst_channel + 1} ` : sch;
    const pt = m.pass_through ? ' +thru' : '';
    if (m.type === 'note_to_cc') return `${sch}${noteName(m.src_note)} \u2192 ${dch}CC${m.dst_cc} (${m.cc_on_value}/${m.cc_off_value})${pt}`;
    if (m.type === 'note_to_cc_toggle') return `${sch}${noteName(m.src_note)} \u2192 ${dch}CC${m.dst_cc} toggle (${m.cc_on_value}/${m.cc_off_value})${pt}`;
    if (m.type === 'cc_to_cc') return `${sch}CC${m.src_cc} (${m.in_range_min}-${m.in_range_max}) \u2192 ${dch}CC${m.dst_cc_num} (${m.out_range_min}-${m.out_range_max})${pt}`;
    if (m.type === 'channel_map') return `${sch || 'CH* '}\u2192 CH${m.dst_channel + 1}`;
    return m.type;
}

// --- Mapping Form (sub-overlay) ---
function MappingFormOverlay({ onSubmit, onClose, editing, srcClientId }) {
    const panelRef = { current: null };
    const close = () => animateClose(panelRef.current, onClose);
    const [type, setType] = useState(editing ? editing.type : 'note_to_cc');
    const [srcChannel, setSrcChannel] = useState(editing && editing.src_channel != null ? String(editing.src_channel) : '');
    const [srcNote, setSrcNote] = useState(editing ? (editing.src_note || 60) : 60);
    const [dstCc, setDstCc] = useState(editing ? (editing.dst_cc || 1) : 1);
    const [ccOnVal, setCcOnVal] = useState(editing ? (editing.cc_on_value != null ? editing.cc_on_value : 127) : 127);
    const [ccOffVal, setCcOffVal] = useState(editing ? (editing.cc_off_value != null ? editing.cc_off_value : 0) : 0);
    const [srcCc, setSrcCc] = useState(editing ? (editing.src_cc || 1) : 1);
    const [dstCcNum, setDstCcNum] = useState(editing ? (editing.dst_cc_num || 1) : 1);
    const [inMin, setInMin] = useState(editing ? (editing.in_range_min || 0) : 0);
    const [inMax, setInMax] = useState(editing ? (editing.in_range_max != null ? editing.in_range_max : 127) : 127);
    const [outMin, setOutMin] = useState(editing ? (editing.out_range_min || 0) : 0);
    const [outMax, setOutMax] = useState(editing ? (editing.out_range_max != null ? editing.out_range_max : 127) : 127);
    const [dstChannel, setDstChannel] = useState(editing ? (editing.dst_channel != null ? editing.dst_channel : 0) : 0);
    const [passThrough, setPassThrough] = useState(editing ? !!editing.pass_through : false);
    const [learning, setLearning] = useState(false);

    // MIDI Learn
    useEffect(() => {
        if (!learning) return;
        const es = new EventSource('/api/events');
        const handler = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data.src_client === srcClientId && (data.note != null || data.cc != null)) {
                    if (data.note != null) {
                        setType('note_to_cc'); setSrcNote(data.note);
                        if (data.channel != null) { setSrcChannel(String(data.channel - 1)); setDstChannel(data.channel - 1); }
                    } else if (data.cc != null) {
                        setType('cc_to_cc'); setSrcCc(data.cc);
                        if (data.channel != null) { setSrcChannel(String(data.channel - 1)); setDstChannel(data.channel - 1); }
                    }
                    setLearning(false);
                }
            } catch {}
        };
        es.addEventListener('midi-activity', handler);
        const timeout = setTimeout(() => setLearning(false), 10000);
        return () => { es.close(); clearTimeout(timeout); };
    }, [learning]);

    useEscapeClose(close);

    const swipe = useSwipeDismiss(close);

    const onSrcChannelChange = (val) => {
        setSrcChannel(val);
        if (val !== '') setDstChannel(+val);
    };

    const submit = () => {
        const m = { type, dst_channel: +dstChannel, pass_through: passThrough };
        if (srcChannel !== '') m.src_channel = +srcChannel;
        if (type === 'note_to_cc' || type === 'note_to_cc_toggle') {
            m.src_note = +srcNote; m.dst_cc = +dstCc;
            m.cc_on_value = +ccOnVal; m.cc_off_value = +ccOffVal;
        } else if (type === 'cc_to_cc') {
            m.src_cc = +srcCc; m.dst_cc_num = +dstCcNum;
            m.in_range_min = +inMin; m.in_range_max = +inMax;
            m.out_range_min = +outMin; m.out_range_max = +outMax;
        }
        onSubmit(m);
    };

    // Wheel onChange adapter: (name, value) → state setter
    const w = (setter) => (_, v) => setter(v);

    return html`
        <div class="mapping-overlay" onclick=${(e) => e.target.className === 'mapping-overlay' && close()}>
            <div class="mapping-panel" ref=${el => panelRef.current = el} ...${swipe}>
                <div class="panel-header">
                    <div class="panel-handle"></div>
                </div>
                <div class="panel-header">
                    <h3>${editing ? 'Edit Mapping' : 'Add Mapping'}</h3>
                    <button class="panel-close" onclick=${close}>\u2715</button>
                </div>
                <${PluginRadio} name="type" label="Type"
                    options=${MAPPING_TYPES.map(t => t.label)}
                    value=${MAPPING_TYPES.find(t => t.value === type)?.label || type}
                    onChange=${(_, label) => { const t = MAPPING_TYPES.find(m => m.label === label); if (t) setType(t.value); }} />
                <div style="display:flex;gap:12px;flex-wrap:wrap">
                    <${PluginWheel} name="srcCh" label="Src Ch" min=${0} max=${16}
                        value=${srcChannel === '' ? 0 : +srcChannel + 1}
                        tickLabel=${(v) => v === 0 ? 'Any' : v}
                        onChange=${(_, v) => { if (v === 0) setSrcChannel(''); else setSrcChannel(String(v - 1)); }} />
                    <${PluginWheel} name="dstCh" label="Dst Ch" min=${1} max=${16}
                        value=${dstChannel + 1} onChange=${(_, v) => setDstChannel(v - 1)} />
                </div>
                ${(type === 'note_to_cc' || type === 'note_to_cc_toggle') && html`
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginNoteSelect} name="srcNote" label="Src Note"
                            value=${srcNote} onChange=${w(setSrcNote)} />
                        <${PluginWheel} name="dstCc" label="Dst CC" min=${0} max=${127}
                            value=${dstCc} onChange=${w(setDstCc)} />
                    </div>
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginWheel} name="onVal" label="On Val" min=${0} max=${127}
                            value=${ccOnVal} onChange=${w(setCcOnVal)} />
                        <${PluginWheel} name="offVal" label="Off Val" min=${0} max=${127}
                            value=${ccOffVal} onChange=${w(setCcOffVal)} />
                    </div>
                `}
                ${type === 'cc_to_cc' && html`
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginWheel} name="srcCc" label="Src CC" min=${0} max=${127}
                            value=${srcCc} onChange=${w(setSrcCc)} />
                        <${PluginWheel} name="dstCcNum" label="Dst CC" min=${0} max=${127}
                            value=${dstCcNum} onChange=${w(setDstCcNum)} />
                    </div>
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginWheel} name="inMin" label="In Min" min=${0} max=${127}
                            value=${inMin} onChange=${w(setInMin)} />
                        <${PluginWheel} name="inMax" label="In Max" min=${0} max=${127}
                            value=${inMax} onChange=${w(setInMax)} />
                    </div>
                    <div style="display:flex;gap:12px">
                        <${PluginWheel} name="outMin" label="Out Min" min=${0} max=${127}
                            value=${outMin} onChange=${w(setOutMin)} />
                        <${PluginWheel} name="outMax" label="Out Max" min=${0} max=${127}
                            value=${outMax} onChange=${w(setOutMax)} />
                    </div>
                `}
                ${type !== 'channel_map' && html`
                    <${PluginToggle} name="passThrough" label="Pass through"
                        value=${passThrough} onChange=${(_, v) => setPassThrough(v)} />
                `}
                <div class="btn-group">
                    <button class="btn btn-primary" onclick=${submit}>${editing ? 'Save' : 'Add'}</button>
                    ${!editing && html`<button class="btn btn-secondary ${learning ? 'btn-held' : ''}" onclick=${() => setLearning(true)}>
                        ${learning ? 'Listening...' : 'MIDI Learn'}
                    </button>`}
                </div>
            </div>
        </div>
    `;
}

function FilterPanel({ connId, filter, mappings, onClose, onApply, onMappingAdd, onMappingDelete, onMappingSave, srcClientId }) {
    const panelRef = { current: null };
    const close = () => animateClose(panelRef.current, onClose);
    const [channelMask, setChannelMask] = useState(filter ? filter.channel_mask : 0xFFFF);
    const [msgTypes, setMsgTypes] = useState(new Set(filter ? filter.msg_types : MSG_TYPES));
    const [mappingForm, setMappingForm] = useState(null); // null | { editing: null|obj, index: null|int }

    // Sync state when filter prop changes from outside (other device updated via SSE)
    const filterKey = filter ? `${filter.channel_mask}:${filter.msg_types.join(',')}` : 'none';
    useEffect(() => {
        setChannelMask(filter ? filter.channel_mask : 0xFFFF);
        setMsgTypes(new Set(filter ? filter.msg_types : MSG_TYPES));
    }, [filterKey]);

    // ESC to close
    useEffect(() => {
        const handler = (e) => { if (e.key === 'Escape') { if (mappingForm) setMappingForm(null); else close(); } };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [mappingForm]);

    const swipe = useSwipeDismiss(close);

    const applyFilter = (mask, types) => onApply(connId, mask, [...types]);

    const toggleChannel = (ch) => {
        const newMask = channelMask ^ (1 << ch);
        setChannelMask(newMask);
        applyFilter(newMask, msgTypes);
    };
    const toggleAllChannels = () => {
        const newMask = channelMask === 0xFFFF ? 0 : 0xFFFF;
        setChannelMask(newMask);
        applyFilter(newMask, msgTypes);
    };
    const toggleMsgType = (t) => {
        const n = new Set(msgTypes);
        n.has(t) ? n.delete(t) : n.add(t);
        setMsgTypes(n);
        applyFilter(channelMask, n);
    };

    const handleMappingSubmit = async (data) => {
        if (mappingForm && mappingForm.editing) {
            await onMappingSave(mappingForm.index, data);
        } else {
            await onMappingAdd(data);
        }
        setMappingForm(null);
    };

    return html`
        <div class="filter-overlay" onclick=${(e) => e.target.className === 'filter-overlay' && close()}>
            <div class="filter-panel" ref=${el => panelRef.current = el} ...${swipe}>
                <div class="panel-header">
                    <div class="panel-handle"></div>
                </div>
                <div class="panel-header">
                    <h3>Connection: ${connId}</h3>
                    <button class="panel-close" onclick=${close}>\u2715</button>
                </div>
                <div class="card">
                    <h3 style="cursor:pointer" onclick=${toggleAllChannels}>MIDI Channels</h3>
                    <div class="channel-grid">
                        ${Array.from({length: 16}, (_, i) => {
                            const on = !!(channelMask & (1 << i));
                            return html`
                                <button class="ch-btn" onclick=${() => toggleChannel(i)}>
                                    <span class="ch-num">${i + 1}</span>
                                    <span class="ch-light">
                                        <span class="ch-dot ${on ? '' : 'lit'}" style="background:${on ? 'var(--surface2)' : 'var(--error)'}"></span>
                                        <span class="ch-dot ${on ? 'lit' : ''}" style="background:${on ? 'var(--success)' : 'var(--surface2)'}"></span>
                                    </span>
                                </button>`;
                        })}
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
                <div class="card">
                    <h3>Mappings</h3>
                    ${(!mappings || mappings.length === 0)
                        ? html`<p style="color:var(--text-dim);font-size:13px">No mappings configured</p>`
                        : mappings.map((m, i) => html`
                            <div class="preset-item">
                                <span class="name" style="font-size:13px">${mappingDesc(m)}</span>
                                <button class="btn btn-secondary" onclick=${() => setMappingForm({ editing: m, index: i })}>Edit</button>
                                <button class="btn btn-danger" onclick=${() => onMappingDelete(i)}>Del</button>
                            </div>
                        `)}
                    <button class="btn btn-primary btn-block" style="margin-top:8px" onclick=${() => setMappingForm({ editing: null, index: null })}>+ Add Mapping</button>
                </div>
            </div>
        </div>
        ${mappingForm && html`<${MappingFormOverlay}
            editing=${mappingForm.editing}
            srcClientId=${srcClientId}
            onSubmit=${handleMappingSubmit}
            onClose=${() => setMappingForm(null)} />`}
    `;
}

// --- Matrix cell with long-press + right-click for filters ---
let _blockClick = false;

function MatrixCell({ on, filtered, onTap, onLongPress, offline }) {
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

// --- Connection Matrix ---
function MatrixHeader({ item, label, isPlugin, pluginType, sendsClock, multiClock, online, stableId, onTap, onLongPress, midiRate }) {
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

function RateMeter({ rate }) {
    if (!rate) return null;
    const max = 1000; // DIN MIDI limit
    const pct = Math.min(100, (rate / max) * 100);
    const color = pct < 50 ? 'var(--success)' : pct < 80 ? '#f0ad4e' : 'var(--accent)';
    return html`<div class="rate-meter" title="${rate} msg/s">
        <div class="rate-bar" style="width:${pct}%;background:${color}"></div>
    </div>`;
}

function ConnectionMatrix({ devices, connections, onToggle, onFilterOpen, onRemoveDevice, showToast, clockSources, midiRates, onDeviceOpen, onAddPlugin }) {
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
    const byName = (a, b) => a.dev_name.localeCompare(b.dev_name);
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
        // Try active connection first
        const active = connMap[`${inp.client_id}:${inp.port_id}-${out.client_id}:${out.port_id}`];
        if (active) return active;
        // Try offline connection by stable ID
        if (inp.stable_id && out.stable_id) {
            return connMap[`offline:${inp.stable_id}:${inp.port_id}|${out.stable_id}:${out.port_id}`];
        }
        return null;
    };
    const isSelf = (inp, out) => inp.client_id && inp.client_id === out.client_id;
    const isOffline = (inp, out) => !inp.online || !out.online;

    // label(): short text shown in matrix row/column headers
    // item.dev_name = current device name (renamed or ALSA default)
    // item.dev_default_name = original ALSA device name
    // item.port_name = current port name (renamed or ALSA default)
    // item.port_default_name = original ALSA port name
    // item.multi = device has multiple input or output ports
    const label = (item) => {
        // Multi-port device with renamed port: show full custom port name (user chose it)
        if (item.multi && item.port_name !== item.port_default_name) {
            return item.port_name;
        }
        // Otherwise: show (possibly renamed) device name, truncated to 2 words
        const parts = item.dev_name.split(' ');
        let short = parts.length > 2 ? parts.slice(0,2).join(' ') : item.dev_name;
        if (item.multi) short += ` p${item.port_id + 1}`;
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

    // Clock indicator: count how many input ports are sending clock
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

// --- Routing Page ---
function RoutingPage({ devices, connections, refresh, showToast, clockSources, midiRates, onDeviceOpen }) {
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
            showToast=${showToast} clockSources=${clockSources} midiRates=${midiRates}
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
    const overwrite = async (name) => {
        if (!confirm(`Overwrite preset "${name}" with current routing?`)) return;
        await api('/presets', { method: 'POST', body: JSON.stringify({ name }) });
        showToast(`Preset "${name}" updated`);
    };
    const del = async (name) => {
        if (!confirm(`Delete preset "${name}"?`)) return;
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
            <h3>Save Current Routing and Instrument Settings</h3>
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
                <div style="margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--surface2)">
                    <div style="font-weight:500;margin-bottom:6px">${name}</div>
                    <div style="display:flex;gap:6px">
                        <button class="btn btn-success" onclick=${() => activate(name)}>Load</button>
                        <button class="btn btn-primary" onclick=${() => overwrite(name)}>Save</button>
                        <button class="btn btn-secondary" onclick=${() => exportPreset(name)}>Export</button>
                        <button class="btn btn-danger" onclick=${() => del(name)}>Del</button>
                    </div>
                </div>
            `)}
        </div>
        <button class="btn btn-secondary btn-block" onclick=${importPreset}>Import Preset</button>
    `;
}

// --- Note name helper ---
const NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
const noteName = (n) => NOTE_NAMES[n % 12] + (Math.floor(n / 12) - 2);

// --- Device Detail Page ---
function PortRenameRow({ device, port, showToast }) {
    const [name, setName] = useState(port.name);
    const [dirty, setDirty] = useState(false);
    const save = async () => {
        await api(`/devices/${device.client_id}/rename-port`, {
            method: 'POST',
            body: JSON.stringify({ port_id: port.port_id, name: name.trim() }),
        });
        showToast('Port renamed');
        setDirty(false);
    };
    const dir = (port.is_input ? 'IN' : '') + (port.is_input && port.is_output ? '/' : '') + (port.is_output ? 'OUT' : '');
    return html`
        <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
            <span style="font-size:11px;color:var(--text-dim);min-width:30px">${dir}</span>
            <input style="flex:1;padding:6px 8px;background:var(--bg);border:1px solid var(--surface2);border-radius:4px;color:var(--text);font-size:12px"
                value=${name} onInput=${e => { setName(e.target.value); setDirty(true); }} onKeyDown=${e => e.key === 'Enter' && save()} />
            ${dirty && name.trim() !== port.name && html`
                <button style="padding:4px 10px;background:var(--accent);color:#fff;border:none;border-radius:4px;font-size:11px;cursor:pointer;white-space:nowrap" onclick=${save}>Save</button>
            `}
        </div>
    `;
}

// --- Scrollable Piano (JS-based scroll + multitouch notes) ---
// touch-action:none so multitouch works with fader simultaneously
function ScrollablePiano({ heldNotes, onNoteDown, onNoteUp, pianoKeys }) {
    const scrollRef = useRef(null);
    const pianoRef = useRef(null);
    const noteDownRef = useRef(onNoteDown);
    noteDownRef.current = onNoteDown;
    const noteUpRef = useRef(onNoteUp);
    noteUpRef.current = onNoteUp;
    // Per-touch state: { startX, startY, scrolling, note, moved }
    const touches = useRef(new Map());
    const SCROLL_THRESH = 12;

    // Scroll to C3 on mount
    useEffect(() => {
        const el = scrollRef.current;
        if (el) el.scrollLeft = 3 * 7 * 34;
    }, []);

    const noteFromPoint = (x, y) => {
        const el = document.elementFromPoint(x, y);
        if (!el || !el.dataset.midi) return null;
        return +el.dataset.midi;
    };

    // All touch handling in JS — no native scroll
    useEffect(() => {
        const container = scrollRef.current;
        if (!container) return;

        function onTouchStart(e) {
            e.preventDefault();
            for (const t of e.changedTouches) {
                const note = noteFromPoint(t.clientX, t.clientY);
                touches.current.set(t.identifier, {
                    startX: t.clientX, startY: t.clientY,
                    scrollLeft: container.scrollLeft,
                    scrolling: false, note: null, moved: false,
                });
                // Play note immediately (will cancel if it becomes a scroll)
                if (note != null) {
                    touches.current.get(t.identifier).note = note;
                    noteDownRef.current(note);
                }
            }
        }

        function onTouchMove(e) {
            e.preventDefault();
            for (const t of e.changedTouches) {
                const state = touches.current.get(t.identifier);
                if (!state) continue;
                const dx = t.clientX - state.startX;
                const dy = t.clientY - state.startY;

                if (!state.scrolling && !state.moved) {
                    // Decide: horizontal scroll or vertical stay
                    if (Math.abs(dx) > SCROLL_THRESH && Math.abs(dx) > Math.abs(dy)) {
                        state.scrolling = true;
                        // Keep the note held while scrolling — note-off on finger lift
                    } else if (Math.abs(dy) > SCROLL_THRESH) {
                        state.moved = true; // vertical — not a scroll, keep note
                    }
                }

                if (state.scrolling) {
                    container.scrollLeft = state.scrollLeft - dx;
                }
            }
        }

        function onTouchEnd(e) {
            for (const t of e.changedTouches) {
                const state = touches.current.get(t.identifier);
                if (!state) continue;
                if (state.note != null) noteUpRef.current(state.note);
                touches.current.delete(t.identifier);
            }
        }

        container.addEventListener('touchstart', onTouchStart, { passive: false });
        container.addEventListener('touchmove', onTouchMove, { passive: false });
        container.addEventListener('touchend', onTouchEnd, { passive: false });
        container.addEventListener('touchcancel', onTouchEnd, { passive: false });
        return () => {
            container.removeEventListener('touchstart', onTouchStart);
            container.removeEventListener('touchmove', onTouchMove);
            container.removeEventListener('touchend', onTouchEnd);
            container.removeEventListener('touchcancel', onTouchEnd);
        };
    }, []);  // stable refs — no re-attach on render

    // Mouse: drag background to scroll, click keys to play
    const onMouseDown = (e) => {
        if (e.target.closest('.piano-key')) return;
        const el = scrollRef.current;
        const startX = e.clientX, startScroll = el.scrollLeft;
        const onMove = (ev) => { el.scrollLeft = startScroll - (ev.clientX - startX); };
        const onUp = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
        window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp);
    };

    const isHeld = (midi) => heldNotes && heldNotes.has(midi);

    return html`<div ref=${scrollRef} style="margin-bottom:16px;overflow-x:hidden;touch-action:none"
        onMouseDown=${onMouseDown}>
        <div class="piano" ref=${pianoRef} style="width:${7 * 8 * 34}px"
            onMouseLeave=${() => onNoteUp()}>
            ${Array.from({length: 8}, (_, oct) =>
                pianoKeys.filter(k => !k.black).map(k => {
                    const midi = (oct + 1) * 12 + k.n;
                    if (midi > 127) return null;
                    return html`<div class="piano-key white ${isHeld(midi) ? 'active' : ''}" data-midi=${midi}
                        onMouseDown=${() => onNoteDown(midi)} onMouseUp=${() => onNoteUp(midi)}>
                        ${k.n === 0 ? html`<span class="piano-label">C${oct}</span>` : ''}
                    </div>`;
                })
            ).flat()}
            ${Array.from({length: 8}, (_, oct) =>
                pianoKeys.filter(k => k.black).map(k => {
                    const midi = (oct + 1) * 12 + k.n;
                    if (midi > 127) return null;
                    const whitesBefore = oct * 7 + pianoKeys.filter(x => !x.black && x.n < k.n).length;
                    const leftPx = whitesBefore * 34;
                    return html`<div class="piano-key black ${isHeld(midi) ? 'active' : ''}" data-midi=${midi}
                        style="left:${leftPx}px"
                        onMouseDown=${(e) => { e.stopPropagation(); onNoteDown(midi); }} onMouseUp=${() => onNoteUp(midi)}>
                    </div>`;
                })
            ).flat()}
        </div>
    </div>`;
}

function DeviceDetailPanel({ device, onClose, showToast, refresh, pluginDisplays }) {
    const panelRef = { current: null };
    const close = () => animateClose(panelRef.current, onClose);
    const swipe = useSwipeDismiss(close);

    const [editName, setEditName] = useState(device.name);
    const [sendChannel, setSendChannel] = useState(0);
    const [sendPort, setSendPort] = useState(0);
    const [ccNum, setCcNum] = useState(1);
    const [ccVal, setCcVal] = useState(64);
    const [heldNotes, setHeldNotes] = useState(new Set());
    const maxEvents = 50;

    // Plugin state
    const isPlugin = !!device.is_plugin;
    const [pluginData, setPluginData] = useState(null);
    const [showHelp, setShowHelp] = useState(false);
    const [pluginParams, setPluginParams] = useState({});
    useEffect(() => {
        if (isPlugin && device.plugin_instance_id) {
            api(`/plugins/instances/${device.plugin_instance_id}`)
                .then(d => { setPluginData(d); setPluginParams(d.params || {}); })
                .catch(() => {});
        }
    }, [device.plugin_instance_id]);

    // Display values come from SSE via pluginDisplays prop
    const displayValues = (pluginDisplays && device.plugin_instance_id) ? pluginDisplays[device.plugin_instance_id] || {} : {};

    const onPluginParamChange = useCallback((name, value) => {
        setPluginParams(prev => ({ ...prev, [name]: value }));
        if (device.plugin_instance_id) {
            api(`/plugins/instances/${device.plugin_instance_id}`, {
                method: 'PATCH',
                body: JSON.stringify({ params: { [name]: value } }),
            }).catch(() => {});
        }
    }, [device.plugin_instance_id]);

    const deletePlugin = async () => {
        if (!confirm('Delete this virtual device?')) return;
        await api(`/plugins/instances/${device.plugin_instance_id}`, { method: 'DELETE' });
        showToast('Plugin deleted');
        close();
        if (refresh) refresh();
    };

    const outPorts = device.ports.filter(p => p.is_output);

    // Use refs for MIDI monitor to avoid re-rendering the whole panel
    const monitorRef = useRef(null);
    const lastEventRef = useRef(null);
    const eventsRef = useRef([]);

    useEffect(() => {
        const es = new EventSource('/api/events');
        const handler = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data.src_client === device.client_id && data.event !== 'Clock') {
                    const line = formatEvent(data);
                    eventsRef.current = [{ line, ts: Date.now() }, ...eventsRef.current].slice(0, maxEvents);
                    if (lastEventRef.current) lastEventRef.current.textContent = line;
                    if (monitorRef.current) {
                        monitorRef.current.innerHTML = eventsRef.current.map(ev =>
                            `<div class="midi-event">${ev.line}</div>`).join('');
                    }
                }
            } catch {}
        };
        es.addEventListener('midi-activity', handler);
        return () => es.close();
    }, [device.client_id]);

    useEscapeClose(close);

    const formatEvent = (d) => {
        let s = d.event;
        if (d.channel != null) s += ` ch${d.channel}`;
        if (d.note != null) s += ` ${noteName(d.note)} vel=${d.velocity}`;
        if (d.cc != null) s += ` cc${d.cc}=${d.value}`;
        return s;
    };

    const [nameDirty, setNameDirty] = useState(false);
    const rename = async () => {
        if (!editName.trim() || editName === device.name) return;
        await api(`/devices/${device.client_id}/rename`, {
            method: 'POST',
            body: JSON.stringify({ name: editName.trim() }),
        });
        showToast('Device renamed');
        setNameDirty(false);
    };

    const sendMidi = (type, extra = {}) => {
        api(`/devices/${device.client_id}/send`, {
            method: 'POST',
            body: JSON.stringify({ type, channel: sendChannel, port: sendPort, ...extra }),
        });
    };

    const pianoNoteDown = (n) => { if (!heldNotes.has(n)) { sendMidi('note_on', { note: n, velocity: 100 }); setHeldNotes(prev => new Set(prev).add(n)); } };
    const pianoNoteUp = (n) => {
        if (n != null) { sendMidi('note_off', { note: n }); setHeldNotes(prev => { const s = new Set(prev); s.delete(n); return s; }); }
        else { heldNotes.forEach(note => sendMidi('note_off', { note })); setHeldNotes(new Set()); }
    };
    const pianoKeys = [
        { n: 0, name: 'C', black: false },
        { n: 1, name: 'C#', black: true },
        { n: 2, name: 'D', black: false },
        { n: 3, name: 'D#', black: true },
        { n: 4, name: 'E', black: false },
        { n: 5, name: 'F', black: false },
        { n: 6, name: 'F#', black: true },
        { n: 7, name: 'G', black: false },
        { n: 8, name: 'G#', black: true },
        { n: 9, name: 'A', black: false },
        { n: 10, name: 'A#', black: true },
        { n: 11, name: 'B', black: false },
    ];

    const sendCC = (val) => {
        setCcVal(val);
        sendMidi('cc', { cc: ccNum, value: val });
    };

    return html`
        <div class="filter-overlay" onclick=${(e) => e.target.className === 'filter-overlay' && close()}>
            <div class="filter-panel" ref=${el => panelRef.current = el} ...${swipe}>
                <div class="panel-header">
                    <div class="panel-handle"></div>
                </div>
                <div class="panel-header" style="display:flex;align-items:center;gap:8px">
                    <input style="flex:1;padding:6px 10px;background:var(--bg);border:1px solid var(--surface2);border-radius:6px;color:var(--text);font-size:16px;font-weight:600"
                        value=${editName} onInput=${e => { setEditName(e.target.value); setNameDirty(true); }}
                        onKeyDown=${e => e.key === 'Enter' && rename()} />
                    ${nameDirty && editName.trim() !== device.name && html`<button style="padding:5px 12px;background:var(--accent);color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;white-space:nowrap" onclick=${rename}>Save</button>`}
                    <button class="panel-close" onclick=${close}>\u2715</button>
                </div>

                ${isPlugin && html`
                    <div class="card">
                        <h3>Ports</h3>
                        ${device.ports.map(p => html`
                            <${PortRenameRow} device=${device} port=${p} showToast=${showToast} />
                        `)}
                    </div>
                `}

                ${isPlugin && pluginData && html`
                    <div class="card">
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                            <h3 style="margin:0">Plugin Config</h3>
                            ${pluginData.help && html`<button style="width:24px;height:24px;border-radius:50%;border:1px solid var(--text-dim);background:none;color:var(--text-dim);font-size:13px;cursor:pointer;display:flex;align-items:center;justify-content:center"
                                onclick=${() => setShowHelp(h => !h)}>?</button>`}
                        </div>
                        ${showHelp && pluginData.help && html`
                            <div style="font-size:12px;color:var(--text-dim);background:var(--bg);padding:10px;border-radius:6px;margin-bottom:12px;white-space:pre-wrap;line-height:1.5">${pluginData.help}</div>
                        `}
                        <${PluginConfigPanel}
                            instanceId=${device.plugin_instance_id}
                            paramsSchema=${pluginData.params_schema}
                            params=${pluginParams}
                            onParamChange=${onPluginParamChange}
                            inputs=${pluginData.inputs}
                            outputs=${pluginData.outputs}
                            ccInputs=${pluginData.cc_inputs}
                            displayOutputs=${pluginData.display_outputs}
                            displayValues=${displayValues} />
                    </div>
                `}

                ${!isPlugin && device.ports.length > 1 && html`
                    <div class="card">
                        <h3>Ports</h3>
                        ${device.ports.map(p => html`
                            <${PortRenameRow} device=${device} port=${p} showToast=${showToast} />
                        `)}
                    </div>
                `}

                ${outPorts.length > 0 && html`
                    <div class="card">
                        <h3>MIDI Test Sender</h3>
                        <div style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap;margin-bottom:8px">
                            <${PluginWheel} name="ch" label="Channel" min=${1} max=${16}
                                value=${sendChannel + 1} onChange=${(_, v) => setSendChannel(v - 1)} />
                            ${outPorts.length > 1 ? html`
                                <div class="form-group">
                                    <label style="font-size:12px;color:var(--text-dim)">Port</label>
                                    <select value=${sendPort} onChange=${e => setSendPort(+e.target.value)}>
                                        ${outPorts.map(p => html`<option value=${p.port_id}>${p.name}</option>`)}
                                    </select>
                                </div>
                            ` : ''}
                        </div>

                        <${ScrollablePiano} heldNotes=${heldNotes}
                            onNoteDown=${pianoNoteDown} onNoteUp=${pianoNoteUp}
                            pianoKeys=${pianoKeys} />

                        <div style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap">
                            <${PluginWheel} name="cc" label="CC #" min=${0} max=${127}
                                value=${ccNum} onChange=${(_, v) => setCcNum(v)} />
                            <${PluginFader} name="ccval" label="Value" min=${0} max=${127}
                                value=${ccVal} onChange=${(_, v) => sendCC(v)} />
                        </div>
                    </div>
                `}

                <div class="card">
                    <h3>MIDI Monitor</h3>
                    <div class="midi-last" ref=${lastEventRef}>Waiting for MIDI...</div>
                    <div class="midi-monitor" ref=${monitorRef}></div>
                </div>

                ${isPlugin && html`
                    <div style="margin-top:16px;padding:16px 0">
                        <button class="btn btn-danger btn-block" onclick=${deletePlugin}>Delete Plugin</button>
                    </div>
                `}
            </div>
        </div>
    `;
}

// --- Devices Page ---
function DevicesPage({ devices, onDeviceSelect, showToast, refresh }) {
    const [pluginTypes, setPluginTypes] = useState({});
    const [showAddSheet, setShowAddSheet] = useState(false);

    useEffect(() => {
        api('/plugins').then(setPluginTypes).catch(() => {});
    }, []);

    const addPlugin = async (typeName) => {
        try {
            await api('/plugins/instances', {
                method: 'POST',
                body: JSON.stringify({ type: typeName }),
            });
            showToast('Virtual device created');
            setShowAddSheet(false);
            refresh();
        } catch (e) {
            showToast('Failed to create plugin');
        }
    };

    const sorted = [...devices].sort((a, b) => a.name.localeCompare(b.name));

    return html`
        <div class="card">
            <h3>Devices (${devices.length})</h3>
            ${sorted.map(d => html`
                <div class="device" style="cursor:pointer;display:flex;align-items:center;gap:8px" onclick=${() => onDeviceSelect(d)}>
                    <${DeviceIcon} device=${d} />
                    <span class="name ${d.is_plugin ? 'dev-name-plugin' : ''}" style="flex:1">${d.name}</span>
                    <span class="ports">${d.is_plugin ? (d.plugin_type_name || d.plugin_type || '') : `${d.ports.length} port${d.ports.length !== 1 ? 's' : ''}`} \u203a</span>
                </div>
            `)}
            ${devices.length === 0 && html`<p style="color:var(--text-dim)">No devices connected</p>`}
        </div>
        <button class="btn btn-primary btn-block" style="margin-top:12px" onclick=${() => setShowAddSheet(true)}>+ Add Virtual Device</button>

        ${showAddSheet && html`
            <div class="filter-overlay" onclick=${(e) => e.target.className === 'filter-overlay' && setShowAddSheet(false)}>
                <div class="filter-panel" style="max-height:70vh">
                    <div class="panel-header">
                        <div class="panel-handle"></div>
                    </div>
                    <div class="panel-header">
                        <h3>Add Virtual Device</h3>
                        <button class="panel-close" onclick=${() => setShowAddSheet(false)}>\u2715</button>
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
                    ${Object.keys(pluginTypes).length === 0 && html`<p style="color:var(--text-dim);padding:16px">No plugins available</p>`}
                </div>
            </div>
        `}
    `;
}

// --- Network Interface Config ---
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

// --- Upgrade Card ---
const UPDATE_LABELS = { downloading: 'Downloading...', installing: 'Installing...', done: 'Updated! Restarting...' };

function UpgradeCard({ showToast }) {
    const [info, setInfo] = useState(null);
    const [checking, setChecking] = useState(false);
    const [updating, setUpdating] = useState(false);
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

// --- WiFi Card ---
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

// --- Settings Page ---
function SettingsPage({ showToast, showMidiBar, toggleMidiBar }) {
    const [ifaces, setIfaces] = useState([]);
    const [sys, setSys] = useState(null);
    const [defaultRouting, setDefaultRouting] = useState('all');
    useEffect(() => { api('/network').then(setIfaces).catch(() => {}); }, []);
    useEffect(() => { api('/system').then(s => { setSys(s); setDefaultRouting(s.default_routing || 'all'); }).catch(() => {}); }, []);

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
        </div>
        <${UpgradeCard} showToast=${showToast} />
        <div class="card">
            <button class="btn btn-secondary btn-block" style="margin-bottom:8px" onclick=${() => location.reload()}>Reload App</button>
            <button class="btn btn-danger btn-block" onclick=${rebootPi}>Reboot Pi</button>
        </div>
    `;
}

// --- Main App ---
function App() {
    const [tab, setTab] = useState('routing');
    const [devices, setDevices] = useState([]);
    const devicesRef = useRef([]);
    const connectionsRef = useRef([]);
    const [connections, setConnections] = useState([]);
    const [toast, setToast] = useState('');
    const [configFallback, setConfigFallback] = useState(false);
    const [version, setVersion] = useState('');
    const [selectedDeviceId, setSelectedDeviceId] = useState(null);
    const selectedDevice = selectedDeviceId != null ? devices.find(d => d.client_id === selectedDeviceId) || null : null;
    const [showMidiBar, setShowMidiBar] = useState(() => localStorage.getItem('midiBar') !== 'off');
    const [midiEvents, setMidiEvents] = useState({});  // src_client -> {name, text}
    const [clockSources, setClockSources] = useState({});  // src_client -> timestamp
    const [midiRates, setMidiRates] = useState({});  // "client:port" -> msgs/sec
    const [pluginDisplays, setPluginDisplays] = useState({});  // instance_id -> {name: value}
    const [sseConnected, setSseConnected] = useState(true);

    const refresh = useCallback(async () => {
        const [devs, conns] = await Promise.all([api('/devices'), api('/connections')]);
        const d = Array.isArray(devs) ? devs : [];
        const c = Array.isArray(conns) ? conns : [];
        setDevices(d);
        devicesRef.current = d;
        setConnections(c);
        connectionsRef.current = c;
    }, []);

    useEffect(() => {
        refresh();
        api('/system').then(s => { setConfigFallback(s.config_fallback); setVersion(s.version || ''); });
        // Expire stale clock sources and midi events
        const expireTimer = setInterval(() => {
            const now = Date.now();
            setClockSources(prev => {
                const next = {};
                let changed = false;
                for (const [k, ts] of Object.entries(prev)) {
                    if (now - ts < 3000) next[k] = ts;
                    else changed = true;
                }
                return changed ? next : prev;
            });
            setMidiEvents(prev => {
                const next = {};
                let changed = false;
                for (const [k, v] of Object.entries(prev)) {
                    if (now - v.ts < 2000) next[k] = v;
                    else changed = true;
                }
                return changed ? next : prev;
            });
        }, 1000);
        return () => clearInterval(expireTimer);
    }, []);

    useSSE((type, data) => {
        if (type === 'device-connected' || type === 'device-disconnected' || type === 'connection-changed') {
            refresh();
        }
        if (type === 'midi-activity') {
            // Track clock sources regardless of connections
            if (data.event === 'Clock') {
                setClockSources(prev => ({...prev, [data.src_client]: Date.now()}));
                return;
            }

            // Only show non-clock events from devices that have active connections
            const hasConn = connectionsRef.current.some(c => c.src_client === data.src_client);
            if (!hasConn) return;

            if (!showMidiBar) return;
            const dev = devicesRef.current.find(d => d.client_id === data.src_client);
            const name = dev ? dev.name : `${data.src_client}`;
            let detail = '';
            if (data.channel != null) detail += `[CH${data.channel}] `;
            if (data.note != null) detail += `${noteName(data.note)} vel=${data.velocity}`;
            else if (data.cc != null) detail += `CC${data.cc}=${data.value}`;
            else detail += data.event;
            setMidiEvents(prev => {
                const old = prev[data.src_client];
                const count = (old && old.detail === detail) ? (old.count || 1) + 1 : 1;
                return {...prev, [data.src_client]: { name, detail, ts: Date.now(), count }};
            });
        }
        if (type === 'midi-rates') {
            setMidiRates(data);
        }
        if (type === 'plugin-display') {
            setPluginDisplays(prev => ({
                ...prev,
                [data.instance_id]: { ...(prev[data.instance_id] || {}), [data.name]: data.value },
            }));
        }
    }, (connected) => {
        setSseConnected(connected);
        if (connected) refresh();
    });

    const toggleMidiBar = () => {
        const next = !showMidiBar;
        setShowMidiBar(next);
        localStorage.setItem('midiBar', next ? 'on' : 'off');
    };

    const showToast = (msg) => {
        setToast(msg);
        setTimeout(() => setToast(''), 2500);
    };

    let page;
    switch (tab) {
        case 'routing':
            page = html`<${RoutingPage} devices=${devices} connections=${connections} refresh=${refresh} showToast=${showToast} clockSources=${clockSources} midiRates=${midiRates}
                onDeviceOpen=${(clientId) => setSelectedDeviceId(clientId)} />`;
            break;
        case 'presets':
            page = html`<${PresetsPage} refresh=${refresh} showToast=${showToast} />`;
            break;
        case 'devices':
            page = html`<${DevicesPage} devices=${devices} onDeviceSelect=${d => setSelectedDeviceId(d.client_id)}
                showToast=${showToast} refresh=${refresh} />`;
            break;
        case 'settings':
            page = html`<${SettingsPage} showToast=${showToast} showMidiBar=${showMidiBar} toggleMidiBar=${toggleMidiBar} />`;
            break;
    }

    return html`
        <div class="header">
            <h1>RaspiMIDIHub${version ? html` <span style="font-size:11px;font-weight:400;color:var(--text-dim)">v${version}</span>` : ''}</h1>
            <span class="status ${sseConnected ? (devices.length > 0 ? 'ok' : '') : 'err'}">${sseConnected ? `${devices.length} device${devices.length !== 1 ? 's' : ''}` : 'Connection lost'}</span>
        </div>
        ${configFallback && html`<div class="banner">Config unreadable — using default all-to-all routing. Save to fix.</div>`}
        <div class="main ${showMidiBar ? 'with-midi-bar' : ''}">${page}</div>
        ${showMidiBar && html`<${MidiBar} events=${midiEvents} />`}
        <nav class="bottom-nav">
            <button class=${tab === 'routing' ? 'active' : ''} onclick=${() => setTab('routing')}>${IconRouting}<span>Routing</span></button>
            <button class=${tab === 'devices' ? 'active' : ''} onclick=${() => setTab('devices')}>${IconStatus}<span>Devices</span></button>
            <button class=${tab === 'presets' ? 'active' : ''} onclick=${() => setTab('presets')}>${IconPreset}<span>Presets</span></button>
            <button class=${tab === 'settings' ? 'active' : ''} onclick=${() => setTab('settings')}>${IconSettings}<span>Settings</span></button>
        </nav>
        ${selectedDevice && html`<${DeviceDetailPanel} key=${selectedDeviceId} device=${selectedDevice}
            onClose=${() => { setSelectedDeviceId(null); refresh(); }}
            showToast=${showToast} refresh=${refresh}
            pluginDisplays=${pluginDisplays} />`}
        <${Toast} message=${toast} />
    `;
}

render(html`<${App} />`, document.getElementById('app'));
