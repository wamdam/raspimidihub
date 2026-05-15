/**
 * CcBinding — the long-press popup that binds a plugin control to
 * an incoming MIDI CC.
 *
 * Mounted once at App level (like the ContextMenu). When a Knob /
 * Wheel / Fader / Radio / Button fires its long-press handler the
 * App opens this popup with `{instanceId, paramName}`. The popup
 * fetches the current binding + default + collisions from the
 * `/api/plugins/cc-mappings` endpoint and lets the user:
 *
 *   - Tap "Learn" — the next inbound CC fills in Ch + CC.
 *   - Edit Ch (Any / 1..16) and CC (0..127) manually.
 *   - Reset to default — restores the plugin author's default_cc.
 *   - Clear — disables the binding entirely; the cleared state is
 *     durable across reboots so the seed default doesn't reappear.
 *
 * Collisions ("Also drives: Arp 1 → Rate") are informational only.
 * One CC may drive multiple controls and that is on purpose.
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html, tickFeedback } from './common.js';

const ANY_CHANNEL_LABEL = 'Any';

function chLabel(ch) {
    return ch === null || ch === undefined ? ANY_CHANNEL_LABEL : String(ch + 1);
}

function fmtBinding(ch, cc) {
    if (cc === null || cc === undefined) return '— cleared —';
    return `Ch ${chLabel(ch)} · CC ${cc}`;
}

async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
}

export function CcBinding({ open, onClose }) {
    // open = null | { instanceId, paramName, paramLabel, pluginName }
    const [binding, setBinding] = useState(null);   // {ch, cc}
    const [defaultCc, setDefaultCc] = useState(null);
    const [collisions, setCollisions] = useState([]);
    const [learning, setLearning] = useState(false);
    const learnIdRef = useRef(null);
    const ccInputRef = useRef(null);

    // Reset state when the popup opens for a new param.
    useEffect(() => {
        if (!open) {
            setBinding(null);
            setDefaultCc(null);
            setCollisions([]);
            setLearning(false);
            learnIdRef.current = null;
            return;
        }
        let cancelled = false;
        (async () => {
            try {
                // Pull this instance's full data — gives us live cc_map
                // + the default_cc_map (the "Reset to default" target).
                const inst = await api(`/api/plugins/instances/${encodeURIComponent(open.instanceId)}`);
                if (cancelled) return;
                const live = (inst.cc_map || {})[open.paramName];
                const dflt = (inst.default_cc_map || {})[open.paramName];
                setBinding(live ? { ch: live.ch, cc: live.cc } : { ch: null, cc: null });
                setDefaultCc(dflt ? dflt.cc : null);
                // Flat list across all instances → collisions for this CC.
                refreshCollisions(open, live && live.cc, live && live.ch);
            } catch (err) {
                console.warn('CcBinding load failed:', err);
            }
        })();
        return () => { cancelled = true; };
    }, [open]);

    // While the popup is open, open a dedicated EventSource for the
    // Learn flow. Cheap — three event types, fires only during binding
    // edits, closes on dismiss. Same pattern devicedetail uses for its
    // monitor.
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
                        events: ['cc_learn_result', 'cc_learn_timeout', 'cc_map_changed'],
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
                setBinding({ ch: d.ch, cc: d.cc });
                refreshCollisions(open, d.cc, d.ch);
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

    // Esc closes the popup; cancel any armed Learn on the way out.
    useEffect(() => {
        if (!open) return;
        const onKey = (e) => { if (e.key === 'Escape') doClose(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [open]);

    async function refreshCollisions(o, cc, ch) {
        if (cc === null || cc === undefined) { setCollisions([]); return; }
        try {
            const { mappings } = await api('/api/plugins/cc-mappings');
            const hits = (mappings || []).filter((m) =>
                m.cc === cc
                && (ch === null || ch === undefined || m.ch === null || m.ch === undefined || m.ch === ch)
                && !(m.instance_id === o.instanceId && m.param === o.paramName));
            setCollisions(hits);
        } catch {
            setCollisions([]);
        }
    }

    async function doLearn() {
        if (!open || learning) return;
        setLearning(true);
        try {
            const r = await api('/api/cc-learn/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ instance_id: open.instanceId, param: open.paramName }),
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
        if (!open || !binding) return;
        try {
            await api(`/api/plugins/instances/${encodeURIComponent(open.instanceId)}/cc-map/${encodeURIComponent(open.paramName)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ch: binding.ch, cc: binding.cc }),
            });
            tickFeedback();
            doClose();
        } catch (err) {
            console.warn('cc-map save failed:', err);
        }
    }

    async function doClear() {
        // Cleared = {ch: null, cc: null} — durable across restart.
        setBinding({ ch: null, cc: null });
        setCollisions([]);
    }

    async function doResetDefault() {
        // Reset = restore plugin author's default_cc, channel = Any.
        if (defaultCc === null) { doClear(); return; }
        setBinding({ ch: null, cc: defaultCc });
        refreshCollisions(open, defaultCc, null);
    }

    async function doClose() {
        await cancelLearn();
        onClose();
    }

    if (!open) return null;

    const channelOpts = [html`<option value="">Any</option>`];
    for (let i = 0; i < 16; i++) channelOpts.push(html`<option value=${i}>${i + 1}</option>`);

    const collisionLine = collisions.length === 0
        ? null
        : collisions.length <= 3
            ? html`<div class="cc-bind-collisions">Also drives: ${collisions.map((c, i) =>
                html`<span>${i > 0 ? ', ' : ''}${c.instance_name} → ${c.param_label}</span>`)}</div>`
            : html`<div class="cc-bind-collisions">Also drives: ${collisions.slice(0, 2).map((c) =>
                `${c.instance_name} → ${c.param_label}`).join(', ')} · +${collisions.length - 2} more</div>`;

    const isCleared = binding && (binding.cc === null || binding.cc === undefined);

    return html`
        <div class="cc-bind-bg" onclick=${doClose}
            onContextMenu=${(e) => { e.preventDefault(); doClose(); }}>
            <div class="cc-bind-modal" onclick=${(e) => e.stopPropagation()}>
                <div class="cc-bind-head">
                    <div class="cc-bind-title">${open.pluginName} → ${open.paramLabel || open.paramName}</div>
                    <button type="button" class="cc-bind-x" onclick=${doClose}>×</button>
                </div>

                <div class="cc-bind-current">
                    Current: <strong>${binding ? fmtBinding(binding.ch, binding.cc) : '…'}</strong>
                    ${defaultCc !== null && html`<span class="cc-bind-default">  ·  default: Ch Any · CC ${defaultCc}</span>`}
                </div>

                <div class="cc-bind-fields">
                    <label class="cc-bind-field">
                        <span>Channel</span>
                        <select value=${binding && binding.ch !== null && binding.ch !== undefined ? String(binding.ch) : ''}
                            onchange=${(e) => {
                                const v = e.target.value;
                                setBinding({ ch: v === '' ? null : parseInt(v, 10), cc: binding ? binding.cc : null });
                            }}>
                            ${channelOpts}
                        </select>
                    </label>
                    <label class="cc-bind-field">
                        <span>CC #</span>
                        <input ref=${ccInputRef} type="number" min="0" max="127"
                            value=${binding && binding.cc !== null && binding.cc !== undefined ? String(binding.cc) : ''}
                            placeholder="—"
                            oninput=${(e) => {
                                const v = e.target.value;
                                const cc = v === '' ? null : Math.max(0, Math.min(127, parseInt(v, 10) || 0));
                                setBinding({ ch: binding ? binding.ch : null, cc });
                            }} />
                    </label>
                </div>

                <div class="cc-bind-actions">
                    ${learning
                        ? html`<button type="button" class="cc-bind-btn cc-bind-learning"
                            onclick=${cancelLearn}>● Move a controller… (Cancel)</button>`
                        : html`<button type="button" class="cc-bind-btn" onclick=${doLearn}>MIDI Learn</button>`}
                    <button type="button" class="cc-bind-btn cc-bind-secondary"
                        onclick=${doResetDefault} disabled=${defaultCc === null}>Reset to default</button>
                    <button type="button" class="cc-bind-btn cc-bind-secondary"
                        onclick=${doClear} disabled=${isCleared}>Clear</button>
                </div>

                ${collisionLine}

                <div class="cc-bind-footer">
                    <button type="button" class="cc-bind-btn cc-bind-secondary" onclick=${doClose}>Cancel</button>
                    <button type="button" class="cc-bind-btn cc-bind-primary" onclick=${doSave}>Save</button>
                </div>
            </div>
        </div>`;
}
