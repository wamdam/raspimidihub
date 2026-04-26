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
import { html, api, useSSE, Toast, MidiBar } from './ui/common.js';
import { IconRouting, IconController, IconPreset, IconSettings } from './ui/icons.js';
import { runStorageCleanup } from './ui/storage.js';
import { useRouter } from './ui/router.js';
import { noteName } from './state/constants.js';
import { DeviceDetailPanel } from './panels/devicedetail.js';
import { RoutingPage } from './pages/routing.js';
import { ControllerPage } from './pages/controller.js';
import { PresetsPage } from './pages/presets.js';
import { SettingsPage } from './pages/settings.js';

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
    // Device-detail panel open state lives in the URL — opening / closing
    // the panel pushes a new history entry, so the back button closes it.
    const selectedDeviceId = route.deviceId != null ? Number(route.deviceId) : null;
    const setSelectedDeviceId = useCallback((id) => {
        navigate({ tab: 'routing', deviceId: id != null ? id : null });
    }, [navigate]);
    const selectedDevice = selectedDeviceId != null ? devices.find(d => d.client_id === selectedDeviceId) || null : null;
    const [showMidiBar, setShowMidiBar] = useState(() => localStorage.getItem('midiBar') !== 'off');
    const [midiEvents, setMidiEvents] = useState({});  // src_client -> {name, text}
    const [clockSources, setClockSources] = useState({});  // src_client -> timestamp
    const [clockQuarters, setClockQuarters] = useState({}); // src_client -> ts of last quarter-note tick
    const [midiRates, setMidiRates] = useState({});  // "client:port" -> msgs/sec
    const [pluginDisplays, setPluginDisplays] = useState({});  // instance_id -> {name: value}
    const [sseConnected, setSseConnected] = useState(true);

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
        api('/system').then(s => { setConfigFallback(s.config_fallback); setVersion(s.version || ''); });
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
    }, (connected) => {
        setSseConnected(connected);
        if (connected) refresh();
    });

    const toggleMidiBar = () => {
        const next = !showMidiBar;
        setShowMidiBar(next);
        localStorage.setItem('midiBar', next ? 'on' : 'off');
    };

    const showToast = (msg) => {
        setToast(msg);
        setTimeout(() => setToast(''), 2500);
    };

    let page;
    switch (tab) {
        case 'routing':
            page = html`<${RoutingPage} devices=${devices} connections=${connections} refresh=${refresh} showToast=${showToast} clockSources=${clockSources} clockQuarters=${clockQuarters} midiRates=${midiRates}
                onDeviceOpen=${(clientId) => setSelectedDeviceId(clientId)} />`;
            break;
        case 'controller':
            page = html`<${ControllerPage} pluginDisplays=${pluginDisplays} showToast=${showToast}
                selectedId=${route.controllerId}
                onSelect=${(id, opts) => navigate({ tab: 'controller', controllerId: id }, opts)} />`;
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
            <h1>RaspiMIDIHub${version ? html` <span style="font-size:11px;font-weight:400;color:var(--text-dim)">v${version}</span>` : ''}</h1>
            <span class="status ${sseConnected ? (devices.length > 0 ? 'ok' : '') : 'err'}">${sseConnected ? `${devices.length} device${devices.length !== 1 ? 's' : ''}` : 'Connection lost'}</span>
        </div>
        ${configFallback && html`<div class="banner">Config unreadable — using default all-to-all routing. Save to fix.</div>`}
        <div class="main ${showMidiBar ? 'with-midi-bar' : ''}">${page}</div>
        ${showMidiBar && html`<${MidiBar} events=${midiEvents} />`}
        <nav class="bottom-nav">
            <button class=${tab === 'routing' ? 'active' : ''} onclick=${() => setTab('routing')}>${IconRouting}<span>Routing</span></button>
            <button class=${tab === 'controller' ? 'active' : ''} onclick=${() => setTab('controller')}>${IconController}<span>Controller</span></button>
            <button class=${tab === 'presets' ? 'active' : ''} onclick=${() => setTab('presets')}>${IconPreset}<span>Presets</span></button>
            <button class=${tab === 'settings' ? 'active' : ''} onclick=${() => setTab('settings')}>${IconSettings}<span>Settings</span></button>
        </nav>
        ${selectedDevice && html`<${DeviceDetailPanel} key=${selectedDeviceId} device=${selectedDevice}
            onClose=${() => { setSelectedDeviceId(null); refresh(); }}
            showToast=${showToast} refresh=${refresh}
            pluginDisplays=${pluginDisplays}
            onJumpToController=${(instanceId) => {
                try { localStorage.setItem('raspimidihub:lastController', instanceId); } catch {}
                navigate({ tab: 'controller', controllerId: instanceId });
            }} />`}
        <${Toast} message=${toast} />
    `;
}

// Hygiene: prune stale per-device localStorage entries on app startup
// so the per-origin store doesn't grow unboundedly across sessions.
runStorageCleanup();

render(html`<${App} />`, document.getElementById('app'));
