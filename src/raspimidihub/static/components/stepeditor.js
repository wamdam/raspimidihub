/**
 * StepEditor plugin control.
 */

import { html, tickFeedback, thudFeedback } from './common.js';
import { useEffect, useRef } from '../lib/hooks.module.js';

// =======================================================================
// STEP EDITOR — grid with on/off dots and mini-wheel offsets
// =======================================================================
export function PluginStepEditor({ name, label, value, onChange, lengthParam, allValues, defaultOn }) {
    // value is array of {on, offset}
    const steps = value || [];
    const length = (lengthParam && allValues && allValues[lengthParam])
        ? parseInt(allValues[lengthParam]) || 16 : steps.length || 16;
    // Extend array if step count increased
    const displaySteps = [];
    for (let i = 0; i < length; i++) {
        displaySteps.push(steps[i] || { on: !!defaultOn, offset: 0 });
    }

    const toggleStep = (i) => {
        tickFeedback();
        const newSteps = [...steps];
        while (newSteps.length <= i) newSteps.push({ on: !!defaultOn, offset: 0 });
        const s = newSteps[i];
        // Cycle: off → on → accent → off
        if (!s.on) {
            newSteps[i] = { ...s, on: true, accent: false };
        } else if (!s.accent) {
            newSteps[i] = { ...s, accent: true };
        } else {
            newSteps[i] = { ...s, on: false, accent: false };
        }
        onChange(name, newSteps);
    };

    const setOffset = (i, offset) => {
        const newSteps = [...steps];
        while (newSteps.length <= i) newSteps.push({ on: false, offset: 0 });
        newSteps[i] = { ...newSteps[i], offset: Math.max(-24, Math.min(24, offset)) };
        onChange(name, newSteps);
    };

    return html`<div class="step-editor">
        <div style="font-size:13px;color:var(--text-dim);margin-bottom:8px">${label}</div>
        <div class="step-grid">
            ${displaySteps.map((step, i) => html`
                <div class="step-cell ${step.on ? (step.accent ? 'on accent' : 'on') : ''} ${i % 4 === 0 ? 'beat' : ''}" key=${i}>
                    <div class="step-head" onclick=${() => toggleStep(i)}></div>
                    <${MiniWheel} value=${step.offset || 0}
                        onChange=${(v) => { tickFeedback(); setOffset(i, v); }} />
                </div>
            `)}
        </div>
    </div>`;
}

export function MiniWheel({ value, onChange }) {
    const containerRef = useRef(null);
    const s = useRef({ value, dragging: false, startY: 0, startVal: 0 });

    useEffect(() => { s.current.value = value; }, [value]);

    // Native event listeners for both touch and mouse
    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;
        function onStart(e) {
            e.preventDefault(); e.stopPropagation();
            const pt = e.touches ? e.touches[0] : e;
            s.current.dragging = true;
            s.current.startY = pt.clientY;
            s.current.startVal = s.current.value;
            if (e.touches) {
                el.addEventListener('touchmove', onMove, { passive: false });
                window.addEventListener('touchend', onEnd);
            } else {
                window.addEventListener('mousemove', onMove);
                window.addEventListener('mouseup', onEnd);
            }
        }
        function onMove(e) {
            e.preventDefault();
            if (!s.current.dragging) return;
            const pt = e.touches ? e.touches[0] : e;
            const dy = s.current.startY - pt.clientY;
            const nv = Math.max(-24, Math.min(24, Math.round(s.current.startVal + dy / 8)));
            if (nv !== s.current.value) { s.current.value = nv; onChange(nv); }
        }
        function onEnd() {
            s.current.dragging = false;
            el.removeEventListener('touchmove', onMove);
            window.removeEventListener('touchend', onEnd);
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onEnd);
        }
        function onWheel(e) {
            e.preventDefault(); e.stopPropagation();
            const delta = e.deltaY > 0 ? -1 : 1;
            const nv = Math.max(-24, Math.min(24, s.current.value + delta));
            if (nv !== s.current.value) { s.current.value = nv; onChange(nv); tickFeedback(); }
        }
        el.addEventListener('touchstart', onStart, { passive: false });
        el.addEventListener('mousedown', onStart);
        el.addEventListener('wheel', onWheel, { passive: false });
        return () => { el.removeEventListener('touchstart', onStart); el.removeEventListener('mousedown', onStart); el.removeEventListener('wheel', onWheel); };
    }, []);

    const display = value > 0 ? `+${value}` : `${value}`;
    return html`<div class="mini-wheel" ref=${containerRef}>
        <div class="mini-wheel-inner" style="display:flex;align-items:center;justify-content:center;height:100%">
            <span style="font-size:9px;color:${value === 0 ? 'rgba(255,255,255,0.3)' : '#fff'};font-weight:${value !== 0 ? '700' : '400'}">${display}</span>
        </div>
    </div>`;
}

