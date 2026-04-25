/**
 * Button plugin control.
 */

import { html, tickFeedback } from './common.js';

// =======================================================================
// BUTTON — rubber push button with LED
// =======================================================================
export function PluginButton({ name, label, value, color, onChange }) {
    const press = () => {
        tickFeedback();
        onChange(name, !value);
    };
    return html`<div class="btn-group-param">
        <span style="font-size:12px;color:var(--text-dim)">${label}</span>
        <button class="rubber-btn ${value ? 'active' : ''}" onclick=${press}>
            <div class="btn-led ${color || 'green'}"></div>
            <span class="btn-text">${value ? 'On' : 'Off'}</span>
        </button>
    </div>`;
}

