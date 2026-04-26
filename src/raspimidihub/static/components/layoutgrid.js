/**
 * PluginLayoutGrid — renders a positioned grid of cells (Knob / Fader /
 * Button / XYPad) with an in-place "Edit" mode that swaps the grid for
 * a flat scrollable list of cell-rename / channel / cc / Learn rows.
 *
 * Edit state is owned by `PluginConfigPanel` and threaded through
 * `displayCtx.editing` + `displayCtx.setEditing`. That way the panel
 * can simultaneously show config_only params (e.g. background colour)
 * and apply a live bg preview, while LayoutGrid still owns the Edit /
 * Save toggle visually. The state is panel-local, so toggling on this
 * browser does NOT propagate to other connected browsers — UI mode,
 * not data. Renames / rebinds / Learn captures DO propagate through
 * the server-stored `labels_param` / `bindings_param` / `learn_param`.
 *
 * `displayCtx.playOnly` suppresses the Edit toggle entirely — used by
 * the Controller fullscreen page where the goal is performance.
 */

import { html } from './common.js';

export function PluginLayoutGrid({ param, values, onChange, displayCtx, renderParam }) {
    const playOnly = !!(displayCtx && displayCtx.playOnly);
    // Edit state is owned by PluginConfigPanel (so it can show/hide
    // config_only params and apply the bg preview). LayoutGrid just
    // reads the flag and toggles via the setter.
    const editing = !!(displayCtx && displayCtx.editing);
    const setEditing = displayCtx && displayCtx.setEditing;

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

    const canEdit = !playOnly && setEditing && (param.labels_param || param.bindings_param || param.learn_param);

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
                const isButton = c.param.type === 'button';
                // Button cells gain on / off CC value columns. Defaults
                // are 127 / 0 server-side; the placeholder shows that.
                const ovOn  = (bindOv.on  != null && bindOv.on  !== '') ? bindOv.on  : null;
                const ovOff = (bindOv.off != null && bindOv.off !== '') ? bindOv.off : null;
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
                        ${isButton ? html`
                            <input class="layout-edit-bind" type="number" min="0" max="127"
                                value=${ovOn != null ? ovOn : ''}
                                placeholder="on 127"
                                title="CC value when button is ON (0-127)"
                                onInput=${(e) => setBinding(c.param.name, 'on',
                                    e.target.value === '' ? null : parseInt(e.target.value, 10))} />
                            <input class="layout-edit-bind" type="number" min="0" max="127"
                                value=${ovOff != null ? ovOff : ''}
                                placeholder="off 0"
                                title="CC value when button is OFF (0-127)"
                                onInput=${(e) => setBinding(c.param.name, 'off',
                                    e.target.value === '' ? null : parseInt(e.target.value, 10))} />
                        ` : null}
                        ${param.learn_param ? html`
                            <button type="button" class="layout-edit-learn ${isLearning ? 'on' : ''}"
                                title=${isLearning ? 'Listening — tap to cancel' : 'MIDI Learn'}
                                onclick=${() => toggleLearn(c.param.name)}>${isLearning ? '…' : 'L'}</button>` : null}
                    ` : null}
                </div>`;
            })}
            <button type="button" class="layout-edit-done" onclick=${() => setEditing(false)}>Save</button>
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
