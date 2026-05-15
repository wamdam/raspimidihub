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
// One pagination "page" is 80% of the visible viewport so the
// previous page's tail row is still in view after the tap.
const PAGE_FACTOR = 0.8;

// Plugins that need pagination — currently identified by their
// schema containing a `patternstrip` param. The Tracker doesn't
// declare one and keeps its own internal scroll target, so it's
// left out of the pager.
function needsPager(schema) {
    if (!schema) return false;
    for (const p of schema) {
        if (p && p.type === 'patternstrip') return true;
    }
    return false;
}

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

    const pagerRef = useRef(null);
    const contentRef = useRef(null);
    const [canUp, setCanUp] = useState(false);
    const [canDown, setCanDown] = useState(false);
    const usePager = pluginData ? needsPager(pluginData.params_schema) : false;

    useEffect(() => {
        if (!usePager) return;
        const el = pagerRef.current;
        const inner = contentRef.current;
        if (!el || !inner) return;
        let raf = 0;
        const update = () => {
            raf = 0;
            const top = el.scrollTop;
            const maxScroll = el.scrollHeight - el.clientHeight;
            setCanUp(top > 4);
            setCanDown(maxScroll > 4 && top < maxScroll - 4);
        };
        const onScroll = () => {
            if (raf) return;
            raf = requestAnimationFrame(update);
        };
        el.addEventListener('scroll', onScroll, { passive: true });
        // Observe the inner content wrapper (rather than the pager
        // itself or just its first child) so any in-place size
        // change — step count grew, slot load brought in a different
        // grid length, a Group expanded — re-evaluates the button
        // visibility immediately.
        const ro = new ResizeObserver(update);
        ro.observe(inner);
        ro.observe(el);  // viewport-size changes (rotate, density)
        update();
        return () => {
            el.removeEventListener('scroll', onScroll);
            ro.disconnect();
            if (raf) cancelAnimationFrame(raf);
        };
    }, [usePager, pluginData?.id]);

    const pageBy = useCallback((dir) => {
        const el = pagerRef.current;
        if (!el) return;
        const step = Math.max(60, el.clientHeight * PAGE_FACTOR);
        el.scrollTo({
            top: el.scrollTop + dir * step,
            behavior: 'smooth',
        });
    }, []);

    if (!pluginData) {
        return html`<div class="controller-loading">Loading…</div>`;
    }
    const displayCtx = {
        outputs: pluginData.display_outputs,
        values: (pluginDisplays && pluginDisplays[instance.id]) || {},
        playOnly: true,
        clockPosition,
    };

    // Plugins that don't declare a PatternStrip (e.g. the Tracker,
    // which has its own internal scroll target) keep the original
    // layout — no pager wrapper, no page buttons.
    if (!usePager) {
        return html`<div class="controller-surface">
            ${renderParamList(pluginData.params_schema, pluginParams, onPluginParamChange, displayCtx)}
        </div>`;
    }

    // Pattern strip renders inline at the end of the param flow (the
    // plugin already lists it last in `params`). Pagination buttons
    // float at the top / bottom of the visible viewport, conditional
    // on overflow in that direction. The inner `.play-pager-content`
    // wrapper exists for the ResizeObserver — it picks up content
    // height changes (step count, slot loads) that wouldn't fire on
    // a per-child observer.
    return html`<div class="play-surface-wrap">
        <div class="play-pager" ref=${pagerRef}>
            <div class="play-pager-content" ref=${contentRef}>
                ${renderParamList(pluginData.params_schema, pluginParams, onPluginParamChange, displayCtx)}
            </div>
        </div>
        ${canUp ? html`<button class="play-page-btn up"
            onclick=${() => pageBy(-1)}>↑ More</button>` : null}
        ${canDown ? html`<button class="play-page-btn down"
            onclick=${() => pageBy(1)}>↓ More</button>` : null}
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

    return html`<div class="page controller-page play-page"
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
