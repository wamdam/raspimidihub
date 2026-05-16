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

import { useCallback, useEffect, useMemo, useRef, useState } from '../hooks.module.js';
import { html } from '../../ui/common.js';
import { SpectatorContext } from './shared-ui-state.js';
import { applyLayoutDensity } from '../../components/common.js';
import { setRouterExternalSource } from '../../ui/router.js';
import { TouchOverlay } from './touchoverlay.js';

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
// Phone-frame bezel sizes (CSS pixels in source-viewport space).
// Tweak these and the scale-to-fit picks up new dimensions for free.
const FRAME_BEZEL = { top: 22, right: 8, bottom: 26, left: 8 };

export function SpectatorView({
    clientId, showTouches, AppComponent,
    frame: initialFrame, tiltX: initialTiltX, tiltY: initialTiltY,
    chroma: initialChroma,
}) {
    const [snapshotLoaded, setSnapshotLoaded] = useState(false);
    const [sourceGone, setSourceGone] = useState(false);
    const [viewport, setViewport] = useState(DEFAULT_VIEWPORT);
    const [scale, setScale] = useState(1);
    // Presentation knobs configurable via URL params and the floating
    // config panel. Drag on the background updates tilt live; the URL
    // is rewritten via replaceState so the result is shareable into
    // an OBS Browser Source.
    const [frame, setFrame] = useState(!!initialFrame);
    const [tiltX, setTiltX] = useState(initialTiltX || 0);
    const [tiltY, setTiltY] = useState(initialTiltY || 0);
    const [chroma, setChroma] = useState(initialChroma || '');
    const [controlsVisible, setControlsVisible] = useState(true);
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

    // Pick the largest uniform scale that fits the (optionally
    // framed) source viewport into our window. Re-measure on window
    // resize and when frame toggles so OBS sources, free-floating
    // tabs and frame on/off all look right.
    useEffect(() => {
        const compute = () => {
            const w = viewport.w + (frame ? FRAME_BEZEL.left + FRAME_BEZEL.right : 0);
            const h = viewport.h + (frame ? FRAME_BEZEL.top + FRAME_BEZEL.bottom : 0);
            const sx = window.innerWidth / w;
            const sy = window.innerHeight / h;
            // Tilt eats some headroom — apply a small safety factor
            // so a 30° tilt doesn't clip the corners outside the
            // viewport. cos(30°) ≈ 0.87; keep it simple and clamp.
            const tiltCost = Math.cos(Math.abs(tiltX) * Math.PI / 180) *
                             Math.cos(Math.abs(tiltY) * Math.PI / 180);
            setScale(Math.min(sx, sy) * Math.max(0.5, tiltCost));
        };
        compute();
        window.addEventListener('resize', compute);
        return () => window.removeEventListener('resize', compute);
    }, [viewport.w, viewport.h, frame, tiltX, tiltY]);

    // Mirror the live presentation knobs back to the URL via
    // replaceState so the same configuration survives a refresh and
    // can be pasted into OBS verbatim.
    useEffect(() => {
        try {
            const url = new URL(window.location.href);
            const set = (k, v) => { if (v) url.searchParams.set(k, v); else url.searchParams.delete(k); };
            set('frame', frame ? '1' : '');
            set('tilt-x', tiltX ? String(Math.round(tiltX)) : '');
            set('tilt-y', tiltY ? String(Math.round(tiltY)) : '');
            set('chroma', chroma || '');
            window.history.replaceState({}, '', url.toString());
        } catch {}
    }, [frame, tiltX, tiltY, chroma]);

    // Auto-hide the config panel after inactivity so OBS captures
    // stay clean. Mouse / touch movement reveals it again. OBS
    // doesn't send pointer events to its Browser Source, so once it
    // fades out it stays hidden in the captured feed.
    useEffect(() => {
        let hideTimer = null;
        const reveal = () => {
            setControlsVisible(true);
            if (hideTimer) clearTimeout(hideTimer);
            hideTimer = setTimeout(() => setControlsVisible(false), 2500);
        };
        reveal();
        window.addEventListener('pointermove', reveal);
        window.addEventListener('pointerdown', reveal);
        return () => {
            if (hideTimer) clearTimeout(hideTimer);
            window.removeEventListener('pointermove', reveal);
            window.removeEventListener('pointerdown', reveal);
        };
    }, []);

    // Background-drag to tilt. Pointer events on the chroma area
    // (outside the framed mirror) become a rotateX/rotateY drag.
    // Up/down → rotateX (peek over), left/right → rotateY.
    const dragRef = useRef(null);
    const onRootPointerDown = (e) => {
        // Ignore drags that start inside the config panel itself.
        if (e.target.closest && e.target.closest('.spectator-controls')) return;
        dragRef.current = {
            sx: e.clientX, sy: e.clientY,
            startX: tiltX, startY: tiltY,
            id: e.pointerId,
        };
        e.currentTarget.setPointerCapture(e.pointerId);
    };
    const onRootPointerMove = (e) => {
        const d = dragRef.current;
        if (!d || d.id !== e.pointerId) return;
        // ~0.3 deg per pixel feels natural; clamp to ±35° so the frame
        // never folds past the camera plane.
        const ry = Math.max(-35, Math.min(35, d.startY + (e.clientX - d.sx) * 0.3));
        const rx = Math.max(-35, Math.min(35, d.startX - (e.clientY - d.sy) * 0.3));
        setTiltX(rx);
        setTiltY(ry);
    };
    const onRootPointerUp = (e) => {
        if (dragRef.current && dragRef.current.id === e.pointerId) {
            dragRef.current = null;
            try { e.currentTarget.releasePointerCapture(e.pointerId); } catch {}
        }
    };

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
        `position:relative;overflow:hidden`
    );
    // .spectator-stage carries the fit-scale AND the user-configurable
    // tilt. Centred via flexbox on the root so the centred origin
    // keeps the framed device pinned no matter how it's rotated.
    const stageStyle = (
        `transform:scale(${scale}) rotateX(${tiltX}deg) rotateY(${tiltY}deg);` +
        `transform-origin:50% 50%;`
    );
    // chroma value passes through verbatim — accepts "#ff00ff" /
    // "magenta" / "rgb(...)" / etc. Empty string means default
    // (the existing dark backdrop); chroma-keying isn't requested.
    const rootStyle = chroma ? `background:${chroma}` : '';

    return html`
        <${SpectatorContext.Provider} value=${ctxValue}>
            <div class="spectator-root" style=${rootStyle}
                onpointerdown=${onRootPointerDown}
                onpointermove=${onRootPointerMove}
                onpointerup=${onRootPointerUp}
                onpointercancel=${onRootPointerUp}>
                <div class="spectator-stage" style=${stageStyle}>
                    <div class="spectator-frame ${frame ? 'with-frame' : ''}">
                        <div class="spectator-app-wrap" style=${wrapStyle}>
                            <${AppComponent} />
                            ${showTouches && html`<${TouchOverlay}
                                pointsRef=${touchPointsRef}
                                width=${viewport.w} height=${viewport.h} />`}
                        </div>
                    </div>
                </div>
                <${SpectatorControls}
                    visible=${controlsVisible}
                    frame=${frame} setFrame=${setFrame}
                    tiltX=${tiltX} setTiltX=${setTiltX}
                    tiltY=${tiltY} setTiltY=${setTiltY}
                    chroma=${chroma} setChroma=${setChroma}
                    onReset=${() => { setTiltX(0); setTiltY(0); }} />
                ${sourceGone && html`<div class="spectator-source-gone">
                    Source disconnected. Waiting for it to come back…
                </div>`}
            </div>
        </${SpectatorContext.Provider}>
    `;
}

