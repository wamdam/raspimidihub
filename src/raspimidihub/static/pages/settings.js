/**
 * Settings page: hub + sub-pages.
 *
 * The hub is a card list of sub-page links (Sys Info, Network, MIDI,
 * Display, Update, Plugin Control Mappings). Each sub-page renders
 * with a `< Settings / <title>` back-bar; the active sub-page lives
 * in the URL (`/settings/<section>`) and per-tab sub-state restores
 * it when bouncing through other bottom-nav tabs.
 */

import { useState, useEffect } from '../lib/hooks.module.js';
import { html, api, hardReload } from '../ui/common.js';
import { UPDATE_LABELS } from '../state/constants.js';
import { getSoundsEnabled, setSoundsEnabled,
         getLayoutDensity, setLayoutDensity, DENSITY_OPTIONS,
         getScrollAssist, setScrollAssist } from '../components/common.js';
import { getTheme, setTheme, listThemes } from '../lib/theme.js';

function NetworkCard({ iface, showToast }) {
    const [method, setMethod] = useState(iface.method || 'auto');
    const [address, setAddress] = useState(iface.address || '');
    const [netmask, setNetmask] = useState(iface.netmask || '255.255.255.0');
    const [gateway, setGateway] = useState(iface.gateway || '');
    const [saving, setSaving] = useState(false);

    const save = async () => {
        setSaving(true);
        const body = { method };
        if (method === 'manual') { body.address = address; body.netmask = netmask; body.gateway = gateway; }
        const res = await api(`/network/${iface.interface}`, { method: 'POST', body: JSON.stringify(body) });
        setSaving(false);
        if (res.error) showToast(res.error);
        else showToast(`${iface.interface} configured`);
    };

    return html`
        <div class="card">
            <h3>${iface.interface} ${iface.up ? html`<span style="color:var(--success);font-size:12px">\u25cf</span>` : html`<span style="color:var(--text-dim);font-size:12px">\u25cb</span>`}</h3>
            ${iface.address && html`<p style="font-size:13px;color:var(--text-dim);margin-bottom:8px">${iface.address}/${iface.netmask}${iface.gateway ? ` gw ${iface.gateway}` : ''}</p>`}
            <div class="form-group">
                <label>Mode</label>
                <select value=${method} onChange=${e => setMethod(e.target.value)}>
                    <option value="auto">DHCP</option>
                    <option value="manual">Static IP</option>
                </select>
            </div>
            ${method === 'manual' && html`
                <div class="form-group">
                    <label>IP Address</label>
                    <input value=${address} onInput=${e => setAddress(e.target.value)} placeholder="10.1.1.2" />
                </div>
                <div style="display:flex;gap:8px">
                    <div class="form-group" style="flex:1">
                        <label>Netmask</label>
                        <input value=${netmask} onInput=${e => setNetmask(e.target.value)} placeholder="255.255.255.0" />
                    </div>
                    <div class="form-group" style="flex:1">
                        <label>Gateway</label>
                        <input value=${gateway} onInput=${e => setGateway(e.target.value)} placeholder="optional" />
                    </div>
                </div>
            `}
            <button class="btn btn-primary btn-block" onclick=${save}>${saving ? 'Applying...' : 'Apply'}</button>
        </div>
    `;
}

// Tiny "we're alive" indicator: a single dot hops along five
// positions, advancing one slot on every poll. Colour reflects the
// most recent poll's outcome — green when polls are getting through,
// red when they're failing (e.g. AP outage with the user's phone on
// a different WiFi). When polling stops, the dot stops with it, so
// the user can tell at a glance whether anything's happening.
//
// Implementation note: all five dots use the same background colour;
// only opacity varies (active = 1, inactive = 0.2). Earlier we did
// this by swapping background between the bright colour and a dim
// surface colour, which mis-rendered on subsequent cycles — the
// active dot looked half-faded after the first lap. Animating only
// opacity sidesteps that whole class of background-transition glitch.
const POLL_DOT_COUNT = 5;
function PollIndicator({ tick, ok }) {
    const active = tick % POLL_DOT_COUNT;
    const colour = ok === null ? 'var(--text-dim)'
                  : ok ? 'var(--success)'
                  : 'var(--danger)';
    return html`
        <div data-testid="poll-indicator"
            style="display:flex;justify-content:center;gap:6px;margin-top:6px;height:8px;align-items:center"
            data-poll-tick=${tick}>
            ${[...Array(POLL_DOT_COUNT)].map((_, i) => html`
                <span style="width:6px;height:6px;border-radius:50%;background:${colour};opacity:${i === active ? 1 : 0.2};transition:opacity 200ms ease-out"></span>
            `)}
        </div>
    `;
}

