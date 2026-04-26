/**
 * XYPad plugin control — square pad with a draggable dot.
 *
 * Two-axis value stored as `{x, y}`. Used inside LayoutGrid templates
 * as a dual-CC source for the §5 Controller plugin. Touch handling
 * follows the multi-touch pattern from Knob/Fader/Wheel: pin the
 * gesture to a single Touch.identifier so two pads can be dragged
 * simultaneously without cross-tracking.
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html, tickFeedback } from './common.js';

export function PluginXYPad({ name, label, value, min, max, onChange }) {
    const padRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;

    const v = (value && typeof value === 'object') ? value : { x: 0, y: 0 };
    const lo = min ?? 0;
    const hi = max ?? 127;
    const safeX = Math.max(lo, Math.min(hi, v.x ?? lo));
    const safeY = Math.max(lo, Math.min(hi, v.y ?? lo));

    // Track the last value WE emitted, so we can compare and only fire
    // onChange when something actually changed (avoid SSE feedback loops).
    const s = useRef({ x: safeX, y: safeY }).current;
    const [, force] = useState(0);

    useEffect(() => {
        s.x = safeX; s.y = safeY;
        force(n => n + 1);
    }, [safeX, safeY]);

    useEffect(() => {
        const el = padRef.current;
        if (!el) return;

        function pointToValue(clientX, clientY) {
            const rect = el.getBoundingClientRect();
            const xr = (clientX - rect.left) / rect.width;
            const yr = 1 - (clientY - rect.top) / rect.height;  // inverted: bottom = min
            const nx = Math.max(lo, Math.min(hi, Math.round(lo + xr * (hi - lo))));
            const ny = Math.max(lo, Math.min(hi, Math.round(lo + yr * (hi - lo))));
            return { x: nx, y: ny };
        }

        function applyMove(clientX, clientY) {
            const next = pointToValue(clientX, clientY);
            if (next.x !== s.x || next.y !== s.y) {
                s.x = next.x; s.y = next.y;
                tickFeedback();
                onChangeRef.current(name, next);
                force(n => n + 1);
            }
        }

        // --- Touch path: pin to a single identifier so two-finger drags
        // on two XY pads track independently.
        let activeTouchId = null;
        function findTouch(e, id) {
            for (const t of e.touches) if (t.identifier === id) return t;
            return null;
        }
        function onTouchStart(e) {
            e.preventDefault(); e.stopPropagation();
            const t = e.changedTouches[0];
            activeTouchId = t.identifier;
            applyMove(t.clientX, t.clientY);
            el.addEventListener('touchmove', onTouchMove, { passive: false });
            window.addEventListener('touchend', onTouchEnd);
            window.addEventListener('touchcancel', onTouchEnd);
        }
        function onTouchMove(e) {
            e.preventDefault(); e.stopPropagation();
            const t = findTouch(e, activeTouchId);
            if (t) applyMove(t.clientX, t.clientY);
        }
        function onTouchEnd(e) {
            if (e) e.stopPropagation();
            for (const t of e.changedTouches) {
                if (t.identifier === activeTouchId) {
                    activeTouchId = null;
                    el.removeEventListener('touchmove', onTouchMove);
                    window.removeEventListener('touchend', onTouchEnd);
                    window.removeEventListener('touchcancel', onTouchEnd);
                    break;
                }
            }
        }

        function onMouseDown(e) {
            e.preventDefault();
            applyMove(e.clientX, e.clientY);
            const mm = (ev) => applyMove(ev.clientX, ev.clientY);
            const mu = () => {
                window.removeEventListener('mousemove', mm);
                window.removeEventListener('mouseup', mu);
            };
            window.addEventListener('mousemove', mm);
            window.addEventListener('mouseup', mu);
        }

        el.addEventListener('touchstart', onTouchStart, { passive: false });
        el.addEventListener('mousedown', onMouseDown);
        return () => {
            el.removeEventListener('touchstart', onTouchStart);
            el.removeEventListener('mousedown', onMouseDown);
        };
    }, [name, lo, hi]);

    const xRatio = (s.x - lo) / (hi - lo || 1);
    const yRatio = (s.y - lo) / (hi - lo || 1);
    const dotLeft = `${xRatio * 100}%`;
    const dotBottom = `${yRatio * 100}%`;

    return html`<div class="xypad-group">
        <span class="xypad-label">${label}</span>
        <div class="xypad-pad" ref=${padRef}>
            <div class="xypad-axis-x"></div>
            <div class="xypad-axis-y"></div>
            <div class="xypad-dot" style="left: ${dotLeft}; bottom: ${dotBottom}"></div>
            <div class="xypad-value">${s.x}, ${s.y}</div>
        </div>
    </div>`;
}
