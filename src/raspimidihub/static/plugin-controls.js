/**
 * Plugin parameter UI components for RaspiMIDIHub.
 *
 * Renders declarative plugin params (Wheel, Fader, Radio, Toggle,
 * StepEditor, CurveEditor, NoteSelect, ChannelSelect, Group)
 * as interactive Preact components with haptic feedback.
 *
 * Based on controls-demo.html reference implementation.
 */

import { h } from './lib/preact.module.js';
import { useState, useEffect, useRef, useCallback } from './lib/hooks.module.js';
import htm from './lib/htm.module.js';

const html = htm.bind(h);

// --- Haptic feedback ---
let audioCtx = null;
function ensureAudio() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    return audioCtx;
}

function tickFeedback() {
    try {
        const ctx = ensureAudio();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'square';
        osc.frequency.value = 3500;
        gain.gain.value = 0.03;
        osc.connect(gain).connect(ctx.destination);
        osc.start(); osc.stop(ctx.currentTime + 0.02);
    } catch {}
    try { navigator.vibrate(2); } catch {}
}

function thudFeedback() {
    try {
        const ctx = ensureAudio();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = 150;
        gain.gain.value = 0.08;
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.08);
        osc.connect(gain).connect(ctx.destination);
        osc.start(); osc.stop(ctx.currentTime + 0.08);
    } catch {}
    try { navigator.vibrate(30); } catch {}
}

// --- Note names ---
const NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
function noteName(n) { return `${NOTE_NAMES[n % 12]}${Math.floor(n / 12) - 2}`; }

// Global touch lock: only one wheel active per touch
const _activeWheelTouch = new Map(); // touchId -> element

