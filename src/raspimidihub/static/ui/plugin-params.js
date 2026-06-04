/**
 * usePluginParams — shared hook for plugin instance param management.
 *
 * Owns the local "what value does the user think this param is right
 * now" state plus the rAF-coalesced + serialised PATCH pipeline AND
 * the eventually-consistent watchdog that recovers from dropped or
 * out-of-order PATCH responses by reconciling against the server's
 * SSE broadcast.
 *
 * Used by both the device-detail panel and the Controller fullscreen
 * page, so updates from one stay in sync with the other through SSE.
 *
 * Returns `{ params, setParams, onParamChange }`.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from '../lib/hooks.module.js';

const IN_FLIGHT_RELEASE_MS = 250;

// Deep-equality check that's safe for dict-valued plugin params (e.g.
// cell_labels). Identity (!==) is always true for fresh dicts even when
// their contents match, which would otherwise loop the watchdog.
function paramsEqual(a, b) {
    if (a === b) return true;
    if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false;
    try { return JSON.stringify(a) === JSON.stringify(b); } catch { return false; }
}

// Walk a params schema and collect names of trigger-style params:
//   - DropButtonRow
//   - Button(trigger=true)
//   - TrackerGrid.cmd_play_param / cmd_stop_param (Play/Stop buttons
//     in the play header — server fires the local transport then
//     resets the bool back to false; without skipping the watchdog
//     re-queue, the server's reset disagrees with our optimistic
//     `true` and re-fires Play after IN_FLIGHT_RELEASE_MS).
// These intentionally cycle their value on the server (fire -> idle,
// drops.action -> 'idle'), so the frontend must NOT optimistically
// commit OR run the watchdog re-queue — both would fight the
// server's authoritative state.
export function collectTriggerParams(schema) {
    const s = new Set();
    const walk = (items) => {
        if (!items) return;
        for (const p of items) {
            if (p.type === 'group') walk(p.children);
            else if (p.type === 'layoutgrid') {
                walk((p.cells || []).map((c) => c.param));
            } else if (p.type === 'trackergrid') {
                if (p.cmd_play_param) s.add(p.cmd_play_param);
                if (p.cmd_play_page_param) s.add(p.cmd_play_page_param);
                if (p.cmd_stop_param) s.add(p.cmd_stop_param);
                if (p.note_preview_param) s.add(p.note_preview_param);
            } else if (p.type === 'dropbuttonrow') s.add(p.name);
            else if (p.type === 'button' && p.trigger) s.add(p.name);
        }
    };
    walk(schema);
    return s;
}

export function usePluginParams({ instanceId, paramsSchema, pluginDisplays }) {
    const [params, setParams] = useState({});

    // Coalesced + serialised PATCH pipeline.
    const pendingPatchesRef = useRef(new Map());     // name -> latest queued value
    const inFlightRef = useRef(new Map());           // name -> timeout id (user dragging)
    const rafIdRef = useRef(null);
    const patchInFlightRef = useRef(false);

    // Refs so the settle-check + watchdog can read latest values
    // outside of a render closure.
    const paramsRef = useRef(params);
    paramsRef.current = params;
    const pluginDisplaysRef = useRef(pluginDisplays);
    pluginDisplaysRef.current = pluginDisplays;

    const triggerParams = useMemo(
        () => collectTriggerParams(paramsSchema),
        [paramsSchema],
    );

    const flushPending = useCallback(() => {
        rafIdRef.current = null;
        if (patchInFlightRef.current) return;
        const map = pendingPatchesRef.current;
        if (map.size === 0) return;
        if (!instanceId) return;

        const body = Object.fromEntries(map);
        map.clear();
        patchInFlightRef.current = true;
        fetch(`/api/plugins/instances/${instanceId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ params: body }),
        }).then((res) => {
            if (!res.ok) {
                for (const [k, v] of Object.entries(body)) {
                    if (!pendingPatchesRef.current.has(k)) pendingPatchesRef.current.set(k, v);
                }
            }
        }).catch(() => {
            for (const [k, v] of Object.entries(body)) {
                if (!pendingPatchesRef.current.has(k)) pendingPatchesRef.current.set(k, v);
            }
        }).finally(() => {
            patchInFlightRef.current = false;
            if (pendingPatchesRef.current.size > 0) {
                setTimeout(flushPending, 30);
            }
        });
    }, [instanceId]);

    // Reset pipeline state whenever the instance changes — old timers /
    // pending patches reference the previous instance's id.
    useEffect(() => {
        if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
        for (const t of inFlightRef.current.values()) clearTimeout(t);
        inFlightRef.current.clear();
        pendingPatchesRef.current.clear();
        patchInFlightRef.current = false;
    }, [instanceId]);

    useEffect(() => () => {
        if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
        for (const t of inFlightRef.current.values()) clearTimeout(t);
    }, []);

    // Settle: pull SSE-broadcasted values into local state for params
    // not currently being dragged on this client. Runs in a real
    // useEffect (post-commit) and uses functional setParams so the
    // comparison reads the latest committed local state — earlier
    // versions used setTimeout + closure-captured `params` and could
    // race two consecutive SSE updates: the second update would see
    // its sseParamsRef bumped, find the old `params` matching, no-op,
    // and the first update's deferred setParams would then commit a
    // stale value as final.
    const sseParamsKey = pluginDisplays && instanceId ? '_params_' + instanceId : null;
    const sseParams = sseParamsKey ? pluginDisplays[sseParamsKey] : null;
    useEffect(() => {
        if (!sseParams) return;
        setParams((prev) => {
            let next = null;
            for (const [k, v] of Object.entries(sseParams)) {
                if (inFlightRef.current.has(k)) continue;
                if (!paramsEqual(prev[k], v)) {
                    if (next === null) next = { ...prev };
                    next[k] = v;
                }
            }
            return next || prev;
        });
    }, [sseParams]);

    const onParamChange = useCallback((name, value) => {
        if (triggerParams.has(name)) {
            // Fire-and-forget: PATCH only, no local optimism, no watchdog.
            if (!instanceId) return;
            pendingPatchesRef.current.set(name, value);
            if (rafIdRef.current === null) {
                rafIdRef.current = requestAnimationFrame(flushPending);
            }
            return;
        }
        setParams((prev) => (prev[name] === value ? prev : { ...prev, [name]: value }));
        if (!instanceId) return;

        pendingPatchesRef.current.set(name, value);
        if (rafIdRef.current === null) {
            rafIdRef.current = requestAnimationFrame(flushPending);
        }

        const existing = inFlightRef.current.get(name);
        if (existing) clearTimeout(existing);
        inFlightRef.current.set(name, setTimeout(() => {
            inFlightRef.current.delete(name);
            // Eventually-consistent watchdog: if the server's last
            // SSE-seen value disagrees with our optimistic local
            // value, re-queue our local value so it eventually wins.
            const ssp = pluginDisplaysRef.current
                && pluginDisplaysRef.current['_params_' + instanceId];
            const localVal = paramsRef.current[name];
            if (instanceId && ssp
                    && ssp[name] !== undefined
                    && !paramsEqual(ssp[name], localVal)
                    && !paramsEqual(pendingPatchesRef.current.get(name), localVal)) {
                pendingPatchesRef.current.set(name, localVal);
                if (rafIdRef.current === null && !patchInFlightRef.current) {
                    rafIdRef.current = requestAnimationFrame(flushPending);
                }
            }
        }, IN_FLIGHT_RELEASE_MS));
    }, [instanceId, flushPending, triggerParams]);

    return { params, setParams, onParamChange };
}