// Phase 5.5 update flow:
//   - the Pi normally lives in AP mode so phones can reach it
//   - to fetch a new release it has to talk to the public internet,
//     which the AP can't do. POST /system/check-update orchestrates
//     a transient WiFi switch (or stays put if ethernet works).
//   - downloads land in /var/lib/raspimidihub/updates/ as deb files
//     plus sibling .changelog.md files. GET /system/versions returns
//     the list. POST /system/install installs a chosen one.
function VersionsCard({ showToast, onUpdatingChange }) {
    const [versions, setVersions] = useState(null);  // {running, stored: [...]}
    const [checking, setChecking] = useState(false);
    const [installing, setInstalling] = useState(false);
    const [statusMsg, setStatusMsg] = useState('');
    const [statusErr, setStatusErr] = useState('');
    const [expandedVersion, setExpandedVersion] = useState(null);
    // pollTick advances at 1 Hz independent of the actual poll cadence
    // — the hopping-dot indicator should keep moving even during an AP
    // outage when fetches throw and no real poll is happening, so the
    // user sees liveness regardless. pollOk is the latest poll's
    // outcome (null = none yet, true = success, false = failure) and
    // drives the dot's colour.
    const [pollTick, setPollTick] = useState(0);
    const [pollOk, setPollOk] = useState(null);
    useEffect(() => {
        if (!checking && !installing) return;
        const id = setInterval(() => setPollTick(t => t + 1), 1000);
        return () => clearInterval(id);
    }, [checking, installing]);
    const setUpdatingFlag = (v) => onUpdatingChange && onUpdatingChange(v);

    const refresh = async () => {
        try {
            const res = await fetch('/api/system/versions').then(r => r.json());
            setVersions(res);
        } catch (e) {}
    };
    useEffect(() => { refresh(); }, []);

    // Watch the orchestrator's status file while a check or install
    // runs. The orchestrator runs as a backgrounded asyncio task on
    // the server; the AP may go down mid-flow when we switch to WiFi
    // client mode. Poll fetches that fail (TypeError on phones when
    // the AP drops) are silently absorbed in the short term — but if
    // they keep failing past STALL_TIMEOUT_MS, the user's phone has
    // probably auto-reconnected to a different saved network and won't
    // come back to the Pi's AP on its own. Surface a help message
    // telling them to reconnect + reload.
    //
    // For an install we also detect the running-version flip, which
    // is the unambiguous "the new deb is live" signal.
    const STALL_TIMEOUT_MS = 90_000;
    const pollStatus = (until, startVersion) => {
        let lastSuccessAt = Date.now();  // kickoff just succeeded
        let stalled = false;
        const id = setInterval(async () => {
            let s = null;
            try {
                const resp = await fetch('/api/system/update-status');
                s = await resp.json();
                lastSuccessAt = Date.now();
                setPollOk(true);
                if (stalled) {
                    stalled = false;
                    setStatusErr('');
                }
            } catch (e) {
                setPollOk(false);
                // Silently keep polling — but if it's been long enough
                // that the phone has clearly given up on the AP, swap
                // to a help message. We don't clearInterval; once the
                // user reconnects, polling resumes and the real status
                // (most likely 'done') replaces this.
                if (!stalled && Date.now() - lastSuccessAt > STALL_TIMEOUT_MS) {
                    stalled = true;
                    setStatusErr(
                        "Can't reach the Pi. The update probably finished, " +
                        "but your phone reconnected to a different WiFi " +
                        "network. Reconnect to the Pi's AP " +
                        "(RaspiMIDIHub-…) and reload this page.");
                    setStatusMsg('');
                }
                return;
            }
            if (!s || !s.status) return;
            const step = s.status.step || '';
            if (step.startsWith('error')) {
                setStatusErr(s.status.message || step);
                setStatusMsg('');
                clearInterval(id);
                setChecking(false); setInstalling(false);
                setUpdatingFlag(false);
                if (until === 'check') refresh();
                return;
            }
            setStatusMsg(UPDATE_LABELS[step] || step);
            if (s.version && startVersion && s.version !== startVersion) {
                clearInterval(id);
                hardReload();
                return;
            }
            if (step === 'done' && until === 'check') {
                clearInterval(id);
                const newCount = (s.status.newly_downloaded || []).length;
                if (newCount > 0) {
                    showToast(`Downloaded ${newCount} new version${newCount === 1 ? '' : 's'}`);
                } else {
                    showToast('Already up to date');
                }
                setChecking(false);
                setStatusMsg('');
                setUpdatingFlag(false);
                refresh();
                return;
            }
        }, 1500);
        return id;
    };

    const checkForUpdates = async () => {
        setChecking(true);
        setStatusErr('');
        setStatusMsg('Starting...');
        setPollTick(0);
        setPollOk(null);
        setUpdatingFlag(true);
        const startVersion = versions ? versions.running : null;
        const pollId = pollStatus('check', startVersion);
        // Server kicks off the orchestrator as a background task and
        // returns "started" immediately — by design, because the AP
        // may go down once it switches to WiFi client mode and a
        // long-held HTTP request would die from the phone's side.
        // The poll loop above carries us through the outage.
        let res;
        try {
            res = await fetch('/api/system/check-update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: '{}',
            });
        } catch (e) {
            clearInterval(pollId);
            setStatusErr(String(e));
            setChecking(false);
            setUpdatingFlag(false);
            return;
        }
        // 409 = another tab/click already started the orchestrator. The
        // poll loop tracks the in-flight run, no need to error out.
        if (res.status === 409) return;
        const body = await res.json().catch(() => ({}));
        if (body.error) {
            clearInterval(pollId);
            setStatusErr(body.error);
            setStatusMsg('');
            setChecking(false);
            setUpdatingFlag(false);
            refresh();
        }
    };

    const installStored = async (version) => {
        if (!confirm(`Install v${version}? The service will restart.`)) return;
        setInstalling(true);
        setStatusErr('');
        setStatusMsg('Starting install...');
        setPollTick(0);
        setPollOk(null);
        setUpdatingFlag(true);
        const startVersion = versions ? versions.running : null;
        pollStatus('install', startVersion);
        const res = await api('/system/install', {
            method: 'POST',
            body: JSON.stringify({ version }),
        });
        if (res.error) {
            setStatusErr(res.error);
            setStatusMsg('');
            setInstalling(false);
            setUpdatingFlag(false);
        }
    };

    return html`
        <div class="card">
            <h3>Software Versions</h3>
            ${!versions ? html`<p style="color:var(--text-dim)">Loading...</p>` : html`
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <span style="font-size:13px">Running: <b>v${versions.running}</b></span>
                    <span style="font-size:12px;color:var(--text-dim)">${(versions.stored || []).length} stored</span>
                </div>
                <button class="btn btn-secondary btn-block" data-testid="check-updates"
                    onclick=${checkForUpdates} disabled=${checking || installing}>
                    ${checking ? 'Checking...' : 'Check GitHub for newer versions'}
                </button>
                <label style="display:flex;align-items:center;gap:8px;margin-top:8px;font-size:12px;color:var(--text-dim);cursor:pointer">
                    <input type="checkbox"
                        checked=${!!versions.include_prereleases}
                        onchange=${async (e) => {
                            const enabled = e.target.checked;
                            try {
                                const r = await fetch('/api/system/include-prereleases', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ enabled }),
                                });
                                if (!r.ok) throw new Error(await r.text());
                                refresh();
                                showToast(enabled
                                    ? 'Alpha / beta releases will be included'
                                    : 'Stable releases only');
                            } catch (err) {
                                showToast('Failed: ' + (err.message || err));
                            }
                        }} />
                    Include alpha / beta releases
                </label>
                ${(statusMsg || statusErr) && html`
                    <p data-testid="update-status" style="font-size:13px;margin-top:8px;text-align:center;font-weight:500;${statusErr ? 'color:var(--danger)' : 'color:var(--warn)'}">
                        ${statusErr || statusMsg}
                    </p>
                `}
                ${(checking || installing) && html`
                    <${PollIndicator} tick=${pollTick} ok=${pollOk} />
                `}

                ${(versions.stored || []).length > 0 ? html`
                    <div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--surface2)">
                        <div style="font-size:12px;color:var(--text-dim);margin-bottom:6px">Downloaded versions (newest first)</div>
                        ${versions.stored.map(v => html`
                            <div style="padding:8px 0;border-bottom:1px solid var(--surface2)">
                                <div style="display:flex;justify-content:space-between;align-items:center">
                                    <span style="font-size:13px">
                                        v${v.version}
                                        ${v.version === versions.running ? html` <span style="color:var(--text-dim);font-size:11px">(current)</span>` : ''}
                                    </span>
                                    <div style="display:flex;gap:6px;align-items:center">
                                        ${v.changelog && html`
                                            <button style="background:none;border:none;color:var(--accent);font-size:11px;cursor:pointer;padding:2px 6px"
                                                onclick=${() => setExpandedVersion(expandedVersion === v.version ? null : v.version)}>
                                                ${expandedVersion === v.version ? 'Hide' : 'Notes'}
                                            </button>
                                        `}
                                        ${v.version !== versions.running && html`
                                            <button class="btn btn-secondary" data-testid=${'install-' + v.version}
                                                style="padding:4px 12px;font-size:12px"
                                                onclick=${() => installStored(v.version)} disabled=${installing || checking}>Install</button>
                                        `}
                                    </div>
                                </div>
                                ${expandedVersion === v.version && v.changelog && html`
                                    <pre style="font-size:11px;color:var(--text-dim);white-space:pre-wrap;margin-top:6px;max-height:200px;overflow-y:auto;background:var(--bg);padding:8px;border-radius:6px">${v.changelog}</pre>
                                `}
                            </div>
                        `)}
                    </div>
                ` : html`
                    <p style="font-size:11px;color:var(--text-dim);margin-top:8px">
                        Click "Check GitHub" to fetch newer versions. They'll be stored locally so you can install them later.
                    </p>
                `}
            `}
        </div>
    `;
}

