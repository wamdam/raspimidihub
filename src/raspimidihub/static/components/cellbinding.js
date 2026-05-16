/**
 * CellBinding — the long-press popup for controller cells.
 *
 * Same modal shape as CcBinding, but for the symmetric (channel, cc)
 * pair that lives on each LayoutCell. Controllers use the same number
 * for both directions — touching the on-screen cell emits a CC out,
 * an incoming CC with the matching (channel, cc) silently mirrors
 * the cell value (no re-emit). One control, two-way.
 *
 * XY pads have TWO independent CC bindings (X axis + Y axis); the
 * popup grows to two axis sections, each with its own Channel + CC
 * wheels and its own MIDI Learn button. Everything else (Save,
 * Reset to factory, Cancel) acts on both axes together.
 *
 * Save semantics:
 *   - Edits stay local until the user hits Save.
 *   - Save → PATCH params.cell_bindings.<cellName> = {...prev, channel,
 *     cc[, channel_y, cc_y]}, preserving Button On/Off and the XY
 *     spring config that the device-detail panel still owns.
 *   - Reset to factory → drops the cell's override entry; the
 *     LayoutCell's factory (channel, cc[, channel_y, cc_y]) takes over.
 *   - MIDI Learn → reuses /api/cc-learn per axis. Captures the
 *     inbound (channel, cc) without committing; Save commits both.
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html, tickFeedback } from './common.js';
import { PluginWheel } from './wheel.js';

async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
}

export function CellBinding({ open, onClose }) {
    // open = null | { instanceId, cellName, cellLabel, pluginName }
    //
    // binding shape:
    //   non-XY:  { x: {channel, cc}, y: null }
    //   XY pad:  { x: {channel, cc}, y: {channel, cc} }
    // The two-axis shape keeps the rendering path uniform — axis 'y'
    // is just hidden when null.
    const [binding, setBinding] = useState(null);
    const [defaults, setDefaults] = useState(null);
    const [learningAxis, setLearningAxis] = useState(null);  // 'x' | 'y' | null
    const learnIdsRef = useRef({ x: null, y: null });
    // Full cell_bindings dict — Save merges back so other fields
    // (button On/Off, spring config) live through the round-trip.
    const bindingsRef = useRef({});

    useEffect(() => {
        if (!open) {
            setBinding(null);
            setDefaults(null);
            setLearningAxis(null);
            learnIdsRef.current = { x: null, y: null };
            bindingsRef.current = {};
            return;
        }
        let cancelled = false;
        (async () => {
            try {
                const inst = await api(`/api/plugins/instances/${encodeURIComponent(open.instanceId)}`);
                if (cancelled) return;
                let cell = null;
                let bindingsParam = null;
                const walk = (params) => {
                    for (const p of params || []) {
                        if (p.type === 'layoutgrid') {
                            bindingsParam = p.bindings_param || null;
                            for (const c of p.cells || []) {
                                if ((c.param && c.param.name) === open.cellName) {
                                    cell = c;
                                    return;
                                }
                            }
                        }
                        if (p.children) walk(p.children);
                    }
                };
                walk(inst.params_schema);
                if (!cell) return;
                const isXY = cell.param && cell.param.type === 'xypad';
                const allBindings = (bindingsParam && inst.params[bindingsParam]) || {};
                bindingsRef.current = { ...allBindings };
                const ov = allBindings[open.cellName] || {};
                const factoryXCh = (cell.channel != null) ? cell.channel : 0;
                const factoryXCc = (cell.cc != null) ? cell.cc : 0;
                const liveXCh = (ov.channel != null) ? ov.channel : factoryXCh;
                const liveXCc = (ov.cc != null) ? ov.cc : factoryXCc;
                let factoryY = null;
                let liveY = null;
                if (isXY) {
                    // Y axis defaults: channel_y falls back to X
                    // channel if not declared (matches the layoutgrid
                    // edit panel's same fallback).
                    const factoryYCh = (cell.channel_y != null) ? cell.channel_y : factoryXCh;
                    const factoryYCc = (cell.cc_y != null) ? cell.cc_y : 0;
                    factoryY = { channel: factoryYCh, cc: factoryYCc };
                    const liveYCh = (ov.channel_y != null) ? ov.channel_y : factoryYCh;
                    const liveYCc = (ov.cc_y != null) ? ov.cc_y : factoryYCc;
                    liveY = { channel: liveYCh, cc: liveYCc };
                }
                setBinding({ x: { channel: liveXCh, cc: liveXCc }, y: liveY });
                setDefaults({
                    x: { channel: factoryXCh, cc: factoryXCc },
                    y: factoryY,
                    bindingsParam,
                    isXY,
                });
            } catch (err) {
                console.warn('CellBinding load failed:', err);
            }
        })();
        return () => { cancelled = true; };
    }, [open]);

    useEffect(() => {
        if (!open) return;
        const es = new EventSource('/api/events');
        const onConnection = (e) => {
            try {
                const { conn_id } = JSON.parse(e.data);
                if (!conn_id) return;
                fetch('/api/sse/subscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        conn_id,
                        events: ['cc_learn_result', 'cc_learn_timeout'],
                        instances: [],
                    }),
                }).catch(() => {});
            } catch {}
        };
        const onLearn = (ev) => {
            try {
                const d = JSON.parse(ev.data);
                // Which axis was learning for THIS learn_id?
                const ids = learnIdsRef.current;
                let axis = null;
                if (ids.x && d.learn_id === ids.x) axis = 'x';
                else if (ids.y && d.learn_id === ids.y) axis = 'y';
                if (!axis) return;
                learnIdsRef.current = { ...ids, [axis]: null };
                setLearningAxis((cur) => (cur === axis ? null : cur));
                setBinding((cur) => {
                    if (!cur) return cur;
                    return {
                        ...cur,
                        [axis]: { channel: d.ch != null ? d.ch : 0, cc: d.cc },
                    };
                });
                tickFeedback();
            } catch {}
        };
        const onTimeout = (ev) => {
            try {
                const d = JSON.parse(ev.data);
                const ids = learnIdsRef.current;
                let axis = null;
                if (ids.x && d.learn_id === ids.x) axis = 'x';
                else if (ids.y && d.learn_id === ids.y) axis = 'y';
                if (!axis) return;
                learnIdsRef.current = { ...ids, [axis]: null };
                setLearningAxis((cur) => (cur === axis ? null : cur));
            } catch {}
        };
        es.addEventListener('connection', onConnection);
        es.addEventListener('cc_learn_result', onLearn);
        es.addEventListener('cc_learn_timeout', onTimeout);
        return () => es.close();
    }, [open]);

    useEffect(() => {
        if (!open) return;
        const onKey = (e) => { if (e.key === 'Escape') doClose(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [open]);

    async function doLearn(axis) {
        if (!open || learningAxis) return;
        setLearningAxis(axis);
        try {
            // The param query string includes the axis suffix so the
            // server-side telemetry is distinguishable (the actual
            // CC capture is axis-blind — first inbound CC wins).
            const r = await api('/api/cc-learn/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    instance_id: open.instanceId,
                    param: `${open.cellName}:${axis}`,
                }),
            });
            learnIdsRef.current = { ...learnIdsRef.current, [axis]: r.learn_id };
        } catch (err) {
            console.warn('cc-learn start failed:', err);
            setLearningAxis(null);
        }
    }

    async function cancelLearn() {
        const ids = learnIdsRef.current;
        learnIdsRef.current = { x: null, y: null };
        setLearningAxis(null);
        for (const lid of [ids.x, ids.y]) {
            if (!lid) continue;
            try { await api('/api/cc-learn/cancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ learn_id: lid }),
            }); } catch {}
        }
    }

    async function doSave() {
        if (!open || !binding || !defaults) return;
        const prev = bindingsRef.current[open.cellName] || {};
        const next = {
            ...prev,
            channel: binding.x.channel,
            cc: binding.x.cc,
        };
        if (defaults.isXY && binding.y) {
            next.channel_y = binding.y.channel;
            next.cc_y = binding.y.cc;
        }
        const merged = {
            ...bindingsRef.current,
            [open.cellName]: next,
        };
        try {
            await api(`/api/plugins/instances/${encodeURIComponent(open.instanceId)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ params: { [defaults.bindingsParam]: merged } }),
            });
            tickFeedback();
            doClose();
        } catch (err) {
            console.warn('cell-binding save failed:', err);
        }
    }

    async function doResetDefault() {
        if (!open || !defaults) return;
        const next = { ...bindingsRef.current };
        delete next[open.cellName];
        try {
            await api(`/api/plugins/instances/${encodeURIComponent(open.instanceId)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ params: { [defaults.bindingsParam]: next } }),
            });
            bindingsRef.current = next;
            setBinding({
                x: { ...defaults.x },
                y: defaults.y ? { ...defaults.y } : null,
            });
            tickFeedback();
        } catch (err) {
            console.warn('cell-binding reset failed:', err);
        }
    }

    async function doClose() {
        await cancelLearn();
        onClose();
    }

    if (!open) return null;

    const isXY = !!(defaults && defaults.isXY);

    // Per-axis wheel block with its own MIDI Learn / Cancel button.
    const axisBlock = (axis, axisLabel) => {
        const cur = binding && binding[axis];
        const factory = defaults && defaults[axis];
        const chWheelVal = cur ? cur.channel + 1 : 1;
        const ccWheelVal = cur ? cur.cc : 0;
        const onCh = (_n, v) => setBinding((b) => b && ({
            ...b,
            [axis]: { channel: v - 1, cc: b[axis].cc },
        }));
        const onCc = (_n, v) => setBinding((b) => b && ({
            ...b,
            [axis]: { channel: b[axis].channel, cc: v },
        }));
        const isLearning = learningAxis === axis;
        const learnLabel = isLearning ? '● Move…' : 'MIDI Learn';
        const learnCls = isLearning ? 'cc-bind-btn cc-bind-learning' : 'cc-bind-btn';
        return html`
            <div class="cc-bind-axis">
                ${isXY ? html`<div class="cc-bind-axis-label">${axisLabel}</div>` : null}
                <div class="cc-bind-current">
                    Current: <strong>${cur ? `Ch ${cur.channel + 1} · CC ${cur.cc}` : '…'}</strong>
                    ${factory && html`<span class="cc-bind-default">  ·  factory: Ch ${factory.channel + 1} · CC ${factory.cc}</span>`}
                </div>
                <div class="cc-bind-fields">
                    <div class="cc-bind-field">
                        <${PluginWheel} name=${`_cell_${axis}_ch`} label="Channel"
                            min=${1} max=${16} value=${chWheelVal} onChange=${onCh} />
                    </div>
                    <div class="cc-bind-field">
                        <${PluginWheel} name=${`_cell_${axis}_cc`} label="CC #"
                            min=${0} max=${127} value=${ccWheelVal} onChange=${onCc} />
                    </div>
                </div>
                <div class="cc-bind-axis-learn">
                    <button type="button" class=${learnCls}
                        onclick=${isLearning ? cancelLearn : () => doLearn(axis)}>
                        ${learnLabel}
                    </button>
                </div>
            </div>
        `;
    };

    const subtitle = isXY
        ? 'MIDI CCs for this XY pad — each axis emits / mirrors independently.'
        : 'MIDI CC for this cell — touch emits, hardware mirrors.';

    return html`
        <div class="cc-bind-bg" onclick=${doClose}
            onContextMenu=${(e) => { e.preventDefault(); doClose(); }}>
            <div class="cc-bind-modal" onclick=${(e) => e.stopPropagation()}>
                <div class="cc-bind-head">
                    <div class="cc-bind-title">${open.pluginName} → ${open.cellLabel || open.cellName}</div>
                    <button type="button" class="cc-bind-x" onclick=${doClose}>×</button>
                </div>

                <div class="cc-bind-subtitle">${subtitle}</div>

                ${axisBlock('x', 'X axis')}
                ${isXY ? axisBlock('y', 'Y axis') : null}

                <div class="cc-bind-actions">
                    <button type="button" class="cc-bind-btn cc-bind-secondary"
                        onclick=${doResetDefault}>Reset to factory</button>
                </div>

                <div class="cc-bind-footer">
                    <button type="button" class="cc-bind-btn cc-bind-secondary" onclick=${doClose}>Cancel</button>
                    <button type="button" class="cc-bind-btn cc-bind-primary" onclick=${doSave}>Save</button>
                </div>
            </div>
        </div>`;
}
