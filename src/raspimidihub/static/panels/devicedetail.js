/**
 * Device detail / plugin config panel: full-screen overlay shown when
 * the user taps a device row in the matrix.
 */

import { useState, useEffect, useRef, useCallback, useMemo } from '../lib/hooks.module.js';
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

// Deep-equality check that's safe for dict-valued plugin params (e.g.
// cell_labels). Identity (!==) is always true for fresh dicts even when
// their contents match, which loops the eventually-consistent watchdog.
function paramsEqual(a, b) {
    if (a === b) return true;
    if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false;
    try { return JSON.stringify(a) === JSON.stringify(b); } catch { return false; }
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

    // Param updates are rAF-coalesced AND serialized over the wire (only
    // one PATCH in flight at a time). Without serialization the browser
    // can multiplex onto multiple HTTP/1.1 connections and a fast drag's
    // PATCHes land at the server out of order — the user releases the
    // knob at max but the server sees an earlier intermediate value as
    // its final state, and that's what gets broadcast.
    //
    // The SSE echo is also suppressed for params the user is actively
    // dragging on this client, so the server-side broadcast doesn't
    // snap the thumb backwards mid-drag.
    const pendingPatchesRef = useRef(new Map());     // name -> latest value queued for PATCH
    const inFlightRef = useRef(new Map());           // name -> timeout id; presence = "user is dragging this"
    const rafIdRef = useRef(null);
    const patchInFlightRef = useRef(false);          // a PATCH is currently on the wire
    const IN_FLIGHT_RELEASE_MS = 250;

    // Refs that track the latest local + server view of params, so the
    // settle-check below can compare them outside of a render closure.
    const pluginParamsRef = useRef(pluginParams);
    pluginParamsRef.current = pluginParams;
    const pluginDisplaysRef = useRef(pluginDisplays);
    pluginDisplaysRef.current = pluginDisplays;

    const flushPending = useCallback(() => {
        rafIdRef.current = null;
        if (patchInFlightRef.current) return;        // queued; will fire after current PATCH finishes
        const map = pendingPatchesRef.current;
        if (map.size === 0) return;
        if (!device.plugin_instance_id) return;

        const params = Object.fromEntries(map);
        map.clear();
        patchInFlightRef.current = true;
        // Use fetch directly so we can detect 429 (rate limit) and re-queue
        // the params instead of silently dropping them. api() resolves on
        // 4xx because it just calls res.json() — the helpful path here is
        // to inspect res.status ourselves.
        fetch(`/api/plugins/instances/${device.plugin_instance_id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ params }),
        }).then(res => {
            if (!res.ok) {
                // Re-queue values we tried to send (fresher onChanges already
                // in pending take precedence — only restore keys that aren't
                // already queued with a newer value).
                for (const [k, v] of Object.entries(params)) {
                    if (!pendingPatchesRef.current.has(k)) {
                        pendingPatchesRef.current.set(k, v);
                    }
                }
            }
        }).catch(() => {
            // Network error — same retry policy as a 4xx.
            for (const [k, v] of Object.entries(params)) {
                if (!pendingPatchesRef.current.has(k)) {
                    pendingPatchesRef.current.set(k, v);
                }
            }
        }).finally(() => {
            patchInFlightRef.current = false;
            if (pendingPatchesRef.current.size > 0) {
                // Small backoff so a sustained 429 storm doesn't busy-loop.
                setTimeout(flushPending, 30);
            }
        });
    }, [device.plugin_instance_id]);

    useEffect(() => () => {
        if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
        for (const t of inFlightRef.current.values()) clearTimeout(t);
        inFlightRef.current.clear();
        pendingPatchesRef.current.clear();
    }, []);

    const sseParamsKey = pluginDisplays && device.plugin_instance_id ? '_params_' + device.plugin_instance_id : null;
    const sseParams = sseParamsKey ? pluginDisplays[sseParamsKey] : null;
    const sseParamsRef = useRef(null);
    if (sseParams && sseParams !== sseParamsRef.current) {
        sseParamsRef.current = sseParams;
        const filtered = {};
        for (const [k, v] of Object.entries(sseParams)) {
            if (inFlightRef.current.has(k)) continue;
            if (!paramsEqual(pluginParams[k], v)) filtered[k] = v;
        }
        if (Object.keys(filtered).length > 0) {
            setTimeout(() => setPluginParams(prev => ({ ...prev, ...filtered })), 0);
        }
    }

    // Trigger-style param names from the schema (DropPad, Button trigger=true).
    // Server intentionally cycles their value (fire -> idle, capture -> captured),
    // so we must NOT optimistically commit the user's input or run the watchdog
    // re-queue logic — both would fight the server's authoritative state.
    const triggerParams = useMemo(() => {
        const s = new Set();
        const walk = (items) => {
            if (!items) return;
            for (const p of items) {
                if (p.type === 'group') walk(p.children);
                else if (p.type === 'layoutgrid') walk((p.cells || []).map(c => c.param));
                else if (p.type === 'droppad') s.add(p.name);
                else if (p.type === 'button' && p.trigger) s.add(p.name);
            }
        };
        walk(pluginData?.params_schema);
        return s;
    }, [pluginData?.params_schema]);

    const onPluginParamChange = useCallback((name, value) => {
        if (triggerParams.has(name)) {
            // Fire-and-forget: PATCH only, no local optimism, no watchdog.
            // The server's authoritative state arrives via SSE.
            if (!device.plugin_instance_id) return;
            pendingPatchesRef.current.set(name, value);
            if (rafIdRef.current === null) {
                rafIdRef.current = requestAnimationFrame(flushPending);
            }
            return;
        }
        setPluginParams(prev => prev[name] === value ? prev : { ...prev, [name]: value });
        if (!device.plugin_instance_id) return;

        pendingPatchesRef.current.set(name, value);
        if (rafIdRef.current === null) {
            rafIdRef.current = requestAnimationFrame(flushPending);
        }

        const existing = inFlightRef.current.get(name);
        if (existing) clearTimeout(existing);
        inFlightRef.current.set(name, setTimeout(() => {
            inFlightRef.current.delete(name);
            // Eventually-consistent watchdog. After the user idles for
            // IN_FLIGHT_RELEASE_MS, compare our optimistic local state
            // for this param against the most recent server value seen
            // via SSE. If they disagree the final PATCH didn't land —
            // re-queue our local value as the authoritative one and
            // flush. The retry-on-429 + serialised flush logic above
            // takes it from there until SSE finally echoes back.
            const ssp = pluginDisplaysRef.current
                && pluginDisplaysRef.current['_params_' + device.plugin_instance_id];
            const localVal = pluginParamsRef.current[name];
            if (device.plugin_instance_id && ssp
                    && ssp[name] !== undefined
                    && !paramsEqual(ssp[name], localVal)
                    && !paramsEqual(pendingPatchesRef.current.get(name), localVal)) {
                pendingPatchesRef.current.set(name, localVal);
                if (rafIdRef.current === null && !patchInFlightRef.current) {
                    rafIdRef.current = requestAnimationFrame(flushPending);
                }
            }
        }, IN_FLIGHT_RELEASE_MS));
    }, [device.plugin_instance_id, flushPending, triggerParams]);

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
