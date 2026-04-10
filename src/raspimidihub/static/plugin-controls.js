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

// =======================================================================
// WHEEL — scrollable drum wheel with momentum
// =======================================================================
function PluginWheel({ name, label, min, max, value, onChange, suffix }) {
    const containerRef = useRef(null);
    const innerRef = useRef(null);
    const stateRef = useRef({ value, velocity: 0, dragging: false, startY: 0, startVal: 0, animId: null });
    const TICK_H = 20;
    const range = max - min;

    useEffect(() => { stateRef.current.value = value; }, [value]);

    const renderTicks = useCallback(() => {
        const el = innerRef.current;
        if (!el) return;
        const v = stateRef.current.value;
        const centerOffset = 30; // container height/2
        el.style.transform = `translateY(${centerOffset - (v - min) * TICK_H}px)`;
        const children = el.children;
        for (let i = 0; i < children.length; i++) {
            const tickVal = min + i;
            const dist = Math.abs(tickVal - v);
            children[i].className = 'wheel-tick' + (dist === 0 ? ' active' : dist === 1 ? ' near' : '');
        }
    }, [min]);

    useEffect(() => {
        renderTicks();
    }, [value, renderTicks]);

    const clamp = (v) => Math.max(min, Math.min(max, Math.round(v)));

    const startDrag = (clientY) => {
        const s = stateRef.current;
        s.dragging = true;
        s.startY = clientY;
        s.lastY = clientY;
        s.startVal = s.value;
        s.velocity = 0;
        if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; }
    };

    const moveDrag = (clientY) => {
        const s = stateRef.current;
        if (!s.dragging) return;
        const dy = s.startY - clientY;
        const newVal = clamp(s.startVal + dy / (TICK_H * 0.8));
        if (newVal !== s.value) {
            const hitBound = (newVal === min || newVal === max) && s.value !== newVal;
            // Track velocity from last position, clamped to avoid wild spins
            const instantVel = (s.lastY - clientY) / (TICK_H * 0.8);
            s.velocity = Math.max(-3, Math.min(3, instantVel));
            s.lastY = clientY;
            s.value = newVal;
            renderTicks();
            onChange(name, newVal);
            if (hitBound) thudFeedback(); else tickFeedback();
        }
    };

    const endDrag = () => {
        const s = stateRef.current;
        s.dragging = false;
        // Momentum — only on touch, skip for mouse (too erratic)
        if (!s.isTouch) { s.velocity = 0; return; }
        const coast = () => {
            if (Math.abs(s.velocity) < 0.3) { s.animId = null; return; }
            s.velocity *= 0.92;
            const newVal = clamp(s.value + s.velocity);
            if (newVal !== s.value) {
                if (newVal === min || newVal === max) { thudFeedback(); s.velocity = 0; }
                else tickFeedback();
                s.value = newVal;
                renderTicks();
                onChange(name, newVal);
            } else { s.velocity = 0; }
            s.animId = requestAnimationFrame(coast);
        };
        if (Math.abs(s.velocity) > 0.5) s.animId = requestAnimationFrame(coast);
    };

    // Scroll wheel: throttled to avoid racing through values
    const onWheel = (e) => {
        e.preventDefault();
        const s = stateRef.current;
        const now = Date.now();
        if (now - (s.lastWheel || 0) < 80) return;
        s.lastWheel = now;
        if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; }
        const delta = e.deltaY > 0 ? -1 : 1;
        const newVal = clamp(s.value + delta);
        if (newVal !== s.value) {
            const hitBound = (newVal === min || newVal === max);
            s.value = newVal;
            renderTicks();
            onChange(name, newVal);
            if (hitBound) thudFeedback(); else tickFeedback();
        }
    };

    const onTouchStart = (e) => { e.preventDefault(); stateRef.current.isTouch = true; startDrag(e.touches[0].clientY); };
    const onTouchMove = (e) => { e.preventDefault(); moveDrag(e.touches[0].clientY); };
    const onTouchEnd = () => endDrag();
    const onMouseDown = (e) => { e.preventDefault(); stateRef.current.isTouch = false; startDrag(e.clientY);
        const mm = (ev) => { ev.preventDefault(); moveDrag(ev.clientY); };
        const mu = () => { endDrag(); window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu); };
        window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu);
    };

    const ticks = [];
    for (let i = min; i <= max; i++) {
        ticks.push(html`<div class="wheel-tick" key=${i}>${suffix ? i + suffix : i}</div>`);
    }

    return html`<div class="wheel-group">
        <span class="wheel-label">${label}</span>
        <div class="wheel-container" ref=${containerRef}
            onTouchStart=${onTouchStart} onTouchMove=${onTouchMove} onTouchEnd=${onTouchEnd}
            onMouseDown=${onMouseDown} onWheel=${onWheel}>
            <div class="wheel-inner" ref=${innerRef}>${ticks}</div>
        </div>
        <span class="wheel-value">${value}${suffix || ''}</span>
    </div>`;
}