// =======================================================================
// WHEEL — scrollable drum wheel (pixel-offset based, matching controls-demo.html)
// =======================================================================
function PluginWheel({ name, label, min, max, value, onChange, suffix, tickLabel }) {
    const containerRef = useRef(null);
    const innerRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    const TICK_H = 20;
    const CENTER = 30 - TICK_H / 2;
    // Persistent state across renders (not React state — direct DOM manipulation)
    const s = useRef({
        value, offset: 0, startY: 0, startOffset: 0, lastY: 0, lastT: 0,
        velocity: 0, animId: null, atBoundary: false, lastWheel: 0,
    }).current;

    const valueToOffset = (v) => CENTER - (v - min) * TICK_H;
    const offsetToValue = (off) => Math.round(min + (CENTER - off) / TICK_H);
    const minOffset = valueToOffset(max); // max value = minimum offset (scrolled up)
    const maxOffset = valueToOffset(min); // min value = maximum offset
    const clampOffset = (off) => Math.max(minOffset, Math.min(maxOffset, off));

    const updateTicks = () => {
        const el = innerRef.current;
        if (!el) return;
        const children = el.children;
        for (let i = 0; i < children.length; i++) {
            const dist = Math.abs(min + i - s.value);
            children[i].className = 'wheel-tick' + (dist === 0 ? ' active' : dist === 1 ? ' near' : '');
        }
    };

    const setOffset = (off) => {
        s.offset = off;
        if (innerRef.current) innerRef.current.style.transform = `translateY(${off}px)`;
    };

    const snapToValue = () => {
        const target = valueToOffset(s.value);
        const snap = () => {
            s.offset += (target - s.offset) * 0.3;
            setOffset(s.offset);
            if (Math.abs(target - s.offset) > 0.5) s.animId = requestAnimationFrame(snap);
            else setOffset(target);
        };
        if (Math.abs(target - s.offset) < 0.5) { setOffset(target); return; }
        s.animId = requestAnimationFrame(snap);
    };

    // Sync from prop changes (e.g. MIDI Learn updating value)
    useEffect(() => {
        s.value = value;
        setOffset(valueToOffset(value));
        updateTicks();
    }, [value]);

    // Attach native event listeners for passive:false + stopPropagation
    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;

        const oc = onChangeRef;

        function onStart(e) {
            e.preventDefault(); e.stopPropagation();
            // Touch lock: claim this touch, skip if another wheel owns it
            if (e.touches) {
                const tid = e.touches[0].identifier;
                if (_activeWheelTouch.has(tid)) return;
                _activeWheelTouch.set(tid, el);
                s._touchId = tid;
            }
            if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; }
            s.atBoundary = false;
            const pt = e.touches ? e.touches[0] : e;
            s.startY = pt.clientY; s.startOffset = s.offset;
            s.lastY = pt.clientY; s.lastT = Date.now(); s.velocity = 0;
            el.addEventListener('touchmove', onMove, { passive: false });
            window.addEventListener('mousemove', onMove);
            window.addEventListener('touchend', onEnd);
            window.addEventListener('mouseup', onEnd);
        }
        function onMove(e) {
            e.preventDefault();
            if (e.touches) e.stopPropagation();
            const pt = e.touches ? e.touches[0] : e;
            const now = Date.now(); const dt = now - s.lastT;
            if (dt > 0) s.velocity = (pt.clientY - s.lastY) / dt;
            s.lastY = pt.clientY; s.lastT = now;
            let raw = s.startOffset + (pt.clientY - s.startY);
            const clamped = clampOffset(raw);
            const hitBound = raw !== clamped;
            s.offset = clamped;
            if (hitBound && !s.atBoundary) { thudFeedback(); s.velocity = 0; s.atBoundary = true; }
            else if (!hitBound) s.atBoundary = false;
            const nv = offsetToValue(s.offset);
            if (nv !== s.value) { tickFeedback(); s.value = nv; updateTicks(); oc.current(name, nv); }
            setOffset(s.offset);
        }
        function onEnd(e) {
            if (e && e.touches) e.stopPropagation();
            // Release touch lock
            if (s._touchId != null) { _activeWheelTouch.delete(s._touchId); s._touchId = null; }
            el.removeEventListener('touchmove', onMove);
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('touchend', onEnd);
            window.removeEventListener('mouseup', onEnd);
            if (Math.abs(s.velocity) > 0.2) animateMomentum();
            else snapToValue();
        }
        function animateMomentum() {
            const friction = 0.95;
            function frame() {
                s.velocity *= friction;
                let raw = s.offset + s.velocity * 16;
                const clamped = clampOffset(raw);
                if (raw !== clamped) { s.offset = clamped; s.velocity = 0; thudFeedback(); setOffset(s.offset); snapToValue(); return; }
                s.offset = clamped;
                const nv = offsetToValue(s.offset);
                if (nv !== s.value) { tickFeedback(); s.value = nv; updateTicks(); oc.current(name, nv); }
                setOffset(s.offset);
                if (Math.abs(s.velocity) > 0.05) s.animId = requestAnimationFrame(frame);
                else snapToValue();
            }
            s.animId = requestAnimationFrame(frame);
        }
        function onWheel(e) {
            e.preventDefault();
            const now = Date.now();
            if (now - s.lastWheel < 80) return;
            s.lastWheel = now;
            if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; }
            const delta = e.deltaY > 0 ? -1 : 1;
            const nv = Math.max(min, Math.min(max, s.value + delta));
            if (nv !== s.value) {
                s.value = nv; setOffset(valueToOffset(nv)); updateTicks(); oc.current(name, nv);
                (nv === min || nv === max) ? thudFeedback() : tickFeedback();
            }
        }
        el.addEventListener('touchstart', onStart, { passive: false });
        el.addEventListener('mousedown', onStart);
        el.addEventListener('wheel', onWheel, { passive: false });
        return () => {
            el.removeEventListener('touchstart', onStart);
            el.removeEventListener('mousedown', onStart);
            el.removeEventListener('wheel', onWheel);
        };
    }, [min, max, name]);

    const ticks = [];
    for (let i = min; i <= max; i++) {
        ticks.push(html`<div class="wheel-tick" key=${i}>${tickLabel ? tickLabel(i) : suffix ? i + suffix : i}</div>`);
    }

    return html`<div class="wheel-group">
        <span class="wheel-label">${label}</span>
        <div class="wheel-container" ref=${containerRef}>
            <div class="wheel-inner" ref=${innerRef}>${ticks}</div>
        </div>
    </div>`;
}

