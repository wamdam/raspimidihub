/**
 * Knob plugin control — round body, rotating indicator, LED arc.
 *
 * The LED arc covers the same 270° arc the knob can travel
 * (-135°..+135°, with 0° = straight up). LEDs are lit up to the
 * current value's angle. Drag vertically to change the value
 * (up = increase) — same gesture as the Wheel, so muscle memory
 * carries over.
 */

import { html, tickFeedback, thudFeedback } from './common.js';
import { useState, useEffect, useRef } from '../lib/hooks.module.js';

const N_LEDS = 13;
const ANGLE_MIN = -135;
const ANGLE_MAX = 135;
const RING_RADIUS = 28;
const KNOB_RADIUS = 20;

// Vertical drag distance per value step. We want a roughly constant
// total-travel feel regardless of range size — about a third of a screen
// (~280 px) from min to max — so a 4-value knob has clear steps and a
// 0..127 knob isn't ridiculous to drag through. Floor at 3 px so the
// finest knob still has reasonable response.
function pixelsPerUnit(min, max) {
    const range = Math.max(1, max - min);
    return Math.max(3, 280 / range);
}

function valueToAngle(v, min, max) {
    const r = (v - min) / (max - min || 1);
    return ANGLE_MIN + r * (ANGLE_MAX - ANGLE_MIN);
}

function angleToXY(angleDeg, radius) {
    // 0° points up (-Y), positive angles rotate clockwise.
    const a = (angleDeg - 90) * Math.PI / 180;
    return [Math.cos(a) * radius, Math.sin(a) * radius];
}

function formatValue(v, displayFactor, unit, labels, min) {
    if (labels && labels.length) return labels[v - (min || 0)] ?? v;
    if (displayFactor) {
        const scaled = v * displayFactor;
        const txt = (scaled % 1 === 0) ? `${scaled}` : scaled.toFixed(1);
        return `${txt}${unit || ''}`;
    }
    return `${v}${unit || ''}`;
}

export function PluginKnob({
    name, label, min, max, value, onChange,
    displayFactor, unit, labels,
}) {
    const containerRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    const s = useRef({ val: value, startY: 0, startVal: 0, animId: null }).current;
    const [val, setVal] = useState(value);

    useEffect(() => { s.val = value; setVal(value); }, [value]);

    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;
        const oc = onChangeRef;

        function setVal_(nv) {
            const clamped = Math.max(min, Math.min(max, nv));
            if (clamped !== s.val) {
                if (clamped === min || clamped === max) thudFeedback();
                else tickFeedback();
                s.val = clamped;
                setVal(clamped);
                oc.current(name, clamped);
            }
        }

        const ppu = pixelsPerUnit(min, max);
        function onMove(e) {
            e.preventDefault();
            if (e.touches) e.stopPropagation();
            const pt = e.touches ? e.touches[0] : e;
            const dy = s.startY - pt.clientY;     // up = positive
            const delta = Math.round(dy / ppu);
            setVal_(s.startVal + delta);
        }

        function onEnd() {
            el.removeEventListener('touchmove', onMove);
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('touchend', onEnd);
            window.removeEventListener('mouseup', onEnd);
        }

        function onStart(e) {
            e.preventDefault();
            e.stopPropagation();
            const pt = e.touches ? e.touches[0] : e;
            s.startY = pt.clientY;
            s.startVal = s.val;
            el.addEventListener('touchmove', onMove, { passive: false });
            window.addEventListener('mousemove', onMove);
            window.addEventListener('touchend', onEnd);
            window.addEventListener('mouseup', onEnd);
        }

        function onWheel(e) {
            e.preventDefault();
            const delta = e.deltaY > 0 ? -1 : 1;
            setVal_(s.val + delta);
        }

        function onDblClick(e) {
            e.preventDefault();
            // Double-click resets to the midpoint of the range.
            setVal_(Math.round((min + max) / 2));
        }

        el.addEventListener('touchstart', onStart, { passive: false });
        el.addEventListener('mousedown', onStart);
        el.addEventListener('wheel', onWheel, { passive: false });
        el.addEventListener('dblclick', onDblClick);
        return () => {
            el.removeEventListener('touchstart', onStart);
            el.removeEventListener('mousedown', onStart);
            el.removeEventListener('wheel', onWheel);
            el.removeEventListener('dblclick', onDblClick);
        };
    }, [min, max, name]);

    const angle = valueToAngle(val, min, max);
    const valRatio = (val - min) / (max - min || 1);
    const litThreshold = ANGLE_MIN + valRatio * (ANGLE_MAX - ANGLE_MIN);
    const [indX, indY] = angleToXY(angle, KNOB_RADIUS - 4);
    const [indEndX, indEndY] = angleToXY(angle, KNOB_RADIUS - 12);

    const leds = [];
    for (let i = 0; i < N_LEDS; i++) {
        const t = i / (N_LEDS - 1);
        const a = ANGLE_MIN + t * (ANGLE_MAX - ANGLE_MIN);
        const [lx, ly] = angleToXY(a, RING_RADIUS);
        const lit = a <= litThreshold + 0.5;
        leds.push(html`<circle cx=${lx} cy=${ly} r="2" fill=${lit ? 'var(--accent)' : 'rgba(255,255,255,0.12)'}
            style=${lit ? 'filter: drop-shadow(0 0 3px var(--accent))' : ''} />`);
    }

    return html`<div class="knob-group">
        <span class="knob-label">${label}</span>
        <div class="knob-container" ref=${containerRef}>
            <svg viewBox="-36 -36 72 72" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <radialGradient id="knob-body" cx="0.35" cy="0.30" r="0.85">
                        <stop offset="0%" stop-color="#5a5a6a" />
                        <stop offset="40%" stop-color="#3a3a48" />
                        <stop offset="100%" stop-color="#1a1a26" />
                    </radialGradient>
                </defs>
                ${leds}
                <circle cx="0" cy="0" r=${KNOB_RADIUS} fill="url(#knob-body)"
                    stroke="rgba(0,0,0,0.6)" stroke-width="1" />
                <line x1=${indX} y1=${indY} x2=${indEndX} y2=${indEndY}
                    stroke="#fff" stroke-width="2.2" stroke-linecap="round"
                    style="filter: drop-shadow(0 0 2px rgba(255,255,255,0.4))" />
            </svg>
            <div class="knob-value">${formatValue(val, displayFactor, unit, labels, min)}</div>
        </div>
    </div>`;
}
