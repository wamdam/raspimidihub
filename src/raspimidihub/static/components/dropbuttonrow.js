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

    // Two distinct progress visuals — different gestures, different
    // languages:
    //  - Long-press capture → full-button vertical fill from the
    //    bottom (the "learning bar"). Goes 0 → 1 over 500 ms; on
    //    completion the snapshot is captured and the fill collapses.
    //  - Bar-quantised schedule → segmented ring around the button,
    //    always rendered (4 dim arc segments with quarter gaps), fills
    //    clockwise from the top with cycle-relative progress.
    // The ring's segmented outline is visible even when no schedule
    // is active, so the "musical quarters of a cycle" cue is always
    // present once the gestures themselves are familiar.
    const ringFill = isScheduled ? progress : 0;

    return html`<div class=${cls} ref=${elRef}>
        <${SegmentedRing} fill=${ringFill}
            bright=${isScheduled || state === 'firing'}
            buttonId=${index} />
        ${pressing ? html`
            <div class="dropbtn-pressfill"
                style="height: ${pressProgress * 100}%"></div>` : null}
        <span class="dropbtn-label">${label}</span>
        ${modeBadge ? html`<span class="dropbtn-mode">${modeBadge}</span>` : null}
    </div>`;
}

// 4-segment progress ring with small quarter gaps. Background segments
// always shown muted; foreground (bright) clipped to a wedge from the
// top, sweeping clockwise to `fill` (0..1). One unique clipPath ID per
// button so multiple rings on the page don't collide.
function SegmentedRing({ fill, bright, buttonId }) {
    const cx = 20, cy = 20, r = 18;
    const stroke = 2.5;
    const circ = 2 * Math.PI * r;
    // 4 dashes / 4 gaps. gap ≈ 4 % of perimeter — visible but tight.
    const gapLen = circ * 0.04;
    const dashLen = (circ - 4 * gapLen) / 4;
    const dasharray = `${dashLen} ${gapLen}`;
    // SVG default circle starts at 3 o'clock; rotate -90° so dash 1
    // begins at 12 o'clock (musically beat 1).
    const rotate = `rotate(-90 ${cx} ${cy})`;
    // The wedge from 12 o'clock to (fill * 360°) clockwise. For
    // fill=0 nothing is shown; for fill=1 the whole circle clips
    // through (use a generous square that covers everything).
    const clipId = `dropring-clip-${buttonId}`;
    let wedge = '';
    if (fill > 0.001) {
        if (fill >= 0.999) {
            // Cover the whole svg box.
            wedge = `M 0 0 L 40 0 L 40 40 L 0 40 Z`;
        } else {
            const a = fill * 2 * Math.PI - Math.PI / 2;  // start at top, clockwise
            const ex = cx + (r + stroke) * Math.cos(a);
            const ey = cy + (r + stroke) * Math.sin(a);
            const largeArc = fill > 0.5 ? 1 : 0;
            wedge =
                `M ${cx} ${cy} ` +
                `L ${cx} ${cy - (r + stroke)} ` +
                `A ${r + stroke} ${r + stroke} 0 ${largeArc} 1 ${ex} ${ey} ` +
                `Z`;
        }
    }
    return html`<svg class="dropbtn-ring" viewBox="0 0 40 40">
        <defs>
            <clipPath id=${clipId}>
                <path d=${wedge} />
            </clipPath>
        </defs>
        <!-- BG segments — always muted dim outline -->
        <circle cx=${cx} cy=${cy} r=${r} fill="none"
            stroke-width=${stroke} stroke-linecap="butt"
            stroke=${bright ? 'rgba(255,170,90,0.30)' : 'rgba(255,170,90,0.18)'}
            stroke-dasharray=${dasharray}
            transform=${rotate} />
        <!-- FG progress — same shape, bright color, clipped to wedge -->
        ${fill > 0.001 ? html`<circle cx=${cx} cy=${cy} r=${r} fill="none"
            stroke="rgba(255,200,140,0.95)" stroke-width=${stroke}
            stroke-linecap="butt"
            stroke-dasharray=${dasharray}
            transform=${rotate}
            clip-path=${`url(#${clipId})`} />` : null}
    </svg>`;
}