// =======================================================================
// FADER — mixer-strip style
// =======================================================================
function PluginFader({ name, label, min, max, value, onChange, vertical, suffix }) {
    const trackRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    const s = useRef({ val: value }).current;
    const [val, setVal] = useState(value);

    useEffect(() => { s.val = value; setVal(value); }, [value]);

    // Native event listeners for passive:false (multitouch compat)
    useEffect(() => {
        const el = trackRef.current;
        if (!el) return;

        const oc = onChangeRef;

        function calcValue(clientX, clientY) {
            const rect = el.getBoundingClientRect();
            let ratio = vertical
                ? 1 - (clientY - rect.top) / rect.height
                : (clientX - rect.left) / rect.width;
            ratio = Math.max(0, Math.min(1, ratio));
            return Math.round(min + ratio * (max - min));
        }

        function handleMove(clientX, clientY) {
            const nv = calcValue(clientX, clientY);
            if (nv !== s.val) { s.val = nv; setVal(nv); oc.current(name, nv); tickFeedback(); }
        }

        function onTouchStart(e) {
            e.preventDefault(); e.stopPropagation();
            handleMove(e.touches[0].clientX, e.touches[0].clientY);
            el.addEventListener('touchmove', onTouchMove, { passive: false });
            window.addEventListener('touchend', onTouchEnd);
        }
        function onTouchMove(e) {
            e.preventDefault(); e.stopPropagation();
            handleMove(e.touches[0].clientX, e.touches[0].clientY);
        }
        function onTouchEnd(e) {
            if (e) e.stopPropagation();
            el.removeEventListener('touchmove', onTouchMove);
            window.removeEventListener('touchend', onTouchEnd);
        }
        function onMouseDown(e) {
            e.preventDefault(); handleMove(e.clientX, e.clientY);
            const mm = (ev) => handleMove(ev.clientX, ev.clientY);
            const mu = () => { window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu); };
            window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu);
        }

        el.addEventListener('touchstart', onTouchStart, { passive: false });
        el.addEventListener('mousedown', onMouseDown);
        return () => { el.removeEventListener('touchstart', onTouchStart); el.removeEventListener('mousedown', onMouseDown); };
    }, [min, max, name, vertical]);

    const ratio = (val - min) / (max - min || 1);
    // Clamp thumb inside track: pad by half thumb width (20px) from each edge
    // Use calc() so it works at any track width
    const thumbStyle = vertical
        ? { bottom: `calc(${ratio * 100}% - 26px + ${(1 - ratio) * 52}px)` }
        : { left: `calc(4px + ${ratio} * (100% - 48px))` };
    const fillStyle = vertical
        ? { height: `${ratio * 100}%` }
        : { width: `calc(12px + ${ratio} * (100% - 24px))` };

    return html`<div class="fader-group ${vertical ? 'vertical' : ''}">
        <span class="fader-label">${label}</span>
        <div class="fader-track ${vertical ? 'vertical' : ''}" ref=${trackRef}>
            <div class="fader-fill" style=${fillStyle}></div>
            <div class="fader-thumb" style=${thumbStyle}>
                <span class="fader-thumb-val">${val}${suffix || ''}</span>
            </div>
        </div>
    </div>`;
}

// =======================================================================
// RADIO — pill buttons
// =======================================================================
function PluginRadio({ name, label, options, value, onChange }) {
    const select = (opt) => {
        tickFeedback();
        onChange(name, opt);
    };
    return html`<div class="radio-group">
        <span class="radio-label">${label}</span>
        <div class="radio-options">
            ${options.map(opt => html`
                <div class="radio-opt ${value === opt ? 'active' : ''}" key=${opt}
                    onclick=${() => select(opt)}>${opt}</div>
            `)}
        </div>
    </div>`;
}

// =======================================================================
// TOGGLE — metal switch
// =======================================================================
function PluginToggle({ name, label, value, onChange }) {
    const toggle = () => {
        tickFeedback();
        onChange(name, !value);
    };
    return html`<div class="toggle-group">
        <span class="toggle-label">${label}</span>
        <div style="display:flex;align-items:center;gap:8px">
            <div class="metal-toggle ${value ? 'on' : ''}" onclick=${toggle}>
                <div class="slot"></div>
                <div class="indicator off-dot"></div>
                <div class="indicator on-dot"></div>
            </div>
            <span class="toggle-state ${value ? 'on' : 'off'}">${value ? 'On' : 'Off'}</span>
        </div>
    </div>`;
}

