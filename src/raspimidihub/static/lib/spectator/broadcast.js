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

import { useCallback, useEffect, useMemo } from '../hooks.module.js';
import { getSSEConnectionId } from '../../ui/sse-subscriptions.js';
import { getLayoutDensity } from '../../components/common.js';

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
        // value now that broadcasting is active. Effects run in mount
        // order and this broadcaster effect runs BEFORE the consumer
        // effects in the same commit — dispatching synchronously hits
        // zero listeners. setTimeout(0) defers the dispatch to the
        // next task, after every consumer's useEffect has registered
        // its 'spectator-rebroadcast' listener. ui:* state changed
        // before this moment never reached the wire otherwise, so a
        // late-joining spectator wouldn't see open menus / popups.
        const rebroadcastTimer = setTimeout(() => {
            window.dispatchEvent(new CustomEvent('spectator-rebroadcast'));
        }, 0);
        const cleanups = [];
        cleanups.push(() => clearTimeout(rebroadcastTimer));

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

        // Scroll — direct per-element listeners. Window-level scroll
        // capture is unreliable across browsers (the scroll event
        // doesn't bubble and some engines won't propagate it past
        // the immediate target). Each scrollable container marks
        // itself with `data-spectator-scroll="<key>"`; we attach a
        // scroll listener to every such element present, and use a
        // MutationObserver to catch elements added later when the
        // user navigates between routes (e.g. the matrix appearing
        // after switching back to the routing tab).
        const lastSent = new Map();   // key -> { x, y, at }
        const pending = new Map();    // key -> timer id
        const attached = new WeakSet();
        const onScrollFn = new WeakMap(); // element -> handler (for removal)
        const flushScroll = (key, el) => {
            pending.delete(key);
            const x = el.scrollLeft, y = el.scrollTop;
            const prev = lastSent.get(key);
            if (prev && prev.x === x && prev.y === y) return;
            lastSent.set(key, { x, y, at: performance.now() });
            postState('scroll', { key, x, y });
        };
        const attachScrollEl = (el) => {
            if (attached.has(el)) return;
            const key = el.getAttribute('data-spectator-scroll');
            if (!key) return;
            attached.add(el);
            const handler = () => {
                const prev = lastSent.get(key);
                const dt = prev ? performance.now() - prev.at : Infinity;
                const delay = Math.max(0, TICK_MS - dt);
                if (!pending.has(key)) {
                    pending.set(key, setTimeout(() => flushScroll(key, el), delay));
                }
            };
            onScrollFn.set(el, handler);
            el.addEventListener('scroll', handler, { passive: true });
            // Initial snapshot so a late spectator picks up the
            // current position even if the user hasn't moved since.
            const x = el.scrollLeft, y = el.scrollTop;
            lastSent.set(key, { x, y, at: performance.now() });
            postState('scroll', { key, x, y });
        };
        // Attach to whatever exists at watch-start.
        for (const el of document.querySelectorAll('[data-spectator-scroll]')) {
            attachScrollEl(el);
        }
        // Catch elements mounted later. The matrix unmounts when the
        // user navigates away and remounts when they return.
        const observer = new MutationObserver((mutations) => {
            for (const m of mutations) {
                for (const node of m.addedNodes) {
                    if (node.nodeType !== 1) continue;
                    if (node.hasAttribute && node.hasAttribute('data-spectator-scroll')) {
                        attachScrollEl(node);
                    }
                    if (node.querySelectorAll) {
                        for (const inner of node.querySelectorAll('[data-spectator-scroll]')) {
                            attachScrollEl(inner);
                        }
                    }
                }
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
        cleanups.push(() => {
            observer.disconnect();
            for (const t of pending.values()) clearTimeout(t);
            pending.clear();
            for (const el of document.querySelectorAll('[data-spectator-scroll]')) {
                const h = onScrollFn.get(el);
                if (h) el.removeEventListener('scroll', h);
            }
        });

        // Touch / pointer — window-level capture so events fire even
        // when a target calls stopPropagation. We send `down` and
        // `up` immediately (edges matter for ripple animation) and
        // throttle `move` to TICK_MS.
        //
        // Two listener tracks:
        //   - Pointer events for mouse + pen (where touch === false).
        //   - Touch events for touchscreen. Pointer events stop
        //     firing once the browser claims a touch gesture for
        //     scrolling (it emits pointercancel and goes silent),
        //     so we'd lose the ripple mid-swipe. Touch events keep
        //     firing throughout the scroll, so we listen to those
        //     directly on touchscreens.
        let lastMoveAt = 0;
        let moveTimer = null;
        let pendingMove = null;
        const sendTouchPos = (kind, x, y, id) => {
            postState('touch', {
                kind, x: Math.round(x), y: Math.round(y), id,
            });
        };
        const onDown = (kind, x, y, id) => sendTouchPos(kind, x, y, id);
        const onUp = (x, y, id) => {
            if (moveTimer != null) { clearTimeout(moveTimer); moveTimer = null; pendingMove = null; }
            sendTouchPos('up', x, y, id);
        };
        const onMove = (x, y, id) => {
            const now = performance.now();
            const dt = now - lastMoveAt;
            if (dt >= TICK_MS) {
                lastMoveAt = now;
                sendTouchPos('move', x, y, id);
                return;
            }
            pendingMove = { x, y, id };
            if (moveTimer != null) return;
            moveTimer = setTimeout(() => {
                moveTimer = null;
                if (!pendingMove) return;
                lastMoveAt = performance.now();
                sendTouchPos('move', pendingMove.x, pendingMove.y, pendingMove.id);
                pendingMove = null;
            }, TICK_MS - dt);
        };

        // Pointer track — mouse and pen only. Touch pointer events
        // would duplicate the touch-event track below, so skip them.
        const onPointerDown = (e) => {
            if (e.pointerType === 'touch') return;
            onDown('down', e.clientX, e.clientY, e.pointerId);
        };
        const onPointerMove = (e) => {
            if (e.pointerType === 'touch') return;
            if (e.pointerType === 'mouse' && !e.buttons) return; // hover noise
            onMove(e.clientX, e.clientY, e.pointerId);
        };
        const onPointerUp = (e) => {
            if (e.pointerType === 'touch') return;
            onUp(e.clientX, e.clientY, e.pointerId);
        };
        window.addEventListener('pointerdown', onPointerDown, { capture: true, passive: true });
        window.addEventListener('pointermove', onPointerMove, { capture: true, passive: true });
        window.addEventListener('pointerup', onPointerUp, { capture: true, passive: true });
        window.addEventListener('pointercancel', onPointerUp, { capture: true, passive: true });

        // Touch track — keeps firing during scroll so the ripple
        // follows the finger even when the gesture turns into a pan.
        const firstTouch = (e) => e.changedTouches && e.changedTouches[0];
        const onTouchStart = (e) => {
            const t = firstTouch(e); if (!t) return;
            onDown('down', t.clientX, t.clientY, t.identifier);
        };
        const onTouchMove = (e) => {
            const t = firstTouch(e); if (!t) return;
            onMove(t.clientX, t.clientY, t.identifier);
        };
        const onTouchEnd = (e) => {
            const t = firstTouch(e); if (!t) return;
            onUp(t.clientX, t.clientY, t.identifier);
        };
        window.addEventListener('touchstart', onTouchStart, { capture: true, passive: true });
        window.addEventListener('touchmove', onTouchMove, { capture: true, passive: true });
        window.addEventListener('touchend', onTouchEnd, { capture: true, passive: true });
        window.addEventListener('touchcancel', onTouchEnd, { capture: true, passive: true });

        cleanups.push(() => {
            window.removeEventListener('pointerdown', onPointerDown, { capture: true });
            window.removeEventListener('pointermove', onPointerMove, { capture: true });
            window.removeEventListener('pointerup', onPointerUp, { capture: true });
            window.removeEventListener('pointercancel', onPointerUp, { capture: true });
            window.removeEventListener('touchstart', onTouchStart, { capture: true });
            window.removeEventListener('touchmove', onTouchMove, { capture: true });
            window.removeEventListener('touchend', onTouchEnd, { capture: true });
            window.removeEventListener('touchcancel', onTouchEnd, { capture: true });
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