// Consolidated WiFi card (rebuilt from the older multi-button version).
//
// State the user can change:
//   - wifi_mode_pref: ap_only / wifi_for_updates / wifi_always
//   - home WiFi credentials (SSID + password) — data only, no live impact
//   - AP password — propagates to hostapd without flipping modes
//
// Mode-pref radio is the only thing that drives the live wlan0 state, and
// it requires explicit Apply (Discard / Apply buttons appear only when
// dirty). Apply is backgrounded server-side because switching to client
// mode tears down the AP and would kill the held-open HTTP request from
// a phone — same pattern as POST /api/system/check-update.
function WiFiCard({ showToast }) {
    const [wifi, setWifi] = useState(null);
    const [pendingPref, setPendingPref] = useState(null);
    const [editing, setEditing] = useState(null); // null | 'home-wifi' | 'ap-password'
    const [applying, setApplying] = useState(false);

    const refresh = () => api('/wifi').then(w => {
        setWifi(w);
        setPendingPref(null);
    }).catch(() => {});
    useEffect(() => { refresh(); }, []);

    if (!wifi) {
        return html`<div class="card"><h3>WiFi</h3><p style="color:var(--text-dim)">Loading...</p></div>`;
    }

    const isAp = wifi.mode === 'ap';
    const hasCreds = !!wifi.saved_client_ssid;
    const savedPref = wifi.wifi_mode_pref;
    const dirty = pendingPref !== null && pendingPref !== savedPref;
    const targetPref = pendingPref ?? savedPref;

    // Apply button label tells the user what's actually about to happen,
    // so clicking Apply never surprises. Four cases:
    //   targetPref==wifi_always + currently AP → "Switch to home WiFi now"
    //   targetPref!=wifi_always + currently client → "Stop client, start AP"
    //   else → "Save (no mode change)"
    let applyLabel = 'Save';
    if (dirty) {
        if (targetPref === 'wifi_always' && isAp) applyLabel = 'Switch to home WiFi now';
        else if (targetPref !== 'wifi_always' && !isAp) applyLabel = 'Stop WiFi client, start AP';
        else applyLabel = 'Save mode';
    }

    const apply = async () => {
        setApplying(true);
        const res = await api('/wifi/apply-mode', {
            method: 'POST', body: JSON.stringify({ pref: targetPref }),
        });
        setApplying(false);
        if (res.error) {
            showToast('Apply failed: ' + res.error);
            return;
        }
        showToast(res.switched ? 'Applying mode change...' : 'Mode saved');
        // Poll /api/wifi a couple of times if a switch was triggered, so
        // the displayed mode catches up. Otherwise just refresh once.
        if (res.switched) {
            setTimeout(refresh, 1500);
            setTimeout(refresh, 4000);
        } else {
            refresh();
        }
    };

    const ModeRadio = ({ value, label, sub, requiresCreds }) => {
        const disabled = requiresCreds && !hasCreds;
        return html`
            <label data-testid=${'mode-' + value}
                style="display:flex;align-items:flex-start;gap:8px;padding:6px 0;cursor:${disabled ? 'not-allowed' : 'pointer'};opacity:${disabled ? 0.5 : 1}">
                <input type="radio" name="wifi-mode-pref" style="margin-top:3px"
                    checked=${targetPref === value}
                    disabled=${disabled || applying}
                    onChange=${() => setPendingPref(value)} />
                <span style="flex:1">
                    <div style="font-size:13px;font-weight:500">${label}</div>
                    <div style="font-size:11px;color:var(--text-dim)">${sub}</div>
                </span>
            </label>
        `;
    };

    return html`
        <div class="card">
            <h3>WiFi</h3>
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;padding:10px;background:var(--bg);border-radius:6px">
                <span style="font-size:20px">${isAp ? '📡' : '🔗'}</span>
                <div style="flex:1">
                    <div style="font-size:15px;font-weight:600">${isAp ? 'Access Point' : 'Client'}: ${wifi.ssid || '-'}</div>
                    <div style="font-size:12px;color:var(--text-dim)">${wifi.ip || 'No IP'}</div>
                </div>
                <span style="font-size:11px;padding:3px 8px;border-radius:4px;font-weight:600;${isAp
                    ? 'background:var(--accent2);color:#fff'
                    : 'background:var(--success);color:#fff'}">${isAp ? 'AP' : 'WiFi'}</span>
            </div>

            <div data-testid="wifi-mode-pref" style="margin-bottom:14px">
                <div style="font-size:13px;color:var(--text-dim);margin-bottom:4px">
                    Network mode${dirty ? html` <span style="color:var(--warn)">unsaved ●</span>` : ''}
                </div>
                <${ModeRadio} value="ap_only" label="AP only"
                    sub="Pi is its own WiFi network. Phones connect to it." />
                <${ModeRadio} value="wifi_for_updates" label="WiFi for updates"
                    sub=${hasCreds
                        ? "Joins home WiFi briefly when fetching releases, then back to AP."
                        : "(set home WiFi below to enable)"}
                    requiresCreds=${true} />
                <${ModeRadio} value="wifi_always" label="WiFi always"
                    sub=${hasCreds
                        ? "Pi joins home WiFi permanently. No AP."
                        : "(set home WiFi below to enable)"}
                    requiresCreds=${true} />
            </div>

            ${dirty && html`
                <div class="btn-group" style="margin-bottom:12px">
                    <button class="btn btn-secondary" onclick=${() => setPendingPref(null)} disabled=${applying}>
                        Discard
                    </button>
                    <button class="btn btn-primary" data-testid="apply-mode"
                        onclick=${apply} disabled=${applying}>
                        ${applying ? 'Applying...' : applyLabel}
                    </button>
                </div>
            `}

            <div style="border-top:1px solid var(--surface2);padding-top:10px">
                <${ConfigRow} label="Home WiFi"
                    value=${wifi.saved_client_ssid || html`<span style="color:var(--text-dim)">not configured</span>`}
                    buttonLabel=${hasCreds ? 'Edit' : 'Set'}
                    testId="edit-home-wifi"
                    onClick=${() => setEditing('home-wifi')} />
                <${ConfigRow} label="AP password" value=${'•'.repeat(8)}
                    buttonLabel="Edit"
                    testId="edit-ap-password"
                    onClick=${() => setEditing('ap-password')} />
            </div>

            ${editing === 'home-wifi' && html`
                <${HomeWiFiModal} wifi=${wifi} showToast=${showToast}
                    onClose=${() => setEditing(null)}
                    onSaved=${() => { setEditing(null); refresh(); }} />
            `}
            ${editing === 'ap-password' && html`
                <${APPasswordModal} showToast=${showToast}
                    onClose=${() => setEditing(null)}
                    onSaved=${() => { setEditing(null); refresh(); }} />
            `}
        </div>
    `;
}

