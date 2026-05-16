/**
 * Per-view SSE subscription model.
 *
 * The server filters events per recipient against each connection's
 * subscription set. Every view declares its interest via
 * `useSSESubscription(events, instances)` — the hook contributes to a
 * global merged set and flushes it to /api/sse/subscribe when the
 * collected set changes.
 *
 * Multiple hooks compose: a Routing page can subscribe to one set and
 * an open device-detail panel inside it adds an instance subscription;
 * the manager unions both contributions and the server receives the
 * merged set. On unmount, each hook removes its contribution and the
 * merged set is reflushed — so navigating away from a view
 * automatically tears its subscription down.
 *
 * Empty subscription = receive nothing. Server has no fallback; views
 * that should always receive certain events (e.g. App's device-list
 * sync) call the hook themselves at the always-mounted level.
 */

import { useEffect, useMemo } from '../lib/hooks.module.js';

const LABEL_KEY = 'raspimidihub:spectatorLabel';

function readPersistedLabel() {
    try { return localStorage.getItem(LABEL_KEY) || ''; } catch { return ''; }
}

class SubscriptionManager {
    constructor() {
        this.contributions = new Map(); // hook_id -> { events: Set, instances: Set }
        this.connId = null;
        this.flushTimer = null;
        this.lastSent = null; // last JSON we POSTed, to dedup
        this.nextId = 0;
        // Optional human-readable label for this device, surfaced via
        // /api/spectator/clients so spectators can pick which source
        // to mirror. Read from localStorage at construction; can be
        // updated at runtime via setSpectatorLabel().
        this.label = readPersistedLabel();
    }

    setConnectionId(id) {
        if (this.connId === id) return;
        this.connId = id;
        this.lastSent = null; // a new connection — force a flush
        this.scheduleFlush();
    }

    setLabel(label) {
        const next = (label || '').slice(0, 64);
        if (this.label === next) return;
        this.label = next;
        try { localStorage.setItem(LABEL_KEY, next); } catch {}
        this.lastSent = null;
        this.scheduleFlush();
    }

    nextHookId() {
        return ++this.nextId;
    }

    register(hookId, events, instances) {
        this.contributions.set(hookId, {
            events: new Set(events || []),
            instances: new Set(instances || []),
        });
        this.scheduleFlush();
    }

    unregister(hookId) {
        if (this.contributions.delete(hookId)) this.scheduleFlush();
    }

    scheduleFlush() {
        if (this.flushTimer != null) return;
        // 50 ms debounce — coalesces a navigation's worth of
        // mount / unmount activity (old view's effects clean up,
        // new view's effects mount) into one POST.
        this.flushTimer = setTimeout(() => {
            this.flushTimer = null;
            this.flush();
        }, 50);
    }

    flush() {
        if (!this.connId) return;
        const events = new Set();
        const instances = new Set();
        for (const c of this.contributions.values()) {
            for (const e of c.events) events.add(e);
            for (const i of c.instances) instances.add(i);
        }
        const body = JSON.stringify({
            conn_id: this.connId,
            events: [...events].sort(),
            instances: [...instances].sort(),
            label: this.label,
        });
        if (body === this.lastSent) return;
        this.lastSent = body;
        fetch('/api/sse/subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
        }).catch(() => {
            // If the POST fails, drop lastSent so we retry on the next change.
            this.lastSent = null;
        });
    }
}

const manager = new SubscriptionManager();

/** Called by App once with the conn_id received in the `connection` SSE event. */
export function setSSEConnectionId(id) {
    manager.setConnectionId(id);
}

/** Read the active conn_id. Used by the spectator broadcaster to
 * stamp outgoing /api/spectator/state POSTs. Returns null until the
 * SSE handshake has produced one. */
export function getSSEConnectionId() {
    return manager.connId;
}

/** Current device label (the human-readable name surfaced in the
 * spectator picker). Empty string when nothing has been set. */
export function getSpectatorLabel() {
    return manager.label || '';
}

/** Update this device's label. Persisted to localStorage; reflushed
 * to the server via /api/sse/subscribe. */
export function setSpectatorLabel(label) {
    manager.setLabel(label);
}

/**
 * Declare this view's SSE interest. Re-runs whenever events / instances
 * change (by value — pass arrays / use stable refs upstream).
 *
 * - `events`: list of event types to receive (e.g. 'midi-activity',
 *   'connection-changed'). Per-instance event types ('plugin-param',
 *   'plugin-display') do NOT belong here — use `instances` instead.
 * - `instances`: list of plugin instance IDs whose plugin-param /
 *   plugin-display events should be delivered.
 */
export function useSSESubscription(events, instances) {
    // Stable hook id per call site (per useMemo). Different mounts of
    // the same component get different ids so they don't clobber.
    const hookId = useMemo(() => manager.nextHookId(), []);
    // Stringify deps so passing literal arrays still re-runs only on
    // value change, not every render.
    const eventsKey = useMemo(
        () => JSON.stringify([...(events || [])].sort()), [events]);
    const instancesKey = useMemo(
        () => JSON.stringify([...(instances || [])].sort()), [instances]);
    useEffect(() => {
        manager.register(hookId, events || [], instances || []);
        return () => manager.unregister(hookId);
    }, [hookId, eventsKey, instancesKey]);
}
