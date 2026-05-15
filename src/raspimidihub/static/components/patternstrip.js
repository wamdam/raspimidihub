/**
 * PatternStrip — bottom-of-play-surface bank selector.
 *
 * Renders a row of `count` tappable buttons (P1..Pn). Tap a button
 * to switch to that slot; the plugin owns the actual snapshot /
 * load mechanics (raspimidihub.slot_bank on the backend) and
 * broadcasts the new live-state values over SSE. The strip itself
 * only mutates the active-slot int param.
 */

import { html, tickFeedback } from './common.js';

export function PluginPatternStrip({ name, value, onChange, count }) {
    const active = Math.max(0, Math.min(count - 1, parseInt(value) || 0));
    const slots = [];
    for (let i = 0; i < count; i++) {
        const isActive = i === active;
        slots.push(html`
            <button
                key=${i}
                class="pattern-strip-btn ${isActive ? 'active' : ''}"
                onClick=${() => {
                    if (i === active) return;
                    tickFeedback();
                    onChange(name, i);
                }}>
                P${i + 1}
            </button>
        `);
    }
    return html`<div class="pattern-strip">${slots}</div>`;
}