function ConfigRow({ label, value, buttonLabel, testId, onClick }) {
    return html`
        <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 0">
            <div style="font-size:13px">
                <span style="color:var(--text-dim)">${label}:</span>
                <span style="margin-left:8px">${value}</span>
            </div>
            <button class="btn btn-secondary" data-testid=${testId}
                style="padding:4px 12px;font-size:12px"
                onclick=${onClick}>${buttonLabel}</button>
        </div>
    `;
}

function HomeWiFiModal({ wifi, showToast, onClose, onSaved }) {
    const [ssid, setSsid] = useState(wifi.saved_client_ssid || '');
    const [password, setPassword] = useState('');
    const [networks, setNetworks] = useState([]);
    const [scanning, setScanning] = useState(false);
    const [busy, setBusy] = useState(false);
    // Two input modes: pick from the live scan (dropdown), or type the
    // SSID manually (text input). Pick is the default; manual is the
    // escape hatch for hidden / out-of-range networks. We open in
    // manual mode if there's a saved SSID that the current scan doesn't
    // see — so the user always sees their saved value, never a blank.
    const [manualEntry, setManualEntry] = useState(false);

    const scan = async () => {
        setScanning(true);
        const nets = await api('/wifi/scan');
        setNetworks(nets || []);
        setScanning(false);
        // After scan finishes: if the saved SSID isn't visible, open in
        // manual mode so the user sees the SSID they have rather than
        // an empty dropdown.
        if (wifi.saved_client_ssid &&
            !nets.some(n => n.ssid === wifi.saved_client_ssid)) {
            setManualEntry(true);
        }
    };
    useEffect(() => { scan(); }, []);

    const save = async () => {
        if (!ssid) return;
        setBusy(true);
        const res = await api('/wifi/credentials', {
            method: 'POST', body: JSON.stringify({ ssid, password }),
        });
        setBusy(false);
        if (res.error) {
            showToast('Save failed: ' + res.error);
            return;
        }
        showToast('Home WiFi saved: ' + ssid);
        onSaved();
    };

    const forget = async () => {
        if (!confirm(`Forget home WiFi "${wifi.saved_client_ssid}"?`)) return;
        setBusy(true);
        const res = await api('/wifi/credentials', {
            method: 'POST', body: JSON.stringify({ action: 'forget' }),
        });
        setBusy(false);
        if (res.error) {
            showToast('Forget failed: ' + res.error);
            return;
        }
        showToast('Home WiFi forgotten');
        onSaved();
    };

    // Handle dropdown selection: the magic value '__manual__' switches
    // to manual entry; anything else is a scan result.
    const onPick = (e) => {
        const v = e.target.value;
        if (v === '__manual__') {
            setManualEntry(true);
            // Don't clobber a typed SSID if the user already had one;
            // they may have switched to manual specifically to keep it.
        } else {
            setSsid(v);
        }
    };

    return html`
        <div onclick=${onClose} style="position:fixed;inset:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:1000;padding:20px">
            <div onclick=${e => e.stopPropagation()} style="background:var(--surface);border-radius:8px;padding:20px;max-width:400px;width:100%;max-height:90vh;overflow-y:auto">
                <h3>Home WiFi</h3>
                <div class="form-group">
                    <label>Network</label>
                    ${manualEntry ? html`
                        <input type="text" data-testid="home-wifi-ssid"
                            value=${ssid} autoFocus
                            onInput=${e => setSsid(e.target.value)}
                            placeholder="SSID" />
                        <button data-testid="home-wifi-back-to-scan"
                            style="background:none;border:none;color:var(--accent);font-size:12px;cursor:pointer;padding:4px 0;margin-top:4px"
                            onclick=${() => setManualEntry(false)}>
                            ← Pick from scan
                        </button>
                    ` : html`
                        <div style="display:flex;gap:8px">
                            <select style="flex:1" data-testid="home-wifi-pick"
                                value=${ssid}
                                onChange=${onPick}>
                                <option value="">${scanning ? 'Scanning...' : 'Pick a network...'}</option>
                                ${networks.map(n => html`<option value=${n.ssid}>${n.ssid} (${n.signal}%${n.security ? ' ' + n.security : ''})</option>`)}
                                <option disabled>──────────</option>
                                <option value="__manual__">Type SSID manually...</option>
                            </select>
                            <button class="btn btn-secondary" style="min-width:48px;padding:8px"
                                onclick=${scan} disabled=${scanning}>${scanning ? '...' : '↻'}</button>
                        </div>
                    `}
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" data-testid="home-wifi-password"
                        value=${password}
                        onInput=${e => setPassword(e.target.value)}
                        placeholder=${wifi.saved_client_ssid ? 'Leave empty to keep current password' : ''} />
                </div>
                <div style="display:flex;justify-content:space-between;gap:8px;margin-top:12px">
                    ${wifi.saved_client_ssid && html`
                        <button class="btn btn-danger" data-testid="home-wifi-forget"
                            onclick=${forget} disabled=${busy}>Forget</button>
                    `}
                    <div style="flex:1"></div>
                    <button class="btn btn-secondary" onclick=${onClose} disabled=${busy}>Cancel</button>
                    <button class="btn btn-primary" data-testid="home-wifi-save"
                        onclick=${save} disabled=${busy || !ssid}>
                        ${busy ? 'Saving...' : 'Save'}
                    </button>
                </div>
            </div>
        </div>
    `;
}

