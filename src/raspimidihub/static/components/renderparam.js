/**
 * Render dispatcher — turns a param schema into the right component.
 */

import { html } from './common.js';
import { PluginWheel } from './wheel.js';
import { PluginFader } from './fader.js';
import { PluginRadio } from './radio.js';
import { PluginToggle } from './toggle.js';
import { PluginButton } from './button.js';
import { PluginStepEditor } from './stepeditor.js';
import { PluginCurveEditor } from './curveeditor.js';
import { PluginNoteSelect } from './noteselect.js';
import { PluginChannelSelect } from './channelselect.js';
import { PluginGroup } from './group.js';
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

    switch (param.type) {
        case 'wheel': {
            const df = param.display_factor;
            const lbls = param.labels;
            const tl = lbls && lbls.length ? (v) => lbls[v - (param.min || 0)] || v
                : df ? (v) => (v * df) % 1 === 0 ? `${v * df}${param.unit || ''}` : `${(v * df).toFixed(1)}${param.unit || ''}`
                : param.unit ? (v) => `${v}${param.unit}` : null;
            return html`<${PluginWheel} name=${param.name} label=${param.label}
                min=${param.min} max=${param.max} value=${val != null ? val : param.default}
                onChange=${onChange} tickLabel=${tl} />`;
        }
        case 'fader':
            return html`<${PluginFader} name=${param.name} label=${param.label}
                min=${param.min} max=${param.max} value=${val != null ? val : param.default}
                vertical=${param.vertical} onChange=${onChange}
                displayFactor=${param.display_factor} displayFormat=${param.display_format} />`;
        case 'radio':
            return html`<${PluginRadio} name=${param.name} label=${param.label}
                options=${param.options} value=${val != null ? val : param.default}
                onChange=${onChange} />`;
        case 'toggle':
            return html`<${PluginToggle} name=${param.name} label=${param.label}
                value=${val != null ? val : param.default} onChange=${onChange} />`;
        case 'button':
            return html`<${PluginButton} name=${param.name} label=${param.label}
                value=${val != null ? val : param.default} color=${param.color}
                onChange=${onChange} />`;
        case 'stepeditor':
            return html`<${PluginStepEditor} name=${param.name} label=${param.label}
                value=${val || []} onChange=${onChange}
                lengthParam=${param.length_param} allValues=${allValues}
                defaultOn=${param.default_on} />`;
        case 'curveeditor':
            return html`<${PluginCurveEditor} name=${param.name} label=${param.label}
                value=${val} onChange=${onChange} />`;
        case 'noteselect':
            return html`<${PluginNoteSelect} name=${param.name} label=${param.label}
                value=${val != null ? val : param.default || 60} onChange=${onChange}
                learnable=${param.learnable !== false} />`;
        case 'channelselect':
            return html`<${PluginChannelSelect} name=${param.name} label=${param.label}
                value=${val != null ? val : param.default || 1} onChange=${onChange} />`;
        case 'display': {
            if (!displayCtx) return null;
            const dout = (displayCtx.outputs || []).find(d => d.name === param.display_name);
            if (!dout) return null;
            const dv = displayCtx.values && displayCtx.values[param.display_name];
            if (dout.type === 'scope') return html`<div style="flex:1;min-width:80px"><${DisplayScope} label=${dout.label} value=${dv} min=${dout.min} max=${dout.max} duration=${dout.duration} /></div>`;
            if (dout.type === 'meter') return html`<div style="flex:1;min-width:80px"><${DisplayMeter} label=${dout.label} value=${dv} min=${dout.min} max=${dout.max} /></div>`;
            return null;
        }
        default:
            return html`<div style="color:var(--text-dim);font-size:12px">Unknown: ${param.type}</div>`;
    }
}

export const INLINE_TYPES = new Set(['wheel', 'fader', 'noteselect', 'channelselect', 'toggle', 'button', 'display']);

export function renderParamGroup(items, values, onChange, displayCtx) {
    const result = [];
    let inlineRun = [];
    const flushInline = () => {
        if (inlineRun.length === 0) return;
        if (inlineRun.length === 1) result.push(inlineRun[0]);
        else result.push(html`<div class="param-row">${inlineRun}</div>`);
        inlineRun = [];
    };
    for (const p of items) {
        const rendered = renderParam(p, values, onChange, values, displayCtx);
        if (!rendered) continue;
        if (INLINE_TYPES.has(p.type)) inlineRun.push(rendered);
        else { flushInline(); result.push(rendered); }
    }
    flushInline();
    return result;
}

export function renderParamList(params, values, onChange, displayCtx) {
    if (!params) return null;
    const expanded = [];
    for (const p of params) {
        if (p.type === 'group') expanded.push({ _isGroup: true, title: p.title, children: p.children });
        else expanded.push(p);
    }
    const result = [];
    let inlineRun = [];
    const flushInline = () => {
        if (inlineRun.length === 0) return;
        if (inlineRun.length === 1) result.push(inlineRun[0]);
        else result.push(html`<div class="param-row">${inlineRun}</div>`);
        inlineRun = [];
    };
    for (const p of expanded) {
        if (p._isGroup) {
            flushInline();
            result.push(html`<${PluginGroup} title=${p.title}>
                ${renderParamGroup(p.children, values, onChange, displayCtx)}
            <//>`);
        } else {
            const rendered = renderParam(p, values, onChange, values, displayCtx);
            if (!rendered) continue;
            if (INLINE_TYPES.has(p.type)) inlineRun.push(rendered);
            else { flushInline(); result.push(rendered); }
        }
    }
    flushInline();
    return result;
}

export function PluginConfigPanel({ instanceId, paramsSchema, params, onParamChange, inputs, outputs, ccInputs, displayOutputs, displayValues }) {
    const displayCtx = { outputs: displayOutputs, values: displayValues };
    return html`<div>
        ${renderParamList(paramsSchema, params, onParamChange, displayCtx)}

        ${inputs && inputs.length > 0 && html`
            <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--surface2)">
                <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:6px">Inputs</div>
                <div style="font-size:12px;color:var(--text)">${inputs.join(', ')}</div>
            </div>
        `}
        ${outputs && outputs.length > 0 && html`
            <div style="margin-top:8px">
                <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text-dim);margin-bottom:6px">Outputs</div>
                <div style="font-size:12px;color:var(--text)">${outputs.join(', ')}</div>
            </div>
        `}
        ${ccInputs && Object.keys(ccInputs).length > 0 && html`
            <div style="margin-top:8px;font-size:11px;color:var(--text-dim)">
                CC automation: ${Object.entries(ccInputs).map(([cc, param]) => `CC#${cc}\u2192${param}`).join(', ')}
            </div>
        `}
    </div>`;
}