// Floating control panel. Hidden in OBS captures (auto-fades on
// inactivity, never reappears because OBS doesn't deliver pointer
// events to its Browser Source). When opened directly in a browser
// tab the user can tweak every knob and copy the resulting URL —
// the configuration round-trips through URL params via replaceState.
function SpectatorControls({
    visible, frame, setFrame,
    tiltX, setTiltX, tiltY, setTiltY,
    chroma, setChroma, onReset,
}) {
    const copyUrl = async () => {
        try { await navigator.clipboard.writeText(window.location.href); } catch {}
    };
    const presets = ['', '#ff00ff', '#00ff00', '#000000'];
    return html`<div class="spectator-controls" style="opacity:${visible ? 1 : 0}">
        <div class="spectator-controls-row">
            <label><input type="checkbox" checked=${frame}
                onChange=${e => setFrame(e.target.checked)} /> Phone frame</label>
        </div>
        <div class="spectator-controls-row">
            <label>Tilt X <span>${Math.round(tiltX)}°</span></label>
            <input type="range" min="-35" max="35" value=${tiltX}
                onInput=${e => setTiltX(Number(e.target.value))} />
        </div>
        <div class="spectator-controls-row">
            <label>Tilt Y <span>${Math.round(tiltY)}°</span></label>
            <input type="range" min="-35" max="35" value=${tiltY}
                onInput=${e => setTiltY(Number(e.target.value))} />
        </div>
        <div class="spectator-controls-row">
            <label>Chroma</label>
            <input type="color" value=${chroma || '#ff00ff'}
                onInput=${e => setChroma(e.target.value)} />
            ${presets.map(p => html`<button class="spectator-chip"
                style=${p ? `background:${p}` : ''}
                title=${p || 'default'}
                onclick=${() => setChroma(p)}>${p ? '' : '×'}</button>`)}
        </div>
        <div class="spectator-controls-row">
            <button onclick=${onReset}>Reset tilt</button>
            <button onclick=${copyUrl}>Copy URL</button>
        </div>
        <div class="spectator-controls-hint">
            Drag the background to tilt. Settings persist in the URL.
        </div>
    </div>`;
}
