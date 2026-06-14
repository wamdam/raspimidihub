/**
 * CCSelect plugin control — a wheel of CC numbers with an inline
 * MIDI-Learn button. Mirrors NoteSelect, but the labels read "Off" /
 * "CC n" and Learn captures the next CC (not note) from midi-activity.
 *
 * Value semantics: -1 = unbound ("Off"), 0..127 = CC number.
 */

import { html, tickFeedback, thudFeedback } from './common.js';
import { useState, useEffect, useRef } from '../lib/hooks.module.js';

const ccLabel = (v) => (v < 0 ? 'Off' : `CC ${v}`);

export function PluginCCSelect({ name, label, value, onChange }) {
    const containerRef = useRef(null);
    const innerRef = useRef(null);
    const TICK_H = 20;
    const CENTER = 26 - TICK_H / 2;
    const MIN = -1;
    const MAX = 127;
    const s = useRef({
        value, offset: 0, startY: 0, startOffset: 0, lastY: 0, lastT: 0,
        velocity: 0, animId: null, atBoundary: false, lastWheel: 0,
    }).current;

    const valueToTickIndex = (v) => v - MIN;
    const valueToOffset = (v) => CENTER - valueToTickIndex(v) * TICK_H;
    const offsetToValue = (off) => Math.round((CENTER - off) / TICK_H) + MIN;
    const minOffset = valueToOffset(MAX);
    const maxOffset = valueToOffset(MIN);
    const clampOffset = (off) => Math.max(minOffset, Math.min(maxOffset, off));
    const clampValue = (v) => Math.max(MIN, Math.min(MAX, v));

    const updateTicks = () => {
        const el = innerRef.current;
        if (!el) return;
        const idx = valueToTickIndex(s.value);
        for (let i = 0; i < el.children.length; i++) {
            const dist = Math.abs(i - idx);
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
            if (e.button === 2) return;
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
        function onWheel(e) {
            e.preventDefault();
            const now = Date.now(); if (now - s.lastWheel < 80) return; s.lastWheel = now;
            if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; }
            const delta = e.deltaY > 0 ? -1 : 1;
            const nv = clampValue(s.value + delta);
            if (nv !== s.value) { s.value = nv; setOffset(valueToOffset(nv)); updateTicks(); onChange(name, nv); (nv === MIN || nv === MAX) ? thudFeedback() : tickFeedback(); }
        }
        el.addEventListener('touchstart', onStart, { passive: false });
        el.addEventListener('mousedown', onStart);
        el.addEventListener('wheel', onWheel, { passive: false });
        return () => {
            el.removeEventListener('touchstart', onStart);
            el.removeEventListener('mousedown', onStart);
            el.removeEventListener('wheel', onWheel);
        };
    }, [name]);

    // Learn: open a fresh SSE, subscribe to midi-activity (the per-view
    // subscription model means an unsubscribed stream gets nothing), then
    // take the next CC we see. 10 s timeout so a forgotten "Listening…"
    // doesn't sit live forever.
    const [learning, setLearning] = useState(false);
    useEffect(() => {
        if (!learning) return;
        const es = new EventSource('/api/events');
        let connId = null;
        const onConn = (e) => {
            try {
                connId = JSON.parse(e.data).conn_id;
                fetch('/api/sse/subscribe', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ conn_id: connId, events: ['midi-activity'], instances: [] }),
                }).catch(() => {});
            } catch {}
        };
        const onMidi = (e) => {
            try {
                const d = JSON.parse(e.data);
                if (d.cc != null) {
                    onChange(name, d.cc);
                    setLearning(false);
                }
            } catch {}
        };
        es.addEventListener('connection', onConn);
        es.addEventListener('midi-activity', onMidi);
        const t = setTimeout(() => setLearning(false), 10000);
        return () => { es.close(); clearTimeout(t); };
    }, [learning]);

    const ticks = [];
    for (let i = MIN; i <= MAX; i++) {
        ticks.push(html`<div class="wheel-tick" key=${i}>${ccLabel(i)}</div>`);
    }
    return html`<div class="wheel-group">
        ${label ? html`<span class="wheel-label">${label}</span>` : null}
        <div class="wheel-container" ref=${containerRef}><div class="wheel-inner" ref=${innerRef}>${ticks}</div></div>
        <button class="btn-learn-inline ${learning ? 'btn-held' : ''}" onclick=${() => setLearning(l => !l)}>
            ${learning ? 'Listening…' : 'Learn'}
        </button>
    </div>`;
}
