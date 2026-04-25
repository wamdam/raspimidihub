/**
 * Device detail / plugin config panel: full-screen overlay shown when
 * the user taps a device row in the matrix.
 */

import { useState, useEffect, useRef, useCallback } from '../lib/hooks.module.js';
import { html, api, animateClose, useEscapeClose, useSwipeDismiss } from '../ui/common.js';
import { noteName } from '../state/constants.js';
import { PluginConfigPanel, PluginWheel, PluginFader } from '../plugin-controls.js';

export function PortRenameRow({ device, port, showToast }) {
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

// touch-action:none so multitouch works with fader simultaneously
export function ScrollablePiano({ heldNotes, onNoteDown, onNoteUp, pianoKeys }) {
    const scrollRef = useRef(null);
    const pianoRef = useRef(null);
    const noteDownRef = useRef(onNoteDown);
    noteDownRef.current = onNoteDown;
    const noteUpRef = useRef(onNoteUp);
    noteUpRef.current = onNoteUp;
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
                    if (Math.abs(dx) > SCROLL_THRESH && Math.abs(dx) > Math.abs(dy)) {
                        state.scrolling = true;
                    } else if (Math.abs(dy) > SCROLL_THRESH) {
                        state.moved = true;
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
    }, []);

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

export function DeviceDetailPanel({ device, onClose, showToast, refresh, pluginDisplays }) {
    const panelRef = { current: null };
    const close = () => animateClose(panelRef.current, onClose);
    const swipe = useSwipeDismiss(close, panelRef);

    const [editName, setEditName] = useState(device.name);
    const sid = device.stable_id || device.client_id;
    const _saved = useRef(JSON.parse(localStorage.getItem(`sender_${sid}`) || '{}'));
    const [sendChannel, _setSendChannel] = useState(_saved.current.ch || 0);
    const [sendPort, setSendPort] = useState(0);
    const [ccNum, _setCcNum] = useState(_saved.current.cc != null ? _saved.current.cc : 1);
    const [ccVal, setCcVal] = useState(64);
    const setSendChannel = (v) => { _setSendChannel(v); _saved.current.ch = v; localStorage.setItem(`sender_${sid}`, JSON.stringify(_saved.current)); };
    const setCcNum = (v) => { _setCcNum(v); _saved.current.cc = v; localStorage.setItem(`sender_${sid}`, JSON.stringify(_saved.current)); };
    const [heldNotes, setHeldNotes] = useState(new Set());
    const maxEvents = 50;

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

    const displayValues = (pluginDisplays && device.plugin_instance_id) ? pluginDisplays[device.plugin_instance_id] || {} : {};

    const sseParamsKey = pluginDisplays && device.plugin_instance_id ? '_params_' + device.plugin_instance_id : null;
    const sseParams = sseParamsKey ? pluginDisplays[sseParamsKey] : null;
    const sseParamsRef = useRef(null);
    if (sseParams && sseParams !== sseParamsRef.current) {
        sseParamsRef.current = sseParams;
        Object.entries(sseParams).forEach(([k, v]) => {
            if (pluginParams[k] !== v) {
                setTimeout(() => setPluginParams(prev => ({ ...prev, ...sseParams })), 0);
            }
        });
    }

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
