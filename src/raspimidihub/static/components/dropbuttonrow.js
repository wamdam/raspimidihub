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

// Visual tick rate while a clock is running. requestAnimationFrame
// (~16 ms / 60 Hz on most browsers) keeps the dead-reckoned tick
// in sync with the audio to within one frame; setInterval at 50 ms
// added 50 ms of perceived lag on top of network jitter.

const LONG_PRESS_MS = 500;
const MODE_BADGES = { immediately: '', bar: '1', '2bar': '2', '4bar': '4', '8bar': '8', '16bar': '16' };
const MODE_ORDER = ['immediately', 'bar', '2bar', '4bar', '8bar', '16bar'];
const MODE_LABELS = ['Now', 'Bar', '2-Bar', '4-Bar', '8-Bar', '16-Bar'];

const clamp01 = (v) => v < 0 ? 0 : (v > 1 ? 1 : v);

// Dead-reckon the live tick: the server's clock-position SSE arrives
// every quarter (24 ticks) but with network + asyncio + render lag —
// blindly using clockPosition.tick lags audible beats by ~1/16 to
// 1/8 note. We extrapolate forward using the tempo (ms_per_tick)
// computed from the last received interval, so the displayed tick
// matches the audible beat wall-time. Returns null if no clock has
// been seen yet.
//
// Cap the projection at one quarter beat (24 ticks). Real SSE
// arrives every quarter; if the next event hasn't shown up within
// that window, the connection is stalled — better to freeze the
// ring than to extrapolate further and produce wrong-direction
// jumps when the next event finally lands. Without this cap a
// network stall + flush burst (or a tab that briefly backgrounded)
// drove the drop-button rings into a "fills many times per second"
// runaway visible to the user.
const MAX_DEAD_RECKON_TICKS = 24;
function liveTickEstimate(cp) {
    if (!cp || cp.tick == null) return null;
    if (!cp.running) return cp.tick;          // transport stopped — freeze
    if (!cp.ms_per_tick) return cp.tick;      // first event, no tempo yet
    const elapsed = Date.now() - cp.received_at;
    const projected = Math.floor(elapsed / cp.ms_per_tick);
    return cp.tick + Math.min(projected, MAX_DEAD_RECKON_TICKS);
}

export function PluginDropButtonRow({ param, values, onChange, displayCtx }) {
    const count = param.count || 4;
    const states = values[param.states_param] || {};
    const labels = values[param.labels_param] || {};
    const modes = values[param.modes_param] || {};
    const schedule = values[param.schedule_param] || null;
    const playOnly = !!(displayCtx && displayCtx.playOnly);
    const clockPosition = displayCtx && displayCtx.clockPosition;

    // Drive re-renders via requestAnimationFrame so dead-reckoned
    // segment transitions are visible at frame rate (~16 ms / 60 Hz)
    // between SSE events — setInterval at 50 ms added 50 ms of stale
    // display on top of network lag. Only runs while transport is
    // active. Single hook in the parent re-renders all 4 buttons.
    const [, setVisualTick] = useState(0);
    const transportRunning = !!(clockPosition && clockPosition.running);
    useEffect(() => {
        if (playOnly !== true || !transportRunning) return;
        let rafId = 0;
        const loop = () => {
            setVisualTick(t => (t + 1) & 0x7fff);
            rafId = requestAnimationFrame(loop);
        };
        rafId = requestAnimationFrame(loop);
        return () => cancelAnimationFrame(rafId);
    }, [playOnly, transportRunning]);

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
            return html`<${DropButton}
                key=${i}
                index=${i}
                label=${label}
                state=${state}
                mode=${mode}
                schedule=${isScheduled ? schedule : null}
                clockPosition=${clockPosition}
                onChange=${onChange}
                paramName=${param.name} />`;
        })}
    </div>`;
}

// One quarter-width button in the row. Owns its own press / progress
// gesture state; reads display state from props.
function DropButton({ index, label, state, mode, schedule,
                     clockPosition, onChange, paramName }) {
    const isScheduled = !!schedule;
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

    // Compute the ring's progress (0..1) from a SINGLE source — the
    // live tick estimate, dead-reckoned forward from the last
    // clock-position SSE. Driving both idle and scheduled paths from
    // the same tick avoids the visual restart that happened when the
    // scheduled-progress snapshot (taken at set_at_tick) was briefly
    // behind the live tick.
    //
    // Idle:      cycle = (current_bar // n) * n .. that bar boundary.
    // Scheduled: cycle = [schedule.cycle_start_tick, schedule.fire_at_tick).
    // Both reduce to "(tick - cycle_start) / cycle_total" using the
    // dead-reckoned tick.
    const liveTick = liveTickEstimate(clockPosition);
    const transportRunning = !!(clockPosition && clockPosition.running);
    let ringProgress = 0;
    if (transportRunning && liveTick != null) {
        const tpb = clockPosition.ticks_per_bar;
        if (isScheduled && schedule.cycle_start_tick != null) {
            const cycleTotal = (schedule.every_n_bars || 1) * tpb;
            ringProgress = clamp01((liveTick - schedule.cycle_start_tick) / cycleTotal);
        } else if (MODE_SEGMENTS[mode]) {
            const cycleTotal = (MODE_SEGMENTS[mode] * tpb) / 4;
            if (cycleTotal > 0) {
                ringProgress = (liveTick % cycleTotal) / cycleTotal;
            }
        }
    }

    // Beat number for the ring's pulse animation. Changes at every
    // 24-tick boundary; the SegmentedRing re-triggers its CSS
    // pulse animation on each change. Only fed when isScheduled and
    // running — idle ring stays still.
    const beatNumber = (transportRunning && liveTick != null)
        ? Math.floor(liveTick / 24) : 0;

    return html`<div class=${cls} ref=${elRef}>
        <${SegmentedRing} mode=${mode}
            progress=${ringProgress}
            isScheduled=${isScheduled}
            beatNumber=${beatNumber}
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
    '2bar': 8,
    '4bar': 16,
    '8bar': 32,
    '16bar': 64,
};
// Idle (no schedule active) — the ring's just-living-here ambient
// colour. Distinctly more muted than the scheduled state so the
// difference reads as "armed and counting down" vs "just waiting".
const SEGMENT_COLOR_LIT = 'rgba(255,170,90,0.55)';
const SEGMENT_COLOR_DIM = 'rgba(255,170,90,0.10)';
// Active (scheduled) — neon-bright peach. CSS adds a drop-shadow
// glow on `.dropbtn-ring.active` and a beat-aligned pulse animation.
const SEGMENT_COLOR_LIT_ACTIVE = 'rgba(255,220,170,1.00)';
const SEGMENT_COLOR_DIM_ACTIVE = 'rgba(255,170,90,0.22)';

