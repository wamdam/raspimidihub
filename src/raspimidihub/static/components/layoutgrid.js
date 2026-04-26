/**
 * PluginLayoutGrid — renders a positioned grid of cells (Knob / Fader /
 * Button / XYPad) with an in-place "Edit" mode that swaps the grid for
 * a flat scrollable list of cell-rename / channel / cc / Learn rows.
 *
 * Edit mode is local React state, not a server-stored param — toggling
 * it on this browser does NOT propagate to other connected browsers
 * (UI mode, not data). Renames / rebinds / Learn captures still flow
 * through `labels_param` / `bindings_param` / `learn_param` which ARE
 * server-stored, so those changes propagate.
 *
 * The `playOnly` prop (passed via `displayCtx.playOnly`) suppresses the
 * Edit toggle entirely — used by the Controller fullscreen page where
 * the goal is performance, not configuration.
 */

import { useState } from '../lib/hooks.module.js';
import { html } from './common.js';

export function PluginLayoutGrid({ param, values, onChange, displayCtx, renderParam }) {
    const playOnly = !!(displayCtx && displayCtx.playOnly);
    const [editing, setEditing] = useState(false);

    const labels = (param.labels_param && values[param.labels_param]) || {};
    const bindings = (param.bindings_param && values[param.bindings_param]) || {};
    const learnTarget = (param.learn_param && values[param.learn_param]) || '';

    const setLabel = (cellName, newLabel) => {
        if (!param.labels_param) return;
        onChange(param.labels_param, { ...labels, [cellName]: newLabel });
    };
    const setBinding = (cellName, key, raw) => {
        if (!param.bindings_param) return;
        const cur = bindings[cellName] || {};
        const parsed = parseInt(raw, 10);
        const next = { ...cur, [key]: Number.isFinite(parsed) ? parsed : null };
        onChange(param.bindings_param, { ...bindings, [cellName]: next });
    };
    const toggleLearn = (cellName) => {
        if (!param.learn_param) return;
        onChange(param.learn_param, learnTarget === cellName ? '' : cellName);
    };

    const canEdit = !playOnly && (param.labels_param || param.bindings_param || param.learn_param);

    // Edit mode: flat list, full-width rows.
    if (editing && canEdit) {
        return html`<div class="layout-grid-editing">
            ${param.cells.map((c) => {
                const labelOv = labels[c.param.name];
                const effectiveLabel = labelOv != null && labelOv !== '' ? labelOv : c.param.label;
                const bindOv = bindings[c.param.name] || {};
                const defCh = c.channel != null ? c.channel + 1 : null;
                const defCc = c.cc;
                const ovCh = (bindOv.channel != null && bindOv.channel !== '') ? bindOv.channel + 1 : null;
                const ovCc = (bindOv.cc != null && bindOv.cc !== '') ? bindOv.cc : null;
                const isLearning = learnTarget === c.param.name;
                return html`<div class="layout-edit-row ${isLearning ? 'learning' : ''}">
                    <span class="layout-edit-default" title=${`Default: ${c.param.label}`}>${c.param.label}</span>
                    <input class="layout-edit-name" type="text"
                        value=${effectiveLabel === c.param.label ? '' : effectiveLabel}
                        placeholder=${c.param.label}
                        onInput=${(e) => setLabel(c.param.name, e.target.value)} />
                    ${param.bindings_param && (defCh != null || defCc != null) ? html`
                        <input class="layout-edit-bind" type="number" min="1" max="16"
                            value=${ovCh != null ? ovCh : ''}
                            placeholder=${defCh != null ? `${defCh}` : 'ch'}
                            title="Channel (1-16)"
                            onInput=${(e) => setBinding(c.param.name, 'channel',
                                e.target.value === '' ? null : (parseInt(e.target.value, 10) - 1))} />
                        <input class="layout-edit-bind" type="number" min="0" max="127"
                            value=${ovCc != null ? ovCc : ''}
                            placeholder=${defCc != null ? `${defCc}` : 'cc'}
                            title="CC (0-127)"
                            onInput=${(e) => setBinding(c.param.name, 'cc',
                                e.target.value === '' ? null : parseInt(e.target.value, 10))} />
                        ${param.learn_param ? html`
                            <button type="button" class="layout-edit-learn ${isLearning ? 'on' : ''}"
                                title=${isLearning ? 'Listening — tap to cancel' : 'MIDI Learn'}
                                onclick=${() => toggleLearn(c.param.name)}>${isLearning ? '…' : 'L'}</button>` : null}
                    ` : null}
                </div>`;
            })}
            <button type="button" class="layout-edit-done" onclick=${() => setEditing(false)}>Done</button>
        </div>`;
    }

    // Play mode: positioned grid + (optionally) an inline "Edit" button.
    const gridStyle = `display:grid;grid-template-columns:repeat(${param.cols}, minmax(0, 1fr));grid-template-rows:repeat(${param.rows}, auto);gap:6px`;
    return html`<div class="layout-grid-wrap">
        <div class="layout-grid" style=${gridStyle}>
            ${param.cells.map((c) => {
                const cellStyle = `grid-column: ${c.col} / span ${c.span_cols}; grid-row: ${c.row} / span ${c.span_rows}; min-width: 0`;
                const labelOv = labels[c.param.name];
                const patchedParam = labelOv != null && labelOv !== ''
                    ? { ...c.param, label: labelOv }
                    : c.param;
                return html`<div class="layout-cell" style=${cellStyle}>
                    ${renderParam(patchedParam, values, onChange, values, displayCtx)}
                </div>`;
            })}
        </div>
        ${canEdit ? html`<button type="button" class="layout-edit-toggle"
            onclick=${() => setEditing(true)}>Edit</button>` : null}
    </div>`;
}
