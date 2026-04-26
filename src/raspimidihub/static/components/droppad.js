/**
 * DropPad plugin control — one-shot snapshot pad with
 *   • short-press → fire  (sends value 'fire'; server snaps cells + emits CCs)
 *   • long-press (≥500 ms with progress ring) → capture
 *     (sends value 'capture'; server snapshots current cell values)
 *
 * The value also reflects "captured" state: `value === 'captured'`
 * means a snapshot exists and the pad is armed; `'idle'` means no
 * snapshot yet (short-press is a no-op until the first capture).
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html, tickFeedback, thudFeedback } from './common.js';

const LONG_PRESS_MS = 500;

export function PluginDropPad({ name, label, value, onChange }) {
    const padRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;

    const armed = value === 'captured';
    const [pressing, setPressing] = useState(false);
    const [progress, setProgress] = useState(0);  // 0..1
    const pressState = useRef({
        startTs: 0, longFired: false, rafId: null, activeTouchId: null,
    });

    useEffect(() => {
        const el = padRef.current;
        if (!el) return;
        const ps = pressState.current;

        function tick() {
            const elapsed = Date.now() - ps.startTs;
            const p = Math.min(1, elapsed / LONG_PRESS_MS);
            setProgress(p);
            if (p >= 1 && !ps.longFired) {
                ps.longFired = true;
                thudFeedback();
                onChangeRef.current(name, 'capture');
            }
            if (elapsed < LONG_PRESS_MS * 1.2 && ps.startTs > 0) {
                ps.rafId = requestAnimationFrame(tick);
            }
        }

        function startPress() {
            ps.startTs = Date.now();
            ps.longFired = false;
            setPressing(true);
            setProgress(0);
            tickFeedback();
            tick();
        }

        function endPress() {
            const elapsed = Date.now() - ps.startTs;
            ps.startTs = 0;
            if (ps.rafId) { cancelAnimationFrame(ps.rafId); ps.rafId = null; }
            setPressing(false);
            setProgress(0);
            // Short-press: only fire if we didn't already long-press,
            // and the press ended before the long-press threshold.
            if (!ps.longFired && elapsed < LONG_PRESS_MS) {
                onChangeRef.current(name, 'fire');
            }
            ps.longFired = false;
        }

        // --- Touch path: pin to a single Touch.identifier.
        function findTouch(e, id) {
            for (const t of e.touches) if (t.identifier === id) return t;
            return null;
        }
        function onTouchStart(e) {
            e.preventDefault(); e.stopPropagation();
            const t = e.changedTouches[0];
            ps.activeTouchId = t.identifier;
            startPress();
            window.addEventListener('touchend', onTouchEnd);
            window.addEventListener('touchcancel', onTouchEnd);
        }
        function onTouchEnd(e) {
            for (const t of e.changedTouches) {
                if (t.identifier === ps.activeTouchId) {
                    ps.activeTouchId = null;
                    window.removeEventListener('touchend', onTouchEnd);
                    window.removeEventListener('touchcancel', onTouchEnd);
                    endPress();
                    break;
                }
            }
        }

        function onMouseDown(e) {
            e.preventDefault();
            startPress();
            const mu = () => {
                window.removeEventListener('mouseup', mu);
                endPress();
            };
            window.addEventListener('mouseup', mu);
        }

        el.addEventListener('touchstart', onTouchStart, { passive: false });
        el.addEventListener('mousedown', onMouseDown);
        return () => {
            el.removeEventListener('touchstart', onTouchStart);
            el.removeEventListener('mousedown', onMouseDown);
            if (ps.rafId) cancelAnimationFrame(ps.rafId);
        };
    }, [name]);

    const text = pressing ? 'HOLD TO LEARN'
        : armed ? 'Learned'
        : (label || 'DROP');

    return html`<div class="droppad-row">
        <div class="droppad ${pressing ? 'pressing' : ''} ${armed ? 'armed' : ''}" ref=${padRef}>
            <span class="droppad-label">${text}</span>
            ${pressing ? html`<div class="droppad-progress" style="width: ${progress * 100}%"></div>` : null}
        </div>
    </div>`;
}