// Discrete segmented ring. N equal arc segments around the button;
// each is fully lit or fully dim. When scheduled the ring uses the
// neon-bright "active" colour and pulses out on every beat (4ths)
// with an exponential decay (sharp peak, slow drop). When idle it
// sits in a more muted colour with no pulse.
//
// `mode`        — segment count (MODE_SEGMENTS[mode]).
// `progress`    — 0..1, cycle-relative.
// `isScheduled` — switches to bright + pulse mode.
// `beatNumber`  — integer, increments on every 24-tick boundary;
//                 used as a React key on the wrapper so the CSS
//                 pulse animation re-triggers cleanly each beat.
function SegmentedRing({ mode, progress, isScheduled, beatNumber, buttonId }) {
    const totalSegs = MODE_SEGMENTS[mode] || 0;
    if (totalSegs === 0) return null;
    const cx = 20, cy = 20, r = 18;
    const stroke = 2.5;
    const gapDeg = totalSegs <= 16 ? 4 : (totalSegs <= 32 ? 2 : 1);
    const segDeg = (360 - totalSegs * gapDeg) / totalSegs;
    const litCount = Math.floor(clamp01(progress) * totalSegs);

    function arcPath(startDeg, sweepDeg) {
        const sa = (startDeg - 90) * Math.PI / 180;
        const ea = (startDeg + sweepDeg - 90) * Math.PI / 180;
        const sx = cx + r * Math.cos(sa);
        const sy = cy + r * Math.sin(sa);
        const ex = cx + r * Math.cos(ea);
        const ey = cy + r * Math.sin(ea);
        const largeArc = sweepDeg > 180 ? 1 : 0;
        return `M ${sx} ${sy} A ${r} ${r} 0 ${largeArc} 1 ${ex} ${ey}`;
    }

    const litColor = isScheduled ? SEGMENT_COLOR_LIT_ACTIVE : SEGMENT_COLOR_LIT;
    const dimColor = isScheduled ? SEGMENT_COLOR_DIM_ACTIVE : SEGMENT_COLOR_DIM;

    const segs = [];
    for (let i = 0; i < totalSegs; i++) {
        const start = i * (segDeg + gapDeg) + gapDeg / 2;
        const isLit = i < litCount;
        segs.push(html`<path key=${i} d=${arcPath(start, segDeg)}
            fill="none" stroke=${isLit ? litColor : dimColor}
            stroke-width=${stroke} stroke-linecap="butt" />`);
    }
    // Re-mount the SVG each beat (key change) so the CSS pulse
    // animation re-runs from frame 0 — "exponential on 1, dropping
    // slowly". When idle, the key is stable; no animation re-runs.
    const wrapperKey = isScheduled ? `${buttonId}-b${beatNumber}` : `${buttonId}-idle`;
    const cls = `dropbtn-ring${isScheduled ? ' active' : ' idle'}`;
    return html`<svg class=${cls} viewBox="0 0 40 40" key=${wrapperKey}>
        ${segs}
    </svg>`;
}
