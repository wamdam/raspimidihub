/**
 * useSourceBroadcaster — dormant-by-default state broadcaster.
 *
 * A source device (i.e. a phone whose UI is being demonstrated)
 * publishes its viewport, scroll position, active route, layout
 * density, touch points, and overlay UI state to POST
 * /api/spectator/state so a spectator browser can mirror the same
 * view.
 *
 * Critically, listeners are attached ONLY when the server tells us
 * `spectator-watch-start` (i.e. at least one spectator subscribed to
 * us). On `spectator-watch-stop` everything detaches. Result: a
 * device that nobody is mirroring pays zero CPU and zero bandwidth
 * for this feature. The caller (App) owns the watched flag and
 * flips it from its useSSE callback.
 *
 * The returned context value plugs into SpectatorContext so
 * useSharedUiState calls broadcast() for overlay state changes.
 */

import { useCallback, useEffect, useMemo } from './hooks.module.js';
import { getSSEConnectionId } from '../ui/sse-subscriptions.js';
import { getLayoutDensity } from '../components/common.js';

// ~30 Hz floor for high-frequency signals. Scroll and touch ride the
// same throttle — the spectator's monitor is the bottleneck anyway
// (60 Hz typical), and 30 fps mirroring looks smooth without
// doubling the bandwidth.
const TICK_MS = 1000 / 30;

function postState(kind, value) {
    const conn_id = getSSEConnectionId();
    if (!conn_id) return;
    try {
        // Fire-and-forget; failures don't matter — the next change
        // will resend. JSON.stringify drops function-typed values
        // (e.g. menu-item onClick handlers) so the wire payload is
        // naturally view-only.
        fetch('/api/spectator/state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conn_id, kind, value }),
            keepalive: true,
        }).catch(() => {});
    } catch {}
}

export function useSourceBroadcaster({ watched, route }) {
    const broadcast = useCallback((kind, value) => {
        if (!watched) return;
        postState(kind, value);
    }, [watched]);

    // Broadcast route changes while watched. The router fires on every
    // history pushState; this just relays.
    useEffect(() => {
        if (!watched || !route) return;
        postState('route', route);
    }, [watched, route]);

    // Attach DOM listeners when watched flips on; detach on flip-off.
    // One useEffect, one cleanup — simpler than per-signal effects
    // for a feature that's all-on or all-off.
    useEffect(() => {
        if (!watched) return undefined;
        // Ask every useSharedUiState consumer to re-emit its current
        // value now that broadcasting is active. ui:* state changed
        // before this moment never reached the wire (broadcast was a
        // no-op, the snapshot cache stayed empty), so a late-joining
        // spectator wouldn't see open menus / popups otherwise.
        window.dispatchEvent(new CustomEvent('spectator-rebroadcast'));
        const cleanups = [];

        // Viewport — initial snapshot plus a resize listener. Phone
        // rotation, soft-keyboard pop, fullscreen entry all trigger
        // resize and the spectator rescales its wrapper to match.
        const sendViewport = () => postState('viewport', {
            w: window.innerWidth, h: window.innerHeight,
        });
        sendViewport();
        const onResize = () => sendViewport();
        window.addEventListener('resize', onResize);
        cleanups.push(() => window.removeEventListener('resize', onResize));

        // Scroll on .main — the matrix's scroll container. Throttled
        // to ~30 Hz via a single trailing-edge timer so a fast swipe
        // ships at most ~30 frames/s, not a burst per scroll tick.
        const main = document.querySelector('.main');
        let scrollTimer = null;
        let lastSentY = -1;
        let lastSentAt = 0;
        const flushScroll = () => {
            scrollTimer = null;
            if (!main) return;
            const y = main.scrollTop;
            if (y === lastSentY) return;
            lastSentY = y;
            lastSentAt = performance.now();
            postState('scroll', { y });
        };
        const onScroll = () => {
            const dt = performance.now() - lastSentAt;
            const delay = Math.max(0, TICK_MS - dt);
            if (scrollTimer == null) scrollTimer = setTimeout(flushScroll, delay);
        };
        if (main) {
            main.addEventListener('scroll', onScroll, { passive: true });
            cleanups.push(() => {
                main.removeEventListener('scroll', onScroll);
                if (scrollTimer != null) clearTimeout(scrollTimer);
            });
            // Initial position so the spectator opens at the right
            // place even if the source hasn't scrolled since load.
            postState('scroll', { y: main.scrollTop });
            lastSentY = main.scrollTop;
            lastSentAt = performance.now();
        }

        // Touch / pointer — window-level capture so events fire even
        // when the target calls stopPropagation. We send `down` and
        // `up` immediately (edges matter for ripple animation) and
        // throttle `move` to TICK_MS.
        let lastMoveAt = 0;
        let moveTimer = null;
        let pendingMove = null;
        const sendTouch = (kind, e) => {
            postState('touch', {
                kind,
                x: Math.round(e.clientX),
                y: Math.round(e.clientY),
                id: e.pointerId,
            });
        };
        const onDown = (e) => sendTouch('down', e);
        const onUp = (e) => {
            if (moveTimer != null) { clearTimeout(moveTimer); moveTimer = null; pendingMove = null; }
            sendTouch('up', e);
        };
        const onMove = (e) => {
            // Filter out unpressed mouse hover noise — the user expects
            // ripples only when the source is actively interacting.
            if (e.pointerType === 'mouse' && !e.buttons) return;
            const now = performance.now();
            const dt = now - lastMoveAt;
            if (dt >= TICK_MS) {
                lastMoveAt = now;
                sendTouch('move', e);
                return;
            }
            // Trailing-edge: remember the latest move and flush at
            // the next tick boundary. Coalesces a swipe into ~30 fps.
            pendingMove = e;
            if (moveTimer != null) return;
            moveTimer = setTimeout(() => {
                moveTimer = null;
                if (!pendingMove) return;
                lastMoveAt = performance.now();
                sendTouch('move', pendingMove);
                pendingMove = null;
            }, TICK_MS - dt);
        };
        window.addEventListener('pointerdown', onDown, { capture: true, passive: true });
        window.addEventListener('pointermove', onMove, { capture: true, passive: true });
        window.addEventListener('pointerup', onUp, { capture: true, passive: true });
        window.addEventListener('pointercancel', onUp, { capture: true, passive: true });
        cleanups.push(() => {
            window.removeEventListener('pointerdown', onDown, { capture: true });
            window.removeEventListener('pointermove', onMove, { capture: true });
            window.removeEventListener('pointerup', onUp, { capture: true });
            window.removeEventListener('pointercancel', onUp, { capture: true });
            if (moveTimer != null) clearTimeout(moveTimer);
        });

        // Density — broadcast initial value + react to changes.
        // setLayoutDensity in components/common.js dispatches the
        // `layout-density-changed` CustomEvent for us to hook.
        const onDensityChange = (e) => postState('density', e.detail);
        window.addEventListener('layout-density-changed', onDensityChange);
        cleanups.push(() => window.removeEventListener('layout-density-changed', onDensityChange));
        postState('density', getLayoutDensity());

        return () => cleanups.forEach(c => { try { c(); } catch {} });
    }, [watched]);

    // Stable context value — re-creating per render would force every
    // useSharedUiState consumer to re-run its effects unnecessarily.
    return useMemo(() => ({
        kind: 'source',
        broadcast,
        subscribe: () => {},
        unsubscribe: () => {},
    }), [broadcast]);
}
