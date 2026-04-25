/**
 * Toggle plugin control.
 */

import { html, tickFeedback } from './common.js';

// =======================================================================
// TOGGLE — metal switch
// =======================================================================
export function PluginToggle({ name, label, value, onChange }) {
    const toggle = () => {
        tickFeedback();
        onChange(name, !value);
    };
    return html`<div class="toggle-group">
        <span class="toggle-label">${label}</span>
        <div class="metal-toggle ${value ? 'on' : ''}" onclick=${toggle}>
            <div class="slot"></div>
            <span class="toggle-text off-text">Off</span>
            <span class="toggle-text on-text">On</span>
        </div>
    </div>`;
}

