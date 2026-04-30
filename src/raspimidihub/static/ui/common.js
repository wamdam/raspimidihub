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
//
// Per-view subscription model: the server filters events per recipient
// against this client's subscription set. The first message after a
// successful SSE connect is `event: connection` carrying a conn_id —
// SubscriptionManager (./sse-subscriptions.js) uses it to call
// /api/sse/subscribe whenever views register / unregister their needs.
export function useSSE(onEvent, onConnChange, onConnectionId) {
    useEffect(() => {
        const es = new EventSource('/api/events');
        const handler = (type) => (e) => {
            try { onEvent(type, JSON.parse(e.data)); }
            catch {}
        };
        // The server-emitted connection-id event — captured by App so
        // the SubscriptionManager can flush the merged set to the
        // server. Distinct from `connection-changed` (routing).
        es.addEventListener('connection', (e) => {
            try {
                const { conn_id } = JSON.parse(e.data);
                if (conn_id && onConnectionId) onConnectionId(conn_id);
            } catch {}
        });
        for (const ev of [
            'device-connected', 'device-disconnected', 'connection-changed',
            'midi-activity', 'midi-rates', 'plugin-display', 'plugin-param',
            'clock-quarter', 'clock-position',
            'transport-start', 'cc-changes', 'panic',
            'plugin-changed', 'config-dirty',
        ]) {
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
//
// Ignores any touch that lands on an element (or descendant of one) that
// handles its own touch — i.e. anything with `touch-action: none`. Every
// interactive plugin control already sets that to disable browser
// gestures, so we don't need to maintain a class-name allowlist any more.
// New controls automatically get the right behaviour.
//
// `onTouchStart` is returned as `onTouchStartCapture` so it ALWAYS runs —
// otherwise the wheel/fader/knob's own stopPropagation in the bubble
// phase prevents this handler from firing, leaving `s.ignore` stale, and
// the panel dismisses when the user drags a control downwards.
function _isOwnTouchHandler(node) {
    let n = node;
    while (n && n.nodeType === 1) {
        const ta = (n.style && n.style.touchAction) || getComputedStyle(n).touchAction;
        if (ta === 'none') return true;
        n = n.parentNode;
    }
    return false;
}
export function useSwipeDismiss(onDismiss, panelRef) {
    const [s] = useState(() => ({ startY: 0, startX: 0, ignore: false }));
    const onTouchStartCapture = (e) => {
        s.startY = e.touches[0].clientY;
        s.startX = e.touches[0].clientX;
        s.ignore = _isOwnTouchHandler(e.target);
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
