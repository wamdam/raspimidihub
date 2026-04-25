/**
 * Display plugin control.
 */

import { html } from './common.js';
import { useEffect, useRef } from '../lib/hooks.module.js';

// =======================================================================
// Meter — read-only knob-style indicator. The LED arc reflects the live
// value; the body shows the number. No drag, no interaction.
// =======================================================================
const N_LEDS = 13;
const ANGLE_MIN = -135;
const ANGLE_MAX = 135;
const RING_RADIUS = 28;
const KNOB_RADIUS = 20;

function angleToXY(angleDeg, radius) {
    const a = (angleDeg - 90) * Math.PI / 180;
    return [Math.cos(a) * radius, Math.sin(a) * radius];
}

export function DisplayMeter({ label, value, min, max }) {
    const lo = min || 0, hi = (max != null ? max : 127);
    const v = value != null ? value : lo;
    const ratio = Math.max(0, Math.min(1, (v - lo) / (hi - lo || 1)));
    const angle = ANGLE_MIN + ratio * (ANGLE_MAX - ANGLE_MIN);
    const [indX, indY] = angleToXY(angle, KNOB_RADIUS - 4);
    const [indEndX, indEndY] = angleToXY(angle, KNOB_RADIUS - 12);

    const leds = [];
    for (let i = 0; i < N_LEDS; i++) {
        const t = i / (N_LEDS - 1);
        const a = ANGLE_MIN + t * (ANGLE_MAX - ANGLE_MIN);
        const [lx, ly] = angleToXY(a, RING_RADIUS);
        const lit = a <= angle + 0.5;
        leds.push(html`<circle cx=${lx} cy=${ly} r="2" fill=${lit ? 'var(--success)' : 'rgba(255,255,255,0.10)'}
            style=${lit ? 'filter: drop-shadow(0 0 3px var(--success))' : ''} />`);
    }

    return html`<div class="knob-group meter-readonly">
        <span class="knob-label">${label}</span>
        <div class="knob-container" style="cursor:default">
            <svg viewBox="-36 -36 72 72" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <radialGradient id="meter-body" cx="0.35" cy="0.30" r="0.85">
                        <stop offset="0%" stop-color="#2a3a36" />
                        <stop offset="40%" stop-color="#1c2826" />
                        <stop offset="100%" stop-color="#0e1614" />
                    </radialGradient>
                </defs>
                ${leds}
                <circle cx="0" cy="0" r=${KNOB_RADIUS} fill="url(#meter-body)"
                    stroke="rgba(0,0,0,0.5)" stroke-width="1" />
                <line x1=${indX} y1=${indY} x2=${indEndX} y2=${indEndY}
                    stroke="var(--success)" stroke-width="2" stroke-linecap="round"
                    style="filter: drop-shadow(0 0 2px var(--success))" />
            </svg>
            <div class="knob-value">${v}</div>
        </div>
    </div>`;
}

export function DisplayScope({ label, value, min, max, duration }) {
    const canvasRef = useRef(null);
    const historyRef = useRef([]);
    const valueRef = useRef(value);
    valueRef.current = value;
    const dur = duration || 2;
    const MAX_POINTS = Math.round(dur * 20);
    const lo = min || 0, hi = max || 127, mid = Math.round((lo + hi) / 2);

    // Use interval to sample valueRef at fixed rate — independent of React renders
    useEffect(() => {
        const interval = setInterval(() => {
            const h = historyRef.current;
            const v = valueRef.current;
            h.push(v != null ? v : lo);
        if (h.length > MAX_POINTS) h.shift();

        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width, ht = canvas.height;

        ctx.clearRect(0, 0, w, ht);

        // Grid: center line
        ctx.strokeStyle = 'rgba(255,255,255,0.08)';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(0, ht / 2); ctx.lineTo(w, ht / 2); ctx.stroke();

        // Waveform
        if (h.length < 2) return;
        ctx.strokeStyle = '#4dd9c0';
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let i = 0; i < h.length; i++) {
            const x = (i / (MAX_POINTS - 1)) * w;
            const y = ht - ((h[i] - lo) / (hi - lo)) * ht;
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
            ctx.stroke();
        }, 50); // 20 Hz redraw
        return () => clearInterval(interval);
    }, []);

    return html`<div style="margin-bottom:8px">
        <div style="font-size:12px;color:var(--text-dim);margin-bottom:4px;text-align:center">${label}</div>
        <div style="display:flex;align-items:stretch;gap:4px">
        <div style="display:flex;flex-direction:column;justify-content:space-between;font-size:9px;color:var(--text-dim);padding:1px 0;min-width:18px;text-align:right">
            <span>${hi}</span><span>${mid}</span><span>${lo}</span>
        </div>
        <div style="flex:1;position:relative">
            <canvas ref=${canvasRef} width="200" height="50"
                style="width:100%;height:50px;border-radius:4px;background:var(--bg);border:1px solid rgba(255,255,255,0.06)"></canvas>
            <span style="position:absolute;bottom:2px;right:4px;font-size:9px;color:var(--text-dim)">${dur}s</span>
        </div>
        </div>
    </div>`;
}

