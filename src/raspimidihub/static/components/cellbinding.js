/**
 * CellBinding — the long-press popup for controller cells.
 *
 * Same modal shape as CcBinding, but for the symmetric (channel, cc)
 * pair that lives on each LayoutCell. Controllers use the same number
 * for both directions — touching the on-screen cell emits a CC out,
 * an incoming CC with the matching (channel, cc) silently mirrors
 * the cell value (no re-emit). One control, two-way.
 *
 * Save semantics:
 *   - Edits stay local until the user hits Save.
 *   - Save → PATCH params.cell_bindings.<cellName> = {channel, cc, ...prev}
 *     (preserves On/Off, XY axes, spring config that the device-detail
 *     panel still owns).
 *   - Reset to default → drops the cell's override entry; the
 *     LayoutCell's factory (channel, cc) takes over.
 *   - MIDI Learn → reuses /api/cc-learn, fills in the wheels on
 *     capture, then Save commits.
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
    const [binding, setBinding] = useState(null);   // {channel, cc}
    const [defaults, setDefaults] = useState(null); // {channel, cc} from LayoutCell
    const [learning, setLearning] = useState(false);
    const learnIdRef = useRef(null);
    // The whole cell-bindings dict — we send the full updated map on
    // Save, preserving any On/Off / XY-axis fields the user set
    // elsewhere.
    const bindingsRef = useRef({});

    useEffect(() => {
        if (!open) {
            setBinding(null);
            setDefaults(null);
            setLearning(false);
            learnIdRef.current = null;
            bindingsRef.current = {};
            return;
        }
        let cancelled = false;
        (async () => {
            try {
                const inst = await api(`/api/plugins/instances/${encodeURIComponent(open.instanceId)}`);
                if (cancelled) return;
                // Find the LayoutGrid in the schema, then the cell.
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
                const allBindings = (bindingsParam && inst.params[bindingsParam]) || {};
                bindingsRef.current = { ...allBindings };
                const ov = allBindings[open.cellName] || {};
                const factoryCh = (cell.channel != null) ? cell.channel : 0;
                const factoryCc = (cell.cc != null) ? cell.cc : 0;
                const liveCh = (ov.channel != null) ? ov.channel : factoryCh;
                const liveCc = (ov.cc != null) ? ov.cc : factoryCc;
                setBinding({ channel: liveCh, cc: liveCc });
                setDefaults({ channel: factoryCh, cc: factoryCc, bindingsParam });
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
                if (!learnIdRef.current || d.learn_id !== learnIdRef.current) return;
                learnIdRef.current = null;
                setLearning(false);
                setBinding({ channel: d.ch != null ? d.ch : 0, cc: d.cc });
                tickFeedback();
            } catch {}
        };
        const onTimeout = (ev) => {
            try {
                const d = JSON.parse(ev.data);
                if (!learnIdRef.current || d.learn_id !== learnIdRef.current) return;
                learnIdRef.current = null;
                setLearning(false);
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

    async function doLearn() {
        if (!open || learning) return;
        setLearning(true);
        try {
            const r = await api('/api/cc-learn/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ instance_id: open.instanceId, param: open.cellName }),
            });
            learnIdRef.current = r.learn_id;
        } catch (err) {
            console.warn('cc-learn start failed:', err);
            setLearning(false);
        }
    }

    async function cancelLearn() {
        const lid = learnIdRef.current;
        learnIdRef.current = null;
        setLearning(false);
        if (!lid) return;
        try { await api('/api/cc-learn/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ learn_id: lid }),
        }); } catch {}
    }

    async function doSave() {
        if (!open || !binding || !defaults) return;
        const prev = bindingsRef.current[open.cellName] || {};
        const merged = {
            ...bindingsRef.current,
            [open.cellName]: { ...prev, channel: binding.channel, cc: binding.cc },
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
        // Drop the override entry — controller falls back to the
        // LayoutCell's factory (channel, cc). Other fields (On/Off,
        // XY axes, spring) that lived under this cell's override are
        // also wiped; if the user wants to keep those, they can edit
        // them again from the device-detail panel.
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
            setBinding({ channel: defaults.channel, cc: defaults.cc });
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

    // Wheel value bridges:
    //   channel: stored 0..15, wheel shows 1..16 (no "Any" — cells
    //     are point-to-point on a specific channel).
    //   cc: 0..127 directly.
    const chWheelVal = binding ? binding.channel + 1 : 1;
    const ccWheelVal = binding ? binding.cc : 0;

    const onChWheel = (_n, v) => setBinding({ channel: v - 1, cc: binding ? binding.cc : 0 });
    const onCcWheel = (_n, v) => setBinding({ channel: binding ? binding.channel : 0, cc: v });

    return html`
        <div class="cc-bind-bg" onclick=${doClose}
            onContextMenu=${(e) => { e.preventDefault(); doClose(); }}>
            <div class="cc-bind-modal" onclick=${(e) => e.stopPropagation()}>
                <div class="cc-bind-head">
                    <div class="cc-bind-title">${open.pluginName} → ${open.cellLabel || open.cellName}</div>
                    <button type="button" class="cc-bind-x" onclick=${doClose}>×</button>
                </div>

                <div class="cc-bind-subtitle">MIDI CC for this cell — touch emits, hardware mirrors.</div>

                <div class="cc-bind-current">
                    Current: <strong>${binding ? `Ch ${binding.channel + 1} · CC ${binding.cc}` : '…'}</strong>
                    ${defaults && html`<span class="cc-bind-default">  ·  factory: Ch ${defaults.channel + 1} · CC ${defaults.cc}</span>`}
                </div>

                <div class="cc-bind-fields">
                    <div class="cc-bind-field">
                        <${PluginWheel} name="_cell_bind_ch" label="Channel"
                            min=${1} max=${16} value=${chWheelVal} onChange=${onChWheel} />
                    </div>
                    <div class="cc-bind-field">
                        <${PluginWheel} name="_cell_bind_cc" label="CC #"
                            min=${0} max=${127} value=${ccWheelVal} onChange=${onCcWheel} />
                    </div>
                </div>

                <div class="cc-bind-actions">
                    ${learning
                        ? html`<button type="button" class="cc-bind-btn cc-bind-learning"
                            onclick=${cancelLearn}>● Move a controller… (Cancel)</button>`
                        : html`<button type="button" class="cc-bind-btn" onclick=${doLearn}>MIDI Learn</button>`}
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
