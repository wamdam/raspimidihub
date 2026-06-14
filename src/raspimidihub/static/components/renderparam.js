/**
 * Render dispatcher — turns a param schema into the right component.
 */

import { html } from './common.js';
import { PluginWheel } from './wheel.js';
import { PluginKnob } from './knob.js';
import { PluginFader } from './fader.js';
import { PluginRadio } from './radio.js';
import { PluginButton } from './button.js';
import { PluginXYPad } from './xypad.js';
import { PluginDropButtonRow } from './dropbuttonrow.js';
import { PluginStepEditor } from './stepeditor.js';
import { PluginCartesianGrid } from './cartesiangrid.js';
import { PluginCurveEditor } from './curveeditor.js';
import { PluginNoteSelect } from './noteselect.js';
import { PluginCCSelect } from './ccselect.js';
import { PluginChannelSelect } from './channelselect.js';
import { PluginGroup } from './group.js';
import { PluginLayoutGrid } from './layoutgrid.js';
import { PluginTrackerGrid } from './trackergrid.js';
import { PluginPatternBank } from './patternbank.js';
import { DisplayMeter, DisplayScope } from './display.js';

// =======================================================================
// PARAM RENDERER — maps param schema to components
// =======================================================================
export function renderParam(param, values, onChange, allValues, displayCtx) {
    const val = values[param.name];

    // Check visible_when condition
    if (param.visible_when) {
        const condParam = param.visible_when.param;
        const condVal = param.visible_when.value;
        const current = allValues[condParam];
        if (Array.isArray(condVal)) {
            if (!condVal.includes(current)) return null;
        } else {
            if (current !== condVal) return null;
        }
    }

    // Two routes for the long-press binding popup:
    //
    //   1) Controller cells (Knob/Fader/Button inside a LayoutGrid
    //      play surface): displayCtx.openCellBinding is set by
    //      LayoutGrid. Long-press opens the CellBinding popup, which
    //      writes the symmetric (channel, cc) pair into the
    //      controller's `cell_bindings` dict. No `default_cc` opt-in
    //      required — every cell carries a binding by definition.
    //
    //   2) Plain plugin params (Arp Rate, CC LFO Freq, ...): the
    //      plugin author signals "this is part of the performance CC
    //      surface" by setting `default_cc` on the dataclass.
    //      Without that marker, no popup fires — keeps setup-group
    //      wheels (Sync, Arp Ch, Ctrl Ch, BPM, ...) silent.
    let onBind;
    if (displayCtx && displayCtx.openCellBinding && displayCtx.instanceId) {
        onBind = (paramName) => displayCtx.openCellBinding(displayCtx.instanceId, paramName);
    } else {
        const optedIn = param.default_cc !== undefined && param.default_cc !== null;
        onBind = (optedIn && displayCtx && displayCtx.openCcBinding && displayCtx.instanceId)
            ? (paramName) => displayCtx.openCcBinding(displayCtx.instanceId, paramName)
            : undefined;
    }

    switch (param.type) {
        case 'wheel': {
            const df = param.display_factor;
            const lbls = param.labels;
            const tl = lbls && lbls.length ? (v) => lbls[v - (param.min || 0)] || v
                : df ? (v) => (v * df) % 1 === 0 ? `${v * df}${param.unit || ''}` : `${(v * df).toFixed(1)}${param.unit || ''}`
                : param.unit ? (v) => `${v}${param.unit}` : null;
            return html`<${PluginWheel} name=${param.name} label=${param.label}
                min=${param.min} max=${param.max} value=${val != null ? val : param.default}
                onChange=${onChange} tickLabel=${tl}
                mini=${param.mini} wide=${param.wide} onBindRequest=${onBind} />`;
        }
        case 'knob':
            return html`<${PluginKnob} name=${param.name} label=${param.label}
                min=${param.min} max=${param.max} value=${val != null ? val : param.default}
                displayFactor=${param.display_factor} unit=${param.unit} labels=${param.labels}
                onChange=${onChange} onBindRequest=${onBind} />`;
        case 'fader':
            return html`<${PluginFader} name=${param.name} label=${param.label}
                min=${param.min} max=${param.max} value=${val != null ? val : param.default}
                vertical=${param.vertical} onChange=${onChange}
                displayFactor=${param.display_factor} displayFormat=${param.display_format}
                onBindRequest=${onBind} />`;
        case 'radio':
            return html`<${PluginRadio} name=${param.name} label=${param.label}
                options=${param.options} value=${val != null ? val : param.default}
                onChange=${onChange} onBindRequest=${onBind} />`;
        case 'button':
            return html`<${PluginButton} name=${param.name} label=${param.label}
                value=${val != null ? val : param.default} color=${param.color}
                trigger=${param.trigger} mini=${param.mini} onChange=${onChange}
                onBindRequest=${onBind} />`;
        case 'stepeditor':
            return html`<${PluginStepEditor} name=${param.name} label=${param.label}
                value=${val || []} onChange=${onChange}
                lengthParam=${param.length_param} allValues=${allValues}
                defaultOn=${param.default_on}
                slotNotesParam=${param.slot_notes_param}
                overrideMode=${param.override_mode}
                algoUnderlayParam=${param.algo_underlay_param} />`;
        case 'cartesiangrid':
            return html`<${PluginCartesianGrid} name=${param.name} label=${param.label}
                value=${val || []} onChange=${onChange} cols=${param.cols}
                sizeParam=${param.size_param} sizes=${param.sizes}
                playheadParam=${param.playhead_param}
                defaultOn=${param.default_on} allValues=${allValues} />`;
        case 'curveeditor':
            return html`<${PluginCurveEditor} name=${param.name} label=${param.label}
                value=${val} onChange=${onChange} />`;
        case 'noteselect':
            return html`<${PluginNoteSelect} name=${param.name} label=${param.label}
                value=${val != null ? val : param.default || 60} onChange=${onChange}
                learnable=${param.learnable !== false} onBindRequest=${onBind} />`;
        case 'ccselect':
            return html`<${PluginCCSelect} name=${param.name} label=${param.label}
                value=${val != null ? val : (param.default != null ? param.default : -1)}
                onChange=${onChange} />`;
        case 'channelselect':
            return html`<${PluginChannelSelect} name=${param.name} label=${param.label}
                value=${val != null ? val : (param.default != null ? param.default : 1)}
                allowAny=${!!param.allow_any} onChange=${onChange} />`;
        case 'display': {
            if (!displayCtx) return null;
            const dout = (displayCtx.outputs || []).find(d => d.name === param.display_name);
            if (!dout) return null;
            const dv = displayCtx.values && displayCtx.values[param.display_name];
            if (dout.type === 'scope') return html`<div class="display-scope-wrap" style="min-width:0"><${DisplayScope} label=${dout.label} value=${dv} min=${dout.min} max=${dout.max} duration=${dout.duration} /></div>`;
            if (dout.type === 'meter') return html`<${DisplayMeter} label=${dout.label} value=${dv} min=${dout.min} max=${dout.max} />`;
            return null;
        }
        case 'dropbuttonrow': {
            return html`<${PluginDropButtonRow} param=${param}
                values=${allValues} onChange=${onChange}
                displayCtx=${displayCtx} />`;
        }
        case 'xypad': {
            const xy = val != null ? val : { x: param.default_x, y: param.default_y };
            return html`<${PluginXYPad} name=${param.name} label=${param.label}
                min=${param.min} max=${param.max} value=${xy}
                springForce=${param.spring_force} springHome=${param.spring_home}
                onChange=${onChange} onBindRequest=${onBind} />`;
        }
        case 'layoutgrid':
            return html`<${PluginLayoutGrid} param=${param} values=${values}
                onChange=${onChange} displayCtx=${displayCtx}
                renderParam=${renderParam} />`;
        case 'trackergrid':
            // play_only filtering now happens generically in
            // renderParamList / renderParamGroup; per-type opt-in
            // is no longer needed here.
            return html`<${PluginTrackerGrid} param=${param} values=${values}
                onChange=${onChange} displayCtx=${displayCtx} />`;
        case 'patternstrip': {
            // Renders inline as the trailing param of the play
            // surface. Tap → flips the active-slot int; long-press →
            // dispatches Paste / Reset via `cmd_param`. No queued /
            // playing / empty modifiers on this side (the strip
            // plugins keep every slot populated).
            const onTap = (idx) => onChange(param.name, idx);
            const onCmd = param.cmd_param
                ? (idx, mode) => onChange(param.cmd_param, { slot: idx, mode })
                : undefined;
            return html`<${PluginPatternBank}
                count=${param.count || 8}
                selected=${val}
                stateKey=${`${displayCtx?.instanceId || 'na'}:${param.name}`}
                onTap=${onTap}
                onCmd=${onCmd} />`;
        }
        default:
            return html`<div style="color:var(--text-dim);font-size:12px">Unknown: ${param.type}</div>`;
    }
}

