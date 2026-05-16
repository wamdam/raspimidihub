/**
 * XYPad plugin control — square pad with a draggable dot.
 *
 * Two-axis value stored as `{x, y}`. Used inside LayoutGrid templates
 * as a dual-CC source for the §5 Controller plugin. Touch handling
 * follows the multi-touch pattern from Knob/Fader/Wheel: pin the
 * gesture to a single Touch.identifier so two pads can be dragged
 * simultaneously without cross-tracking.
 *
 * Spring (per-cell config):
 *   - springForce 0..127: 0 = off, 1 = very slow snap-back, 127 = very
 *     fast. Linear map to a tau between ~5 s (force=1) and ~30 ms
 *     (force=127); each animation frame nudges the value by dt/tau
 *     toward home (exponential decay).
 *   - springHome "bottom_left" → (min, min); "center" → midpoint.
 * Animation runs only on the browser doing the gesture; other browsers
 * pick up the values via SSE through the same param-update channel.
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html, tickFeedback, makeLongPress } from './common.js';

export function PluginXYPad({ name, label, value, min, max, onChange, springForce, springHome, onBindRequest }) {
    const padRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    const onBindRef = useRef(onBindRequest);
    onBindRef.current = onBindRequest;

    const v = (value && typeof value === 'object') ? value : { x: 0, y: 0 };
    const lo = min ?? 0;
    const hi = max ?? 127;
    const safeX = Math.max(lo, Math.min(hi, v.x ?? lo));
    const safeY = Math.max(lo, Math.min(hi, v.y ?? lo));

    // Track the last value WE emitted, so we can compare and only fire
    // onChange when something actually changed (avoid SSE feedback loops).
    const s = useRef({ x: safeX, y: safeY }).current;
    const [, force] = useState(0);

    // Spring config can change between renders (user edits the cell);
    // a ref lets the long-lived event-handler closure read the current
    // values without re-binding listeners.
    const springRef = useRef({ force: springForce, home: springHome });
    springRef.current = { force: springForce, home: springHome };

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

        function applyValue(nx, ny) {
            if (nx !== s.x || ny !== s.y) {
                s.x = nx; s.y = ny;
                onChangeRef.current(name, { x: nx, y: ny });
                force(n => n + 1);
            }
        }

        function applyMove(clientX, clientY) {
            const next = pointToValue(clientX, clientY);
            if (next.x !== s.x || next.y !== s.y) {
                tickFeedback();
                applyValue(next.x, next.y);
            }
        }

        // --- Spring animation: exponential decay toward home.
        // Track position as a float across frames and only emit when the
        // rounded integer changes — without this, slow forces stalled
        // because the per-frame delta was below 0.5 px so Math.round
        // returned the same int every frame and we never advanced.
        let springRaf = null;
        let springLastT = 0;
        let springFx = 0;
        let springFy = 0;
        function cancelSpring() {
            if (springRaf !== null) {
                cancelAnimationFrame(springRaf);
                springRaf = null;
            }
        }
        function startSpring() {
            cancelSpring();
            const f = springRef.current.force;
            if (!f || f < 1) return;
            // Linear map: force=1 → 5000 ms, force=127 → ~30 ms.
            const tauMs = 5030 - (Math.min(127, Math.max(1, f)) * 5000 / 127);
            // Accept legacy "center"/"bottom_left" (lowercase, snake) and
            // the new display-string values "Center"/"Bottom-left".
            const homeStr = (springRef.current.home || "").toLowerCase();
            const isCenter = homeStr === "center";
            const home = isCenter
                ? { x: Math.round((lo + hi) / 2), y: Math.round((lo + hi) / 2) }
                : { x: lo, y: lo };
            springFx = s.x;
            springFy = s.y;
            springLastT = performance.now();
            function tick(now) {
                if (activeTouchId !== null || mouseDragging) {
                    springRaf = null;
                    return;
                }
                const dt = now - springLastT;
                springLastT = now;
                const k = Math.min(1, dt / tauMs);
                springFx = springFx + (home.x - springFx) * k;
                springFy = springFy + (home.y - springFy) * k;
                applyValue(Math.round(springFx), Math.round(springFy));
                if (Math.abs(springFx - home.x) < 0.5 &&
                    Math.abs(springFy - home.y) < 0.5) {
                    applyValue(home.x, home.y);
                    springRaf = null;
                    return;
                }
                springRaf = requestAnimationFrame(tick);
            }
            springRaf = requestAnimationFrame(tick);
        }

        // Long-press → open the binding popup. Holding still on an XY
        // pad opens the CellBinding modal; the in-flight drag is
        // aborted via applyValue being skipped after lp.moveDidFire.
        const lp = makeLongPress(() => {
            if (onBindRef.current) onBindRef.current(name);
        });

        // --- Touch path: pin to a single identifier so two-finger drags
        // on two XY pads track independently.
        let activeTouchId = null;
        function findTouch(e, id) {
            for (const t of e.touches) if (t.identifier === id) return t;
            return null;
        }
        function onTouchStart(e) {
            e.preventDefault(); e.stopPropagation();
            cancelSpring();
            const t = e.changedTouches[0];
            activeTouchId = t.identifier;
            lp.start(t.clientX, t.clientY);
            applyMove(t.clientX, t.clientY);
            el.addEventListener('touchmove', onTouchMove, { passive: false });
            window.addEventListener('touchend', onTouchEnd);
            window.addEventListener('touchcancel', onTouchEnd);
        }
        function onTouchMove(e) {
            e.preventDefault(); e.stopPropagation();
            const t = findTouch(e, activeTouchId);
            if (!t) return;
            if (lp.moveDidFire(t.clientX, t.clientY)) return;
            applyMove(t.clientX, t.clientY);
        }
        function onTouchEnd(e) {
            if (e) e.stopPropagation();
            for (const t of e.changedTouches) {
                if (t.identifier === activeTouchId) {
                    activeTouchId = null;
                    lp.end();
                    el.removeEventListener('touchmove', onTouchMove);
                    window.removeEventListener('touchend', onTouchEnd);
                    window.removeEventListener('touchcancel', onTouchEnd);
                    startSpring();
                    break;
                }
            }
        }

        let mouseDragging = false;
        function onMouseDown(e) {
            if (e.button === 2) return;  // right-click → onContextMenu
            e.preventDefault();
            cancelSpring();
            mouseDragging = true;
            lp.start(e.clientX, e.clientY);
            applyMove(e.clientX, e.clientY);
            const mm = (ev) => {
                if (lp.moveDidFire(ev.clientX, ev.clientY)) {
                    window.removeEventListener('mousemove', mm);
                    window.removeEventListener('mouseup', mu);
                    mouseDragging = false;
                    return;
                }
                applyMove(ev.clientX, ev.clientY);
            };
            const mu = () => {
                lp.end();
                window.removeEventListener('mousemove', mm);
                window.removeEventListener('mouseup', mu);
                mouseDragging = false;
                startSpring();
            };
            window.addEventListener('mousemove', mm);
            window.addEventListener('mouseup', mu);
        }
        function onContextMenu(e) {
            e.preventDefault();
            if (onBindRef.current) onBindRef.current(name);
        }

        el.addEventListener('touchstart', onTouchStart, { passive: false });
        el.addEventListener('mousedown', onMouseDown);
        el.addEventListener('contextmenu', onContextMenu);
        return () => {
            cancelSpring();
            el.removeEventListener('touchstart', onTouchStart);
            el.removeEventListener('mousedown', onMouseDown);
            el.removeEventListener('contextmenu', onContextMenu);
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
