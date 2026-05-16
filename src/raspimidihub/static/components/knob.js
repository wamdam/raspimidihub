/**
 * Knob plugin control — round body, rotating indicator, LED arc.
 *
 * The LED arc covers the same 270° arc the knob can travel
 * (-135°..+135°, with 0° = straight up). LEDs are lit up to the
 * current value's angle. Drag vertically to change the value
 * (up = increase) — same gesture as the Wheel, so muscle memory
 * carries over.
 */

import { html, tickFeedback, thudFeedback, makeLongPress } from './common.js';
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
    displayFactor, unit, labels, onBindRequest,
}) {
    const containerRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    const onBindRef = useRef(onBindRequest);
    onBindRef.current = onBindRequest;
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
        // Long-press → open the CC binding popup. If the user keeps
        // their finger still for 500 ms the timer fires, the popup
        // opens, and the in-flight drag is aborted (move handlers
        // exit early via lp.moveDidFire).
        const lp = makeLongPress(() => {
            if (onBindRef.current) onBindRef.current(name);
        });

        function applyMove(clientY) {
            const dy = s.startY - clientY;        // up = positive
            const delta = Math.round(dy / ppu);
            setVal_(s.startVal + delta);
        }

        // --- Touch path: track the gesture's own touch identifier so
        // two-finger drags on two knobs don't cross-track on e.touches[0].
        let activeTouchId = null;
        function findTouch(e, id) {
            for (const t of e.touches) if (t.identifier === id) return t;
            return null;
        }
        function onTouchStart(e) {
            e.preventDefault();
            e.stopPropagation();
            const t = e.changedTouches[0];
            activeTouchId = t.identifier;
            s.startY = t.clientY;
            s.startVal = s.val;
            lp.start(t.clientX, t.clientY);
            el.addEventListener('touchmove', onTouchMove, { passive: false });
            window.addEventListener('touchend', onTouchEnd);
            window.addEventListener('touchcancel', onTouchEnd);
        }
        function onTouchMove(e) {
            e.preventDefault();
            e.stopPropagation();
            const t = findTouch(e, activeTouchId);
            if (!t) return;
            if (lp.moveDidFire(t.clientX, t.clientY)) return;
            applyMove(t.clientY);
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
                    break;
                }
            }
        }

        // --- Mouse path: separate from touch (no multitouch concerns).
        function onMouseDown(e) {
            if (e.button === 2) return;  // right-click handled by onContextMenu
            e.preventDefault();
            s.startY = e.clientY;
            s.startVal = s.val;
            lp.start(e.clientX, e.clientY);
            const mm = (ev) => {
                if (lp.moveDidFire(ev.clientX, ev.clientY)) {
                    window.removeEventListener('mousemove', mm);
                    window.removeEventListener('mouseup', mu);
                    return;
                }
                applyMove(ev.clientY);
            };
            const mu = () => {
                lp.end();
                window.removeEventListener('mousemove', mm);
                window.removeEventListener('mouseup', mu);
            };
            window.addEventListener('mousemove', mm);
            window.addEventListener('mouseup', mu);
        }

        function onContextMenu(e) {
            e.preventDefault();
            if (onBindRef.current) onBindRef.current(name);
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

        el.addEventListener('touchstart', onTouchStart, { passive: false });
        el.addEventListener('mousedown', onMouseDown);
        el.addEventListener('contextmenu', onContextMenu);
        el.addEventListener('wheel', onWheel, { passive: false });
        el.addEventListener('dblclick', onDblClick);
        return () => {
            el.removeEventListener('touchstart', onTouchStart);
            el.removeEventListener('mousedown', onMouseDown);
            el.removeEventListener('contextmenu', onContextMenu);
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
        leds.push(html`<circle cx=${lx} cy=${ly} r="2" fill=${lit ? 'var(--accent)' : 'var(--border)'}
            style=${lit ? 'filter: drop-shadow(0 0 3px var(--knob-led-glow))' : ''} />`);
    }

    return html`<div class="knob-group">
        <span class="knob-label">${label}</span>
        <div class="knob-container" ref=${containerRef}>
            <svg viewBox="-36 -36 72 72" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <radialGradient id="knob-body" cx="0.35" cy="0.30" r="0.85">
                        <stop offset="0%"   style="stop-color: var(--knob-body-1)" />
                        <stop offset="40%"  style="stop-color: var(--knob-body-2)" />
                        <stop offset="100%" style="stop-color: var(--knob-body-3)" />
                    </radialGradient>
                </defs>
                ${leds}
                <circle cx="0" cy="0" r=${KNOB_RADIUS} fill="url(#knob-body)"
                    stroke="var(--knob-rim-shadow)" stroke-width="1" />
                <line x1=${indX} y1=${indY} x2=${indEndX} y2=${indEndY}
                    stroke="var(--knob-indicator)" stroke-width="2.2" stroke-linecap="round"
                    style="filter: drop-shadow(0 0 2px rgba(255, 255, 255, 0.4))" />
            </svg>
            <div class="knob-value">${formatValue(val, displayFactor, unit, labels, min)}</div>
        </div>
    </div>`;
}