export const INLINE_TYPES = new Set(['wheel', 'knob', 'fader', 'noteselect', 'ccselect', 'channelselect', 'button', 'display', 'xypad']);

function isInline(p) {
    return INLINE_TYPES.has(p.type);
}

// Wrap a rendered inline param with a grid-column-span container if
// the param schema declares a span > 1. Single-cell params render as-is.
function applySpan(rendered, span) {
    if (!span || span <= 1) return rendered;
    return html`<div class="param-cell" style="grid-column: span ${span}">${rendered}</div>`;
}

// Stamp a stable key on a vnode so Preact reconciles params by identity,
// not sibling index. Without this, a `visible_when` param appearing or
// disappearing shifts indices and Preact reuses a neighbour's component
// instance for a different param — bleeding its internal state (e.g. a
// Wheel's last displayed value). Keying by param name pins each control
// to its own instance. (Preact reads vnode.key at diff time, so setting
// it post-construction is honoured.)
function withKey(vnode, key) {
    if (vnode && typeof vnode === 'object') vnode.key = key;
    return vnode;
}

export function renderParamGroup(items, values, onChange, displayCtx, cols) {
    const result = [];
    let inlineRun = [];
    // Track the max span requested in the current run. A solo span=1 item
    // is left unwrapped (preserves Note Transpose's bare wheel etc.); a
    // solo item that asked for span>1 needs a param-row grid parent for
    // its grid-column-span to take effect.
    let inlineMaxSpan = 1;
    const rowStyle = cols && cols !== 4
        ? `grid-template-columns: repeat(${cols}, minmax(0, 1fr))`
        : null;
    const flushInline = () => {
        if (inlineRun.length === 0) return;
        if (inlineRun.length === 1 && inlineMaxSpan <= 1) result.push(inlineRun[0]);
        else if (rowStyle) result.push(html`<div class="param-row" style=${rowStyle}>${inlineRun}</div>`);
        else result.push(html`<div class="param-row">${inlineRun}</div>`);
        inlineRun = [];
        inlineMaxSpan = 1;
    };
    const playOnly = !!(displayCtx && displayCtx.playOnly);
    for (const p of items) {
        // config_only params (e.g. background colour picker) live in
        // the device-detail panel (which is now always in flat-config
        // mode for Controllers) and are hidden on play surfaces.
        // play_only is the mirror — performance controls that already
        // appear on the fullscreen Play surface, hidden from the
        // device-detail panel so they don't render twice.
        if (p.config_only && playOnly) continue;
        if (p.play_only && !playOnly) continue;
        // Honour visible_when on nested children (top-level
        // visible_when is checked in renderParamList; this branch
        // covers params + groups nested inside another Group).
        if (p.visible_when) {
            const cur = values[p.visible_when.param];
            const cv = p.visible_when.value;
            const matches = Array.isArray(cv) ? cv.includes(cur) : cur === cv;
            if (!matches) continue;
        }
        // Nested group — render its title + recurse into its
        // children. Without this branch a Group-inside-Group falls
        // through to renderParam's `Unknown` default.
        if (p.type === 'group') {
            flushInline();
            result.push(html`<${PluginGroup} key=${`group:${p.title}`} title=${p.title}>
                ${renderParamGroup(p.children, values, onChange, displayCtx, p.cols)}
            <//>`);
            continue;
        }
        const rendered = renderParam(p, values, onChange, values, displayCtx);
        if (!rendered) continue;
        if (isInline(p)) {
            inlineRun.push(withKey(applySpan(rendered, p.span), p.name));
            if (p.span && p.span > inlineMaxSpan) inlineMaxSpan = p.span;
        }
        else { flushInline(); result.push(withKey(rendered, p.name)); }
    }
    flushInline();
    return result;
}

