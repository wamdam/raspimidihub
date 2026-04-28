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

import { useState, useEffect } from '../lib/hooks.module.js';
import { html, animateClose, useSwipeDismiss } from '../ui/common.js';
import { useTapMenu } from '../ui/contextmenu.js';
import { MSG_TYPES, MSG_LABELS } from '../state/constants.js';
import { MappingFormOverlay, mappingDesc } from './mappingform.js';

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
    const [mappingForm, setMappingForm] = useState(null); // null | { editing: null|obj, index: null|int }

    // Sync state when filter prop changes from outside (other device updated via SSE)
    const filterKey = filter ? `${filter.channel_mask}:${filter.msg_types.join(',')}` : 'none';
    useEffect(() => {
        setChannelMask(filter ? filter.channel_mask : 0xFFFF);
        setMsgTypes(new Set(filter ? filter.msg_types : MSG_TYPES));
    }, [filterKey]);

    // ESC to close (with mapping-form precedence)
    useEffect(() => {
        const handler = (e) => { if (e.key === 'Escape') { if (mappingForm) setMappingForm(null); else close(); } };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [mappingForm]);

    const swipe = useSwipeDismiss(close, panelRef);

    const applyFilter = (mask, types) => onApply(connId, mask, [...types]);

    const toggleChannel = (ch) => {
        const newMask = channelMask ^ (1 << ch);
        setChannelMask(newMask);
        applyFilter(newMask, msgTypes);
    };
    const toggleAllChannels = () => {
        const newMask = channelMask === 0xFFFF ? 0 : 0xFFFF;
        setChannelMask(newMask);
        applyFilter(newMask, msgTypes);
    };
    const toggleMsgType = (t) => {
        const n = new Set(msgTypes);
        n.has(t) ? n.delete(t) : n.add(t);
        setMsgTypes(n);
        applyFilter(channelMask, n);
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
            <div class="filter-panel" ref=${el => panelRef.current = el} ...${swipe}>
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
