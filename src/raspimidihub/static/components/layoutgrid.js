/**
 * PluginLayoutGrid — renders a positioned grid of cells (Knob / Fader /
 * Button / XYPad) on play surfaces, OR a flat config list (one row per
 * cell with name / channel / cc / on / off / Learn) in the device-
 * detail panel.
 *
 * Mode is decided by `displayCtx.playOnly`:
 *
 *   - playOnly === true  → live positioned cells (Controller page).
 *   - playOnly !== true  → flat config list, IF the LayoutGrid declares
 *                          any of `labels_param` / `bindings_param` /
 *                          `learn_param`. Without those, falls back to
 *                          the live grid (used by `ui_demo`).
 *
 * Renames / rebinds / Learn captures all auto-save through the normal
 * onChange → PATCH pipeline; there's no separate Save button. The
 * server-stored `labels_param` / `bindings_param` / `learn_param`
 * propagate via SSE so other browsers see the changes immediately.
 */

import { html } from './common.js';

export function PluginLayoutGrid({ param, values, onChange, displayCtx, renderParam }) {
    const playOnly = !!(displayCtx && displayCtx.playOnly);
    const hasConfigSurface = param.labels_param || param.bindings_param || param.learn_param;

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

    // Config view — shown in the device-detail panel for any LayoutGrid
    // that opted in by declaring labels_param / bindings_param /
    // learn_param. Each cell becomes a multi-line card:
    //
    //   Knob   [name input]
    //   Ch [_]  CC [__]                              Learn
    //
    //   Button [name input]
    //   Ch [_]  CC [__]                              Learn
    //   On [__]  Off [__]
    //
    // Live cells live on the Controller page (playOnly).
    if (!playOnly && hasConfigSurface) {
        const TYPE_LABEL = { knob: 'Knob', fader: 'Fader', button: 'Button', wheel: 'Wheel', xypad: 'XY Pad' };
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
                const isXYPad = c.param.type === 'xypad';
                const typeLabel = TYPE_LABEL[c.param.type] || c.param.type;
                const ovOn  = (bindOv.on  != null && bindOv.on  !== '') ? bindOv.on  : null;
                const ovOff = (bindOv.off != null && bindOv.off !== '') ? bindOv.off : null;
                const defCcY = c.cc_y;
                const ovCcY = (bindOv.cc_y != null && bindOv.cc_y !== '') ? bindOv.cc_y : null;
                const hasBindings = param.bindings_param && (defCh != null || defCc != null);
                return html`<div class="cell-edit ${isLearning ? 'learning' : ''}">
                    <div class="cell-edit-row">
                        <span class="cell-edit-type">${typeLabel}</span>
                        <input class="cell-edit-name" type="text"
                            value=${effectiveLabel === c.param.label ? '' : effectiveLabel}
                            placeholder=${c.param.label}
                            onInput=${(e) => setLabel(c.param.name, e.target.value)} />
                    </div>
                    ${hasBindings ? html`<div class="cell-edit-row">
                        <span class="cell-edit-fieldlabel">Ch</span>
                        <input class="cell-edit-num" type="number" min="1" max="16"
                            value=${ovCh != null ? ovCh : (defCh != null ? defCh : '')}
                            title="Channel (1-16)"
                            onInput=${(e) => setBinding(c.param.name, 'channel',
                                e.target.value === '' ? null : (parseInt(e.target.value, 10) - 1))} />
                        <span class="cell-edit-fieldlabel">${isXYPad ? 'CC X' : 'CC'}</span>
                        <input class="cell-edit-num" type="number" min="0" max="127"
                            value=${ovCc != null ? ovCc : (defCc != null ? defCc : '')}
                            title=${isXYPad ? 'X-axis CC (0-127)' : 'CC (0-127)'}
                            onInput=${(e) => setBinding(c.param.name, 'cc',
                                e.target.value === '' ? null : parseInt(e.target.value, 10))} />
                        ${isXYPad ? html`
                            <span class="cell-edit-fieldlabel">CC Y</span>
                            <input class="cell-edit-num" type="number" min="0" max="127"
                                value=${ovCcY != null ? ovCcY : (defCcY != null ? defCcY : '')}
                                title="Y-axis CC (0-127)"
                                onInput=${(e) => setBinding(c.param.name, 'cc_y',
                                    e.target.value === '' ? null : parseInt(e.target.value, 10))} />
                        ` : null}
                        ${param.learn_param ? html`
                            <button type="button" class="cell-edit-learn ${isLearning ? 'on' : ''}"
                                title=${isLearning ? 'Listening for incoming CC — tap to cancel'
                                    : (isXYPad
                                        ? 'Tap, then twist a hardware knob to capture the X-axis (channel, cc). Type CC Y manually.'
                                        : 'Tap, then twist a hardware knob to capture its (channel, cc)')}
                                onclick=${() => toggleLearn(c.param.name)}>${isLearning ? 'Listening…' : 'Learn'}</button>` : null}
                    </div>` : null}
                    ${isButton && hasBindings ? html`<div class="cell-edit-row">
                        <span class="cell-edit-fieldlabel">On</span>
                        <input class="cell-edit-num" type="number" min="0" max="127"
                            value=${ovOn != null ? ovOn : 127}
                            title="CC value when the button is ON (0-127)"
                            onInput=${(e) => setBinding(c.param.name, 'on',
                                e.target.value === '' ? null : parseInt(e.target.value, 10))} />
                        <span class="cell-edit-fieldlabel">Off</span>
                        <input class="cell-edit-num" type="number" min="0" max="127"
                            value=${ovOff != null ? ovOff : 0}
                            title="CC value when the button is OFF (0-127)"
                            onInput=${(e) => setBinding(c.param.name, 'off',
                                e.target.value === '' ? null : parseInt(e.target.value, 10))} />
                        <button type="button" class="cell-edit-swap"
                            title="Swap On / Off values"
                            onclick=${() => {
                                const curOn  = ovOn  != null ? ovOn  : 127;
                                const curOff = ovOff != null ? ovOff : 0;
                                // Setting both via two updates so each goes
                                // through the same setBinding pipeline.
                                const cur = bindings[c.param.name] || {};
                                onChange(param.bindings_param, {
                                    ...bindings,
                                    [c.param.name]: { ...cur, on: curOff, off: curOn },
                                });
                            }}>↔</button>
                    </div>` : null}
                </div>`;
            })}
        </div>`;
    }

    // Play mode: positioned grid of live cells.
    const gridStyle = `display:grid;grid-template-columns:repeat(${param.cols}, minmax(0, 1fr));grid-template-rows:repeat(${param.rows}, auto);gap:6px`;
    return html`<div class="layout-grid" style=${gridStyle}>
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
    </div>`;
}
