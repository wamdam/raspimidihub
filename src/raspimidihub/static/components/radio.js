/**
 * Radio plugin control.
 */

import { useRef } from '../lib/hooks.module.js';
import { html, tickFeedback } from './common.js';

// Long-press / right-click on a Radio opens the CC binding popup.
// Tap selects an option as before. The popup is anchored to the row,
// not the individual pill, because the binding controls the Radio
// as a whole (CC value 0..127 → option index via _cc_to_param).
const LONG_PRESS_MS = 500;

// =======================================================================
// RADIO — pill buttons
// =======================================================================
export function PluginRadio({ name, label, options, value, onChange, onBindRequest }) {
    const select = (opt) => {
        tickFeedback();
        onChange(name, opt);
    };
    const pressRef = useRef({ ts: 0, fired: false });
    const onPointerDown = () => {
        pressRef.current = { ts: Date.now(), fired: false };
        if (!onBindRequest) return;
        setTimeout(() => {
            const s = pressRef.current;
            if (s.ts > 0 && !s.fired && Date.now() - s.ts >= LONG_PRESS_MS - 5) {
                s.fired = true;
                onBindRequest(name);
            }
        }, LONG_PRESS_MS);
    };
    const onPointerEnd = (opt) => (e) => {
        const fired = pressRef.current.fired;
        pressRef.current = { ts: 0, fired: false };
        if (fired) { e && e.preventDefault && e.preventDefault(); return; }
        select(opt);
    };
    const onContextMenu = (e) => {
        e.preventDefault();
        if (onBindRequest) onBindRequest(name);
    };
    return html`<div class="radio-group" oncontextmenu=${onContextMenu}>
        <span class="radio-label">${label}</span>
        <div class="radio-options">
            ${options.map(opt => html`
                <div class="radio-opt ${value === opt ? 'active' : ''}" key=${opt}
                    onpointerdown=${onPointerDown}
                    onpointerup=${onPointerEnd(opt)}
                    onpointerleave=${() => { pressRef.current = { ts: 0, fired: false }; }}
                    onpointercancel=${() => { pressRef.current = { ts: 0, fired: false }; }}
                    oncontextmenu=${onContextMenu}>${opt}</div>
            `)}
        </div>
    </div>`;
}

