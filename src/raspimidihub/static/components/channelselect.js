/**
 * ChannelSelect plugin control.
 */

import { html } from './common.js';
import { PluginWheel } from './wheel.js';

// =======================================================================
// CHANNEL SELECT — wheel 1-16
// =======================================================================
export function PluginChannelSelect({ name, label, value, onChange, allowAny }) {
    // allowAny: extend the wheel down to 0 with an "Any" label so a
    // plugin can use the same control as a channel filter (0 = no
    // filter, 1-16 = filter to that channel).
    const min = allowAny ? 0 : 1;
    const tickLabel = allowAny ? (v) => v === 0 ? 'Any' : v : null;
    return html`<${PluginWheel} name=${name} label=${label} min=${min} max=${16}
        value=${value} onChange=${onChange} tickLabel=${tickLabel} />`;
}

