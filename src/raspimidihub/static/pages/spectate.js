/**
 * SpectatorView — re-renders the same UI as a chosen source device,
 * driven by the source's broadcast `spectator-state` events.
 *
 * Boot path: when `?spectate=<conn_id>` is in the URL, app.js mounts
 * this component instead of the normal <App/>. We then mount <App/>
 * ourselves inside a fixed-pixel wrapper sized to the source's
 * viewport and CSS-transform-scaled to fit ours. The mirrored App
 * reads route via setRouterExternalSource and overlay state via
 * SpectatorContext.
 *
 * Two EventSources end up open on a spectator tab:
 *
 *   1. ours, used only for `connection` (to learn our conn_id), the
 *      lifecycle events (`spectator-state`, `spectator-source-gone`),
 *      and the eventual /api/sse/subscribe with `spectate_target`.
 *   2. App's, opened by its own useSSE() call — that's where MIDI /
 *      plugin-param / device events arrive so the mirrored UI shows
 *      the same live activity the source sees.
 *
 * Two connections per spectator tab is a modest cost (well under the
 * server cap of 30) and avoids a much bigger refactor of useSSE into
 * a shared bus.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from '../lib/hooks.module.js';
import { html } from '../ui/common.js';
import { SpectatorContext } from '../lib/shared-ui-state.js';
import { applyLayoutDensity } from '../components/common.js';
import { setRouterExternalSource } from '../ui/router.js';
import { TouchOverlay } from '../components/touchoverlay.js';

const DEFAULT_ROUTE = {
    tab: 'routing', controllerId: null, playId: null, deviceId: null,
    settingsSection: null,
};
const DEFAULT_VIEWPORT = { w: 412, h: 915 };  // a typical phone portrait

// Spectator mounts <App/> only after the snapshot fetch returns so
// the first render already has the right route / viewport / density.
// Without this, App renders the default route, then re-renders when
// the snapshot lands — visually jarring and sometimes leaks a click
// of "wrong view" through the OBS recording.
export function SpectatorView({ clientId, showTouches, AppComponent }) {
    const [snapshotLoaded, setSnapshotLoaded] = useState(false);
    const [sourceGone, setSourceGone] = useState(false);
    const [viewport, setViewport] = useState(DEFAULT_VIEWPORT);
    const [scale, setScale] = useState(1);
    const routeRef = useRef(DEFAULT_ROUTE);
    const routeSubsRef = useRef(new Set());
    const uiSubsRef = useRef(new Map());           // 'ui:<key>' -> Set<cb>
    // Latest received value for each ui:<key>, replayed when a
    // consumer subscribes after the event has already arrived. Two
    // races force this: (a) the snapshot may carry ui:* state but
    // App isn't mounted yet so no subscribers exist, and (b) the
    // source can publish between watch-start and our App mount.
    const uiLatestRef = useRef(new Map());
    // Latest scroll position per scrollable container (keyed by the
    // source's `data-spectator-scroll` attribute). Held as a ref so
    // we can re-apply after App mounts — the source typically
    // publishes its scroll before .main / .matrix exist on the
    // spectator's DOM.
    const scrollByKeyRef = useRef(new Map());
    const touchPointsRef = useRef([]);
    // Our SSE conn_id; needed to POST /api/sse/subscribe with our
    // spectate_target. Set when the EventSource emits `connection`.
    const ourConnIdRef = useRef(null);

    // Dispatchers for incoming state pieces. Kept in refs so the
    // EventSource handler closure (created once on mount) always
    // sees the current logic without re-binding.
    const applyState = useCallback((kind, value) => {
        if (kind === 'route') {
            const merged = { ...DEFAULT_ROUTE, ...(value || {}) };
            routeRef.current = merged;
            for (const cb of routeSubsRef.current) {
                try { cb(merged); } catch (err) { console.warn('route sub:', err); }
            }
        } else if (kind === 'viewport') {
            if (value && value.w > 0 && value.h > 0) {
                setViewport({ w: value.w, h: value.h });
            }
        } else if (kind === 'scroll') {
            if (!value) return;
            // New format carries a `key` matching the source's
            // `data-spectator-scroll` attribute so each scrollable
            // container (.main, .matrix, …) mirrors independently.
            // The y-only legacy shape is treated as key='main' for
            // forward-compatible snapshot replay.
            const key = value.key || 'main';
            const x = value.x || 0;
            const y = value.y || 0;
            scrollByKeyRef.current.set(key, { x, y });
            const el = document.querySelector(
                `.spectator-app-wrap [data-spectator-scroll="${key}"]`);
            if (el) { el.scrollTop = y; el.scrollLeft = x; }
        } else if (kind === 'density') {
            applyLayoutDensity(value || 'default');
        } else if (kind === 'touch') {
            if (!value) return;
            touchPointsRef.current.push({
                kind: value.kind,
                x: value.x,
                y: value.y,
                t: performance.now(),
            });
            // Soft cap so a long press doesn't grow the array forever
            // before the ripple animation drains it.
            if (touchPointsRef.current.length > 200) {
                touchPointsRef.current.splice(0, touchPointsRef.current.length - 200);
            }
        } else if (kind && kind.startsWith('ui:')) {
            // Cache the latest value so a subscriber that mounts AFTER
            // this event still picks it up (via replay in subscribe()).
            uiLatestRef.current.set(kind, value);
            const subs = uiSubsRef.current.get(kind);
            if (subs) for (const cb of subs) {
                try { cb(value); } catch (err) { console.warn('ui sub:', err); }
            }
        }
    }, []);

    // Install the router external source. App's useRouter() reads
    // this on mount — so it must be set BEFORE App renders.
    useEffect(() => {
        setRouterExternalSource({
            getRoute: () => routeRef.current,
            subscribe: (cb) => {
                routeSubsRef.current.add(cb);
                return () => routeSubsRef.current.delete(cb);
            },
        });
        return () => setRouterExternalSource(null);
    }, []);

    // Snapshot fetch + EventSource setup. Both gated by `clientId` so
    // that swapping targets via the picker re-runs cleanly.
    useEffect(() => {
        let cancelled = false;
        // Step 1: GET the cached last_state so we don't render a
        // blank frame before the first live event lands.
        fetch(`/api/spectator/snapshot/${encodeURIComponent(clientId)}`)
            .then(r => r.json())
            .then(snap => {
                if (cancelled) return;
                const state = (snap && snap.state) || {};
                if (snap && snap.viewport) setViewport(snap.viewport);
                for (const [kind, value] of Object.entries(state)) {
                    applyState(kind, value);
                }
                setSnapshotLoaded(true);
            })
            .catch(() => { if (!cancelled) setSnapshotLoaded(true); });

        // Step 2: open the spectator EventSource. Once we have our
        // conn_id, POST /api/sse/subscribe with spectate_target so the
        // server marks us as a watcher of `clientId` and starts
        // routing spectator-state events to us. The server also
        // notifies the source via spectator-watch-start so its
        // broadcaster wakes up.
        const es = new EventSource('/api/events');
        es.addEventListener('connection', (e) => {
            try {
                const { conn_id } = JSON.parse(e.data);
                if (!conn_id) return;
                ourConnIdRef.current = conn_id;
                fetch('/api/sse/subscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        conn_id,
                        events: ['spectator-source-gone'],
                        instances: [],
                        spectate_target: clientId,
                    }),
                }).catch(() => {});
            } catch {}
        });
        es.addEventListener('spectator-state', (e) => {
            try {
                const d = JSON.parse(e.data);
                if (d.conn_id !== clientId) return;
                applyState(d.kind, d.value);
            } catch {}
        });
        es.addEventListener('spectator-source-gone', (e) => {
            try {
                const d = JSON.parse(e.data);
                if (d.conn_id === clientId) setSourceGone(true);
            } catch {}
        });
        return () => {
            cancelled = true;
            es.close();
        };
    }, [clientId, applyState]);

    // After App mounts (and on every route change inside it), apply
    // the most recently received scroll position to each scrollable
    // container. The first scroll events from the source typically
    // land before .main / .matrix exist on the spectator's DOM;
    // without this catch-up the mirror would render at the wrong
    // scroll position. We also re-run when routeRef changes via a
    // small tick — incoming route changes swap the matrix in/out.
    useEffect(() => {
        if (!snapshotLoaded) return undefined;
        const apply = () => {
            for (const [key, pos] of scrollByKeyRef.current) {
                const el = document.querySelector(
                    `.spectator-app-wrap [data-spectator-scroll="${key}"]`);
                if (el) { el.scrollTop = pos.y; el.scrollLeft = pos.x; }
            }
        };
        // Apply on mount, then again after rAF so route-swap mounts
        // (matrix shows up after switching to /routing) get caught.
        apply();
        const raf = requestAnimationFrame(apply);
        return () => cancelAnimationFrame(raf);
    }, [snapshotLoaded]);

    // Pick the largest uniform scale that fits the source viewport
    // into our window. Re-measure on window resize so OBS sources
    // and free-floating tabs both look right.
    useEffect(() => {
        const compute = () => {
            const sx = window.innerWidth / viewport.w;
            const sy = window.innerHeight / viewport.h;
            setScale(Math.min(sx, sy));
        };
        compute();
        window.addEventListener('resize', compute);
        return () => window.removeEventListener('resize', compute);
    }, [viewport.w, viewport.h]);

    // SpectatorContext value: register/unregister callbacks for
    // `ui:<key>` events so useSharedUiState consumers stay in sync.
    // Subscribers may mount AFTER an event has already arrived
    // (snapshot replay, or source publishing between watch-start
    // and App mount). The replay-on-subscribe below covers that
    // race; without it the first received value is silently
    // dropped and popups never appear.
    const ctxValue = useMemo(() => ({
        kind: 'spectator',
        broadcast: () => {},
        subscribe: (kind, cb) => {
            let set = uiSubsRef.current.get(kind);
            if (!set) { set = new Set(); uiSubsRef.current.set(kind, set); }
            set.add(cb);
            const last = uiLatestRef.current.get(kind);
            if (last !== undefined) {
                try { cb(last); } catch (err) { console.warn('ui replay:', err); }
            }
        },
        unsubscribe: (kind, cb) => {
            const set = uiSubsRef.current.get(kind);
            if (set) {
                set.delete(cb);
                if (set.size === 0) uiSubsRef.current.delete(kind);
            }
        },
    }), []);

    if (!snapshotLoaded) {
        return html`<div class="spectator-loading">Connecting to source…</div>`;
    }

    const wrapStyle = (
        `width:${viewport.w}px;height:${viewport.h}px;` +
        `transform:scale(${scale});transform-origin:0 0;` +
        `position:absolute;top:0;left:0;overflow:hidden`
    );

    return html`
        <${SpectatorContext.Provider} value=${ctxValue}>
            <div class="spectator-app-wrap" style=${wrapStyle}>
                <${AppComponent} />
                ${showTouches && html`<${TouchOverlay}
                    pointsRef=${touchPointsRef}
                    width=${viewport.w} height=${viewport.h} />`}
            </div>
            ${sourceGone && html`<div class="spectator-source-gone">
                Source disconnected. Waiting for it to come back…
            </div>`}
        </${SpectatorContext.Provider}>
    `;
}
