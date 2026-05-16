/**
 * App entry point: top-level state, SSE wiring, page routing, render boot.
 *
 * Everything else lives next door:
 *   ui/        — shared primitives (html, hooks, icons, Toast, MidiBar)
 *   state/     — constants
 *   panels/    — full-screen overlays (mapping form, filter, device detail)
 *   pages/     — routing / controller / settings + the connection matrix
 *   components/— plugin parameter controls (already split in step 4)
 */

import { render } from './lib/preact.module.js';
import { useState, useEffect, useRef, useCallback } from './lib/hooks.module.js';
import { html, api, useSSE, Toast, MidiBar, hardReload } from './ui/common.js';
import { applyLayoutDensity, getLayoutDensity } from './components/common.js';
import { ScrollAssist } from './components/scrollassist.js';
import { ContextMenu } from './ui/contextmenu.js';
import { CcBinding } from './components/ccbinding.js';
import { CellBinding } from './components/cellbinding.js';
import { setSSEConnectionId, useSSESubscription } from './ui/sse-subscriptions.js';
import { IconRouting, IconController, IconPlay, IconSettings, IconFullscreen, IconFullscreenExit } from './ui/icons.js';
import { runStorageCleanup } from './ui/storage.js';
import { useRouter } from './ui/router.js';
import { noteName } from './state/constants.js';
import { DeviceDetailPanel } from './panels/devicedetail.js';
import { RoutingPage } from './pages/routing.js';
import { ControllerPage } from './pages/controller.js';
import { PlayPage } from './pages/play.js';
import { SettingsPage } from './pages/settings.js';
import { SpectatorContext, useSharedUiState } from './lib/shared-ui-state.js';
import { useSourceBroadcaster } from './lib/spectator-broadcast.js';
import { SpectatorView } from './pages/spectate.js';

// Header badge: "RaspiMIDIHub [● if stale] v2.0.9·a1b2c3d4". The red
// dot is the only visual when the loaded JS bundle's build token
// differs from the server's current one — clicking it triggers
// hardReload, same as the old "stale, reload" link did.
function VersionBadge({ version, loadedBuild, serverBuild }) {
    if (!version) return html`<h1>RaspiMIDIHub</h1>`;
    // loadedBuild looks like "2.0.9-69ee5610" (?v=<version>-<token>);
    // serverBuild is just "69ee5610" — strip the version prefix so we
    // compare apples to apples.
    const loadedToken = loadedBuild ? loadedBuild.split('-').pop() : '';
    const stale = serverBuild && loadedToken && serverBuild !== loadedToken;
    return html`<h1>RaspiMIDIHub${stale ? html`<span class="stale-dot"
            title="Server has been redeployed since this tab loaded — tap to reload"
            onclick=${hardReload}></span>` : ''}
        <span style="font-size:11px;font-weight:400;color:var(--text-dim);margin-left:10px">
            v${version}${loadedToken ? '·' + loadedToken : ''}
        </span>
    </h1>`;
}

// Fullscreen toggle in the header. Uses the standard Fullscreen API
// — works on Android Chrome / Firefox / Edge, no-op on iOS Safari
// (which only supports fullscreen on <video>; iPhone users get
// edge-to-edge via the PWA "Add to Home Screen" path instead).
// Tracks document.fullscreenElement so the icon flips when the
// user exits via the system gesture (e.g. swipe-down on Android).
function FullscreenButton() {
    const [isFs, setIsFs] = useState(
        typeof document !== 'undefined' && !!document.fullscreenElement);
    useEffect(() => {
        const onChange = () => setIsFs(!!document.fullscreenElement);
        document.addEventListener('fullscreenchange', onChange);
        return () => document.removeEventListener('fullscreenchange', onChange);
    }, []);
    const toggle = async () => {
        try {
            if (document.fullscreenElement) {
                await document.exitFullscreen();
            } else if (document.documentElement.requestFullscreen) {
                await document.documentElement.requestFullscreen();
            }
        } catch {}
    };
    // Hide entirely on browsers without the API (iOS Safari) so we
    // don't ship a button that does nothing.
    if (typeof document === 'undefined'
            || !document.documentElement.requestFullscreen) {
        return null;
    }
    return html`<button class="fullscreen-btn"
        title=${isFs ? 'Exit fullscreen' : 'Enter fullscreen'}
        onclick=${toggle}>
        ${isFs ? IconFullscreenExit : IconFullscreen}
    </button>`;
}

