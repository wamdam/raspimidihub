/**
 * Tiny router for the app's three pieces of bookmarkable state:
 *
 *   - `tab`           — 'routing' | 'controller' | 'presets' | 'settings'
 *   - `controllerId`  — selected instance on the Controller page
 *   - `deviceId`      — open device-detail panel on the Routing page
 *
 * URL forms:
 *
 *   /                              → routing
 *   /routing                       → routing
 *   /routing/d/<device_id>         → routing + device panel open
 *   /controller                    → controller (last-viewed via localStorage)
 *   /controller/<instance_id>      → controller, that instance selected
 *   /presets
 *   /settings
 *
 * `navigate({...})` pushes a new history entry; the browser back/forward
 * buttons fire popstate, the hook resyncs from window.location, and the
 * app re-renders. Modal-level state (popovers, edit toggles, scroll
 * position) is intentionally NOT in the URL — phone-first UI doesn't
 * benefit from that level of granularity.
 */

import { useEffect, useState, useCallback } from '../lib/hooks.module.js';

const TABS = new Set(['routing', 'controller', 'presets', 'settings']);

export function parseURL() {
    let path = '/';
    try { path = window.location.pathname || '/'; } catch {}
    const parts = path.replace(/^\/+/, '').split('/').filter(Boolean);
    const route = { tab: 'routing', controllerId: null, deviceId: null };
    if (parts.length === 0) return route;
    if (!TABS.has(parts[0])) return route;
    route.tab = parts[0];
    if (route.tab === 'routing' && parts[1] === 'd' && parts[2]) {
        route.deviceId = decodeURIComponent(parts[2]);
    } else if (route.tab === 'controller' && parts[1]) {
        route.controllerId = decodeURIComponent(parts[1]);
    }
    return route;
}

export function buildURL({ tab, controllerId, deviceId }) {
    const t = TABS.has(tab) ? tab : 'routing';
    if (t === 'routing') {
        return deviceId != null ? `/routing/d/${encodeURIComponent(deviceId)}` : '/routing';
    }
    if (t === 'controller') {
        return controllerId ? `/controller/${encodeURIComponent(controllerId)}` : '/controller';
    }
    return `/${t}`;
}

export function useRouter() {
    const [route, setRoute] = useState(parseURL);

    useEffect(() => {
        const onPop = () => setRoute(parseURL());
        window.addEventListener('popstate', onPop);
        return () => window.removeEventListener('popstate', onPop);
    }, []);

    // Replace the initial URL so '/' becomes '/routing' (or whatever we
    // parsed) — gives back/forward something concrete to land on.
    useEffect(() => {
        try {
            const url = buildURL(route);
            if (url !== window.location.pathname) {
                window.history.replaceState({}, '', url);
            }
        } catch {}
        // run once on mount
    }, []);

    const navigate = useCallback((next, opts = {}) => {
        const merged = {
            tab: next.tab !== undefined ? next.tab : 'routing',
            controllerId: next.controllerId !== undefined ? next.controllerId : null,
            deviceId: next.deviceId !== undefined ? next.deviceId : null,
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
