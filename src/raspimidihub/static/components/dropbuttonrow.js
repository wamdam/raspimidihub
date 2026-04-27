/**
 * DropButtonRow plugin control — row of N quarter-width snapshot
 * buttons with per-button mode (immediately / bar / 4bar).
 *
 * Each button:
 *   • short-press → fire (sends {action: 'fire', button_id})
 *       Server resolves: immediately mode = fire now; bar/4bar mode
 *       = schedule, fire on the next bar boundary.
 *   • long-press (≥500 ms with progress ring) → capture
 *       (sends {action: 'capture', button_id})
 *   • short-press while THIS button is scheduled → cancel
 *       (server treats a fire on a scheduled button as a cancel)
 *   • only one button on the row can be `scheduled` at a time.
 *
 * Auxiliary state lives in sibling params on the plugin instance:
 *   • drop_states[id]    : 'idle'|'captured'|'scheduled'|'firing'
 *   • drop_labels[id]    : display name (default A/B/C/D)
 *   • drop_modes[id]     : 'immediately'|'bar'|'4bar'
 *   • drop_schedule      : {button_id, set_at_tick, fire_at_tick,
 *                           progress: 0..1} or null
 *
 * The schema param exposes the names of those siblings so this
 * component can resolve them generically.
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html, tickFeedback, thudFeedback } from './common.js';
import { PluginWheel } from './wheel.js';

const LONG_PRESS_MS = 500;
const MODE_BADGES = { immediately: '', bar: '1', '4bar': '4', '8bar': '8', '16bar': '16' };
const MODE_ORDER = ['immediately', 'bar', '4bar', '8bar', '16bar'];
const MODE_LABELS = ['Now', 'Bar', '4-Bar', '8-Bar', '16-Bar'];

export function PluginDropButtonRow({ param, values, onChange, displayCtx }) {
    const count = param.count || 4;
    const states = values[param.states_param] || {};
    const labels = values[param.labels_param] || {};
    const modes = values[param.modes_param] || {};
    const schedule = values[param.schedule_param] || null;
    const playOnly = !!(displayCtx && displayCtx.playOnly);
    const clockPosition = displayCtx && displayCtx.clockPosition;

    // Config branch — one card per button with a name input + mode
    // wheel + capture / clear hint. Lives in the device-detail panel
    // (Routing tab → tap the controller).
    if (!playOnly) {
        return html`<div class="droprow-config">
            ${Array.from({ length: count }, (_, i) => {
                const sid = String(i);
                const label = labels[sid] || String.fromCharCode(65 + i);
                const mode = modes[sid] || 'immediately';
                const stateText = states[sid] === 'captured' ? 'Loaded' :
                                  states[sid] === 'scheduled' ? 'Scheduled' :
                                  states[sid] === 'firing' ? 'Firing' : 'Empty';
                const setLabel = (v) => {
                    onChange(param.labels_param, { ...labels, [sid]: v });
                };
                const setMode = (_n, idx) => {
                    onChange(param.modes_param,
                        { ...modes, [sid]: MODE_ORDER[idx] || 'immediately' });
                };
                const clearSnapshot = () => {
                    const snaps = values[param.snapshots_param] || {};
                    const next = { ...snaps };
                    delete next[sid];
                    onChange(param.snapshots_param, next);
                };
                return html`<div class="dropbtn-edit ${states[sid] === 'captured' ? 'loaded' : ''}" key=${i}>
                    <div class="dropbtn-edit-row">
                        <span class="dropbtn-edit-tag">Drop ${i + 1}</span>
                        <input class="dropbtn-edit-name" type="text"
                            value=${label === String.fromCharCode(65 + i) ? '' : label}
                            placeholder=${String.fromCharCode(65 + i)}
                            onInput=${(e) => setLabel(e.target.value)} />
                        <span class="dropbtn-edit-state">${stateText}</span>
                    </div>
                    <div class="dropbtn-edit-row">
                        <span class="dropbtn-edit-fieldlabel">Fire</span>
                        <div class="dropbtn-edit-wheel">
                            <${PluginWheel}
                                name=${'mode_' + sid}
                                label=""
                                min=${0} max=${MODE_ORDER.length - 1}
                                value=${Math.max(0, MODE_ORDER.indexOf(mode))}
                                tickLabel=${(i) => MODE_LABELS[i] || String(i)}
                                onChange=${setMode} />
                        </div>
                        ${states[sid] === 'captured' ? html`
                            <button type="button" class="dropbtn-edit-clear"
                                title="Clear this button's snapshot"
                                onclick=${clearSnapshot}>Clear</button>` : null}
                    </div>
                </div>`;
            })}
        </div>`;
    }

    // Play branch — the row of 4 quarter-width buttons.
    return html`<div class="droprow">
        ${Array.from({ length: count }, (_, i) => {
            const sid = String(i);
            const state = states[sid] || 'idle';
            const label = labels[sid] || String.fromCharCode(65 + i);
            const mode = modes[sid] || 'immediately';
            const isScheduled = schedule && Number(schedule.button_id) === i;
            const progress = isScheduled ? Number(schedule.progress || 0) : 0;
            return html`<${DropButton}
                key=${i}
                index=${i}
                label=${label}
                state=${state}
                mode=${mode}
                progress=${progress}
                isScheduled=${isScheduled}
                clockPosition=${clockPosition}
                onChange=${onChange}
                paramName=${param.name} />`;
        })}
    </div>`;
}

// One quarter-width button in the row. Owns its own press / progress
// gesture state; reads display state from props.
function DropButton({ index, label, state, mode, progress, isScheduled,
                     clockPosition, onChange, paramName }) {
    const elRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;

    const [pressing, setPressing] = useState(false);
    const [pressProgress, setPressProgress] = useState(0); // 0..1 (long-press)
    const [flashing, setFlashing] = useState(false);
    const flashTimer = useRef(null);
    const ps = useRef({
        startTs: 0, longFired: false, rafId: null, activeTouchId: null,
    });

    function triggerFlash() {
        setFlashing(true);
        if (flashTimer.current) clearTimeout(flashTimer.current);
        flashTimer.current = setTimeout(() => setFlashing(false), 200);
    }
    useEffect(() => () => {
        if (flashTimer.current) clearTimeout(flashTimer.current);
    }, []);

    useEffect(() => {
        const el = elRef.current;
        if (!el) return;
        const s = ps.current;

        function tick() {
            const elapsed = Date.now() - s.startTs;
            const p = Math.min(1, elapsed / LONG_PRESS_MS);
            setPressProgress(p);
            if (p >= 1 && !s.longFired) {
                s.longFired = true;
                thudFeedback();
                onChangeRef.current(paramName,
                    { action: 'capture', button_id: index });
                triggerFlash();
            }
            if (elapsed < LONG_PRESS_MS * 1.2 && s.startTs > 0) {
                s.rafId = requestAnimationFrame(tick);
            }
        }
        function startPress() {
            s.startTs = Date.now();
            s.longFired = false;
            setPressing(true);
            setPressProgress(0);
            tickFeedback();
            tick();
        }
        function endPress() {
            const elapsed = Date.now() - s.startTs;
            s.startTs = 0;
            if (s.rafId) { cancelAnimationFrame(s.rafId); s.rafId = null; }
            setPressing(false);
            setPressProgress(0);
            if (!s.longFired && elapsed < LONG_PRESS_MS) {
                onChangeRef.current(paramName,
                    { action: 'fire', button_id: index });
                triggerFlash();
            }
            s.longFired = false;
        }

        function onTouchStart(e) {
            e.preventDefault(); e.stopPropagation();
            const t = e.changedTouches[0];
            s.activeTouchId = t.identifier;
            startPress();
            window.addEventListener('touchend', onTouchEnd);
            window.addEventListener('touchcancel', onTouchEnd);
        }
        function onTouchEnd(e) {
            for (const t of e.changedTouches) {
                if (t.identifier === s.activeTouchId) {
                    s.activeTouchId = null;
                    window.removeEventListener('touchend', onTouchEnd);
                    window.removeEventListener('touchcancel', onTouchEnd);
                    endPress();
                    break;
                }
            }
        }
        function onMouseDown(e) {
            e.preventDefault();
            startPress();
            const mu = () => { window.removeEventListener('mouseup', mu); endPress(); };
            window.addEventListener('mouseup', mu);
        }

        el.addEventListener('touchstart', onTouchStart, { passive: false });
        el.addEventListener('mousedown', onMouseDown);
        return () => {
            el.removeEventListener('touchstart', onTouchStart);
            el.removeEventListener('mousedown', onMouseDown);
            if (s.rafId) cancelAnimationFrame(s.rafId);
        };
    }, [index, paramName]);

    // Visual classes:
    //   armed     — snapshot loaded (state in 'captured'|'scheduled'|'firing')
    //   pressing  — finger/mouse down right now (long-press in flight)
    //   scheduled — server says this button is the scheduled one
    //   firing    — brief flash on actual fire
    const armed = state !== 'idle';
    const cls = [
        'dropbtn',
        armed ? 'armed' : '',
        pressing ? 'pressing' : '',
        flashing ? 'flashing' : '',
        isScheduled ? 'scheduled' : '',
        state === 'firing' ? 'firing' : '',
    ].filter(Boolean).join(' ');

    // Mode badge ("1"/"4"/"8"/"16") in a corner; blank for immediately.
    const modeBadge = MODE_BADGES[mode] || '';

    // Compute the ring's progress (0..1) — three sources:
    //   isScheduled  → server's cycle-relative progress (filling toward fire)
    //   clockPosition → live music position within this button's mode cycle
    //                   (always running while a master clock is up, so the
    //                   ring is never frozen at "0" pre-press)
    //   neither      → 0 (no clock running)
    // Both compute the same thing visually when in the same cycle —
    // pressing to schedule is a no-op for the ring's lit count if you
    // press exactly on a grid boundary.
    let ringProgress = 0;
    if (isScheduled) {
        ringProgress = progress;
    } else if (clockPosition && MODE_SEGMENTS[mode]) {
        const cycleTotalTicks = MODE_SEGMENTS[mode] * (clockPosition.ticks_per_bar / 4);
        if (cycleTotalTicks > 0) {
            ringProgress = (clockPosition.tick % cycleTotalTicks) / cycleTotalTicks;
        }
    }

    return html`<div class=${cls} ref=${elRef}>
        <${SegmentedRing} mode=${mode}
            progress=${ringProgress}
            lit=${ringProgress > 0 || isScheduled}
            buttonId=${index} />
        ${pressing ? html`
            <div class="dropbtn-pressfill"
                style="height: ${pressProgress * 100}%"></div>` : null}
        <span class="dropbtn-label">${label}</span>
        ${modeBadge ? html`<span class="dropbtn-mode">${modeBadge}</span>` : null}
    </div>`;
}

// Segments-per-mode: 4 quarter-notes per bar × bars in the cycle.
// `immediately` mode shows no ring at all. The configured mode's
// segment count is used even when nothing is scheduled, so the ring
// shape always reads as "this is a 1-bar / 4-bar / … button".
const MODE_SEGMENTS = {
    immediately: 0,
    bar: 4,
    '4bar': 16,
    '8bar': 32,
    '16bar': 64,
};
const SEGMENT_COLOR_LIT = 'rgba(255,200,140,0.95)';
const SEGMENT_COLOR_DIM = 'rgba(255,170,90,0.20)';

// Discrete segmented ring: N equal arc segments around the button.
// Each is fully lit or fully dim; nothing is partially filled. So
// pressing exactly on beat 2 of a 1-bar button lights segment 1
// immediately (1 quarter has elapsed in the cycle), rather than
// showing a fractional fill that confuses the eye.
//
// `mode`     — the button's configured mode (segment count = MODE_SEGMENTS[mode]).
// `progress` — 0..1, cycle-relative; only meaningful when scheduled.
// `lit`      — overall: are any segments currently in the bright state?
function SegmentedRing({ mode, progress, lit, buttonId }) {
    const totalSegs = MODE_SEGMENTS[mode] || 0;
    if (totalSegs === 0) return null;
    const cx = 20, cy = 20, r = 18;
    const stroke = 2.5;
    // Gap visible but proportionally smaller for higher segment counts
    // (otherwise the ring becomes mostly gap at 64 segments).
    const gapDeg = totalSegs <= 16 ? 4 : (totalSegs <= 32 ? 2 : 1);
    const segDeg = (360 - totalSegs * gapDeg) / totalSegs;
    const litCount = lit ? Math.floor(progress * totalSegs) : 0;

    function arcPath(startDeg, sweepDeg) {
        // -90 makes 0° = 12 o'clock; clockwise sweep.
        const sa = (startDeg - 90) * Math.PI / 180;
        const ea = (startDeg + sweepDeg - 90) * Math.PI / 180;
        const sx = cx + r * Math.cos(sa);
        const sy = cy + r * Math.sin(sa);
        const ex = cx + r * Math.cos(ea);
        const ey = cy + r * Math.sin(ea);
        const largeArc = sweepDeg > 180 ? 1 : 0;
        return `M ${sx} ${sy} A ${r} ${r} 0 ${largeArc} 1 ${ex} ${ey}`;
    }

    const segs = [];
    for (let i = 0; i < totalSegs; i++) {
        const start = i * (segDeg + gapDeg) + gapDeg / 2;
        const isLit = i < litCount;
        segs.push(html`<path key=${i} d=${arcPath(start, segDeg)}
            fill="none" stroke=${isLit ? SEGMENT_COLOR_LIT : SEGMENT_COLOR_DIM}
            stroke-width=${stroke} stroke-linecap="butt" />`);
    }
    return html`<svg class="dropbtn-ring" viewBox="0 0 40 40">${segs}</svg>`;
}