// =======================================================================
// FADER — mixer-strip style
// =======================================================================
function PluginFader({ name, label, min, max, value, onChange, vertical, suffix }) {
    const trackRef = useRef(null);
    const [val, setVal] = useState(value);
    const lastVal = useRef(value);

    useEffect(() => { setVal(value); lastVal.current = value; }, [value]);

    const calcValue = (clientX, clientY) => {
        const rect = trackRef.current.getBoundingClientRect();
        let ratio;
        if (vertical) {
            ratio = 1 - (clientY - rect.top) / rect.height;
        } else {
            ratio = (clientX - rect.left) / rect.width;
        }
        ratio = Math.max(0, Math.min(1, ratio));
        return Math.round(min + ratio * (max - min));
    };

    const handleMove = (clientX, clientY) => {
        const newVal = calcValue(clientX, clientY);
        if (newVal !== lastVal.current) {
            lastVal.current = newVal;
            setVal(newVal);
            onChange(name, newVal);
            tickFeedback();
        }
    };

    const onTouchStart = (e) => { e.preventDefault(); handleMove(e.touches[0].clientX, e.touches[0].clientY); };
    const onTouchMove = (e) => { e.preventDefault(); handleMove(e.touches[0].clientX, e.touches[0].clientY); };
    const onMouseDown = (e) => {
        e.preventDefault(); handleMove(e.clientX, e.clientY);
        const mm = (ev) => handleMove(ev.clientX, ev.clientY);
        const mu = () => { window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu); };
        window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu);
    };

    const ratio = (val - min) / (max - min || 1);
    const thumbStyle = vertical
        ? { bottom: `${ratio * 100}%`, transform: 'translateY(50%)' }
        : { left: `${ratio * 100}%`, transform: 'translateX(-50%)' };
    const fillStyle = vertical
        ? { height: `${ratio * 100}%` }
        : { width: `${ratio * 100}%` };

    return html`<div class="fader-group ${vertical ? 'vertical' : ''}">
        <span class="fader-label">${label}</span>
        <div class="fader-track ${vertical ? 'vertical' : ''}" ref=${trackRef}
            onTouchStart=${onTouchStart} onTouchMove=${onTouchMove}
            onMouseDown=${onMouseDown}>
            <div class="fader-fill" style=${fillStyle}></div>
            <div class="fader-thumb" style=${thumbStyle}></div>
        </div>
        <span class="fader-value">${val}${suffix || ''}</span>
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
        <div class="metal-toggle ${value ? 'on' : ''}" onclick=${toggle}>
            <div class="slot"></div>
            <div class="indicator off-dot"></div>
            <div class="indicator on-dot"></div>
        </div>
        <span class="toggle-state ${value ? 'on' : 'off'}">${value ? 'On' : 'Off'}</span>
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
// NOTE SELECT — wheel with note names
// =======================================================================
function PluginNoteSelect({ name, label, value, onChange }) {
    // Wrap PluginWheel with note name display
    const containerRef = useRef(null);
    const innerRef = useRef(null);
    const stateRef = useRef({ value, velocity: 0, dragging: false, startY: 0, startVal: 0, animId: null });
    const TICK_H = 20;

    useEffect(() => { stateRef.current.value = value; renderTicks(); }, [value]);

    const renderTicks = () => {
        const el = innerRef.current;
        if (!el) return;
        const v = stateRef.current.value;
        el.style.transform = `translateY(${30 - v * TICK_H}px)`;
        for (let i = 0; i < el.children.length; i++) {
            const dist = Math.abs(i - v);
            el.children[i].className = 'wheel-tick' + (dist === 0 ? ' active' : dist === 1 ? ' near' : '');
        }
    };

    const clamp = (v) => Math.max(0, Math.min(127, Math.round(v)));

    const startDrag = (clientY) => {
        const s = stateRef.current;
        s.dragging = true; s.startY = clientY; s.lastY = clientY; s.startVal = s.value; s.velocity = 0;
        if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; }
    };
    const moveDrag = (clientY) => {
        const s = stateRef.current;
        if (!s.dragging) return;
        const dy = s.startY - clientY;
        const newVal = clamp(s.startVal + dy / (TICK_H * 0.8));
        if (newVal !== s.value) {
            const hitBound = (newVal === 0 || newVal === 127) && s.value !== newVal;
            const instantVel = (s.lastY - clientY) / (TICK_H * 0.8);
            s.velocity = Math.max(-3, Math.min(3, instantVel));
            s.lastY = clientY;
            s.value = newVal;
            renderTicks();
            onChange(name, newVal);
            if (hitBound) thudFeedback(); else tickFeedback();
        }
    };
    const endDrag = () => {
        const s = stateRef.current;
        s.dragging = false;
        if (!s.isTouch) { s.velocity = 0; return; }
        const coast = () => {
            if (Math.abs(s.velocity) < 0.3) return;
            s.velocity *= 0.92;
            const nv = clamp(s.value + s.velocity);
            if (nv !== s.value) {
                if (nv === 0 || nv === 127) { thudFeedback(); s.velocity = 0; }
                else tickFeedback();
                s.value = nv; renderTicks(); onChange(name, nv);
            } else s.velocity = 0;
            s.animId = requestAnimationFrame(coast);
        };
        if (Math.abs(s.velocity) > 0.5) s.animId = requestAnimationFrame(coast);
    };

    const onWheel = (e) => {
        e.preventDefault();
        const s = stateRef.current;
        const now = Date.now();
        if (now - (s.lastWheel || 0) < 80) return;
        s.lastWheel = now;
        if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; }
        const delta = e.deltaY > 0 ? -1 : 1;
        const nv = clamp(s.value + delta);
        if (nv !== s.value) {
            s.value = nv; renderTicks(); onChange(name, nv);
            (nv === 0 || nv === 127) ? thudFeedback() : tickFeedback();
        }
    };

    const onTouchStart = (e) => { e.preventDefault(); stateRef.current.isTouch = true; startDrag(e.touches[0].clientY); };
    const onTouchMove = (e) => { e.preventDefault(); moveDrag(e.touches[0].clientY); };
    const onMouseDown = (e) => { e.preventDefault(); stateRef.current.isTouch = false; startDrag(e.clientY);
        const mm = (ev) => { ev.preventDefault(); moveDrag(ev.clientY); };
        const mu = () => { endDrag(); window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu); };
        window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu);
    };

    const ticks = [];
    for (let i = 0; i <= 127; i++) ticks.push(html`<div class="wheel-tick" key=${i}>${noteName(i)}</div>`);

    return html`<div class="wheel-group">
        <span class="wheel-label">${label}</span>
        <div class="wheel-container" ref=${containerRef}
            onTouchStart=${onTouchStart} onTouchMove=${onTouchMove} onTouchEnd=${() => endDrag()}
            onMouseDown=${onMouseDown} onWheel=${onWheel}>
            <div class="wheel-inner" ref=${innerRef}>${ticks}</div>
        </div>
        <span class="wheel-value">${noteName(value)}</span>
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

function renderParamList(params, values, onChange) {
    if (!params) return null;
    return params.map(p => {
        if (p.type === 'group') {
            return html`<${PluginGroup} title=${p.title}>
                ${p.children.map(child => renderParam(child, values, onChange, values))}
            <//>`;
        }
        return renderParam(p, values, onChange, values);
    });
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
