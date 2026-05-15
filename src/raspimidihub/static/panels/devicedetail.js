/**
 * Device detail / plugin config panel: full-screen overlay shown when
 * the user taps a device row in the matrix.
 */

import { useState, useEffect, useRef } from '../lib/hooks.module.js';
import { html, api, animateClose, useEscapeClose, useSwipeDismiss } from '../ui/common.js';
import { useSSESubscription } from '../ui/sse-subscriptions.js';
import { noteName } from '../state/constants.js';
import { PluginConfigPanel, PluginWheel, PluginFader } from '../plugin-controls.js';
import { SysExSenderControls } from '../components/sysexsender.js';
import { usePluginParams } from '../ui/plugin-params.js';
import { IconMaximize } from '../ui/icons.js';
import { touchTs } from '../ui/storage.js';

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

    // Mouse path mirrors the touch state machine: press plays the note
    // under the cursor; once horizontal motion exceeds SCROLL_THRESH we
    // switch to scroll mode and release the note.
    const onMouseDown = (e) => {
        const el = scrollRef.current;
        if (!el) return;
        const startX = e.clientX, startScroll = el.scrollLeft;
        const note = noteFromPoint(e.clientX, e.clientY);
        if (note != null) noteDownRef.current(note);
        let scrolling = false;
        let released = false;
        const releaseNote = () => {
            if (note != null && !released) { noteUpRef.current(note); released = true; }
        };
        const onMove = (ev) => {
            const dx = ev.clientX - startX;
            if (!scrolling && Math.abs(dx) > SCROLL_THRESH) {
                scrolling = true;
                releaseNote();
            }
            if (scrolling) el.scrollLeft = startScroll - dx;
        };
        const onUp = () => {
            releaseNote();
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onUp);
        };
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
    };

    const isHeld = (midi) => heldNotes && heldNotes.has(midi);

    return html`<div ref=${scrollRef} style="margin-bottom:16px;overflow-x:hidden;touch-action:none"
        onMouseDown=${onMouseDown}>
        <div class="piano" ref=${pianoRef} style="width:${7 * 8 * 34}px">
            ${Array.from({length: 8}, (_, oct) =>
                pianoKeys.filter(k => !k.black).map(k => {
                    const midi = (oct + 1) * 12 + k.n;
                    if (midi > 127) return null;
                    return html`<div class="piano-key white ${isHeld(midi) ? 'active' : ''}" data-midi=${midi}>
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
                        style="left:${leftPx}px">
                    </div>`;
                })
            ).flat()}
        </div>
    </div>`;
}