// Bottom-nav tab switch with per-tab sub-state memory. Saves the
// currently-visible sub-state (open device panel on Routing, selected
// instance on Controller / Play) at the moment of leaving, then
// restores the destination tab's last sub-state on arrival. Stored
// per-device in localStorage — the user might want Euclidean
// permanently on one phone and Tracker on another. An explicit
// "close" of the sub-state (panel dismissed, no instance selected)
// is preserved as an empty string, so reopening the tab honours
// that close instead of springing the panel back open.
const TAB_SUBKEY = {
    routing: 'deviceId',
    controller: 'controllerId',
    play: 'playId',
    settings: 'settingsSection',
};
function tabStorageKey(tab) { return `raspimidihub:lastIn:${tab}`; }
function saveTabSubState(route) {
    const key = TAB_SUBKEY[route.tab];
    if (!key) return;
    const val = route[key];
    try { localStorage.setItem(tabStorageKey(route.tab), val != null ? String(val) : ''); } catch {}
}
function loadTabSubState(tab) {
    const key = TAB_SUBKEY[tab];
    if (!key) return null;
    try {
        const v = localStorage.getItem(tabStorageKey(tab));
        return v || null;  // empty string => intentionally cleared
    } catch { return null; }
}

function App({ onSpectatorWatched, onRouteChange }) {
    const { route, navigate } = useRouter();
    const tab = route.tab;

    // Publish route changes upward so SourceAppWrapper's broadcaster
    // can mirror them. In spectator mode the prop is undefined and
    // this is a no-op.
    useEffect(() => {
        if (onRouteChange) onRouteChange(route);
    }, [route, onRouteChange]);
    const setTab = useCallback((t) => {
        // Capture where we're leaving FROM, then jump to the new
        // tab's remembered sub-state (or empty if nothing saved /
        // explicitly cleared).
        saveTabSubState(route);
        if (t === route.tab) return;  // re-tap of current tab is a no-op
        const key = TAB_SUBKEY[t];
        const restored = loadTabSubState(t);
        if (key && restored) {
            navigate({ tab: t, [key]: restored });
        } else {
            navigate({ tab: t });
        }
    }, [navigate, route]);
    const [devices, setDevices] = useState([]);
    const devicesRef = useRef([]);
    const connectionsRef = useRef([]);
    const [connections, setConnections] = useState([]);
    const [toast, setToast] = useState('');
    const [configFallback, setConfigFallback] = useState(false);
    const [version, setVersion] = useState('');
    // Server's current build token vs the one this JS bundle was loaded
    // against. They diverge after a redeploy → user needs to reload to
    // pick up new JS. The badge in the header makes that visible at a
    // glance instead of "is my browser running stale code?" guesswork.
    const [serverBuild, setServerBuild] = useState('');
    // The build token in our entry script URL (?v=…). Window.location
    // doesn't carry it; we read it from the script tag we were loaded
    // from. The header script tag is the one that matches /app.js.
    const loadedBuild = (() => {
        try {
            for (const s of document.querySelectorAll('script[src*="app.js"]')) {
                const m = s.getAttribute('src').match(/[?&]v=([^&]+)/);
                if (m) return decodeURIComponent(m[1]);
            }
        } catch {}
        return '';
    })();
    // Device-detail panel open state lives in the URL — opening / closing
    // the panel pushes a new history entry, so the back button closes it.
    const selectedDeviceId = route.deviceId != null ? Number(route.deviceId) : null;
    const setSelectedDeviceId = useCallback((id) => {
        navigate({ tab: 'routing', deviceId: id != null ? id : null });
    }, [navigate]);
    // ControllerPage's refreshList depends on this callback's identity;
    // an inline arrow recreated per render fired the list-fetch effect
    // on every SSE event (~20/s during a fader move) and pinned the
    // server's asyncio loop on JSON serialisation. useCallback keeps
    // identity stable so the effect only fires when `navigate` itself
    // changes (~never).
    const setControllerId = useCallback((id, opts) => {
        navigate({ tab: 'controller', controllerId: id }, opts);
    }, [navigate]);
    const setPlayId = useCallback((id, opts) => {
        navigate({ tab: 'play', playId: id }, opts);
    }, [navigate]);
    // Pencil icon on the Play bar opens the device-detail panel
    // for the current sequencer instance (Plugin Config). Same lookup
    // path as openControllerConfig.
    const openPlayConfig = useCallback((instanceId) => {
        const dev = devicesRef.current.find(
            (d) => d.stable_id === 'plugin-' + instanceId);
        if (dev) navigate({ tab: 'routing', deviceId: dev.client_id });
    }, [navigate]);
    // Pencil icon on the Controller bar opens the device-detail panel
    // for the current instance (where Plugin Config / per-cell rebind /
    // Spring config live). Plugin instances appear in the device list
    // with stable_id `plugin-<instance_id>`; we look up the matching
    // ALSA client_id and route to /routing/d/<client_id>.
    const openControllerConfig = useCallback((instanceId) => {
        const dev = devicesRef.current.find(
            (d) => d.stable_id === 'plugin-' + instanceId);
        if (dev) navigate({ tab: 'routing', deviceId: dev.client_id });
    }, [navigate]);
    const selectedDevice = selectedDeviceId != null ? devices.find(d => d.client_id === selectedDeviceId) || null : null;
    const [showMidiBar, setShowMidiBar] = useState(() => localStorage.getItem('midiBar') !== 'off');
    const [midiEvents, setMidiEvents] = useState({});  // src_client -> {name, text}
    const [clockSources, setClockSources] = useState({});  // src_client -> timestamp
    const [clockQuarters, setClockQuarters] = useState({}); // src_client -> ts of last quarter-note tick
    // Global clock-bus heartbeat — broadcast every quarter from the
    // server's ClockBus. Drives the Controller drop-button rings
    // even when no drop is scheduled. {tick, ticks_per_bar, received_at}
    // (received_at: Date.now() at the moment the SSE arrived).
    const [clockPosition, setClockPosition] = useState(null);
    const [midiRates, setMidiRates] = useState({});  // "client:port" -> msgs/sec
    const [pluginDisplays, setPluginDisplays] = useState({});  // instance_id -> {name: value}
    const [sseConnected, setSseConnected] = useState(true);
    // True when in-memory routing/plugin state has diverged from
    // /boot/firmware/raspimidihub/config.json — drives the small dark-red
    // asterisk on the bottom-nav Routing icon. Server pushes transitions
    // via the `config-dirty` SSE event; initial value comes from the
    // /api/system fetch on mount.
    const [configDirty, setConfigDirty] = useState(false);

    const refresh = useCallback(async () => {
        const [devs, conns] = await Promise.all([api('/devices'), api('/connections')]);
        const d = Array.isArray(devs) ? devs : [];
        const c = Array.isArray(conns) ? conns : [];
        setDevices(d);
        devicesRef.current = d;
        setConnections(c);
        connectionsRef.current = c;
    }, []);

    useEffect(() => {
        refresh();
        api('/system').then(s => {
            setConfigFallback(s.config_fallback);
            setVersion(s.version || '');
            setServerBuild(s.build_token || '');
            setConfigDirty(!!s.config_dirty);
        });
        // Expire stale clock sources and midi events
        const expireTimer = setInterval(() => {
            const now = Date.now();
            setClockSources(prev => {
                const next = {};
                let changed = false;
                for (const [k, ts] of Object.entries(prev)) {
                    if (now - ts < 3000) next[k] = ts;
                    else changed = true;
                }
                return changed ? next : prev;
            });
            setMidiEvents(prev => {
                const next = {};
                let changed = false;
                for (const [k, v] of Object.entries(prev)) {
                    if (now - v.ts < 2000) next[k] = v;
                    else changed = true;
                }
                return changed ? next : prev;
            });
        }, 1000);
        return () => clearInterval(expireTimer);
    }, []);

    useSSE((type, data) => {
        if (type === 'device-connected' || type === 'device-disconnected' || type === 'connection-changed') {
            refresh();
        }
        if (type === 'config-dirty') {
            setConfigDirty(!!data.dirty);
        }
        if (type === 'midi-activity') {
            // Clock is no longer broadcast as midi-activity (server
            // sends clock-quarter at 1/24 the rate; see __main__).
            // Only show non-clock events from devices that have active connections
            const hasConn = connectionsRef.current.some(c => c.src_client === data.src_client);
            if (!hasConn) return;

            if (!showMidiBar) return;
            const dev = devicesRef.current.find(d => d.client_id === data.src_client);
            const name = dev ? dev.name : `${data.src_client}`;
            let detail = '';
            if (data.channel != null) detail += `[CH${data.channel}] `;
            if (data.note != null) detail += `${noteName(data.note)} vel=${data.velocity}`;
            else if (data.cc != null) detail += `CC${data.cc}=${data.value}`;
            else detail += data.event;
            setMidiEvents(prev => {
                const old = prev[data.src_client];
                const count = (old && old.detail === detail) ? (old.count || 1) + 1 : 1;
                return {...prev, [data.src_client]: { name, detail, ts: Date.now(), count }};
            });
        }
        if (type === 'midi-rates') {
            setMidiRates(data);
        }
        if (type === 'plugin-param') {
            setPluginDisplays(prev => ({
                ...prev,
                ['_params_' + data.instance_id]: { ...(prev['_params_' + data.instance_id] || {}), [data.name]: data.value },
            }));
        }
        if (type === 'plugin-display') {
            setPluginDisplays(prev => ({
                ...prev,
                [data.instance_id]: { ...(prev[data.instance_id] || {}), [data.name]: data.value },
            }));
        }
        if (type === 'clock-quarter') {
            // Both maps key on src_client. clockQuarters drives the
            // pulse (re-keying the icon retriggers its CSS animation
            // every quarter), clockSources gates whether the icon
            // shows at all + flips the multi-clock warning colour.
            // We populate both from clock-quarter because clock
            // midi-activity is suppressed for SSE-traffic reasons
            // (see __main__.on_midi_event).
            setClockQuarters(prev => ({ ...prev, [data.src_client]: Date.now() }));
            setClockSources(prev => ({ ...prev, [data.src_client]: Date.now() }));
        }
        if (type === 'clock-position') {
            const now = Date.now();
            // Track tempo from the interval between successive
            // clock-position events (server emits every 24 ticks =
            // 1 quarter). The frontend dead-reckons the live tick
            // forward from this so visual segments match audible
            // beats — without it, SSE arrival lag (network + render)
            // shows as ~1/16-1/8 note visual delay vs the audio.
            setClockPosition(prev => {
                let ms_per_tick = prev?.ms_per_tick;
                // Only re-derive if running and tick advanced; on
                // restart (tick 0 after Start) the interval is
                // meaningless.
                if (prev && prev.running && data.running
                        && data.tick > prev.tick && now > prev.received_at) {
                    const dt = now - prev.received_at;
                    const dticks = data.tick - prev.tick;
                    const measured = dt / dticks;
                    // Skip implausibly small intervals — TCP delivering
                    // buffered SSE events back-to-back (after a brief
                    // network stall, or a tab resuming) clumps them at
                    // < 1 ms apart, which collapses ms_per_tick toward
                    // zero and makes the drop-button dead-reckoning
                    // extrapolate liveTick wildly. 5 ms/tick is ~480
                    // BPM at 24 PPQN — well past any real music.
                    if (measured >= 5) {
                        // EWMA: one jittery interval (e.g., one event
                        // 200 ms late, next on time) only nudges
                        // ms_per_tick partway toward the spurious
                        // value, so the dead-reckoning stays stable.
                        // Sustained tempo changes still propagate over
                        // a handful of events. Without this, valid-
                        // looking but jittery measurements made the
                        // ring "tick 2-3 times fast" between freezes
                        // when SSE delivery wasn't perfectly even.
                        ms_per_tick = ms_per_tick != null
                            ? 0.75 * ms_per_tick + 0.25 * measured
                            : measured;
                    }
                }
                return {
                    tick: data.tick,
                    ticks_per_bar: data.ticks_per_bar,
                    running: !!data.running,
                    received_at: now,
                    ms_per_tick,
                };
            });
        }
        if (type === 'spectator-watch-start' && onSpectatorWatched) {
            // A spectator just connected to us; SourceAppWrapper
            // turns its broadcaster on. Re-firing while already
            // watched is a no-op (useState dedup).
            onSpectatorWatched(true);
        }
        if (type === 'spectator-watch-stop' && onSpectatorWatched) {
            onSpectatorWatched(false);
        }
    }, (connected) => {
        setSseConnected(connected);
        if (connected) refresh();
    }, (conn_id) => {
        // Server emits this exactly once after a successful SSE handshake;
        // hand it to the SubscriptionManager so per-view useSSESubscription
        // hooks can flush their merged set to /api/sse/subscribe.
        setSSEConnectionId(conn_id);
    });

    // App-level baseline subscription. The header always shows the
    // device count and SSE-status indicator, so we always need device
    // and connection lifecycle events. Pages add their own on top.
    useSSESubscription(
        ['device-connected', 'device-disconnected', 'connection-changed',
         'panic', 'plugin-changed', 'config-dirty'],
        [],
    );

    const toggleMidiBar = () => {
        const next = !showMidiBar;
        setShowMidiBar(next);
        localStorage.setItem('midiBar', next ? 'on' : 'off');
    };

    const showToast = (msg) => {
        setToast(msg);
        setTimeout(() => setToast(''), 2500);
    };

    // Phase 6: shared client-side clipboard + context menu.
    //
    // clipboard is a single typed slot — kind: "connection" | "plugin" |
    // "mapping". `null` = empty (Paste items disabled wherever they
    // appear). Lifted to App so any cell, header, or row can read +
    // write it without prop-drilling through three component layers.
    //
    // contextMenu state holds the currently-open menu's anchor + items
    // (or null = none). showContextMenu is the helper we pass down so
    // children just call `showContextMenu(x, y, items)` without knowing
    // about the menu's internals.
    const [clipboard, setClipboard] = useState(null);
    // contextMenu / ccBinding / cellBinding flow through the
    // spectator broadcast channel so a spectator mirrors the
    // currently-open popover. JSON serialization strips menu-item
    // onClick handlers — the spectator renders the menu but its
    // clicks are inert (see ContextMenu's item.action guard).
    const [contextMenu, setContextMenu] = useSharedUiState('contextMenu', null);
    const showContextMenu = useCallback((x, y, items) => {
        setContextMenu({ x, y, items });
    }, [setContextMenu]);
    const closeContextMenu = useCallback(() => setContextMenu(null), [setContextMenu]);

    // CC binding popup state. Long-press / right-click on a bindable
    // control passes through `openCcBinding(instanceId, paramName)`
    // (threaded via displayCtx in renderparam.js).
    const [ccBinding, setCcBinding] = useSharedUiState('ccBinding', null);
    const openCcBinding = useCallback(async (instanceId, paramName) => {
        // Look up the plugin's display name + param label so the
        // popup header reads "Arp 1 → Rate" instead of opaque IDs.
        try {
            const inst = await api(`/plugins/instances/${encodeURIComponent(instanceId)}`);
            const findLabel = (items) => {
                for (const p of items || []) {
                    if (p.name === paramName) return p.label || p.name;
                    if (p.type === 'group' && p.children) {
                        const hit = findLabel(p.children);
                        if (hit) return hit;
                    }
                }
                return null;
            };
            const paramLabel = findLabel(inst.params_schema) || paramName;
            setCcBinding({
                instanceId,
                paramName,
                paramLabel,
                pluginName: inst.name || instanceId,
            });
        } catch (err) {
            console.warn('openCcBinding lookup failed:', err);
            setCcBinding({ instanceId, paramName, paramLabel: paramName, pluginName: instanceId });
        }
    }, []);
    const closeCcBinding = useCallback(() => setCcBinding(null), [setCcBinding]);

    // Controller-cell binding popup. Parallel to openCcBinding but for
    // LayoutGrid cells — those carry a symmetric (channel, cc) in
    // `cell_bindings` rather than an entry in `cc_map`. Long-press on
    // a controller cell on the Controller page routes here.
    const [cellBinding, setCellBinding] = useSharedUiState('cellBinding', null);
    const openCellBinding = useCallback(async (instanceId, cellName) => {
        try {
            const inst = await api(`/plugins/instances/${encodeURIComponent(instanceId)}`);
            // Find the cell's label in the LayoutGrid schema. The
            // label may be overridden via the cell_labels dict; check
            // that first, fall back to the schema label.
            let cellLabel = cellName;
            let labelsParam = null;
            for (const p of inst.params_schema || []) {
                if (p.type !== 'layoutgrid') continue;
                labelsParam = p.labels_param || null;
                for (const c of p.cells || []) {
                    if ((c.param && c.param.name) === cellName) {
                        cellLabel = (c.param && c.param.label) || cellName;
                        break;
                    }
                }
                break;
            }
            const overrides = (labelsParam && inst.params[labelsParam]) || {};
            if (overrides[cellName]) cellLabel = overrides[cellName];
            setCellBinding({
                instanceId,
                cellName,
                cellLabel,
                pluginName: inst.name || instanceId,
            });
        } catch (err) {
            console.warn('openCellBinding lookup failed:', err);
            setCellBinding({ instanceId, cellName, cellLabel: cellName, pluginName: instanceId });
        }
    }, []);
    const closeCellBinding = useCallback(() => setCellBinding(null), [setCellBinding]);

    let page;
    switch (tab) {
        case 'routing':
            page = html`<${RoutingPage} devices=${devices} connections=${connections} refresh=${refresh} showToast=${showToast} clockSources=${clockSources} clockQuarters=${clockQuarters} midiRates=${midiRates}
                onDeviceOpen=${(clientId) => setSelectedDeviceId(clientId)}
                clipboard=${clipboard} setClipboard=${setClipboard}
                showContextMenu=${showContextMenu} />`;
            break;
        case 'controller':
            page = html`<${ControllerPage} pluginDisplays=${pluginDisplays} showToast=${showToast}
                selectedId=${route.controllerId}
                onSelect=${setControllerId}
                onEditConfig=${openControllerConfig}
                openCcBinding=${openCcBinding}
                openCellBinding=${openCellBinding}
                clockPosition=${clockPosition} />`;
            break;
        case 'play':
            page = html`<${PlayPage} pluginDisplays=${pluginDisplays} showToast=${showToast}
                selectedId=${route.playId}
                onSelect=${setPlayId}
                onEditConfig=${openPlayConfig}
                openCcBinding=${openCcBinding}
                clockPosition=${clockPosition} />`;
            break;
        case 'settings':
            page = html`<${SettingsPage} showToast=${showToast}
                showMidiBar=${showMidiBar} toggleMidiBar=${toggleMidiBar}
                section=${route.settingsSection}
                onNavigate=${(s) => navigate({ tab: 'settings', settingsSection: s })}
                openCcBinding=${openCcBinding}
                openCellBinding=${openCellBinding} />`;
            break;
    }

    return html`
        <div class="header">
            <${VersionBadge} version=${version} loadedBuild=${loadedBuild} serverBuild=${serverBuild} />
            <div class="header-right">
                <span class="status ${sseConnected ? (devices.length > 0 ? 'ok' : '') : 'err'}">${sseConnected ? `${devices.length} device${devices.length !== 1 ? 's' : ''}` : 'Connection lost'}</span>
                <${FullscreenButton} />
            </div>
        </div>
        ${configFallback && html`<div class="banner">Config unreadable — using default all-to-all routing. Save to fix.</div>`}
        <div class="main ${showMidiBar ? 'with-midi-bar' : ''}" data-spectator-scroll="main">${page}<${ScrollAssist} /></div>
        ${showMidiBar && html`<${MidiBar} events=${midiEvents} />`}
        <nav class="bottom-nav">
            <button class=${tab === 'routing' ? 'active' : ''} onclick=${() => setTab('routing')}>
                <span class="nav-icon-wrap">
                    ${IconRouting}
                    ${configDirty ? html`<span class="dirty-asterisk" title="Unsaved changes">*</span>` : ''}
                </span>
                <span>Routing</span>
            </button>
            <button class=${tab === 'controller' ? 'active' : ''} onclick=${() => setTab('controller')}>${IconController}<span>Controller</span></button>
            <button class=${tab === 'play' ? 'active' : ''} onclick=${() => setTab('play')}>${IconPlay}<span>Play</span></button>
            <button class=${tab === 'settings' ? 'active' : ''} onclick=${() => setTab('settings')}>${IconSettings}<span>Settings</span></button>
        </nav>
        ${selectedDevice && html`<${DeviceDetailPanel} key=${selectedDeviceId} device=${selectedDevice}
            onClose=${() => { setSelectedDeviceId(null); refresh(); }}
            showToast=${showToast} refresh=${refresh}
            pluginDisplays=${pluginDisplays}
            clipboard=${clipboard} setClipboard=${setClipboard}
            showContextMenu=${showContextMenu}
            openCcBinding=${openCcBinding}
            onJumpToController=${(instanceId) => navigate({ tab: 'controller', controllerId: instanceId })}
            onJumpToPlay=${(instanceId) => navigate({ tab: 'play', playId: instanceId })} />`}
        <${Toast} message=${toast} />
        <${ContextMenu} menu=${contextMenu} onClose=${closeContextMenu} />
        <${CcBinding} open=${ccBinding} onClose=${closeCcBinding} />
        <${CellBinding} open=${cellBinding} onClose=${closeCellBinding} />
    `;
}

