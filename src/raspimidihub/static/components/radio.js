/**
 * Radio plugin control.
 */

import { html, tickFeedback } from './common.js';

// =======================================================================
// RADIO — pill buttons
// =======================================================================
export function PluginRadio({ name, label, options, value, onChange }) {
    const select = (opt) => {
        tickFeedback();
        onChange(name, opt);
    };
    return html`<div class="radio-group">
        <span class="radio-label">${label}</span>
        <div class="radio-options">
            ${options.map(opt => html`
                <div class="radio-opt ${value === opt ? 'active' : ''}" key=${opt}
                    onclick=${() => select(opt)}>${opt}</div>
            `)}
        </div>
    </div>`;
}

