/**
 * TouchOverlay — fading-ripple visualisation for incoming touch
 * events. Used on the spectator view (?touches=1) so the audience
 * can see where the source phone is being touched.
 *
 * Props:
 *   - points: array of {kind, x, y, id, t} pushed by the spectator
 *     page from incoming `spectator-state` events of kind 'touch'.
 *     The array is the rolling history; entries fade out via the
 *     ripple animation and are pruned by the parent.
 *   - scale: number; the spectator wraps the app tree in a CSS
 *     transform: scale(...) to fit the source's viewport. Points
 *     arrive in source-viewport coordinates so we render this
 *     overlay INSIDE the scaled wrapper for free.
 *
 * Render strategy: an absolutely-positioned <canvas> sized to the
 * source viewport. requestAnimationFrame loop draws expanding fading
 * rings (down events) and trails (move events). Cheap: a handful of
 * arcs per frame.
 */

import { useEffect, useRef } from '../hooks.module.js';
import { html } from '../../ui/common.js';

const DOWN_RIPPLE_MS = 600;   // expanding ring after a down/up
const MOVE_DOT_MS = 280;      // dot trail after each move
const RIPPLE_MAX_RADIUS = 38; // px (in source-viewport coordinates)
const MOVE_DOT_RADIUS = 10;

export function TouchOverlay({ pointsRef, width, height }) {
    const canvasRef = useRef(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return undefined;
        const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        let raf = null;
        const tick = () => {
            ctx.clearRect(0, 0, width, height);
            const now = performance.now();
            const pts = pointsRef.current;
            // Prune expired entries in place — newest at the end.
            while (pts.length && now - pts[0].t
                    > (pts[0].kind === 'move' ? MOVE_DOT_MS : DOWN_RIPPLE_MS)) {
                pts.shift();
            }
            for (const p of pts) {
                const age = now - p.t;
                if (p.kind === 'move') {
                    const k = 1 - age / MOVE_DOT_MS;
                    if (k <= 0) continue;
                    ctx.beginPath();
                    ctx.arc(p.x, p.y, MOVE_DOT_RADIUS * (0.4 + 0.6 * k), 0, Math.PI * 2);
                    ctx.fillStyle = `rgba(255, 200, 60, ${0.35 * k})`;
                    ctx.fill();
                } else {
                    // Down + up share an expanding ring. Down is a bit
                    // brighter; up has the same ring so a tap-release
                    // still leaves a visible mark even if the down
                    // ring already started fading.
                    const k = age / DOWN_RIPPLE_MS;
                    if (k >= 1) continue;
                    const alpha = (1 - k) * (p.kind === 'down' ? 0.85 : 0.6);
                    ctx.beginPath();
                    ctx.arc(p.x, p.y, RIPPLE_MAX_RADIUS * (0.2 + 0.8 * k), 0, Math.PI * 2);
                    ctx.strokeStyle = `rgba(255, 220, 90, ${alpha})`;
                    ctx.lineWidth = 3;
                    ctx.stroke();
                }
            }
            raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
        return () => { if (raf != null) cancelAnimationFrame(raf); };
    }, [pointsRef, width, height]);

    return html`<canvas ref=${canvasRef} class="spectator-touch-overlay" />`;
}
