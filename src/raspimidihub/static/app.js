/**
 * App entry point: top-level state, SSE wiring, page routing, render boot.
 *
 * Everything else lives next door:
 *   ui/        — shared primitives (html, hooks, icons, Toast, MidiBar)
 *   state/     — constants
 *   panels/    — full-screen overlays (mapping form, filter, device detail)
 *   pages/     — routing / presets / settings + the connection matrix
 *   components/— plugin parameter controls (already split in step 4)
 */

import { render } from './lib/preact.module.js';
import { useState, useEffect, useRef, useCallback } from './lib/hooks.module.js';
import { html, api, useSSE, Toast, MidiBar, hardReload } from './ui/common.js';
import { ContextMenu } from './ui/contextmenu.js';
import { setSSEConnectionId, useSSESubscription } from './ui/sse-subscriptions.js';
import { IconRouting, IconController, IconPreset, IconSettings } from './ui/icons.js';
import { runStorageCleanup } from './ui/storage.js';
import { useRouter } from './ui/router.js';
import { noteName } from './state/constants.js';
import { DeviceDetailPanel } from './panels/devicedetail.js';
import { RoutingPage } from './pages/routing.js';
import { ControllerPage } from './pages/controller.js';
import { PresetsPage } from './pages/presets.js';
import { SettingsPage } from './pages/settings.js';

// Header badge: "v2.0.9·a1b2c3d4" plus a "stale, reload" warning when
// the loaded JS bundle's build token differs from the server's current
// one. Lets the user verify they're running fresh code at a glance.
function VersionBadge({ version, loadedBuild, serverBuild }) {
    if (!version) return html`<h1>RaspiMIDIHub</h1>`;
    // loadedBuild looks like "2.0.9-69ee5610" (?v=<version>-<token>);
    // serverBuild is just "69ee5610" — strip the version prefix so we
    // compare apples to apples.
    const loadedToken = loadedBuild ? loadedBuild.split('-').pop() : '';
    const stale = serverBuild && loadedToken && serverBuild !== loadedToken;
    return html`<h1>RaspiMIDIHub
        <span style="font-size:11px;font-weight:400;color:var(--text-dim);margin-left:10px">
            v${version}${loadedToken ? '·' + loadedToken : ''}
            ${stale ? html`<span style="color:#f80;cursor:pointer;margin-left:6px"
                title="Server has been redeployed since this tab loaded — click to reload"
                onclick=${hardReload}>· stale, reload</span>` : ''}
        </span>
    </h1>`;
}

function App() {
    const { route, navigate } = useRouter();
    const tab = route.tab;
    const setTab = useCallback((t) => navigate({ tab: t }), [navigate]);
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
            // Track clock sources regardless of connections
            if (data.event === 'Clock') {
                setClockSources(prev => ({...prev, [data.src_client]: Date.now()}));
                return;
            }

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
            setClockQuarters(prev => ({ ...prev, [data.src_client]: Date.now() }));
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
    const [contextMenu, setContextMenu] = useState(null);
    const showContextMenu = useCallback((x, y, items) => {
        setContextMenu({ x, y, items });
    }, []);
    const closeContextMenu = useCallback(() => setContextMenu(null), []);

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
                clockPosition=${clockPosition} />`;
            break;
        case 'presets':
            page = html`<${PresetsPage} refresh=${refresh} showToast=${showToast} />`;
            break;
        case 'settings':
            page = html`<${SettingsPage} showToast=${showToast} showMidiBar=${showMidiBar} toggleMidiBar=${toggleMidiBar} />`;
            break;
    }

    return html`
        <div class="header">
            <${VersionBadge} version=${version} loadedBuild=${loadedBuild} serverBuild=${serverBuild} />
            <span class="status ${sseConnected ? (devices.length > 0 ? 'ok' : '') : 'err'}">${sseConnected ? `${devices.length} device${devices.length !== 1 ? 's' : ''}` : 'Connection lost'}</span>
        </div>
        ${configFallback && html`<div class="banner">Config unreadable — using default all-to-all routing. Save to fix.</div>`}
        <div class="main ${showMidiBar ? 'with-midi-bar' : ''}">${page}</div>
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
            <button class=${tab === 'presets' ? 'active' : ''} onclick=${() => setTab('presets')}>${IconPreset}<span>Presets</span></button>
            <button class=${tab === 'settings' ? 'active' : ''} onclick=${() => setTab('settings')}>${IconSettings}<span>Settings</span></button>
        </nav>
        ${selectedDevice && html`<${DeviceDetailPanel} key=${selectedDeviceId} device=${selectedDevice}
            onClose=${() => { setSelectedDeviceId(null); refresh(); }}
            showToast=${showToast} refresh=${refresh}
            pluginDisplays=${pluginDisplays}
            clipboard=${clipboard} setClipboard=${setClipboard}
            showContextMenu=${showContextMenu}
            onJumpToController=${(instanceId) => navigate({ tab: 'controller', controllerId: instanceId })} />`}
        <${Toast} message=${toast} />
        <${ContextMenu} menu=${contextMenu} onClose=${closeContextMenu} />
    `;
}

// Hygiene: prune stale per-device localStorage entries on app startup
// so the per-origin store doesn't grow unboundedly across sessions.
runStorageCleanup();

render(html`<${App} />`, document.getElementById('app'));
