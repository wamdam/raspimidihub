/**
 * PluginLayoutGrid — renders a positioned grid of cells (Knob / Fader /
 * Button / XYPad) on play surfaces, OR a flat config list (one row per
 * cell with name / button On-Off / XY spring) in the device-detail
 * panel.
 *
 * Mode is decided by `displayCtx.playOnly`:
 *
 *   - playOnly === true  → live positioned cells (Controller page).
 *   - playOnly !== true  → flat config list, IF the LayoutGrid declares
 *                          `labels_param` / `bindings_param`. Without
 *                          those, falls back to the live grid (used by
 *                          `ui_demo`).
 *
 * As of Phase 4 of the CC-binding work, the per-cell (channel, cc) +
 * MIDI Learn editor lives on the Controller page as a long-press
 * popup (components/cellbinding.js). The device-detail flat list is
 * now strictly for cell-level *extras* — labels, button On / Off
 * values, XY-pad spring ergonomics — that don't fit the popup's
 * binding-only scope.
 *
 * Renames / button On-Off / spring edits all auto-save through the
 * normal onChange → PATCH pipeline; there's no separate Save button.
 */

import { html } from './common.js';
import { PluginWheel } from './wheel.js';

const SPRING_HOME_OPTIONS = ["Bottom-left", "Center"];

// Storage normalisation: legacy values "bottom_left" / "center" still
// load correctly into the new display-string options. Returns the
// display string the Radio expects.
function normaliseSpringHome(v) {
    if (v == null || v === "") return "Bottom-left";
    const s = String(v).toLowerCase();
    if (s === "center") return "Center";
    return "Bottom-left";
}

