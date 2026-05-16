/**
 * StepEditor plugin control.
 */

import { html, tickFeedback, thudFeedback } from './common.js';
import { useEffect, useRef } from '../lib/hooks.module.js';
import { noteName } from '../state/constants.js';

// =======================================================================
// STEP EDITOR — grid with on/off dots and mini-wheel offsets
// =======================================================================
export function PluginStepEditor({ name, label, value, onChange, lengthParam, allValues, defaultOn, slotNotesParam, overrideMode, algoUnderlayParam }) {
    // Cell shape differs by mode:
    //   plain mode    → {on, accent, offset}
    //   override mode → {state: "default"|"on"|"accent"|"off", offset}
    // override_mode cells also read a sibling per-step boolean array
    // (algoUnderlayParam) to render the algorithm's preview as a
    // subdued underlay on default-state cells.
    const steps = value || [];
    const length = (lengthParam && allValues && allValues[lengthParam])
        ? parseInt(allValues[lengthParam]) || 16 : steps.length || 16;
    // Optional per-slot note assignments (Arpeggiator's `programmed`
    // pattern). When the sibling param is populated, render the note
    // name (C4, F#3, …) in the cell so the user can see what's loaded.
    const slotNotes = (slotNotesParam && allValues
                       && Array.isArray(allValues[slotNotesParam]))
        ? allValues[slotNotesParam] : null;
    const algoUnderlay = (algoUnderlayParam && allValues
                          && Array.isArray(allValues[algoUnderlayParam]))
        ? allValues[algoUnderlayParam] : null;

    const emptyCell = () => overrideMode
        ? { state: 'default', offset: 0 }
        : { on: !!defaultOn, offset: 0 };

    // Extend array if step count increased
    const displaySteps = [];
    for (let i = 0; i < length; i++) {
        displaySteps.push(steps[i] || emptyCell());
    }

    const toggleStep = (i) => {
        tickFeedback();
        const newSteps = [...steps];
        while (newSteps.length <= i) newSteps.push(emptyCell());
        const s = newSteps[i];
        if (overrideMode) {
            // Cycle: default → on → accent → off → default
            const cur = s.state || 'default';
            const next = cur === 'default' ? 'on'
                       : cur === 'on'      ? 'accent'
                       : cur === 'accent'  ? 'off'
                       : 'default';
            newSteps[i] = { ...s, state: next };
        } else {
            // Plain cycle: off → on → accent → off
            if (!s.on) {
                newSteps[i] = { ...s, on: true, accent: false };
            } else if (!s.accent) {
                newSteps[i] = { ...s, accent: true };
            } else {
                newSteps[i] = { ...s, on: false, accent: false };
            }
        }
        onChange(name, newSteps);
    };

    const setOffset = (i, offset) => {
        const newSteps = [...steps];
        while (newSteps.length <= i) newSteps.push(emptyCell());
        newSteps[i] = { ...newSteps[i], offset: Math.max(-24, Math.min(24, offset)) };
        onChange(name, newSteps);
    };

    const cellClass = (step, i) => {
        const beat = i % 4 === 0 ? ' beat' : '';
        if (overrideMode) {
            const st = step.state || 'default';
            if (st === 'on')     return `force-on${beat}`;
            if (st === 'accent') return `force-on accent${beat}`;
            if (st === 'off')    return `force-off${beat}`;
            // default: tint if the algorithm wants this step on.
            const alg = algoUnderlay && algoUnderlay[i];
            return `${alg ? 'alg-on' : ''}${beat}`;
        }
        return `${step.on ? (step.accent ? 'on accent' : 'on') : ''}${beat}`;
    };

    return html`<div class="step-editor">
        <div style="font-size:13px;color:var(--text-dim);margin-bottom:8px">${label}</div>
        <div class="step-grid">
            ${displaySteps.map((step, i) => {
                const slotNote = slotNotes ? slotNotes[i] : null;
                return html`
                <div class="step-cell ${cellClass(step, i)}" key=${i}>
                    <div class="step-head" onclick=${() => toggleStep(i)}></div>
                    <${MiniWheel} value=${step.offset || 0}
                        onChange=${(v) => { tickFeedback(); setOffset(i, v); }} />
                    ${slotNotes ? html`<div class="step-slot-note">${slotNote != null ? noteName(slotNote) : ''}</div>` : ''}
                </div>
            `;})}
        </div>
    </div>`;
}

export function MiniWheel({ value, onChange }) {
    const containerRef = useRef(null);
    const s = useRef({ value, dragging: false, startY: 0, startVal: 0 });
    // Listeners are bound once in a `[]` effect, so capturing onChange
    // directly would freeze a stale parent closure (parent rebuilds the
    // step array each render — using stale onChange wipes sibling slots).
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;

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
            if (nv !== s.current.value) { s.current.value = nv; onChangeRef.current(nv); }
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
            if (nv !== s.current.value) { s.current.value = nv; onChangeRef.current(nv); tickFeedback(); }
        }
        el.addEventListener('touchstart', onStart, { passive: false });
        el.addEventListener('mousedown', onStart);
        el.addEventListener('wheel', onWheel, { passive: false });
        return () => { el.removeEventListener('touchstart', onStart); el.removeEventListener('mousedown', onStart); el.removeEventListener('wheel', onWheel); };
    }, []);

    const display = value > 0 ? `+${value}` : `${value}`;
    return html`<div class="mini-wheel" ref=${containerRef}>
        <div class="mini-wheel-inner" style="display:flex;align-items:center;justify-content:center;height:100%">
            <span style="font-size:9px;color:${value === 0 ? 'var(--text-dim)' : 'var(--text)'};font-weight:${value !== 0 ? '700' : '400'}">${display}</span>
        </div>
    </div>`;
}

