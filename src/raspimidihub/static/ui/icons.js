/**
 * Inline SVG icons + the device-icon resolvers (PluginIcon, DeviceIcon).
 */

import { html } from './common.js';
import { useEffect, useState } from '../lib/hooks.module.js';

export const IconRouting = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h4l4 6-4 6H4"/><path d="M20 6h-4l-4 6 4 6h4"/></svg>`;
export const IconPreset = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>`;
export const IconSettings = html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2m0 18v2m-9-11h2m16 0h2m-3.64-6.36l-1.42 1.42M6.06 17.94l-1.42 1.42m0-12.72l1.42 1.42m11.88 11.88l1.42 1.42"/></svg>`;

// DIN MIDI connector icon (5-pin) for hardware devices
export const IconDIN = html`<svg viewBox="0 0 20 20" class="dev-icon din"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="6" cy="8" r="1.2" fill="currentColor"/><circle cx="14" cy="8" r="1.2" fill="currentColor"/><circle cx="10" cy="13" r="1.2" fill="currentColor"/><circle cx="7" cy="12" r="1.2" fill="currentColor"/><circle cx="13" cy="12" r="1.2" fill="currentColor"/></svg>`;

// Plugin icon: fetched from /api/plugins/icon/{type} and injected inline so currentColor works.
const _iconCache = {};
export function PluginIcon({ type }) {
    const [svg, setSvg] = useState(_iconCache[type] || null);
    useEffect(() => {
        if (_iconCache[type]) { setSvg(_iconCache[type]); return; }
        fetch(`/api/plugins/icon/${type}`).then(r => r.ok ? r.text() : '').then(t => {
            if (t) { _iconCache[type] = t; setSvg(t); }
        }).catch(() => {});
    }, [type]);
    if (!svg) return null;
    return html`<span class="dev-icon plugin" dangerouslySetInnerHTML=${{ __html: svg }}></span>`;
}

export function DeviceIcon({ device }) {
    if (device.is_plugin && device.plugin_type) return html`<${PluginIcon} type=${device.plugin_type} />`;
    return IconDIN;
}
