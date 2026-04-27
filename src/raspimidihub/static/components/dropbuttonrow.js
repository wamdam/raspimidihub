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
const MODE_BADGES = { immediately: '', bar: '1', '4bar': '4' };
const MODE_ORDER = ['immediately', 'bar', '4bar'];
const MODE_LABELS = ['Now', '1 bar', '4 bars'];

export function PluginDropButtonRow({ param, values, onChange, displayCtx }) {
    const count = param.count || 4;
    const states = values[param.states_param] || {};
    const labels = values[param.labels_param] || {};
    const modes = values[param.modes_param] || {};
    const schedule = values[param.schedule_param] || null;
    const playOnly = !!(displayCtx && displayCtx.playOnly);

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
                                labels=${MODE_LABELS}
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
                onChange=${onChange}
                paramName=${param.name} />`;
        })}
    </div>`;
}

// One quarter-width button in the row. Owns its own press / progress
// gesture state; reads display state from props.
function DropButton({ index, label, state, mode, progress, isScheduled,
                     onChange, paramName }) {
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
    //   armed   — has a snapshot loaded (state === 'captured' / 'scheduled' / 'firing')
    //   pressing — finger / mouse down right now (long-press progress bar visible)
    //   scheduled — server says this button is the scheduled one
    //   firing   — brief flash on actual fire
    const armed = state !== 'idle';
    const cls = [
        'dropbtn',
        armed ? 'armed' : '',
        pressing ? 'pressing' : '',
        flashing ? 'flashing' : '',
        isScheduled ? 'scheduled' : '',
        state === 'firing' ? 'firing' : '',
    ].filter(Boolean).join(' ');

    // Mode badge ("1" / "4") in a corner; nothing for immediately mode.
    const modeBadge = MODE_BADGES[mode] || '';

    // SVG ring at 0..1 progress (clockwise from top). Only shown
    // while THIS button is the scheduled one.
    const ringRadius = 18;
    const ringCirc = 2 * Math.PI * ringRadius;
    const ringDashOff = ringCirc * (1 - progress);

    return html`<div class=${cls} ref=${elRef}>
        ${isScheduled ? html`
            <svg class="dropbtn-ring" viewBox="0 0 40 40">
                <circle cx="20" cy="20" r=${ringRadius}
                    fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round"
                    stroke-dasharray=${ringCirc}
                    stroke-dashoffset=${ringDashOff}
                    transform="rotate(-90 20 20)" />
            </svg>` : null}
        <span class="dropbtn-label">${label}</span>
        ${modeBadge ? html`<span class="dropbtn-mode">${modeBadge}</span>` : null}
        ${pressing ? html`
            <div class="dropbtn-pressbar"
                style="width: ${pressProgress * 100}%"></div>` : null}
    </div>`;
}