// =======================================================================
// STEP EDITOR — grid with on/off dots and mini-wheel offsets
// =======================================================================
function PluginStepEditor({ name, label, value, onChange, lengthParam, allValues }) {
    // value is array of {on, offset}
    const steps = value || [];
    const length = (lengthParam && allValues && allValues[lengthParam])
        ? parseInt(allValues[lengthParam]) || 16 : steps.length || 16;
    const displaySteps = steps.slice(0, length);

    const toggleStep = (i) => {
        tickFeedback();
        const newSteps = [...steps];
        while (newSteps.length <= i) newSteps.push({ on: false, offset: 0 });
        newSteps[i] = { ...newSteps[i], on: !newSteps[i].on };
        onChange(name, newSteps);
    };

    const setOffset = (i, offset) => {
        const newSteps = [...steps];
        while (newSteps.length <= i) newSteps.push({ on: false, offset: 0 });
        newSteps[i] = { ...newSteps[i], offset: Math.max(-24, Math.min(24, offset)) };
        onChange(name, newSteps);
    };

    return html`<div class="step-editor">
        <div style="font-size:13px;color:var(--text-dim);margin-bottom:8px">${label}</div>
        <div class="step-grid">
            ${displaySteps.map((step, i) => html`
                <div class="step-cell ${step.on ? 'on' : ''} ${i % 4 === 0 ? 'beat' : ''}" key=${i}>
                    <div class="step-head" onclick=${() => toggleStep(i)}></div>
                    <${MiniWheel} value=${step.offset || 0}
                        onChange=${(v) => { tickFeedback(); setOffset(i, v); }} />
                </div>
            `)}
        </div>
    </div>`;
}

function MiniWheel({ value, onChange }) {
    const containerRef = useRef(null);
    const stateRef = useRef({ value, dragging: false, startY: 0, startVal: 0 });

    useEffect(() => { stateRef.current.value = value; }, [value]);

    const onTouchStart = (e) => {
        e.preventDefault(); e.stopPropagation();
        stateRef.current.dragging = true;
        stateRef.current.startY = e.touches[0].clientY;
        stateRef.current.startVal = stateRef.current.value;
    };
    const onTouchMove = (e) => {
        e.preventDefault(); e.stopPropagation();
        if (!stateRef.current.dragging) return;
        const dy = stateRef.current.startY - e.touches[0].clientY;
        const newVal = Math.max(-24, Math.min(24, Math.round(stateRef.current.startVal + dy / 8)));
        if (newVal !== stateRef.current.value) {
            stateRef.current.value = newVal;
            onChange(newVal);
        }
    };
    const onTouchEnd = () => { stateRef.current.dragging = false; };

    const display = value > 0 ? `+${value}` : `${value}`;
    return html`<div class="mini-wheel" ref=${containerRef}
        onTouchStart=${onTouchStart} onTouchMove=${onTouchMove} onTouchEnd=${onTouchEnd}>
        <div class="mini-wheel-inner" style="display:flex;align-items:center;justify-content:center;height:100%">
            <span style="font-size:9px;color:${value === 0 ? 'rgba(255,255,255,0.3)' : '#fff'}">${display}</span>
        </div>
    </div>`;
}

// =======================================================================
// CURVE EDITOR — drawable 128-point curve with presets
// =======================================================================
const CURVE_PRESETS = {
    'Linear':      (i) => i,
    'Soft':        (i) => Math.round(127 * Math.pow(i / 127, 0.5)),
    'Hard':        (i) => Math.round(127 * Math.pow(i / 127, 2)),
    'Exponential': (i) => Math.round(127 * Math.pow(i / 127, 3)),
    'Logarithmic': (i) => Math.round(127 * Math.pow(i / 127, 0.33)),
    'S-Curve':     (i) => { const x = i / 127; return Math.round(127 * (x < 0.5 ? 2 * x * x : 1 - 2 * (1 - x) * (1 - x))); },
};

function PluginCurveEditor({ name, label, value, onChange }) {
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
        ctx.strokeStyle = 'rgba(255,255,255,0.06)';
        ctx.lineWidth = 1;
        for (let i = 1; i < 4; i++) {
            const p = (i / 4) * w;
            ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, h); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(w, p); ctx.stroke();
        }

        // Diagonal reference
        ctx.strokeStyle = 'rgba(255,255,255,0.1)';
        ctx.beginPath(); ctx.moveTo(0, h); ctx.lineTo(w, 0); ctx.stroke();

        // Curve
        const curve = curveRef.current;
        ctx.strokeStyle = '#e94560';
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