export function PluginLayoutGrid({ param, values, onChange, displayCtx, renderParam }) {
    const playOnly = !!(displayCtx && displayCtx.playOnly);
    const hasConfigSurface = param.labels_param || param.bindings_param;

    const labels = (param.labels_param && values[param.labels_param]) || {};
    const bindings = (param.bindings_param && values[param.bindings_param]) || {};

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
    const setBindingStr = (cellName, key, value) => {
        if (!param.bindings_param) return;
        const cur = bindings[cellName] || {};
        const next = { ...cur, [key]: value };
        onChange(param.bindings_param, { ...bindings, [cellName]: next });
    };

    // Config view — shown in the device-detail panel for any LayoutGrid
    // that opted in by declaring labels_param or bindings_param. Each
    // cell becomes a card with the name input and any per-type extras
    // (button On/Off, XY spring config):
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
            <p class="layout-grid-editing-hint">
                Cell label and per-type extras. To rebind a cell's MIDI
                channel and CC, long-press the cell on the Controller
                page.
            </p>
            ${param.cells.map((c) => {
                const labelOv = labels[c.param.name];
                const effectiveLabel = labelOv != null && labelOv !== '' ? labelOv : c.param.label;
                const bindOv = bindings[c.param.name] || {};
                const isButton = c.param.type === 'button';
                const isXYPad = c.param.type === 'xypad';
                const typeLabel = TYPE_LABEL[c.param.type] || c.param.type;
                const ovOn  = (bindOv.on  != null && bindOv.on  !== '') ? bindOv.on  : null;
                const ovOff = (bindOv.off != null && bindOv.off !== '') ? bindOv.off : null;
                const hasBindings = !!param.bindings_param;
                return html`<div class="cell-edit">
                    <div class="cell-edit-row">
                        <span class="cell-edit-type">${typeLabel}</span>
                        <input class="cell-edit-name" type="text"
                            value=${effectiveLabel === c.param.label ? '' : effectiveLabel}
                            placeholder=${c.param.label}
                            onInput=${(e) => setLabel(c.param.name, e.target.value)} />
                    </div>
                    ${hasBindings && isXYPad ? (() => {
                        const defForce = c.spring_force != null ? c.spring_force : 0;
                        const defHome = c.spring_home != null ? c.spring_home : 'Bottom-left';
                        const ovForce = (bindOv.spring_force != null && bindOv.spring_force !== '')
                            ? bindOv.spring_force : null;
                        const ovHome = (typeof bindOv.spring_home === 'string' && bindOv.spring_home !== '')
                            ? bindOv.spring_home : null;
                        const effForce = ovForce != null ? ovForce : defForce;
                        const effHome = normaliseSpringHome(ovHome != null ? ovHome : defHome);
                        // Home wheel: 2 ticks, each labelled. Storage
                        // stays as the string "Bottom-left" / "Center"
                        // so old saves still load; only the wheel↔string
                        // adapter here knows the index mapping.
                        const homeIdx = effHome === "Center" ? 1 : 0;
                        return html`<div class="cell-edit-row spring-row mini-controls">
                            <${PluginWheel} mini
                                name=${`${c.param.name}_spring_force`}
                                label="Spring Force"
                                min=${0}
                                max=${127}
                                value=${effForce}
                                onChange=${(_, v) => setBinding(c.param.name, 'spring_force', v)} />
                            <${PluginWheel} mini
                                name=${`${c.param.name}_spring_home`}
                                label="Home"
                                min=${0}
                                max=${1}
                                value=${homeIdx}
                                tickLabel=${(v) => SPRING_HOME_OPTIONS[v] || ''}
                                onChange=${(_, v) => setBindingStr(c.param.name, 'spring_home',
                                    SPRING_HOME_OPTIONS[v] || 'Bottom-left')} />
                        </div>`;
                    })() : null}
                    ${isButton && hasBindings ? html`<div class="cell-edit-row mini-controls">
                        <${PluginWheel} mini name=${c.param.name + '_on'} label="On"
                            min=${0} max=${127}
                            value=${ovOn != null ? ovOn : 127}
                            onChange=${(_, v) => setBinding(c.param.name, 'on', v)} />
                        <${PluginWheel} mini name=${c.param.name + '_off'} label="Off"
                            min=${0} max=${127}
                            value=${ovOff != null ? ovOff : 0}
                            onChange=${(_, v) => setBinding(c.param.name, 'off', v)} />
                        <button type="button" class="cell-edit-swap"
                            title="Swap On / Off values"
                            onclick=${() => {
                                const curOn  = ovOn  != null ? ovOn  : 127;
                                const curOff = ovOff != null ? ovOff : 0;
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
    //
    // Each cell gets the cell-binding popup route via openCellBinding —
    // long-pressing a knob/fader/button opens the same CellBinding modal
    // as the plugin-control popup, but tied to the cell's symmetric
    // (channel, cc) pair in cell_bindings. The bindings_param check
    // gates the popup so LayoutGrids without a bindings surface
    // (ui_demo) stay non-bindable.
    const cellCtx = (param.bindings_param && displayCtx && displayCtx.openCellBinding)
        ? displayCtx
        : { ...(displayCtx || {}), openCellBinding: undefined };
    const gridStyle = `display:grid;grid-template-columns:repeat(${param.cols}, minmax(0, 1fr));grid-template-rows:repeat(${param.rows}, auto);gap:6px`;
    return html`<div class="layout-grid" style=${gridStyle}>
        ${param.cells.map((c) => {
            const cellStyle = `grid-column: ${c.col} / span ${c.span_cols}; grid-row: ${c.row} / span ${c.span_rows}; min-width: 0`;
            const labelOv = labels[c.param.name];
            const patched = { ...c.param };
            if (labelOv != null && labelOv !== '') patched.label = labelOv;
            // XY pads: layer cell defaults + per-cell binding overrides
            // for the spring config so the rendered <PluginXYPad> picks
            // up the effective values without a separate plumbing path.
            if (c.param.type === 'xypad') {
                const bindOv = bindings[c.param.name] || {};
                const cellSpringForce = c.spring_force != null ? c.spring_force : 0;
                const cellSpringHome = c.spring_home != null ? c.spring_home : 'bottom_left';
                patched.spring_force = (typeof bindOv.spring_force === 'number')
                    ? bindOv.spring_force : cellSpringForce;
                patched.spring_home = (typeof bindOv.spring_home === 'string')
                    ? bindOv.spring_home : cellSpringHome;
            }
            return html`<div class="layout-cell" style=${cellStyle}>
                ${renderParam(patched, values, onChange, values, cellCtx)}
            </div>`;
        })}
    </div>`;
}
