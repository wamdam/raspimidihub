/**
 * Display plugin control.
 */

import { html } from './common.js';

// =======================================================================
// PLUGIN CONFIG PANEL — renders full plugin parameter UI
// =======================================================================
export function DisplayMeter({ label, value, min, max }) {
    const pct = Math.max(0, Math.min(100, ((value || 0) - (min || 0)) / ((max || 127) - (min || 0)) * 100));
    const color = pct < 50 ? 'var(--success)' : pct < 80 ? '#f0ad4e' : 'var(--accent)';
    return html`<div style="margin-bottom:12px">
        <div style="font-size:12px;color:var(--text-dim);margin-bottom:4px">${label}: ${value || 0}</div>
        <div style="height:8px;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden">
            <div style="height:100%;width:${pct}%;background:${color};border-radius:4px;transition:width 0.1s"></div>
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