// =======================================================================
// NOTE SELECT — PluginWheel with note name labels instead of numbers
// =======================================================================
function PluginNoteSelect({ name, label, value, onChange }) {
    // Reuse PluginWheel with a custom suffix that shows note names
    // We override the tick rendering by using noteName labels
    const containerRef = useRef(null);
    const innerRef = useRef(null);
    const TICK_H = 20;
    const CENTER = 30 - TICK_H / 2;
    const s = useRef({
        value, offset: 0, startY: 0, startOffset: 0, lastY: 0, lastT: 0,
        velocity: 0, animId: null, atBoundary: false, lastWheel: 0,
    }).current;

    const valueToOffset = (v) => CENTER - v * TICK_H;
    const offsetToValue = (off) => Math.round((CENTER - off) / TICK_H);
    const minOffset = valueToOffset(127);
    const maxOffset = valueToOffset(0);
    const clampOffset = (off) => Math.max(minOffset, Math.min(maxOffset, off));

    const updateTicks = () => {
        const el = innerRef.current;
        if (!el) return;
        for (let i = 0; i < el.children.length; i++) {
            const dist = Math.abs(i - s.value);
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
        function onWheel(e) { e.preventDefault(); const now = Date.now(); if (now - s.lastWheel < 80) return; s.lastWheel = now; if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; } const delta = e.deltaY > 0 ? -1 : 1; const nv = Math.max(0, Math.min(127, s.value + delta)); if (nv !== s.value) { s.value = nv; setOffset(valueToOffset(nv)); updateTicks(); onChange(name, nv); (nv === 0 || nv === 127) ? thudFeedback() : tickFeedback(); } }
        el.addEventListener('touchstart', onStart, { passive: false }); el.addEventListener('mousedown', onStart); el.addEventListener('wheel', onWheel, { passive: false });
        return () => { el.removeEventListener('touchstart', onStart); el.removeEventListener('mousedown', onStart); el.removeEventListener('wheel', onWheel); };
    }, [name]);

    const ticks = []; for (let i = 0; i <= 127; i++) ticks.push(html`<div class="wheel-tick" key=${i}>${noteName(i)}</div>`);
    return html`<div class="wheel-group">
        <span class="wheel-label">${label}</span>
        <div class="wheel-container" ref=${containerRef}><div class="wheel-inner" ref=${innerRef}>${ticks}</div></div>
    </div>`;
}

// =======================================================================
// CHANNEL SELECT — wheel 1-16
// =======================================================================
function PluginChannelSelect({ name, label, value, onChange }) {
    return html`<${PluginWheel} name=${name} label=${label} min=${1} max=${16}
        value=${value} onChange=${onChange} />`;
}

// =======================================================================
// GROUP — titled section
// =======================================================================
function PluginGroup({ title, children }) {
    return html`<div style="margin-bottom:16px">
        <div style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--surface2)">${title}</div>
        ${children}
    </div>`;
}

// =======================================================================
// PARAM RENDERER — maps param schema to components
// =======================================================================
function renderParam(param, values, onChange, allValues) {
    const val = values[param.name];

    // Check visible_when condition
    if (param.visible_when) {
        const condParam = param.visible_when.param;
        const condVal = param.visible_when.value;
        const current = allValues[condParam];
        if (Array.isArray(condVal)) {
            if (!condVal.includes(current)) return null;
        } else {
            if (current !== condVal) return null;
        }
    }

    switch (param.type) {
        case 'wheel':
            return html`<${PluginWheel} name=${param.name} label=${param.label}
                min=${param.min} max=${param.max} value=${val != null ? val : param.default}
                onChange=${onChange} />`;
        case 'fader':
            return html`<${PluginFader} name=${param.name} label=${param.label}
                min=${param.min} max=${param.max} value=${val != null ? val : param.default}
                vertical=${param.vertical} onChange=${onChange} />`;
        case 'radio':
            return html`<${PluginRadio} name=${param.name} label=${param.label}
                options=${param.options} value=${val != null ? val : param.default}
                onChange=${onChange} />`;
        case 'toggle':
            return html`<${PluginToggle} name=${param.name} label=${param.label}
                value=${val != null ? val : param.default} onChange=${onChange} />`;
        case 'stepeditor':
            return html`<${PluginStepEditor} name=${param.name} label=${param.label}
                value=${val || []} onChange=${onChange}
                lengthParam=${param.length_param} allValues=${allValues} />`;
        case 'curveeditor':
            return html`<${PluginCurveEditor} name=${param.name} label=${param.label}
                value=${val} onChange=${onChange} />`;
        case 'noteselect':
            return html`<${PluginNoteSelect} name=${param.name} label=${param.label}
                value=${val != null ? val : param.default || 60} onChange=${onChange} />`;
        case 'channelselect':
            return html`<${PluginChannelSelect} name=${param.name} label=${param.label}
                value=${val != null ? val : param.default || 1} onChange=${onChange} />`;
        default:
            return html`<div style="color:var(--text-dim);font-size:12px">Unknown: ${param.type}</div>`;
    }
}

