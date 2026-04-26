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

// =======================================================================
// BUTTON — rubber push button with LED
// =======================================================================
export function PluginButton({ name, label, value, color, onChange, trigger }) {
    const [flashing, setFlashing] = useState(false);
    const flashTimer = useRef(null);

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

    useEffect(() => () => {
        if (flashTimer.current) clearTimeout(flashTimer.current);
    }, []);

    const lit = trigger ? (flashing || value) : value;

    return html`<div class="btn-group-param">
        <span style="font-size:12px;color:var(--text-dim)">${label}</span>
        <button class="rubber-btn ${lit ? 'active' : ''}" onclick=${press}>
            <div class="btn-led ${color || 'green'}"></div>
            ${trigger ? null : html`<span class="btn-text">${value ? 'On' : 'Off'}</span>`}
        </button>
    </div>`;
}
