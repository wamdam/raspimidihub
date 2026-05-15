/**
 * Button plugin control.
 *
 * Two modes:
 *   - Latching (default): click flips value. LED follows value.
 *     Off/On text shown.
 *   - Trigger (trigger=true): click always sends `true`. LED stays lit
 *     for at least 100 ms, then follows value (the server is expected
 *     to reset value back to false and broadcast it via SSE).
 *     No Off/On text.
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html, tickFeedback } from './common.js';

const TRIGGER_MIN_FLASH_MS = 100;
const LONG_PRESS_MS = 500;

// =======================================================================
// BUTTON — rubber push button with LED
// =======================================================================
export function PluginButton({ name, label, value, color, onChange, trigger, mini, onBindRequest }) {
    const [flashing, setFlashing] = useState(false);
    const flashTimer = useRef(null);
    const pressRef = useRef({ ts: 0, fired: false });

    const press = () => {
        tickFeedback();
        if (trigger) {
            setFlashing(true);
            if (flashTimer.current) clearTimeout(flashTimer.current);
            flashTimer.current = setTimeout(() => setFlashing(false), TRIGGER_MIN_FLASH_MS);
            onChange(name, true);
        } else {
            onChange(name, !value);
        }
    };

    const onPointerDown = (e) => {
        if (e.button === 2) return;  // right-click → onContextMenu
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
    const onPointerUp = (e) => {
        const fired = pressRef.current.fired;
        pressRef.current = { ts: 0, fired: false };
        if (fired) { e.preventDefault(); return; }
        press();
    };
    const onPointerLeave = () => { pressRef.current = { ts: 0, fired: false }; };
    const onContextMenu = (e) => {
        e.preventDefault();
        if (onBindRequest) onBindRequest(name);
    };

    useEffect(() => () => {
        if (flashTimer.current) clearTimeout(flashTimer.current);
    }, []);

    const lit = trigger ? (flashing || value) : value;

    return html`<div class=${mini ? 'btn-group-param mini' : 'btn-group-param'}>
        ${label ? html`<span style="font-size:12px;color:var(--text-dim)">${label}</span>` : null}
        <button class="rubber-btn ${mini ? 'mini' : ''} ${lit ? 'active' : ''}"
            onpointerdown=${onPointerDown}
            onpointerup=${onPointerUp}
            onpointerleave=${onPointerLeave}
            onpointercancel=${onPointerLeave}
            oncontextmenu=${onContextMenu}>
            <div class="btn-led ${color || 'green'}"></div>
            ${trigger ? null : html`<span class="btn-text">${value ? 'On' : 'Off'}</span>`}
        </button>
    </div>`;
}