const INLINE_TYPES = new Set(['wheel', 'noteselect', 'channelselect', 'toggle']);

function renderParamGroup(items, values, onChange) {
    // Group consecutive inline params into flex rows
    const result = [];
    let inlineRun = [];
    const flushInline = () => {
        if (inlineRun.length === 0) return;
        if (inlineRun.length === 1) {
            result.push(inlineRun[0]);
        } else {
            result.push(html`<div class="param-row">${inlineRun}</div>`);
        }
        inlineRun = [];
    };
    for (const p of items) {
        const rendered = renderParam(p, values, onChange, values);
        if (!rendered) continue;
        if (INLINE_TYPES.has(p.type)) {
            inlineRun.push(rendered);
        } else {
            flushInline();
            result.push(rendered);
        }
    }
    flushInline();
    return result;
}

function renderParamList(params, values, onChange) {
    if (!params) return null;
    // Expand groups in place, then run the inline grouping
    const expanded = [];
    for (const p of params) {
        if (p.type === 'group') {
            expanded.push({ _isGroup: true, title: p.title, children: p.children });
        } else {
            expanded.push(p);
        }
    }
    const result = [];
    let inlineRun = [];
    const flushInline = () => {
        if (inlineRun.length === 0) return;
        if (inlineRun.length === 1) result.push(inlineRun[0]);
        else result.push(html`<div class="param-row">${inlineRun}</div>`);
        inlineRun = [];
    };
    for (const p of expanded) {
        if (p._isGroup) {
            flushInline();
            result.push(html`<${PluginGroup} title=${p.title}>
                ${renderParamGroup(p.children, values, onChange)}
            <//>`);
        } else {
            const rendered = renderParam(p, values, onChange, values);
            if (!rendered) continue;
            if (INLINE_TYPES.has(p.type)) inlineRun.push(rendered);
            else { flushInline(); result.push(rendered); }
        }
    }
    flushInline();
    return result;
}

// =======================================================================
// PLUGIN CONFIG PANEL — renders full plugin parameter UI
// =======================================================================
function PluginConfigPanel({ instanceId, paramsSchema, params, onParamChange, inputs, outputs, ccInputs }) {
    return html`<div>
        ${renderParamList(paramsSchema, params, onParamChange)}

        ${inputs && inputs.length > 0 && html`
            <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--surface2)">
                <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:6px">Inputs</div>
                <div style="font-size:12px;color:var(--text)">${inputs.join(', ')}</div>
            </div>
        `}
        ${outputs && outputs.length > 0 && html`
            <div style="margin-top:8px">
                <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:6px">Outputs</div>
                <div style="font-size:12px;color:var(--text)">${outputs.join(', ')}</div>
            </div>
        `}
        ${ccInputs && Object.keys(ccInputs).length > 0 && html`
            <div style="margin-top:8px;font-size:11px;color:var(--text-dim)">
                CC automation: ${Object.entries(ccInputs).map(([cc, param]) => `CC#${cc}\u2192${param}`).join(', ')}
            </div>
        `}
    </div>`;
}

export {
    PluginWheel, PluginFader, PluginRadio, PluginToggle,
    PluginStepEditor, PluginCurveEditor, PluginNoteSelect, PluginChannelSelect,
    PluginGroup, PluginConfigPanel, renderParamList,
    tickFeedback, thudFeedback,
};
