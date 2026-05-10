/**
 * Play fullscreen page — sequencers (kind === "play").
 *
 * Mirrors ControllerPage's surface-carousel pattern: lists every
 * plugin instance with `kind === "play"` (Tracker, future sequencer
 * plugins) and renders the selected one as a fullscreen play surface
 * via the same renderParamList machinery.
 *
 * Selection lives in the URL (`/play/<instance_id>`) — same router
 * conventions as the Controller page.
 */

import { html, api } from '../ui/common.js';
import { useEffect, useState, useCallback, useRef } from '../lib/hooks.module.js';
import { useSSESubscription } from '../ui/sse-subscriptions.js';
import { renderParamList } from '../components/renderparam.js';
import { usePluginParams } from '../ui/plugin-params.js';

const SWIPE_MIN_PX = 50;
const SWIPE_MAX_MS = 700;

function PlaySurface({ instance, pluginData, pluginDisplays, clockPosition }) {
    const {
        params: pluginParams,
        setParams: setPluginParams,
        onParamChange: onPluginParamChange,
    } = usePluginParams({
        instanceId: instance.id,
        paramsSchema: pluginData?.params_schema,
        pluginDisplays,
    });
    useEffect(() => {
        if (pluginData?.params) setPluginParams(pluginData.params);
    }, [pluginData?.params]);

    if (!pluginData) {
        return html`<div class="controller-loading">Loading…</div>`;
    }
    const displayCtx = {
        outputs: pluginData.display_outputs,
        values: (pluginDisplays && pluginDisplays[instance.id]) || {},
        playOnly: true,
        clockPosition,
    };
    return html`<div class="controller-surface">
        ${renderParamList(pluginData.params_schema, pluginParams, onPluginParamChange, displayCtx)}
    </div>`;
}

export function PlayPage({ pluginDisplays, showToast, selectedId, onSelect, onEditConfig, clockPosition }) {
    useSSESubscription(
        ['transport-start', 'clock-position'],
        selectedId ? [selectedId] : [],
    );
    const [instances, setInstances] = useState([]);
    const [pluginData, setPluginData] = useState(null);
    const [loaded, setLoaded] = useState(false);

    const setSelectedId = useCallback((id) => {
        if (onSelect) onSelect(id);
    }, [onSelect]);

    const refreshList = useCallback(async () => {
        try {
            const list = await api('/plugins/instances');
            const surfaces = (list || [])
                .filter((i) => i.kind === 'play')
                .sort((a, b) => (a.id < b.id ? -1 : 1));
            setInstances(surfaces);
            setLoaded(true);
            if (surfaces.length === 0) {
                setPluginData(null);
                return;
            }
            const haveValid = selectedId && surfaces.some((s) => s.id === selectedId);
            if (!haveValid && onSelect) {
                onSelect(surfaces[0].id, { replace: true });
            }
        } catch {
            setLoaded(true);
        }
    }, [selectedId, onSelect]);

    useEffect(() => { refreshList(); }, [refreshList]);

    useEffect(() => {
        if (!selectedId) { setPluginData(null); return; }
        api(`/plugins/instances/${selectedId}`)
            .then(setPluginData)
            .catch(() => setPluginData(null));
    }, [selectedId]);

    if (!loaded) {
        return html`<div class="page controller-page">
            <div class="controller-loading">Loading…</div>
        </div>`;
    }
    if (instances.length === 0) {
        return html`<div class="page controller-page">
            <div class="controller-empty">
                <p>No Play surfaces yet.</p>
                <p style="font-size:12px;color:var(--text-dim);margin-top:8px">
                    Add one from the Routing tab — for now, "Tracker".
                </p>
            </div>
        </div>`;
    }

    const selected = instances.find((i) => i.id === selectedId) || instances[0];
    const tabIndex = instances.findIndex((i) => i.id === selected.id);
    const prev = tabIndex > 0 ? instances[tabIndex - 1] : null;
    const next = tabIndex < instances.length - 1 ? instances[tabIndex + 1] : null;

    const swipeRef = useRef({ x: 0, y: 0, t: 0, active: false });
    const onTouchStart = useCallback((e) => {
        const t = e.changedTouches && e.changedTouches[0];
        if (!t) return;
        swipeRef.current = { x: t.clientX, y: t.clientY, t: Date.now(), active: true };
    }, []);
    const onTouchEnd = useCallback((e) => {
        const s = swipeRef.current;
        if (!s.active) return;
        s.active = false;
        const t = e.changedTouches && e.changedTouches[0];
        if (!t) return;
        const dx = t.clientX - s.x;
        const dy = t.clientY - s.y;
        const dt = Date.now() - s.t;
        if (dt > SWIPE_MAX_MS) return;
        if (Math.abs(dx) < SWIPE_MIN_PX) return;
        if (Math.abs(dx) < Math.abs(dy) * 2) return;
        if (dx < 0 && next) setSelectedId(next.id);
        else if (dx > 0 && prev) setSelectedId(prev.id);
    }, [prev, next, setSelectedId]);

    return html`<div class="page controller-page"
            ontouchstart=${onTouchStart}
            ontouchend=${onTouchEnd}
            ontouchcancel=${onTouchEnd}>
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
            ${onEditConfig ? html`<button class="controller-arrow"
                title="Edit plugin config"
                onclick=${() => onEditConfig(selected.id)}>✎</button>` : null}
            <button class="controller-arrow" disabled=${!next}
                onclick=${() => next && setSelectedId(next.id)}>›</button>
        </div>
        <${PlaySurface}
            key=${selected.id}
            instance=${selected}
            pluginData=${pluginData && pluginData.id === selected.id ? pluginData : null}
            pluginDisplays=${pluginDisplays}
            clockPosition=${clockPosition} />
    </div>`;
}