function APPasswordModal({ showToast, onClose, onSaved }) {
    const [password, setPassword] = useState('');
    const [busy, setBusy] = useState(false);

    const save = async () => {
        if (password.length < 8) {
            showToast('Password must be at least 8 characters');
            return;
        }
        setBusy(true);
        const res = await api('/wifi/ap-password', {
            method: 'POST', body: JSON.stringify({ password }),
        });
        setBusy(false);
        if (res.error) {
            showToast('Save failed: ' + res.error);
            return;
        }
        showToast('AP password saved');
        onSaved();
    };

    return html`
        <div onclick=${onClose} style="position:fixed;inset:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:1000;padding:20px">
            <div onclick=${e => e.stopPropagation()} style="background:var(--surface);border-radius:8px;padding:20px;max-width:400px;width:100%;max-height:90vh;overflow-y:auto">
                <h3>Change AP password</h3>
                <div class="form-group">
                    <label>New password (≥ 8 chars)</label>
                    <input type="password" data-testid="ap-password-input"
                        value=${password} autoFocus
                        onInput=${e => setPassword(e.target.value)} />
                </div>
                <p style="font-size:11px;color:var(--text-dim);margin-bottom:12px">
                    Phones already connected stay connected; new ones need the new password.
                </p>
                <div style="display:flex;justify-content:flex-end;gap:8px">
                    <button class="btn btn-secondary" onclick=${onClose} disabled=${busy}>Cancel</button>
                    <button class="btn btn-primary" data-testid="ap-password-save"
                        onclick=${save} disabled=${busy || password.length < 8}>
                        ${busy ? 'Saving...' : 'Save'}
                    </button>
                </div>
            </div>
        </div>
    `;
}

