/**
 * Tiny router for the app's bookmarkable state:
 *
 *   - `tab`             — 'routing' | 'controller' | 'play' | 'settings'
 *   - `controllerId`    — selected instance on the Controller page
 *   - `playId`          — selected instance on the Play page
 *   - `deviceId`        — open device-detail panel on the Routing page
 *   - `settingsSection` — active Settings sub-page ('sys-info', 'network',
 *                         'midi', 'display', 'update', 'cc-bindings'),
 *                         or null = the Settings hub itself.
 *
 * URL forms:
 *
 *   /                              → routing
 *   /routing                       → routing
 *   /routing/d/<device_id>         → routing + device panel open
 *   /controller                    → controller (last-viewed via localStorage)
 *   /controller/<instance_id>      → controller, that instance selected
 *   /play                          → play surface carousel
 *   /play/<instance_id>            → play, that surface selected
 *   /settings                      → settings hub
 *   /settings/<section>            → settings sub-page
 *
 * `navigate({...})` pushes a new history entry; the browser back/forward
 * buttons fire popstate, the hook resyncs from window.location, and the
 * app re-renders. Modal-level state (popovers, edit toggles, scroll
 * position) is intentionally NOT in the URL — phone-first UI doesn't
 * benefit from that level of granularity.
 */

import { useEffect, useState, useCallback } from '../lib/hooks.module.js';

const TABS = new Set(['routing', 'controller', 'play', 'settings']);
const SETTINGS_SECTIONS = new Set([
    'sys-info', 'network', 'midi', 'display', 'update', 'cc-bindings',
    'spectator',
]);

// Optional external route source — set at boot by spectator mode to
// drive the route from the network instead of window.location. When
// non-null, useRouter() ignores popstate and navigate() is a no-op
// (the spectator is view-only). The source contract:
//
//   { getRoute(): RouteShape,
//     subscribe(cb): unsubscribe }
//
// The spectator entry page constructs one of these from the incoming
// `spectator-state` events of kind 'route' and installs it before
// the App tree renders.
let _externalSource = null;
export function setRouterExternalSource(src) { _externalSource = src; }

export function parseURL() {
    let path = '/';
    try { path = window.location.pathname || '/'; } catch {}
    const parts = path.replace(/^\/+/, '').split('/').filter(Boolean);
    const route = {
        tab: 'routing', controllerId: null, playId: null, deviceId: null,
        settingsSection: null,
    };
    if (parts.length === 0) return route;
    if (!TABS.has(parts[0])) return route;
    route.tab = parts[0];
    if (route.tab === 'routing' && parts[1] === 'd' && parts[2]) {
        route.deviceId = decodeURIComponent(parts[2]);
    } else if (route.tab === 'controller' && parts[1]) {
        route.controllerId = decodeURIComponent(parts[1]);
    } else if (route.tab === 'play' && parts[1]) {
        route.playId = decodeURIComponent(parts[1]);
    } else if (route.tab === 'settings' && parts[1]
            && SETTINGS_SECTIONS.has(parts[1])) {
        route.settingsSection = parts[1];
    }
    return route;
}

export function buildURL({ tab, controllerId, playId, deviceId, settingsSection }) {
    const t = TABS.has(tab) ? tab : 'routing';
    if (t === 'routing') {
        return deviceId != null ? `/routing/d/${encodeURIComponent(deviceId)}` : '/routing';
    }
    if (t === 'controller') {
        return controllerId ? `/controller/${encodeURIComponent(controllerId)}` : '/controller';
    }
    if (t === 'play') {
        return playId ? `/play/${encodeURIComponent(playId)}` : '/play';
    }
    if (t === 'settings') {
        return settingsSection ? `/settings/${settingsSection}` : '/settings';
    }
    return `/${t}`;
}

export function useRouter() {
    const ext = _externalSource;
    const [route, setRoute] = useState(() => ext ? ext.getRoute() : parseURL());

    useEffect(() => {
        if (ext) {
            // Mirror an external source: subscribe to its updates and
            // discard window.location entirely. The source decides
            // what the route is.
            return ext.subscribe(setRoute);
        }
        const onPop = () => setRoute(parseURL());
        window.addEventListener('popstate', onPop);
        return () => window.removeEventListener('popstate', onPop);
    }, []);

    // Replace the initial URL so '/' becomes '/routing' (or whatever we
    // parsed) — gives back/forward something concrete to land on.
    // Skipped under an external source: rewriting window.location would
    // clobber the ?spectate=<id> query the spectator entry depends on.
    useEffect(() => {
        if (ext) return;
        try {
            const url = buildURL(route);
            if (url !== window.location.pathname) {
                window.history.replaceState({}, '', url);
            }
        } catch {}
        // run once on mount
    }, []);

    const navigate = useCallback((next, opts = {}) => {
        if (ext) return;  // spectator view is read-only
        const merged = {
            tab: next.tab !== undefined ? next.tab : 'routing',
            controllerId: next.controllerId !== undefined ? next.controllerId : null,
            playId: next.playId !== undefined ? next.playId : null,
            deviceId: next.deviceId !== undefined ? next.deviceId : null,
            settingsSection: next.settingsSection !== undefined ? next.settingsSection : null,
        };
        const url = buildURL(merged);
        try {
            const cur = window.location.pathname;
            if (url !== cur) {
                if (opts.replace) window.history.replaceState({}, '', url);
                else window.history.pushState({}, '', url);
            }
        } catch {}
        setRoute(merged);
    }, []);

    return { route, navigate };
}
