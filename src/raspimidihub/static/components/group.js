/**
 * Group plugin control.
 */

import { html } from './common.js';

// =======================================================================
// GROUP — titled section
// =======================================================================
export function PluginGroup({ title, children }) {
    return html`<div style="margin-bottom:16px">
        ${title ? html`<div style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--surface2)">${title}</div>` : null}
        ${children}
    </div>`;
}

