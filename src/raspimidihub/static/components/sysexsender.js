/**
 * SysEx Sender — file-input UI shown in the SysEx Sender plugin's
 * device-detail panel.
 *
 * The plugin has zero params. This component is the entire user
 * surface: pick a .syx file, the browser POSTs the raw bytes to
 * `/api/plugins/instances/<id>/sysex`, the server chunks + paces
 * them out the OUT port and returns `{sent, ms}` for the toast.
 *
 * No client-side state survives a page reload — there's no
 * "remember last file" because the bytes never live on disk.
 */

import { useState, useRef } from '../lib/hooks.module.js';
import { html } from '../ui/common.js';

export function SysExSenderControls({ instanceId, showToast }) {
    const [busy, setBusy] = useState(false);
    const inputRef = useRef(null);

    const onPick = async (e) => {
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        setBusy(true);
        try {
            const buf = await file.arrayBuffer();
            const r = await fetch(
                `/api/plugins/instances/${instanceId}/sysex`,
                { method: 'POST',
                  headers: { 'Content-Type': 'application/octet-stream' },
                  body: buf });
            if (!r.ok) {
                const txt = await r.text();
                showToast(`Send failed: ${txt || r.status}`);
                return;
            }
            const { sent, ms } = await r.json();
            showToast(`Sent ${sent} bytes in ${ms} ms`);
        } catch (err) {
            showToast(`Send failed: ${err.message || err}`);
        } finally {
            setBusy(false);
            // Clear the input so picking the same file again still
            // fires onChange — handy when re-sending.
            if (inputRef.current) inputRef.current.value = '';
        }
    };

    return html`<div style="padding:8px 0">
        <button class="btn btn-primary" style="width:100%"
            disabled=${busy}
            onclick=${() => inputRef.current && inputRef.current.click()}>
            ${busy ? 'Sending...' : 'Pick .syx file & send'}
        </button>
        <input ref=${el => inputRef.current = el} type="file"
            accept=".syx,application/octet-stream"
            style="display:none" onchange=${onPick} />
        <p style="font-size:11px;color:var(--text-dim);margin-top:8px;line-height:1.4">
            Bytes are streamed straight to the connected destination
            (256-byte chunks, 5 ms gap). Nothing is saved.
        </p>
    </div>`;
}