export function DeviceDetailPanel({ device, onClose, showToast, refresh, pluginDisplays, onJumpToController, onJumpToPlay }) {
    // While the panel is open we want plugin-param + plugin-display
    // events for THIS device's plugin instance (if it's a plugin) so
    // the inline param controls and meters / scopes update live.
    // Empty list when the device isn't a plugin — the hook still
    // contributes a no-op subscription that costs nothing.
    useSSESubscription(
        [],
        device.is_plugin && device.plugin_instance_id ? [device.plugin_instance_id] : [],
    );
    const panelRef = { current: null };
    const close = () => animateClose(panelRef.current, onClose);
    const swipe = useSwipeDismiss(close, panelRef);

    const [editName, setEditName] = useState(device.name);
    // Per-device clock-source toggle. The engine drops Clock/Start/
    // Stop/Continue from blocked devices before they reach the
    // ClockBus, so a multi-clock setup can be tamed without unticking
    // Clock/RT in every connection's filter card.
    const [clockBlocked, setClockBlocked] = useState(!!device.clock_blocked);
    useEffect(() => { setClockBlocked(!!device.clock_blocked); },
              [device.client_id, device.clock_blocked]);
    const sid = device.stable_id || device.client_id;
    const _saved = useRef(JSON.parse(localStorage.getItem(`sender_${sid}`) || '{}'));
    const [sendChannel, _setSendChannel] = useState(_saved.current.ch || 0);
    const [sendPort, setSendPort] = useState(0);
    const [ccNum, _setCcNum] = useState(_saved.current.cc != null ? _saved.current.cc : 1);
    const [ccVal, setCcVal] = useState(64);
    const setSendChannel = (v) => { _setSendChannel(v); _saved.current.ch = v; localStorage.setItem(`sender_${sid}`, JSON.stringify(touchTs(_saved.current))); };
    const setCcNum = (v) => { _setCcNum(v); _saved.current.cc = v; localStorage.setItem(`sender_${sid}`, JSON.stringify(touchTs(_saved.current))); };
    const [heldNotes, setHeldNotes] = useState(new Set());
    const maxEvents = 50;

    const isPlugin = !!device.is_plugin;
    const [pluginData, setPluginData] = useState(null);
    const [showHelp, setShowHelp] = useState(false);
    const [showSender, setShowSender] = useState(false);
    const [showMonitor, setShowMonitor] = useState(false);
    const {
        params: pluginParams,
        setParams: setPluginParams,
        onParamChange: onPluginParamChange,
    } = usePluginParams({
        instanceId: device.plugin_instance_id,
        paramsSchema: pluginData?.params_schema,
        pluginDisplays,
    });
    useEffect(() => {
        if (isPlugin && device.plugin_instance_id) {
            api(`/plugins/instances/${device.plugin_instance_id}`)
                .then(d => { setPluginData(d); setPluginParams(d.params || {}); })
                .catch(() => {});
        }
    }, [device.plugin_instance_id]);

    const displayValues = (pluginDisplays && device.plugin_instance_id) ? pluginDisplays[device.plugin_instance_id] || {} : {};

    const deletePlugin = async () => {
        if (!confirm('Delete this virtual device?')) return;
        await api(`/plugins/instances/${device.plugin_instance_id}`, { method: 'DELETE' });
        showToast('Plugin deleted');
        close();
        if (refresh) refresh();
    };

    const isBluetooth = !!device.is_bluetooth;
    // bt-<MAC> is the stable_id format from device_id.py — strip the
    // prefix to get the raw MAC for the bluetooth API.
    const btAddress = (isBluetooth && device.stable_id && device.stable_id.startsWith('bt-'))
        ? device.stable_id.slice(3) : null;
    const disconnectBt = async () => {
        if (!btAddress) return;
        await api('/bluetooth/disconnect', { method: 'POST', body: JSON.stringify({ address: btAddress }) });
        showToast('Bluetooth device disconnected');
        close();
        if (refresh) refresh();
    };
    const forgetBt = async () => {
        if (!btAddress) return;
        if (!confirm(`Forget ${device.name}? It will need to be reconnected manually.`)) return;
        await api(`/bluetooth/${encodeURIComponent(btAddress)}`, { method: 'DELETE' });
        showToast('Bluetooth device removed');
        close();
        if (refresh) refresh();
    };

    const outPorts = device.ports.filter(p => p.is_output);

    const monitorRef = useRef(null);
    const lastEventRef = useRef(null);
    const eventsRef = useRef([]);

    // The monitor opens its own EventSource so live midi-activity
    // events drop into THIS panel's monitor list without going through
    // the App's debounced midi-bar pipeline. Two things matter:
    //   1) only run while the user has the monitor open — every
    //      EventSource is a separate SSE connection, costs a queue and
    //      a heartbeat slot on the server;
    //   2) the per-view subscription model means a fresh connection
    //      filters everything out by default, so we POST a
    //      midi-activity subscription as soon as we get our conn_id.
    useEffect(() => {
        if (!showMonitor) return;
        const es = new EventSource('/api/events');
        // rAF-coalesce DOM writes: many events can arrive in one frame
        // (e.g. 4 LCXL3 faders fanning into Mixer 8). Updating the
        // <div> innerHTML on every event was the bottleneck — now we
        // mutate eventsRef cheaply on each event and only render once
        // per animation frame.
        let pendingRender = false;
        const scheduleRender = () => {
            if (pendingRender) return;
            pendingRender = true;
            requestAnimationFrame(() => {
                pendingRender = false;
                const evs = eventsRef.current;
                if (lastEventRef.current && evs.length) {
                    lastEventRef.current.textContent = evs[0].line;
                }
                if (monitorRef.current) {
                    monitorRef.current.innerHTML = evs.map(ev =>
                        `<div class="midi-event">${ev.line}</div>`).join('');
                }
            });
        };
        const handler = (e) => {
            try {
                const data = JSON.parse(e.data);
                // Match either as event source (e.g. moving a fader on
                // a hardware controller) or as routing destination
                // (e.g. Mixer 8 receiving CCs from LCXL3 via the matrix).
                const isSrc = data.src_client === device.client_id;
                const isDst = Array.isArray(data.dst_clients)
                    && data.dst_clients.includes(device.client_id);
                if ((isSrc || isDst) && data.event !== 'Clock') {
                    const line = formatEvent(data);
                    eventsRef.current = [{ line, ts: Date.now() }, ...eventsRef.current].slice(0, maxEvents);
                    scheduleRender();
                }
            } catch {}
        };
        const onConnection = (e) => {
            try {
                const { conn_id } = JSON.parse(e.data);
                if (!conn_id) return;
                fetch('/api/sse/subscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        conn_id, events: ['midi-activity'], instances: [],
                    }),
                }).catch(() => {});
            } catch {}
        };
        es.addEventListener('connection', onConnection);
        es.addEventListener('midi-activity', handler);
        return () => es.close();
    }, [device.client_id, showMonitor]);

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

                ${/* Plugin Config — first for plugins. Help button reveals plugin
                    description AND the Inputs descriptor list at the bottom. */ ''}
                ${isPlugin && pluginData && html`
                    <div class="card" style="padding-top:8px">
                        <div style="display:flex;align-items:center;justify-content:space-between;padding-bottom:5px;margin-bottom:8px">
                            <h3 style="margin:0;line-height:1">Plugin Config</h3>
                            <div style="display:flex;align-items:center;gap:6px">
                                ${pluginData.kind === 'controller' && onJumpToController && html`<button
                                    style="width:20px;height:20px;border-radius:50%;border:1px solid var(--text-dim);background:none;color:var(--text-dim);cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;flex:0 0 auto"
                                    title="Open in fullscreen Controller view"
                                    onclick=${() => onJumpToController(device.plugin_instance_id)}>${IconMaximize}</button>`}
                                ${pluginData.kind === 'play' && onJumpToPlay && html`<button
                                    style="width:20px;height:20px;border-radius:50%;border:1px solid var(--text-dim);background:none;color:var(--text-dim);cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;flex:0 0 auto"
                                    title="Open in fullscreen Play view"
                                    onclick=${() => onJumpToPlay(device.plugin_instance_id)}>${IconMaximize}</button>`}
                                ${(pluginData.help || (pluginData.inputs && pluginData.inputs.length)) && html`<button style="width:20px;height:20px;border-radius:50%;border:1px solid var(--text-dim);background:none;color:var(--text-dim);font-size:12px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;flex:0 0 auto"
                                    onclick=${() => setShowHelp(h => !h)}>?</button>`}
                            </div>
                        </div>
                        ${showHelp && html`
                            <div style="background:var(--bg);padding:10px;border-radius:6px;margin-bottom:12px">
                                ${pluginData.help && html`
                                    <div style="font-size:12px;color:var(--text-dim);line-height:1.5">${
                                        // Reflow help text: split on blank lines into
                                        // paragraphs, then each line is either a flowed
                                        // sentence (hard line-wraps inside collapse to
                                        // spaces) or a bullet starting with "- "/"* "
                                        // (kept as its own line). Lets the source keep
                                        // 70-col line wrapping for readability while the
                                        // rendered output reflows to the panel width.
                                        pluginData.help.split(/\n\s*\n/).map((para, pi) => {
                                            const blocks = [];
                                            let buf = '';
                                            const flush = () => { if (buf) { blocks.push({bullet: false, text: buf}); buf = ''; } };
                                            for (const raw of para.split('\n')) {
                                                const t = raw.trim();
                                                if (!t) { flush(); continue; }
                                                if (/^[-*]\s/.test(t) || /^\d+\.\s/.test(t)) {
                                                    flush();
                                                    blocks.push({bullet: true, text: t});
                                                } else {
                                                    buf = buf ? buf + ' ' + t : t;
                                                }
                                            }
                                            flush();
                                            return html`<div key=${pi} style="margin-top:${pi === 0 ? '0' : '8px'}">${
                                                blocks.map((b, bi) => html`<div key=${bi}
                                                    style="${b.bullet ? 'padding-left:8px;text-indent:-8px;' : ''}margin-top:${bi === 0 ? '0' : '2px'}">${b.text}</div>`)
                                            }</div>`;
                                        })
                                    }</div>
                                `}
                                ${pluginData.inputs && pluginData.inputs.length > 0 && html`
                                    <div style="margin-top:${pluginData.help ? '12px' : '0'};padding-top:${pluginData.help ? '10px' : '0'};${pluginData.help ? 'border-top:1px solid var(--surface2);' : ''}">
                                        <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:6px">Inputs</div>
                                        <div style="font-size:12px;color:var(--text)">${pluginData.inputs.join(', ')}</div>
                                    </div>
                                `}
                            </div>
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
                        ${pluginData.type === 'sysex_sender' && html`
                            <${SysExSenderControls}
                                instanceId=${device.plugin_instance_id}
                                showToast=${showToast} />`}
                    </div>
                `}

                ${/* Per-device clock veto — hardware only, online only.
                    Plugins gate via PluginBase.feeds_clock_bus and don't
                    need a runtime toggle. Off = engine drops this device's
                    Clock/Start/Stop/Continue before they reach the bus. */ ''}
                ${!isPlugin && device.online !== false && html`
                    <div class="card">
                        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
                            <div style="flex:1">
                                <div style="font-size:13px;font-weight:600">Drive system clock</div>
                                <div style="font-size:11px;color:var(--text-dim);margin-top:2px;line-height:1.4">
                                    Off = ignore MIDI Clock / Start / Stop from this device.
                                    Use this when more than one source is sending clock.
                                </div>
                            </div>
                            <button class="rubber-btn ${clockBlocked ? '' : 'active'}"
                                onclick=${async () => {
                                    const next = !clockBlocked;
                                    setClockBlocked(next);
                                    const r = await api(`/devices/${device.client_id}/clock-source`, {
                                        method: 'POST',
                                        body: JSON.stringify({ enabled: !next }),
                                    });
                                    if (!r || r.error) {
                                        setClockBlocked(!next);
                                        showToast('Failed: ' + ((r && r.error) || 'unknown'));
                                    } else {
                                        showToast(next ? 'Clock blocked' : 'Clock enabled');
                                        if (refresh) refresh();
                                    }
                                }}>
                                <div class="btn-led green"></div>
                                <span class="btn-text">${clockBlocked ? 'Off' : 'On'}</span>
                            </button>
                        </div>
                    </div>
                `}

                ${/* Ports — second for plugins, first (and only) for hardware
                    devices with multiple ports. */ ''}
                ${isPlugin && html`
                    <div class="card">
                        <h3>Ports</h3>
                        ${device.ports.map(p => html`
                            <${PortRenameRow} device=${device} port=${p} showToast=${showToast} />
                        `)}
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

                ${/* MIDI Test Sender — collapsed by default (rarely used during
                    play; expand on demand). */ ''}
                ${outPorts.length > 0 && html`
                    <div class="card">
                        <button style="background:none;border:none;color:var(--text);font-size:14px;font-weight:600;cursor:pointer;padding:0;display:flex;align-items:center;gap:6px;width:100%;text-transform:uppercase;letter-spacing:1px"
                            onclick=${() => setShowSender(s => !s)}>
                            <span style="color:var(--text-dim);font-size:11px">${showSender ? '▼' : '▶'}</span>
                            <span>MIDI Test Sender</span>
                        </button>
                        ${showSender && html`
                            <div style="margin-top:12px">
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
                                <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;align-items:flex-start">
                                    <${PluginWheel} name="cc" label="CC #" min=${0} max=${127}
                                        value=${ccNum} onChange=${(_, v) => setCcNum(v)} />
                                    <div style="grid-column:span 3;min-width:0">
                                        <${PluginFader} name="ccval" label="Value" min=${0} max=${127}
                                            value=${ccVal} onChange=${(_, v) => sendCC(v)} />
                                    </div>
                                </div>
                            </div>
                        `}
                    </div>
                `}

                ${/* MIDI Monitor — collapsed by default. */ ''}
                <div class="card">
                    <button style="background:none;border:none;color:var(--text);font-size:14px;font-weight:600;cursor:pointer;padding:0;display:flex;align-items:center;gap:6px;width:100%;text-transform:uppercase;letter-spacing:1px"
                        onclick=${() => setShowMonitor(m => !m)}>
                        <span style="color:var(--text-dim);font-size:11px">${showMonitor ? '▼' : '▶'}</span>
                        <span>MIDI Monitor</span>
                    </button>
                    ${showMonitor && html`
                        <div style="margin-top:12px">
                            <div class="midi-last" ref=${lastEventRef}>Waiting for MIDI...</div>
                            <div class="midi-monitor" ref=${monitorRef}></div>
                        </div>
                    `}
                </div>

                ${isPlugin && html`
                    <div style="margin-top:16px;padding:16px 0">
                        <button class="btn btn-danger btn-block" onclick=${deletePlugin}>Delete Plugin</button>
                    </div>
                `}

                ${isBluetooth && btAddress && html`
                    <div style="margin-top:16px;padding:16px 0;display:flex;gap:8px">
                        <button class="btn btn-block" style="flex:1" onclick=${disconnectBt}>Disconnect</button>
                        <button class="btn btn-danger btn-block" style="flex:1" onclick=${forgetBt}>Forget</button>
                    </div>
                `}
            </div>
        </div>
    `;
}
