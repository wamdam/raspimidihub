/**
 * Per-connection filter + mappings overlay.
 *
 * Phase 6: mapping rows lost their inline Edit/Del buttons. Single-tap
 * on a row now opens the edit overlay; long-press / right-click pops a
 * menu (Edit · Copy · Remove). When the App-level clipboard holds a
 * mapping, a `[ + Paste Mapping ]` button appears next to `[ + Add
 * Mapping ]`. Paste-with-bump is owned by the parent (RoutingPage) —
 * it sees the clipboard and the connection id, runs the retry loop.
 */

import { useState, useEffect, useRef } from '../lib/hooks.module.js';
import { html, animateClose, useSwipeDismiss } from '../ui/common.js';
import { useTapMenu } from '../ui/contextmenu.js';
import { MSG_TYPES, MSG_LABELS } from '../state/constants.js';
import { MappingFormOverlay, mappingDesc } from './mappingform.js';
import { useSharedUiState } from '../lib/spectator/shared-ui-state.js';

function MappingRow({ mapping, onEdit, onCopy, onRemove, showContextMenu }) {
    const trigger = useTapMenu(showContextMenu, () => [
        { label: 'Edit', action: onEdit },
        { label: 'Copy', action: onCopy },
        { divider: true },
        { label: 'Remove', danger: true, action: onRemove },
    ]);
    return html`<div class="preset-item" style="cursor:pointer;user-select:none"
        onClick=${trigger.onClick} onContextMenu=${trigger.onContextMenu}>
        <span class="name" style="font-size:13px">${mappingDesc(mapping)}</span>
    </div>`;
}