// USB tethering: when the user plugs their phone into a USB-A port and
// enables USB tethering / Personal Hotspot via USB, the kernel exposes
// a usb0 / enxXX interface and the phone's DHCP gives the Pi an IP.
// The Pi's web server already binds 0.0.0.0 so the phone's browser can
// reach the UI at that IP — but only if the user knows the IP. This
// card surfaces it as a clickable link, polled at the same cadence as
// the rest of the Settings page.
function UsbTetherCard() {
    const [state, setState] = useState({ active: false, interface: null, ip: null });
    useEffect(() => {
        let cancelled = false;
        const tick = () => {
            api('/network/usb-tether').then(s => {
                if (!cancelled) setState(s);
            }).catch(() => {});
        };
        tick();
        const id = setInterval(tick, 2000);
        return () => { cancelled = true; clearInterval(id); };
    }, []);

    return html`
        <div class="card">
            <h3>USB Tethering</h3>
            ${state.active ? html`
                <p>Phone connected. Open <a href="http://${state.ip}/" style="color:var(--accent);text-decoration:underline">http://${state.ip}/</a> on your phone for a faster connection.</p>
                <p style="font-size:11px;color:var(--text-dim);margin-top:4px">Interface: ${state.interface}</p>
            ` : html`
                <p style="color:var(--text-dim)">Connect your phone via USB and enable USB tethering / Personal Hotspot for a faster connection. The Pi will appear at the address your phone assigns it.</p>
            `}
        </div>
    `;
}


// --- Sub-pages -------------------------------------------------------
//
// Each sub-page is a self-contained component; the hub picks one based
// on the URL section. The sub-pages reuse the existing card components
// (WiFiCard, VersionsCard, etc.) — only the grouping into pages is new.

// System Info sub-page — system stats, Reload, Reboot.
function SettingsSysInfo({ showToast, isUpgrading }) {
    const [sys, setSys] = useState(null);
    useEffect(() => {
        let cancelled = false;
        const tick = () => {
            api('/system').then(s => { if (!cancelled) setSys(s); }).catch(() => {});
        };
        tick();
        const id = setInterval(tick, 2000);
        return () => { cancelled = true; clearInterval(id); };
    }, []);

    const rebootPi = async () => {
        if (confirm('Reboot the Raspberry Pi?')) {
            showToast('Rebooting...');
            fetch('/api/system/reboot', { method: 'POST' }).catch(() => {});
        }
    };

    const uptimeStr = sys && sys.uptime_seconds != null
        ? `${Math.floor(sys.uptime_seconds/3600)}h ${Math.floor((sys.uptime_seconds%3600)/60)}m`
        : '?';

    return html`
        ${sys && html`
            <div class="card">
                <h3>System</h3>
                <div class="stat-grid">
                    <div class="stat"><div class="label">Hostname</div><div class="value">${sys.hostname}</div></div>
                    <div class="stat"><div class="label">Version</div><div class="value">${sys.version}</div></div>
                    <div class="stat"><div class="label">CPU Temp</div><div class="value">${sys.cpu_temp_c != null ? sys.cpu_temp_c + '°C' : '?'}</div></div>
                    <div class="stat"><div class="label">Uptime</div><div class="value">${uptimeStr}</div></div>
                    ${sys.load1 != null && html`<div class="stat"><div class="label">Load (1m)</div><div class="value">${sys.load1}</div></div>`}
                    ${sys.cpu_percent != null && html`<div class="stat" title="Process CPU as percent-of-one-core. 100% = the asyncio loop has saturated one core (the failure mode that causes lag); >100% means plugin worker threads are summing in. Updated every second.">
                        <div class="label">CPU</div>
                        <div class="value">${sys.cpu_percent}%</div>
                    </div>`}
                    <div class="stat"><div class="label">RAM</div><div class="value">${sys.ram.available_mb || '?'} / ${sys.ram.total_mb || '?'} MB</div></div>
                    ${sys.sse_per_sec != null && html`<div class="stat" title="Broadcast events/sec the server pushes to every connected browser.">
                        <div class="label">SSE / sec</div>
                        <div class="value">${sys.sse_per_sec}${sys.sse_clients ? html` <span style="color:var(--text-dim);font-size:11px">× ${sys.sse_clients} ${sys.sse_clients === 1 ? 'client' : 'clients'}</span>` : ''}</div>
                    </div>`}
                    ${sys.sse_queue_depths && sys.sse_queue_depths.length > 0 && html`<div class="stat" title="Per-client SSE outbox depths (max 100).">
                        <div class="label">SSE backlog</div>
                        <div class="value">${sys.sse_queue_depths.join(' / ')}</div>
                    </div>`}
                    ${sys.latency_max && html`
                        <div class="stat" title="asyncio scheduling lag.">
                            <div class="label">Loop lag</div>
                            <div class="value">${sys.latency_max.loop_lag != null ? sys.latency_max.loop_lag + ' ms' : '—'}</div>
                        </div>
                        <div class="stat" title="MIDI in to SSE out latency.">
                            <div class="label">MIDI in → SSE out</div>
                            <div class="value">${sys.latency_max.midi_in_sse_out != null ? sys.latency_max.midi_in_sse_out + ' ms' : '—'}</div>
                        </div>
                        <div class="stat" title="Userspace filter/mapping latency.">
                            <div class="label">MIDI in → MIDI out</div>
                            <div class="value">${sys.latency_max.midi_in_midi_out != null ? sys.latency_max.midi_in_midi_out + ' ms' : '—'}</div>
                        </div>
                        <div class="stat" title="Plugin PATCH to send_cc latency.">
                            <div class="label">Control in → MIDI out</div>
                            <div class="value">${sys.latency_max.control_in_midi_out != null ? sys.latency_max.control_in_midi_out + ' ms' : '—'}</div>
                        </div>
                    `}
                    ${(sys.ip_addresses || []).map(ip => html`
                        <div class="stat"><div class="label">${ip.interface}</div><div class="value">${ip.address}</div></div>
                    `)}
                </div>
            </div>
        `}
        <div class="card">
            <button class="btn btn-secondary btn-block" style="margin-bottom:8px" onclick=${hardReload} disabled=${isUpgrading}>Reload App</button>
            <button class="btn btn-danger btn-block" onclick=${rebootPi} disabled=${isUpgrading}>${isUpgrading ? 'Upgrade in progress...' : 'Reboot Pi'}</button>
        </div>
    `;
}

