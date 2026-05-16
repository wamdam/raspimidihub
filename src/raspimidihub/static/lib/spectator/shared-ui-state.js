/**
 * useSharedUiState — useState that mirrors across spectators.
 *
 * Some UI state lives in component-local useState today (context
 * menu, CC-binding popup, Add-plugin overlay, BT panel). For
 * spectator mode to show the same view as the source phone, those
 * pieces need to cross the wire.
 *
 * One small abstraction layer keeps the source code idiomatic:
 *
 *   - Source side: wraps useState, calls ctx.broadcast on every
 *     write. JSON-encoding strips any function-typed values (e.g.
 *     menu item onClick handlers), so the wire payload is naturally
 *     view-only.
 *
 *   - Spectator side: registers a subscriber that mirrors incoming
 *     `ui:<key>` events into local state. The setter is a no-op —
 *     spectator clicks don't drive UI state.
 *
 * The SpectatorContext default is a no-op source (broadcast does
 * nothing). The actual broadcaster Provider lives in
 * spectator-broadcast.js (source side) and pages/spectate.js
 * (spectator side).
 */

import { createContext } from '../preact.module.js';
import { useCallback, useContext, useEffect, useRef, useState } from '../hooks.module.js';

export const SpectatorContext = createContext({
    kind: 'source',
    broadcast: () => {},
    subscribe: () => {},
    unsubscribe: () => {},
});

export function useSharedUiState(key, initial) {
    const ctx = useContext(SpectatorContext);
    // Hold the latest ctx in a ref so the returned setter keeps a
    // stable identity across ctx changes. Without this, every
    // useCallback in the codebase that wraps the setter and uses
    // empty deps (e.g. openCcBinding in app.js) would capture the
    // first-render ctx — whose broadcast() is the no-op default —
    // and never broadcast even once the source becomes watched.
    const ctxRef = useRef(ctx);
    ctxRef.current = ctx;
    const [value, setValue] = useState(initial);
    const valRef = useRef(initial);
    valRef.current = value;
    const isSpectator = ctx.kind === 'spectator';

    useEffect(() => {
        if (!isSpectator) return undefined;
        const cb = (v) => setValue(v == null ? initial : v);
        ctx.subscribe(`ui:${key}`, cb);
        return () => ctx.unsubscribe(`ui:${key}`, cb);
        // initial intentionally excluded — re-subscribing on a literal
        // initial-prop identity change would tear down on every render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isSpectator, key, ctx]);

    // Source-side re-broadcast on watch-start. The broadcaster's
    // POSTs only fire while watched, so any ui:* state changes that
    // happened BEFORE a spectator joined left no trace on the server
    // (broadcast was a no-op, snapshot cache stays empty). On
    // watch-start the broadcaster dispatches a `spectator-rebroadcast`
    // CustomEvent and every consumer re-emits its current value, so a
    // late-joining spectator catches up on whatever popups / menus
    // are already showing.
    useEffect(() => {
        if (isSpectator) return undefined;
        const onRebroadcast = () => {
            try { ctxRef.current.broadcast(`ui:${key}`, valRef.current); } catch {}
        };
        window.addEventListener('spectator-rebroadcast', onRebroadcast);
        return () => window.removeEventListener('spectator-rebroadcast', onRebroadcast);
    }, [isSpectator, key]);

    const setter = useCallback((v) => {
        if (ctxRef.current.kind === 'spectator') return;
        const next = typeof v === 'function' ? v(valRef.current) : v;
        setValue(next);
        ctxRef.current.broadcast(`ui:${key}`, next);
    }, [key]);

    return [value, setter];
}
