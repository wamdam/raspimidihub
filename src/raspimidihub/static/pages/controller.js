/**
 * Controller fullscreen page.
 *
 * Lists all Controller plugin instances (filtered by plugin_type
 * starting with `controller_`) and renders the selected one as a
 * fullscreen play surface. The drop pad + LayoutGrid fill the page
 * so the user can drive a tablet or phone like dedicated hardware.
 *
 * Last-viewed instance persists in
 * `localStorage["raspimidihub:lastController"]` per device, so
 * coming back to the Controller tab opens the same surface.
 */

import { html, api } from '../ui/common.js';
import { useEffect, useState, useCallback } from '../lib/hooks.module.js';
import { renderParamList } from '../components/renderparam.js';
import { usePluginParams } from '../ui/plugin-params.js';

const LAST_KEY = 'raspimidihub:lastController';

function ControllerSurface({ instance, pluginData, pluginDisplays }) {
    const {
        params: pluginParams,
        setParams: setPluginParams,
        onParamChange: onPluginParamChange,
    } = usePluginParams({
        instanceId: instance.id,
        paramsSchema: pluginData?.params_schema,
        pluginDisplays,
    });

    // Seed local params from the fetched instance data — usePluginParams
    // starts at {} so the cells would render with their schema defaults
    // instead of the user's saved positions until SSE caught up.
    useEffect(() => {
        if (pluginData?.params) setPluginParams(pluginData.params);
    }, [pluginData?.params]);

    if (!pluginData) {
        return html`<div class="controller-loading">Loading…</div>`;
    }
    const displayCtx = {
        outputs: pluginData.display_outputs,
        values: (pluginDisplays && pluginDisplays[instance.id]) || {},
        // ControllerPage is a play surface — never show the LayoutGrid's
        // edit toggle. Editing happens in the device-detail panel.
        playOnly: true,
    };
    return html`<div class="controller-surface">
        ${renderParamList(pluginData.params_schema, pluginParams, onPluginParamChange, displayCtx)}
    </div>`;
}

export function ControllerPage({ pluginDisplays, showToast }) {
    const [instances, setInstances] = useState([]);
    const [selectedId, setSelectedIdRaw] = useState(null);
    const [pluginData, setPluginData] = useState(null);

    const setSelectedId = useCallback((id) => {
        setSelectedIdRaw(id);
        if (id) {
            try { localStorage.setItem(LAST_KEY, id); } catch {}
        }
    }, []);

    const refreshList = useCallback(async () => {
        try {
            const list = await api('/plugins/instances');
            const controllers = (list || [])
                .filter((i) => (i.type || '').startsWith('controller_'))
                .sort((a, b) => (a.id < b.id ? -1 : 1));
            setInstances(controllers);
            if (controllers.length === 0) {
                setSelectedIdRaw(null);
                setPluginData(null);
                return;
            }
            const stored = (() => { try { return localStorage.getItem(LAST_KEY); } catch { return null; } })();
            const hasStored = stored && controllers.some((c) => c.id === stored);
            const id = hasStored ? stored : controllers[0].id;
            setSelectedIdRaw(id);
        } catch {}
    }, []);

    useEffect(() => { refreshList(); }, [refreshList]);

    // Fetch the selected instance's full data (including params_schema)
    // whenever the selection changes.
    useEffect(() => {
        if (!selectedId) { setPluginData(null); return; }
        api(`/plugins/instances/${selectedId}`)
            .then(setPluginData)
            .catch(() => setPluginData(null));
    }, [selectedId]);

    // --- Empty state: no controllers yet.
    if (instances.length === 0) {
        return html`<div class="page controller-page">
            <div class="controller-empty">
                <p>No Controller plugins yet.</p>
                <p style="font-size:12px;color:var(--text-dim);margin-top:8px">
                    Add one from the Routing tab — pick "Controller — Mixer 8",
                    "Controller — Performance 16" or "Controller — FX 6".
                </p>
            </div>
        </div>`;
    }

    const selected = instances.find((i) => i.id === selectedId) || instances[0];
    const tabIndex = instances.findIndex((i) => i.id === selected.id);
    const prev = tabIndex > 0 ? instances[tabIndex - 1] : null;
    const next = tabIndex < instances.length - 1 ? instances[tabIndex + 1] : null;

    return html`<div class="page controller-page">
        <div class="controller-bar">
            <button class="controller-arrow" disabled=${!prev}
                onclick=${() => prev && setSelectedId(prev.id)}>‹</button>
            <select class="controller-select"
                value=${selected.id}
                onchange=${(e) => setSelectedId(e.target.value)}>
                ${instances.map((i) => html`
                    <option value=${i.id}>${i.name}</option>
                `)}
            </select>
            <button class="controller-arrow" disabled=${!next}
                onclick=${() => next && setSelectedId(next.id)}>›</button>
        </div>
        <${ControllerSurface}
            key=${selected.id}
            instance=${selected}
            pluginData=${pluginData && pluginData.id === selected.id ? pluginData : null}
            pluginDisplays=${pluginDisplays} />
    </div>`;
}