function SettingsNetwork({ showToast }) {
    const [ifaces, setIfaces] = useState([]);
    useEffect(() => { api('/network').then(setIfaces).catch(() => {}); }, []);
    return html`
        <${WiFiCard} showToast=${showToast} />
        <${UsbTetherCard} />
        ${ifaces.filter(i => i.interface !== 'wlan0' && !/^(usb\d+|enx[0-9a-f]{12})$/.test(i.interface)).map(i => html`
            <${NetworkCard} iface=${i} showToast=${showToast} />
        `)}
    `;
}

function SettingsMidi({ showToast }) {
    const [defaultRouting, setDefaultRouting] = useState('all');
    useEffect(() => {
        api('/system').then(s => setDefaultRouting(s.default_routing || 'all')).catch(() => {});
    }, []);
    const changeDefaultRouting = async (val) => {
        setDefaultRouting(val);
        await api('/system', { method: 'PATCH', body: JSON.stringify({ default_routing: val }) });
        showToast('Default routing: ' + (val === 'all' ? 'all-to-all' : 'none'));
    };
    return html`
        <div class="card">
            <h3>MIDI Routing</h3>
            <div class="form-group">
                <label>New devices</label>
                <select value=${defaultRouting} onChange=${e => changeDefaultRouting(e.target.value)}>
                    <option value="all">Connect all (default)</option>
                    <option value="none">Disconnected (manual)</option>
                </select>
            </div>
            <p style="font-size:11px;color:var(--text-dim)">When a new device is plugged in, should it be connected to all other devices automatically?</p>
        </div>
    `;
}

function SettingsDisplay({ showMidiBar, toggleMidiBar }) {
    const [soundsOn, setSoundsOn] = useState(getSoundsEnabled());
    const [density, setDensity] = useState(getLayoutDensity());
    const [scrollAssistOn, setScrollAssistOn] = useState(getScrollAssist());
    const [theme, setThemeState] = useState(getTheme());
    const [themes, setThemes] = useState(null);
    useEffect(() => {
        listThemes().then(m => setThemes(m.themes || []));
    }, []);
    return html`
        <div class="card">
            <h3>Display <span style="color:var(--text-dim);font-size:11px;font-weight:400;margin-left:6px">(this device only)</span></h3>
            <label class="msg-toggle">
                <input type="checkbox" checked=${showMidiBar} onchange=${toggleMidiBar} />
                <span>MIDI activity bar</span>
            </label>
            <label class="msg-toggle">
                <input type="checkbox" checked=${soundsOn}
                    onchange=${e => { setSoundsEnabled(e.target.checked); setSoundsOn(e.target.checked); }} />
                <span>Knob / wheel tick sounds</span>
            </label>
            <label class="msg-toggle">
                <input type="checkbox" data-testid="scroll-assist-toggle"
                    checked=${scrollAssistOn}
                    onchange=${e => { setScrollAssist(e.target.checked); setScrollAssistOn(e.target.checked); }} />
                <span>Scroll-assist buttons</span>
            </label>
            <div class="form-group" style="margin-top:10px;margin-bottom:0">
                <label>Layout density</label>
                <select data-testid="layout-density"
                    value=${density}
                    onChange=${e => { setLayoutDensity(e.target.value); setDensity(e.target.value); }}>
                    ${DENSITY_OPTIONS.map(o => html`<option value=${o.value}>${o.label}</option>`)}
                </select>
            </div>
            ${themes && themes.length > 1 ? html`
                <div class="form-group" style="margin-top:10px;margin-bottom:0">
                    <label>Theme</label>
                    <select data-testid="theme-select"
                        value=${theme}
                        onChange=${e => { setTheme(e.target.value); setThemeState(e.target.value); }}>
                        ${themes.map(t => html`<option value=${t.id}>${t.name}</option>`)}
                    </select>
                </div>
            ` : null}
        </div>
    `;
}

function SettingsUpdate({ showToast, onUpgradingChange }) {
    return html`<${VersionsCard} showToast=${showToast} onUpdatingChange=${onUpgradingChange} />`;
}