export function renderParamList(params, values, onChange, displayCtx) {
    if (!params) return null;
    const playOnly = !!(displayCtx && displayCtx.playOnly);
    const expanded = [];
    for (const p of params) {
        if (p.config_only && playOnly) continue;
        if (p.play_only && !playOnly) continue;
        if (p.visible_when) {
            const cur = values[p.visible_when.param];
            const cv = p.visible_when.value;
            const matches = Array.isArray(cv) ? cv.includes(cur) : cur === cv;
            if (!matches) continue;
        }
        if (p.type === 'group') expanded.push({ _isGroup: true, title: p.title, children: p.children, cols: p.cols });
        else expanded.push(p);
    }
    const result = [];
    let inlineRun = [];
    // See renderParamGroup — a solo span>1 item needs a param-row grid
    // parent for the column span to take effect; solo span=1 stays bare.
    let inlineMaxSpan = 1;
    const flushInline = () => {
        if (inlineRun.length === 0) return;
        if (inlineRun.length === 1 && inlineMaxSpan <= 1) result.push(inlineRun[0]);
        else result.push(html`<div class="param-row">${inlineRun}</div>`);
        inlineRun = [];
        inlineMaxSpan = 1;
    };
    for (const p of expanded) {
        if (p._isGroup) {
            flushInline();
            result.push(html`<${PluginGroup} key=${`group:${p.title}`} title=${p.title}>
                ${renderParamGroup(p.children, values, onChange, displayCtx, p.cols)}
            <//>`);
        } else {
            const rendered = renderParam(p, values, onChange, values, displayCtx);
            if (!rendered) continue;
            // Apply span here too — renderParamGroup already does this
            // for grouped params, but top-level inline params (e.g. the
            // Arpeggiator's Pattern + Rate wheels) need the same path
            // so `span=2` actually widens the grid cell.
            if (isInline(p)) {
                inlineRun.push(withKey(applySpan(rendered, p.span), p.name));
                if (p.span && p.span > inlineMaxSpan) inlineMaxSpan = p.span;
            }
            else { flushInline(); result.push(withKey(rendered, p.name)); }
        }
    }
    flushInline();
    return result;
}

export function PluginConfigPanel({ instanceId, paramsSchema, params, onParamChange, inputs, outputs, displayOutputs, displayValues, openCcBinding }) {
    // Plugin-config panel is always in config / flat-list mode now —
    // the live cell view lives on the Controller page exclusively. Auto-
    // saves on change like every other plugin param. No Save button.
    const bgChoice = ((params && params.bg) || 'Default').toString().toLowerCase();
    const displayCtx = {
        outputs: displayOutputs,
        values: displayValues,
        instanceId,
        openCcBinding,
    };
    return html`<div class=${`plugin-config-preview bg-${bgChoice}`}>
        ${renderParamList(paramsSchema, params, onParamChange, displayCtx)}

        ${outputs && outputs.length > 0 && html`
            <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--surface2)">
                <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:6px">Outputs</div>
                <div style="font-size:12px;color:var(--text)">${outputs.join(', ')}</div>
            </div>
        `}
    </div>`;
}