// SourceAppWrapper exists for one reason: App needs to consume the
// SpectatorContext from BEFORE its hooks run (useSharedUiState calls
// useContext at the top of App, before App's own return-time
// Provider would take effect). So the source-mode boot path wraps
// App in this component, which provides the source-side context up
// the tree. In spectator mode this wrapper is bypassed — SpectatorView
// provides its own context above App directly.
function SourceAppWrapper() {
    const [watched, setWatched] = useState(false);
    const [route, setRoute] = useState(null);
    const sourceCtx = useSourceBroadcaster({ watched, route });
    return html`<${SpectatorContext.Provider} value=${sourceCtx}>
        <${App} onSpectatorWatched=${setWatched} onRouteChange=${setRoute} />
    </${SpectatorContext.Provider}>`;
}

// Hygiene: prune stale per-device localStorage entries on app startup
// so the per-origin store doesn't grow unboundedly across sessions.
runStorageCleanup();

// Apply the persisted layout-density preference before first render
// so the tightened (or default) chrome is in effect from frame zero —
// avoids a flash of the wrong spacing on app boot.
applyLayoutDensity(getLayoutDensity());

// Spectator-mode boot branch. When ?spectate=<conn_id> is in the URL,
// we render SpectatorView instead of the normal app — the view drives
// App from a network-supplied route/state instead of from window
// state, so OBS Browser Source (or any tab) can mirror a phone with
// effectively zero latency. ?touches=1 enables the ripple overlay.
const _spectateParams = (() => {
    try {
        const p = new URLSearchParams(window.location.search);
        const cid = p.get('spectate');
        if (!cid) return null;
        return { clientId: cid, showTouches: p.get('touches') === '1' };
    } catch { return null; }
})();

if (_spectateParams) {
    render(html`<${SpectatorView}
        clientId=${_spectateParams.clientId}
        showTouches=${_spectateParams.showTouches}
        AppComponent=${App} />`, document.getElementById('app'));
} else {
    render(html`<${SourceAppWrapper} />`, document.getElementById('app'));
}
