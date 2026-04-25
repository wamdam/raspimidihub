/**
 * Shared UI primitives: html template tag, fetch helper,
 * reusable hooks, and tiny ambient widgets (Toast, MidiBar).
 */

import { h } from '../lib/preact.module.js';
import htm from '../lib/htm.module.js';
import { useEffect, useState } from '../lib/hooks.module.js';

export const html = htm.bind(h);

// --- API helper ---
export async function api(path, opts = {}) {
    const res = await fetch(`/api${path}`, {
        headers: { 'Content-Type': 'application/json', ...opts.headers },
        ...opts,
    });
    return res.json();
}

// --- ESC closes panel ---
export function useEscapeClose(close) {
    useEffect(() => {
        const handler = (e) => { if (e.key === 'Escape') close(); };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, []);
}

// --- SSE subscription ---
export function useSSE(onEvent, onConnChange) {
    useEffect(() => {
        const es = new EventSource('/api/events');
        const handler = (type) => (e) => {
            try { onEvent(type, JSON.parse(e.data)); }
            catch {}
        };
        for (const ev of ['device-connected','device-disconnected','connection-changed','midi-activity','midi-rates','plugin-display','plugin-param','clock-quarter']) {
            es.addEventListener(ev, handler(ev));
        }
        es.onopen = () => onConnChange(true);
        es.onerror = () => onConnChange(false);
        return () => es.close();
    }, []);
}

// --- Animated panel close ---
export function animateClose(panelEl, onDone) {
    if (!panelEl) { onDone(); return; }
    panelEl.classList.add('closing');
    panelEl.addEventListener('animationend', onDone, { once: true });
    setTimeout(onDone, 250); // fallback
}

// --- Swipe-down dismiss hook ---
// Checks both target element AND movement direction to avoid false triggers
// on plugin controls that handle their own touch.
//
// `onTouchStart` is returned as `onTouchStartCapture` so it ALWAYS runs —
// otherwise the wheel/fader's own stopPropagation in the bubble phase
// prevents this handler from firing, leaving `s.ignore` stale, and the
// panel dismisses when the user drags a wheel downwards.
const _swipeIgnore = '.wheel-group, .wheel-container, .wheel-label, .knob-group, .knob-container, .knob-label, .knob-value, .fader-track, .fader-group, .metal-toggle, .toggle-group, .piano, .piano-key, .mini-wheel, .curve-canvas-wrap, .step-head, .note-select';
export function useSwipeDismiss(onDismiss, panelRef) {
    const [s] = useState(() => ({ startY: 0, startX: 0, ignore: false }));
    const onTouchStartCapture = (e) => {
        s.startY = e.touches[0].clientY;
        s.startX = e.touches[0].clientX;
        s.ignore = !!(e.target && e.target.closest && e.target.closest(_swipeIgnore));
    };
    const onTouchEnd = (e) => {
        if (s.ignore) return;
        const dy = e.changedTouches[0].clientY - s.startY;
        const dx = Math.abs(e.changedTouches[0].clientX - s.startX);
        const el = panelRef && panelRef.current;
        if (dy > 80 && dx < 50 && (!el || el.scrollTop <= 0)) onDismiss();
    };
    return { onTouchStartCapture, onTouchEnd };
}

// --- Toast ---
export function Toast({ message }) {
    if (!message) return null;
    return html`<div class="toast">${message}</div>`;
}

// --- MIDI Activity Bar ---
export function MidiBar({ events }) {
    const now = Date.now();
    const entries = Object.values(events).filter(e => now - e.ts < 2000).sort((a, b) => b.ts - a.ts);
    const truncName = (n) => n.length > 8 ? n.slice(0, 7) + '\u2026' : n;
    const countStr = (e) => e.count > 1 ? ' x' + e.count : '';
    if (entries.length === 0) return html`<div class="midi-bar"><span class="midi-bar-empty">\u00b7\u00b7\u00b7</span></div>`;
    const left = entries[0];
    const right = entries.length > 1 ? entries[1] : null;
    return html`<div class="midi-bar">
        <span class="midi-bar-l"><b>In:</b> <span class="midi-bar-name">${truncName(left.name)}</span> ${left.detail}${countStr(left)}</span>
        ${right && html`<span class="midi-bar-r"><b>In:</b> <span class="midi-bar-name">${truncName(right.name)}</span>\u2002${right.detail}${countStr(right)}</span>`}
    </div>`;
}
