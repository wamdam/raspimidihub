/**
 * ChannelSelect plugin control.
 */

import { html } from './common.js';
import { PluginWheel } from './wheel.js';

// =======================================================================
// CHANNEL SELECT — wheel 1-16
// =======================================================================
export function PluginChannelSelect({ name, label, value, onChange }) {
    return html`<${PluginWheel} name=${name} label=${label} min=${1} max=${16}
        value=${value} onChange=${onChange} />`;
}