// Plugin Control Mappings — flat editable table of every per-instance
// CC binding. Row click opens the same CcBinding popup as long-press.
// Live cc_map_changed SSE refreshes the table while the user edits.
function SettingsCcBindings({ openCcBinding, openCellBinding }) {
    const [rows, setRows] = useState(null);
    const reload = async () => {
        try {
            const r = await api('/plugins/cc-mappings');
            setRows(r.mappings || []);
        } catch { setRows([]); }
    };
    useEffect(() => {
        reload();
        const es = new EventSource('/api/events');
        const onConn = (e) => {
            try {
                const { conn_id } = JSON.parse(e.data);
                if (!conn_id) return;
                fetch('/api/sse/subscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ conn_id, events: ['cc_map_changed', 'plugin-changed'], instances: [] }),
                }).catch(() => {});
            } catch {}
        };
        const onChange = () => reload();
        es.addEventListener('connection', onConn);
        es.addEventListener('cc_map_changed', onChange);
        es.addEventListener('plugin-changed', onChange);
        return () => es.close();
    }, []);

    if (rows === null) {
        return html`<div class="card"><p style="color:var(--text-dim)">Loading...</p></div>`;
    }
    if (rows.length === 0) {
        return html`<div class="card">
            <h3>Plugin Control Mappings</h3>
            <p style="color:var(--text-dim);font-size:13px">No plugin instances yet. Add one from the Routing tab to start binding controls to MIDI CC.</p>
        </div>`;
    }
    const fmtCh = (ch) => ch === null || ch === undefined ? 'Any' : String(ch + 1);
    const fmtCc = (cc) => cc === null || cc === undefined ? '—' : String(cc);
    return html`
        <div class="card">
            <h3>Plugin Control Mappings</h3>
            <p style="font-size:11px;color:var(--text-dim);margin-bottom:10px">
                Every CC binding across all plugins. Tap a row to edit, MIDI-Learn, or clear.
                Same popup as long-press on the control itself.
            </p>
            <table class="cc-map-table">
                <thead><tr>
                    <th>Plugin</th><th>Param</th><th>Ch</th><th>CC</th>
                </tr></thead>
                <tbody>
                    ${rows.map(r => {
                        // Cell rows open the CellBinding popup; param
                        // rows open CcBinding. The popup itself shows
                        // both axes for XY pads even if the table row
                        // is just the X (or Y) axis — clicking either
                        // axis row is equivalent.
                        const onClick = r.kind === 'cell'
                            ? () => openCellBinding && openCellBinding(r.instance_id, r.param)
                            : () => openCcBinding && openCcBinding(r.instance_id, r.param);
                        return html`
                            <tr key=${`${r.instance_id}/${r.param}/${r.axis || ''}`}
                                class=${(r.cc === null || r.cc === undefined) ? 'cleared' : ''}
                                onclick=${onClick}>
                                <td>${r.instance_name}</td>
                                <td>${r.param_label}</td>
                                <td>${fmtCh(r.ch)}</td>
                                <td>${fmtCc(r.cc)}</td>
                            </tr>`;
                    })}
                </tbody>
            </table>
        </div>
    `;
}

// --- Hub + dispatcher -----------------------------------------------

const SECTIONS = [
    { key: 'sys-info',    title: 'Sys Info',                hint: 'Hostname, CPU, RAM, latency, Reload, Reboot' },
    { key: 'network',     title: 'Network',                 hint: 'WiFi mode, AP password, USB tether, Ethernet' },
    { key: 'midi',        title: 'MIDI',                    hint: 'Default routing for new devices' },
    { key: 'display',     title: 'Display',                 hint: 'MIDI activity bar, sounds, scroll-assist, density' },
    { key: 'update',      title: 'Update',                  hint: 'Check GitHub, manage stored versions' },
    { key: 'cc-bindings', title: 'Plugin Control Mappings', hint: 'CC bindings across every plugin instance' },
];

export function SettingsPage({ showToast, showMidiBar, toggleMidiBar,
                                section, onNavigate, openCcBinding, openCellBinding }) {
    const [isUpgrading, setIsUpgrading] = useState(false);

    if (section) {
        const meta = SECTIONS.find(s => s.key === section);
        const title = meta ? meta.title : section;
        let body;
        switch (section) {
            case 'sys-info':    body = html`<${SettingsSysInfo} showToast=${showToast} isUpgrading=${isUpgrading} />`; break;
            case 'network':     body = html`<${SettingsNetwork} showToast=${showToast} />`; break;
            case 'midi':        body = html`<${SettingsMidi} showToast=${showToast} />`; break;
            case 'display':     body = html`<${SettingsDisplay} showMidiBar=${showMidiBar} toggleMidiBar=${toggleMidiBar} />`; break;
            case 'update':      body = html`<${SettingsUpdate} showToast=${showToast} onUpgradingChange=${setIsUpgrading} />`; break;
            case 'cc-bindings': body = html`<${SettingsCcBindings} openCcBinding=${openCcBinding} openCellBinding=${openCellBinding} />`; break;
            default:            body = html`<div class="card"><p>Unknown section</p></div>`;
        }
        return html`
            <div class="settings-subnav">
                <button class="settings-back" onclick=${() => onNavigate(null)}
                    aria-label="Back to Settings">‹ Settings</button>
                <span class="settings-subnav-title">${title}</span>
            </div>
            ${body}
        `;
    }

    return html`
        <div class="settings-hub">
            ${SECTIONS.map(s => html`
                <button class="settings-hub-item" key=${s.key}
                    data-testid=${'settings-hub-' + s.key}
                    onclick=${() => onNavigate(s.key)}>
                    <span class="settings-hub-title">${s.title}</span>
                    <span class="settings-hub-hint">${s.hint}</span>
                    <span class="settings-hub-chev">›</span>
                </button>
            `)}
        </div>
    `;
}
