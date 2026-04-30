/**
 * Controller fullscreen page.
 *
 * Lists all Controller plugin instances (filtered by plugin_type
 * starting with `controller_`) and renders the selected one as a
 * fullscreen play surface. The drop pad + LayoutGrid fill the page
 * so the user can drive a tablet or phone like dedicated hardware.
 *
 * Selection lives in the URL (`/controller/<instance_id>`) — the
 * router is the single source of truth, so reload / back / forward /
 * bookmark all do the obvious thing. When the URL has no id the page
 * defaults to the first instance via `replaceState` (no extra history
 * entry). No localStorage needed any more — the URL preserves state.
 */

import { html, api } from '../ui/common.js';
import { useEffect, useState, useCallback, useRef } from '../lib/hooks.module.js';
import { useSSESubscription } from '../ui/sse-subscriptions.js';
import { renderParamList } from '../components/renderparam.js';
import { usePluginParams } from '../ui/plugin-params.js';

// Horizontal-swipe thresholds for instance switching. Need a clear
// horizontal intent: at least SWIPE_MIN px sideways AND more than 2x
// the vertical movement, finished within a short window.
const SWIPE_MIN_PX = 50;
const SWIPE_MAX_MS = 700;

function ControllerSurface({ instance, pluginData, pluginDisplays, clockPosition }) {
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
        // Live clock-bus heartbeat (broadcast every quarter); used by
        // the drop-button rings to advance even when no schedule is
        // active. Null when no clock is running.
        clockPosition,
    };
    return html`<div class="controller-surface">
        ${renderParamList(pluginData.params_schema, pluginParams, onPluginParamChange, displayCtx)}
    </div>`;
}

export function ControllerPage({ pluginDisplays, showToast, selectedId, onSelect, onEditConfig, clockPosition }) {
    // Subscribe only to plugin events for the currently-selected
    // instance — that's the only plugin whose cells are visible. Also
    // grab transport-start so the surface can react to global play /
    // stop. App-level baseline already covers plugin-changed for the
    // dropdown.
    useSSESubscription(
        // clock-position drives the always-running drop-button rings —
        // the controller surface needs the live tick count to advance
        // their segments in time with the music.
        ['transport-start', 'clock-position'],
        selectedId ? [selectedId] : [],
    );
    const [instances, setInstances] = useState([]);
    const [pluginData, setPluginData] = useState(null);
    // null = haven't fetched yet; true = fetched at least once. Lets us
    // tell "really empty" apart from "the API is still loading", so we
    // don't flash "No Controller plugins yet" while the fetch is in
    // flight on a slow Pi.
    const [loaded, setLoaded] = useState(false);

    // Public setter: notifies the router; the URL update flows back as
    // a new selectedId prop on the next render.
    const setSelectedId = useCallback((id) => {
        if (onSelect) onSelect(id);
    }, [onSelect]);

    const refreshList = useCallback(async () => {
        try {
            const list = await api('/plugins/instances');
            const controllers = (list || [])
                .filter((i) => (i.type || '').startsWith('controller_'))
                .sort((a, b) => (a.id < b.id ? -1 : 1));
            setInstances(controllers);
            setLoaded(true);
            if (controllers.length === 0) {
                setPluginData(null);
                return;
            }
            // If the URL has no id (or an id not in the list), default to
            // the first instance via replaceState — no new history entry.
            const haveValid = selectedId && controllers.some((c) => c.id === selectedId);
            if (!haveValid && onSelect) {
                onSelect(controllers[0].id, { replace: true });
            }
        } catch {
            setLoaded(true);  // even on failure, show empty state rather than spin forever
        }
    }, [selectedId, onSelect]);

    useEffect(() => { refreshList(); }, [refreshList]);

    // Fetch the selected instance's full data (including params_schema)
    // whenever the selection changes.
    useEffect(() => {
        if (!selectedId) { setPluginData(null); return; }
        api(`/plugins/instances/${selectedId}`)
            .then(setPluginData)
            .catch(() => setPluginData(null));
    }, [selectedId]);

    // --- Loading: fetch in flight, don't flash the empty state.
    if (!loaded) {
        return html`<div class="page controller-page">
            <div class="controller-loading">Loading…</div>
        </div>`;
    }
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

    // Page-level horizontal swipe to switch instances. Knobs / faders /
    // buttons / wheels all stopPropagation in their own touchstart, so
    // a touch that starts on a control never reaches this handler —
    // adjusting a control wins over swiping. Empty space, the controller
    // bar, and the surface around cells all bubble up here.
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

    // Read the per-instance background choice off the SSE-broadcast
    // params (avoids waiting for the slower instance fetch to land).
    const sseParams = (pluginDisplays && pluginDisplays['_params_' + selected.id]) || {};
    const bgChoice = (sseParams.bg || 'Default').toString().toLowerCase();

    return html`<div class="page controller-page bg-${bgChoice}"
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
        <${ControllerSurface}
            key=${selected.id}
            instance=${selected}
            pluginData=${pluginData && pluginData.id === selected.id ? pluginData : null}
            pluginDisplays=${pluginDisplays}
            clockPosition=${clockPosition} />
    </div>`;
}