export function FilterPanel({ connId, filter, mappings, onClose, onApply, onMappingAdd, onMappingDelete, onMappingSave, onMappingCopy, onMappingPaste, srcClientId, clipboard, showContextMenu }) {
    const panelRef = { current: null };
    const close = () => animateClose(panelRef.current, onClose);
    const [channelMask, setChannelMask] = useState(filter ? filter.channel_mask : 0xFFFF);
    const [msgTypes, setMsgTypes] = useState(new Set(filter ? filter.msg_types : MSG_TYPES));
    // mappingForm drives the add/edit overlay. Shared via
    // useSharedUiState so a spectator mirrors the form when the
    // source taps + Add Mapping / Edit on a row — otherwise the
    // overlay opens only on the source and the spectator sees just
    // the filter panel underneath.
    const [mappingForm, setMappingForm] = useSharedUiState('mappingForm', null); // null | { editing: null|obj, index: null|int }

    // Track the most recent write we've sent to the server. Server SSE
    // echoes that match it = "server caught up" (clear pending and
    // accept future SSE updates as authoritative). Echoes that don't
    // match = stale server snapshots racing the user's rapid-fire
    // toggling — ignore them and let local state stay ahead. Without
    // this, fast filter clicks were getting overwritten by SSE for the
    // *previous* state, so toggles appeared to undo themselves.
    const pendingRef = useRef(null); // { mask, types: [] } | null
    const sameAsFilter = (mask, types, f) => {
        if (!f || mask !== f.channel_mask) return false;
        const a = new Set(types);
        const b = new Set(f.msg_types);
        if (a.size !== b.size) return false;
        for (const t of a) if (!b.has(t)) return false;
        return true;
    };
    const filterKey = filter ? `${filter.channel_mask}:${filter.msg_types.join(',')}` : 'none';
    useEffect(() => {
        if (pendingRef.current !== null) {
            if (sameAsFilter(pendingRef.current.mask,
                              pendingRef.current.types, filter)) {
                pendingRef.current = null;
            }
            return; // ignore SSE while local edits are unsettled
        }
        setChannelMask(filter ? filter.channel_mask : 0xFFFF);
        setMsgTypes(new Set(filter ? filter.msg_types : MSG_TYPES));
    }, [filterKey]);

    const sendApply = (mask, types) => {
        pendingRef.current = { mask, types: [...types] };
        onApply(connId, mask, [...types]);
    };

    // ESC to close (with mapping-form precedence)
    useEffect(() => {
        const handler = (e) => { if (e.key === 'Escape') { if (mappingForm) setMappingForm(null); else close(); } };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [mappingForm]);

    const swipe = useSwipeDismiss(close, panelRef);

    const toggleChannel = (ch) => {
        const newMask = channelMask ^ (1 << ch);
        setChannelMask(newMask);
        sendApply(newMask, msgTypes);
    };
    const toggleAllChannels = () => {
        const newMask = channelMask === 0xFFFF ? 0 : 0xFFFF;
        setChannelMask(newMask);
        sendApply(newMask, msgTypes);
    };
    const toggleMsgType = (t) => {
        const n = new Set(msgTypes);
        n.has(t) ? n.delete(t) : n.add(t);
        setMsgTypes(n);
        sendApply(channelMask, n);
    };

    const handleMappingSubmit = async (data) => {
        if (mappingForm && mappingForm.editing) {
            await onMappingSave(mappingForm.index, data);
        } else {
            await onMappingAdd(data);
        }
        setMappingForm(null);
    };

    return html`
        <div class="filter-overlay" onclick=${(e) => e.target.className === 'filter-overlay' && close()}>
            <div class="filter-panel" data-spectator-scroll="filter-panel"
                 ref=${el => panelRef.current = el} ...${swipe}>
                <div class="panel-header">
                    <div class="panel-handle"></div>
                </div>
                <div class="panel-header">
                    <h3>Connection: ${connId}</h3>
                    <button class="panel-close" onclick=${close}>\u2715</button>
                </div>
                <div class="card">
                    <h3 style="cursor:pointer" onclick=${toggleAllChannels}>MIDI Channels</h3>
                    <div class="channel-grid">
                        ${Array.from({length: 16}, (_, i) => {
                            const on = !!(channelMask & (1 << i));
                            return html`
                                <button class="ch-btn" onclick=${() => toggleChannel(i)}>
                                    <span class="ch-num">${i + 1}</span>
                                    <span class="ch-light">
                                        <span class="ch-dot ${on ? '' : 'lit'}" style="background:${on ? 'var(--surface2)' : 'var(--error)'}"></span>
                                        <span class="ch-dot ${on ? 'lit' : ''}" style="background:${on ? 'var(--success)' : 'var(--surface2)'}"></span>
                                    </span>
                                </button>`;
                        })}
                    </div>
                </div>
                <div class="card">
                    <h3>Message Types</h3>
                    <div class="msg-types">
                        ${MSG_TYPES.map(t => html`
                            <label class="msg-toggle">
                                <input type="checkbox" checked=${msgTypes.has(t)} onchange=${() => toggleMsgType(t)} />
                                <span>${MSG_LABELS[t]}</span>
                            </label>
                        `)}
                    </div>
                </div>
                <div class="card">
                    <h3>Mappings</h3>
                    ${(!mappings || mappings.length === 0)
                        ? html`<p style="color:var(--text-dim);font-size:13px">No mappings configured</p>`
                        : mappings.map((m, i) => html`
                            <${MappingRow} key=${i} mapping=${m}
                                onEdit=${() => setMappingForm({ editing: m, index: i })}
                                onCopy=${() => onMappingCopy && onMappingCopy(m)}
                                onRemove=${() => onMappingDelete(i)}
                                showContextMenu=${showContextMenu} />
                        `)}
                    <div style="display:flex;gap:6px;margin-top:8px">
                        <button class="btn btn-primary" style="flex:1" onclick=${() => setMappingForm({ editing: null, index: null })}>+ Add Mapping</button>
                        ${clipboard && clipboard.kind === 'mapping' && html`
                            <button class="btn btn-secondary" style="flex:1" data-testid="paste-mapping"
                                onclick=${() => onMappingPaste && onMappingPaste()}>+ Paste Mapping</button>
                        `}
                    </div>
                </div>
            </div>
        </div>
        ${mappingForm && html`<${MappingFormOverlay}
            editing=${mappingForm.editing}
            srcClientId=${srcClientId}
            onSubmit=${handleMappingSubmit}
            onClose=${() => setMappingForm(null)} />`}
    `;
}
