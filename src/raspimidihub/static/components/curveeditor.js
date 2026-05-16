/**
 * CurveEditor plugin control.
 */

import { html, tickFeedback } from './common.js';
import { useState, useEffect, useRef } from '../lib/hooks.module.js';
import { token } from '../lib/theme.js';

// =======================================================================
// CURVE EDITOR — drawable 128-point curve with presets
// =======================================================================
export const CURVE_PRESETS = {
    'Linear':      (i) => i,
    'Soft':        (i) => Math.round(127 * Math.pow(i / 127, 0.5)),
    'Hard':        (i) => Math.round(127 * Math.pow(i / 127, 2)),
    'Exponential': (i) => Math.round(127 * Math.pow(i / 127, 3)),
    'Logarithmic': (i) => Math.round(127 * Math.pow(i / 127, 0.33)),
    'S-Curve':     (i) => { const x = i / 127; return Math.round(127 * (x < 0.5 ? 2 * x * x : 1 - 2 * (1 - x) * (1 - x))); },
};

export function PluginCurveEditor({ name, label, value, onChange }) {
    const canvasRef = useRef(null);
    const curveRef = useRef(value || Array.from({length: 128}, (_, i) => i));
    const [preset, setPreset] = useState('');

    useEffect(() => { curveRef.current = value || Array.from({length: 128}, (_, i) => i); draw(); }, [value]);

    const draw = () => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        // Grid
        ctx.strokeStyle = token('curve-grid-minor');
        ctx.lineWidth = 1;
        for (let i = 1; i < 4; i++) {
            const p = (i / 4) * w;
            ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, h); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(w, p); ctx.stroke();
        }

        // Diagonal reference
        ctx.strokeStyle = token('curve-grid-major');
        ctx.beginPath(); ctx.moveTo(0, h); ctx.lineTo(w, 0); ctx.stroke();

        // Curve
        const curve = curveRef.current;
        ctx.strokeStyle = token('curve-stroke');
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let i = 0; i < 128; i++) {
            const x = (i / 127) * w;
            const y = h - (curve[i] / 127) * h;
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
    };

    const handleDraw = (clientX, clientY) => {
        const canvas = canvasRef.current;
        const rect = canvas.getBoundingClientRect();
        const x = Math.max(0, Math.min(127, Math.round((clientX - rect.left) / rect.width * 127)));
        const y = Math.max(0, Math.min(127, 127 - Math.round((clientY - rect.top) / rect.height * 127)));
        const curve = [...curveRef.current];
        curve[x] = y;
        // Interpolate gaps
        if (curveRef.current._lastX !== undefined && Math.abs(x - curveRef.current._lastX) > 1) {
            const x0 = curveRef.current._lastX, y0 = curveRef.current._lastY;
            const steps = Math.abs(x - x0);
            for (let s = 1; s < steps; s++) {
                const xi = Math.round(x0 + (x - x0) * s / steps);
                curve[xi] = Math.round(y0 + (y - y0) * s / steps);
            }
        }
        curveRef.current = curve;
        curveRef.current._lastX = x;
        curveRef.current._lastY = y;
        setPreset('');
        draw();
        onChange(name, curve);
    };

    const onTouchStart = (e) => { e.preventDefault(); handleDraw(e.touches[0].clientX, e.touches[0].clientY); };
    const onTouchMove = (e) => { e.preventDefault(); handleDraw(e.touches[0].clientX, e.touches[0].clientY); };
    const onTouchEnd = () => { delete curveRef.current._lastX; };
    const onMouseDown = (e) => {
        e.preventDefault(); handleDraw(e.clientX, e.clientY);
        const mm = (ev) => handleDraw(ev.clientX, ev.clientY);
        const mu = () => { delete curveRef.current._lastX; window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu); };
        window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu);
    };

    const applyPreset = (name) => {
        const fn = CURVE_PRESETS[name];
        if (!fn) return;
        const curve = Array.from({length: 128}, (_, i) => fn(i));
        curveRef.current = curve;
        setPreset(name);
        draw();
        tickFeedback();
        onChange('curve', curve);
    };

    useEffect(() => { draw(); }, []);

    return html`<div class="curve-group">
        <div style="font-size:13px;color:var(--text-dim);margin-bottom:8px">${label}</div>
        <div class="curve-canvas-wrap"
            onTouchStart=${onTouchStart} onTouchMove=${onTouchMove} onTouchEnd=${onTouchEnd}
            onMouseDown=${onMouseDown}>
            <canvas ref=${canvasRef} width="280" height="280"></canvas>
        </div>
        <div class="curve-presets">
            ${Object.keys(CURVE_PRESETS).map(p => html`
                <div class="radio-opt ${preset === p ? 'active' : ''}" key=${p}
                    onclick=${() => applyPreset(p)}>${p}</div>
            `)}
        </div>
    </div>`;
}

