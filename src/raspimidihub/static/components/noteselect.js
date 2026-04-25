/**
 * NoteSelect plugin control.
 */

import { html, tickFeedback, thudFeedback, noteName } from './common.js';
import { useState, useEffect, useRef } from '../lib/hooks.module.js';

// =======================================================================
// NOTE SELECT — PluginWheel with note name labels instead of numbers
// =======================================================================
export function PluginNoteSelect({ name, label, value, onChange, learnable }) {
    // Reuse PluginWheel with a custom suffix that shows note names
    // We override the tick rendering by using noteName labels
    const containerRef = useRef(null);
    const innerRef = useRef(null);
    const TICK_H = 20;
    const CENTER = 30 - TICK_H / 2;
    const s = useRef({
        value, offset: 0, startY: 0, startOffset: 0, lastY: 0, lastT: 0,
        velocity: 0, animId: null, atBoundary: false, lastWheel: 0,
    }).current;

    const valueToOffset = (v) => CENTER - v * TICK_H;
    const offsetToValue = (off) => Math.round((CENTER - off) / TICK_H);
    const minOffset = valueToOffset(127);
    const maxOffset = valueToOffset(0);
    const clampOffset = (off) => Math.max(minOffset, Math.min(maxOffset, off));

    const updateTicks = () => {
        const el = innerRef.current;
        if (!el) return;
        for (let i = 0; i < el.children.length; i++) {
            const dist = Math.abs(i - s.value);
            el.children[i].className = 'wheel-tick' + (dist === 0 ? ' active' : dist === 1 ? ' near' : '');
        }
    };
    const setOffset = (off) => { s.offset = off; if (innerRef.current) innerRef.current.style.transform = `translateY(${off}px)`; };
    const snapToValue = () => {
        const target = valueToOffset(s.value);
        const snap = () => { s.offset += (target - s.offset) * 0.3; setOffset(s.offset); if (Math.abs(target - s.offset) > 0.5) s.animId = requestAnimationFrame(snap); else setOffset(target); };
        if (Math.abs(target - s.offset) < 0.5) { setOffset(target); return; } s.animId = requestAnimationFrame(snap);
    };

    useEffect(() => { s.value = value; setOffset(valueToOffset(value)); updateTicks(); }, [value]);

    useEffect(() => {
        const el = containerRef.current; if (!el) return;
        function onStart(e) {
            e.preventDefault(); e.stopPropagation();
            if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; }
            s.atBoundary = false; const pt = e.touches ? e.touches[0] : e;
            s.startY = pt.clientY; s.startOffset = s.offset; s.lastY = pt.clientY; s.lastT = Date.now(); s.velocity = 0;
            el.addEventListener('touchmove', onMove, { passive: false }); el.addEventListener('mousemove', onMove);
            window.addEventListener('touchend', onEnd); window.addEventListener('mouseup', onEnd);
        }
        function onMove(e) {
            e.preventDefault(); e.stopPropagation(); const pt = e.touches ? e.touches[0] : e;
            const now = Date.now(); const dt = now - s.lastT; if (dt > 0) s.velocity = (pt.clientY - s.lastY) / dt;
            s.lastY = pt.clientY; s.lastT = now; let raw = s.startOffset + (pt.clientY - s.startY);
            const clamped = clampOffset(raw); if (raw !== clamped && !s.atBoundary) { thudFeedback(); s.velocity = 0; s.atBoundary = true; } else if (raw === clamped) s.atBoundary = false;
            s.offset = clamped; const nv = offsetToValue(s.offset);
            if (nv !== s.value) { tickFeedback(); s.value = nv; updateTicks(); onChange(name, nv); } setOffset(s.offset);
        }
        function onEnd(e) {
            if (e) e.stopPropagation();
            el.removeEventListener('touchmove', onMove); el.removeEventListener('mousemove', onMove);
            window.removeEventListener('touchend', onEnd); window.removeEventListener('mouseup', onEnd);
            if (Math.abs(s.velocity) > 0.2) { const friction = 0.95; function frame() { s.velocity *= friction; let raw = s.offset + s.velocity * 16; const cl = clampOffset(raw); if (raw !== cl) { s.offset = cl; s.velocity = 0; thudFeedback(); setOffset(s.offset); snapToValue(); return; } s.offset = cl; const nv = offsetToValue(s.offset); if (nv !== s.value) { tickFeedback(); s.value = nv; updateTicks(); onChange(name, nv); } setOffset(s.offset); if (Math.abs(s.velocity) > 0.05) s.animId = requestAnimationFrame(frame); else snapToValue(); } s.animId = requestAnimationFrame(frame); }
            else snapToValue();
        }
        function onWheel(e) { e.preventDefault(); const now = Date.now(); if (now - s.lastWheel < 80) return; s.lastWheel = now; if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; } const delta = e.deltaY > 0 ? -1 : 1; const nv = Math.max(0, Math.min(127, s.value + delta)); if (nv !== s.value) { s.value = nv; setOffset(valueToOffset(nv)); updateTicks(); onChange(name, nv); (nv === 0 || nv === 127) ? thudFeedback() : tickFeedback(); } }
        el.addEventListener('touchstart', onStart, { passive: false }); el.addEventListener('mousedown', onStart); el.addEventListener('wheel', onWheel, { passive: false });
        return () => { el.removeEventListener('touchstart', onStart); el.removeEventListener('mousedown', onStart); el.removeEventListener('wheel', onWheel); };
    }, [name]);

    const [learning, setLearning] = useState(false);
    useEffect(() => {
        if (!learning) return;
        const es = new EventSource('/api/events');
        const onMidi = (e) => {
            try {
                const d = JSON.parse(e.data);
                if (d.note != null) {
                    onChange(name, d.note);
                    setLearning(false);
                }
            } catch {}
        };
        es.addEventListener('midi-activity', onMidi);
        const t = setTimeout(() => setLearning(false), 10000);
        return () => { es.close(); clearTimeout(t); };
    }, [learning]);

    const ticks = []; for (let i = 0; i <= 127; i++) ticks.push(html`<div class="wheel-tick" key=${i}>${noteName(i)}</div>`);
    return html`<div class="wheel-group">
        <span class="wheel-label">${label}</span>
        <div class="wheel-container" ref=${containerRef}><div class="wheel-inner" ref=${innerRef}>${ticks}</div></div>
        ${learnable && html`<button class="btn-learn-inline ${learning ? 'btn-held' : ''}" onclick=${() => setLearning(l => !l)}>
            ${learning ? 'Listening\u2026' : 'Learn'}
        </button>`}
    </div>`;
}

