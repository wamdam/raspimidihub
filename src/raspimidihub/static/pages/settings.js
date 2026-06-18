/**
 * Settings page: hub + sub-pages.
 *
 * The hub is a card list of sub-page links (Sys Info, Network, MIDI,
 * Display, Update, Plugin Control Mappings). Each sub-page renders
 * with a `< Settings / <title>` back-bar; the active sub-page lives
 * in the URL (`/settings/<section>`) and per-tab sub-state restores
 * it when bouncing through other bottom-nav tabs.
 */

import { useState, useEffect, useCallback } from '../lib/hooks.module.js';
import { html, api, hardReload } from '../ui/common.js';
import { UPDATE_LABELS } from '../state/constants.js';
import { getSoundsEnabled, setSoundsEnabled,
         getLayoutDensity, setLayoutDensity, DENSITY_OPTIONS,
         getScrollAssist, setScrollAssist } from '../components/common.js';
import { getTheme, setTheme, listThemes } from '../lib/theme.js';
import { getSSEConnectionId, getSpectatorLabel, setSpectatorLabel } from '../ui/sse-subscriptions.js';

function NetworkCard({ iface, showToast, reload }) {
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
        if (res.error) { showToast(res.error); return; }
        showToast(`${iface.interface} configured`);
        // NetworkManager takes a moment to apply the new address; re-fetch
        // so the address list above the form reflects what eth0 actually
        // carries now, not the pre-apply snapshot (which often showed only
        // the link-local fallback).
        if (reload) { reload(); setTimeout(reload, 1800); }
    };

    return html`
        <div class="card">
            <h3>${iface.interface} ${iface.up ? html`<span style="color:var(--success);font-size:12px">\u25cf</span>` : html`<span style="color:var(--text-dim);font-size:12px">\u25cb</span>`}</h3>
            ${(iface.addresses?.length || iface.address) && html`<div style="font-size:13px;color:var(--text-dim);margin-bottom:8px">
                ${(iface.addresses?.length ? iface.addresses : [`${iface.address}/${iface.netmask}`]).map(a => html`
                    <div>${a}${a.startsWith('169.254.') ? html` <span style="opacity:.7">(link-local)</span>` : ''}</div>`)}
                ${iface.gateway ? html`<div>gw ${iface.gateway}</div>` : ''}
            </div>`}
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
                <${ConfigRow} label="AP radio"
                    value=${html`${wifi.ap_band === '5' ? '5 GHz' : '2.4 GHz'} · ${
                        wifi.ap_country
                            ? wifi.ap_country
                            : html`<span style="color:var(--text-dim)">${wifi.resolved_country || '—'} (auto)</span>`}`}
                    buttonLabel="Edit"
                    testId="edit-ap-radio"
                    onClick=${() => setEditing('ap-radio')} />
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
            ${editing === 'ap-radio' && html`
                <${APRadioModal} wifi=${wifi} showToast=${showToast}
                    onClose=${() => setEditing(null)}
                    onSaved=${() => { setEditing(null); setTimeout(refresh, 1500); setTimeout(refresh, 4000); }} />
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

// Curated regulatory-country list for the AP-radio dropdown. Empty
// value = auto-detect from the kernel regdomain. Kept short and common
// rather than the full ISO 3166 set; any saved code not in the list is
// appended so it never silently disappears.
const AP_COUNTRIES = [
    ['DE', 'Germany'], ['AT', 'Austria'], ['CH', 'Switzerland'],
    ['FR', 'France'], ['IT', 'Italy'], ['ES', 'Spain'], ['PT', 'Portugal'],
    ['NL', 'Netherlands'], ['BE', 'Belgium'], ['LU', 'Luxembourg'],
    ['GB', 'United Kingdom'], ['IE', 'Ireland'], ['DK', 'Denmark'],
    ['SE', 'Sweden'], ['NO', 'Norway'], ['FI', 'Finland'], ['PL', 'Poland'],
    ['CZ', 'Czechia'], ['SK', 'Slovakia'], ['HU', 'Hungary'],
    ['US', 'United States'], ['CA', 'Canada'], ['AU', 'Australia'],
    ['NZ', 'New Zealand'], ['JP', 'Japan'],
];

function APRadioModal({ wifi, showToast, onClose, onSaved }) {
    const [band, setBand] = useState(wifi.ap_band === '5' ? '5' : '2.4');
    const [country, setCountry] = useState(wifi.ap_country || '');
    const [busy, setBusy] = useState(false);
    const supports5 = !!wifi.band_5ghz_supported;

    // Surface a saved code that isn't in the curated list.
    const extras = (country && !AP_COUNTRIES.some(([c]) => c === country))
        ? [[country, country]] : [];

    const save = async () => {
        setBusy(true);
        const res = await api('/wifi/ap-radio', {
            method: 'POST', body: JSON.stringify({ band, country }),
        });
        setBusy(false);
        if (res.error) {
            showToast('Save failed: ' + res.error);
            return;
        }
        showToast(res.switched ? 'Applying radio change — the AP restarts briefly...' : 'AP radio saved');
        onSaved();
    };

    // Band option rendered as a compact selectable row (NOT inside a
    // .form-group — that stretches the radio input to full width).
    const BandRow = ({ value, title, desc, disabled }) => html`
        <label style="display:flex;align-items:flex-start;gap:10px;padding:10px;margin-bottom:6px;
                      border:1px solid ${band === value ? 'var(--accent)' : 'var(--surface-2)'};
                      border-radius:6px;cursor:${disabled ? 'not-allowed' : 'pointer'};
                      opacity:${disabled ? 0.5 : 1};background:var(--bg)">
            <input type="radio" name="ap-band"
                style="width:16px;height:16px;min-height:0;flex:none;margin-top:2px;accent-color:var(--accent)"
                checked=${band === value} disabled=${busy || disabled}
                onChange=${() => setBand(value)} />
            <span style="flex:1;min-width:0">
                <div style="font-size:13px;font-weight:600">${title}</div>
                <div style="font-size:11px;color:var(--text-dim);line-height:1.4">${desc}</div>
            </span>
        </label>`;

    return html`
        <div onclick=${onClose} style="position:fixed;inset:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:1000;padding:20px">
            <div onclick=${e => e.stopPropagation()} style="background:var(--surface);border-radius:8px;padding:20px;max-width:420px;width:100%;max-height:90vh;overflow-y:auto">
                <h3 style="margin-top:0">AP radio</h3>
                <div style="margin-bottom:14px">
                    <div style="font-size:12px;color:var(--text-dim);margin-bottom:6px">Band</div>
                    <${BandRow} value="2.4" title="2.4 GHz"
                        desc="Works on every Pi. Longest range. Shares the band with Bluetooth." />
                    <div data-testid="ap-band-5">
                        <${BandRow} value="5"
                            title=${supports5 ? '5 GHz' : '5 GHz — not supported on this Pi'}
                            desc="Frees the 2.4 GHz band for Bluetooth — best when BLE-MIDI is flaky. Shorter range; needs a 5 GHz-capable phone."
                            disabled=${!supports5} />
                    </div>
                </div>
                <div class="form-group">
                    <label>Country (regulatory)</label>
                    <select data-testid="ap-country-select" disabled=${busy}
                        value=${country} onChange=${e => setCountry(e.target.value)}>
                        <option value="">Auto-detect (${wifi.resolved_country || 'DE'})</option>
                        ${[...AP_COUNTRIES, ...extras].map(([code, name]) => html`
                            <option value=${code}>${name} (${code})</option>`)}
                    </select>
                    <p style="font-size:11px;color:var(--text-dim);margin-top:4px">
                        Required for 5 GHz and must match where the Pi is used.
                    </p>
                </div>
                <p style="font-size:11px;color:var(--warn);margin-bottom:12px">
                    Saving restarts the access point — phones on the AP drop for a few seconds and reconnect. If 5 GHz fails to come up, the Pi falls back to 2.4 GHz automatically.
                </p>
                <div style="display:flex;justify-content:flex-end;gap:8px">
                    <button class="btn btn-secondary" onclick=${onClose} disabled=${busy}>Cancel</button>
                    <button class="btn btn-primary" data-testid="ap-radio-save"
                        onclick=${save} disabled=${busy}>
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

    const factoryReset = async () => {
        if (!confirm('Factory reset: erase ALL routing, plugins, filters and '
            + 'settings, then reboot.\n\nWiFi / access-point settings and your '
            + 'saved backups are kept (restore one from Settings → Backup).\n\n'
            + 'Continue?')) return;
        if (!confirm('Really reset to factory defaults? This cannot be undone '
            + 'except by restoring a backup.')) return;
        showToast('Factory reset — resetting and rebooting...');
        fetch('/api/system/factory-reset', { method: 'POST' }).catch(() => {});
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
                    ${sys.alsa_ports && html`<div class="stat" title="ALSA sequencer ports held by the hub's client. Every filtered or mapped connection uses two; the kernel caps a client at ${sys.alsa_ports.max}. At the ceiling, new filters can no longer be created.">
                        <div class="label">ALSA ports</div>
                        <div class="value" style=${sys.alsa_ports.used >= sys.alsa_ports.max * 0.8 ? 'color:var(--danger,#e94560)' : ''}>${sys.alsa_ports.used} / ${sys.alsa_ports.max}</div>
                    </div>`}
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
                        ${sys.latency_max.net_midi_rx != null && html`
                            <div class="stat" title="RTP-MIDI packet in to ALSA inject — the hub's share of network MIDI latency (wire time not included).">
                                <div class="label">Net MIDI in → MIDI out</div>
                                <div class="value">${sys.latency_max.net_midi_rx + ' ms'}</div>
                            </div>
                        `}
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
            <button class="btn btn-danger btn-block" style="margin-bottom:8px" onclick=${rebootPi} disabled=${isUpgrading}>${isUpgrading ? 'Upgrade in progress...' : 'Reboot Pi'}</button>
            <button class="btn btn-danger btn-block" onclick=${factoryReset} disabled=${isUpgrading}>Factory Reset</button>
            <p style="font-size:11px;color:var(--text-dim);margin:8px 2px 0">
                Factory Reset erases routing, plugins and settings and reboots.
                WiFi/AP settings and your backups are kept.
            </p>
        </div>
    `;
}

function SettingsNetwork({ showToast }) {
    const [ifaces, setIfaces] = useState([]);
    const reload = useCallback(() => { api('/network').then(setIfaces).catch(() => {}); }, []);
    useEffect(() => { reload(); }, [reload]);
    return html`
        <${WiFiCard} showToast=${showToast} />
        <${UsbTetherCard} />
        ${ifaces.filter(i => i.interface !== 'wlan0' && !/^(usb\d+|enx[0-9a-f]{12})$/.test(i.interface)).map(i => html`
            <${NetworkCard} iface=${i} showToast=${showToast} reload=${reload} />
        `)}
    `;
}

function SettingsMidi({ showToast }) {
    const [defaultRouting, setDefaultRouting] = useState('none');
    useEffect(() => {
        api('/system').then(s => setDefaultRouting(s.default_routing || 'none')).catch(() => {});
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
                    <option value="none">Disconnected (default)</option>
                    <option value="all">Connect all</option>
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

// --- Spectator mirroring --------------------------------------------
//
// Picks one source device to mirror into OBS or another tab. The list
// is refreshed every 3 s from /api/spectator/clients. The current
// device's own conn_id is filtered out (you can't usefully mirror
// yourself); the rest become tappable links. The device-name field
// at the top sets this connection's label so other devices see a
// readable name instead of a UUID.
function SettingsBackup({ showToast }) {
    const [backups, setBackups] = useState(null);
    const [autosave, setAutosave] = useState(null);
    const [busy, setBusy] = useState(false);

    const load = () => api('/backups')
        .then(r => { setBackups(r.backups || []); setAutosave(r.autosave || null); })
        .catch(() => { setBackups([]); setAutosave(null); });
    useEffect(() => { load(); }, []);

    // No RTC on the appliance, so we show time relative to uptime, not a
    // (meaningless) date. Backups from before the last reboot can't have
    // an honest relative time — #seq still orders them.
    const fmtAgo = (b) => {
        if (!b.same_session || b.age_seconds == null) return 'before last reboot';
        const s = b.age_seconds;
        if (s < 60) return s + 's ago';
        if (s < 3600) return Math.floor(s / 60) + ' min ago';
        if (s < 86400) return Math.floor(s / 3600) + ' h ago';
        return Math.floor(s / 86400) + ' d ago';
    };
    const fmtSize = (b) => (b >= 1024 ? (b / 1024).toFixed(1) + ' KB' : (b || 0) + ' B');

    const restore = async (seq) => {
        if (!window.confirm(
            'Restore backup #' + seq + '?\n\nThis replaces the live config. ' +
            'Use "Load" to return to your last Save, or Save to keep the restored one.')) {
            return;
        }
        setBusy(true);
        try {
            await api('/backups/' + seq + '/restore', { method: 'POST' });
            showToast('Backup #' + seq + ' restored — Save to keep it');
        } catch (e) {
            showToast('Restore failed');
        } finally {
            setBusy(false);
        }
    };

    if (backups === null) {
        return html`<div class="card"><h3>Backups</h3>
            <p style="color:var(--text-dim)">Loading…</p></div>`;
    }
    // The background autosave (resume snapshot), distinct from the
    // deliberate Save checkpoints below.
    const fmtAutosave = () => {
        if (!autosave) return 'no autosave yet';
        if (!autosave.same_session || autosave.age_seconds == null)
            return 'before last reboot';
        const s = autosave.age_seconds;
        if (s < 60) return s + 's ago';
        if (s < 3600) return Math.floor(s / 60) + ' min ago';
        if (s < 86400) return Math.floor(s / 3600) + ' h ago';
        return Math.floor(s / 86400) + ' d ago';
    };

    return html`
        <div class="card">
            <div style="display:flex;align-items:center;gap:8px">
                <h3 style="flex:1;margin:0">Backups</h3>
                <button class="btn btn-secondary" disabled=${busy}
                    onClick=${load} title="Refresh">↻</button>
            </div>
            <div style="display:flex;align-items:baseline;gap:8px;margin-top:8px;
                        padding:8px 10px;background:var(--bg-elevated,rgba(255,255,255,0.04));
                        border-radius:6px">
                <span style="font-size:12px;color:var(--text-dim);flex:1">
                    Last autosave (live resume snapshot)
                </span>
                <span style="font-size:13px">${fmtAutosave()}</span>
            </div>
            <p style="font-size:11px;color:var(--text-dim)">
                A checkpoint is written automatically on every <strong>Save</strong>
                (newest first, last 50 kept). The summary shows roughly what changed
                since the previous checkpoint. <strong>Restore</strong> replaces the
                live config — Save afterwards to keep it, or use Load to revert.
                Times are relative to uptime (this device has no clock); checkpoints
                from before the last reboot show only their <code>#number</code>.
            </p>
            ${backups.length === 0 ? html`
                <p style="color:var(--text-dim)">No backups yet — they appear after your first Save.</p>
            ` : html`
                <div class="backup-list">
                    ${backups.map(b => html`
                        <div key=${b.seq} style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border)">
                            <div style="flex:1;min-width:0">
                                <div style="font-size:13px">#${b.seq} · ${fmtAgo(b)}</div>
                                <div style="font-size:11px;color:var(--text-dim)">${b.summary || ''} · ${fmtSize(b.bytes)}</div>
                            </div>
                            <button class="btn btn-secondary" disabled=${busy}
                                onClick=${() => restore(b.seq)}>Restore</button>
                            <a class="btn btn-secondary" href=${'/api/backups/' + b.seq + '/download'}
                                download>Download</a>
                        </div>
                    `)}
                </div>
            `}
        </div>
    `;
}

function SettingsSpectator() {
    const [label, setLabelState] = useState(() => getSpectatorLabel());
    const [clients, setClients] = useState([]);
    const [myConnId, setMyConnId] = useState(() => getSSEConnectionId());

    useEffect(() => {
        let cancelled = false;
        const refresh = async () => {
            try {
                const r = await fetch('/api/spectator/clients');
                const d = await r.json();
                if (!cancelled) setClients(d.clients || []);
            } catch {}
            if (!cancelled) setMyConnId(getSSEConnectionId());
        };
        refresh();
        const t = setInterval(refresh, 3000);
        return () => { cancelled = true; clearInterval(t); };
    }, []);

    const onLabelChange = (v) => {
        setLabelState(v);
        setSpectatorLabel(v);
    };

    const myUrl = myConnId
        ? `${window.location.origin}/?spectate=${encodeURIComponent(myConnId)}&touches=1`
        : '';
    const copyMyUrl = async () => {
        if (!myUrl) return;
        try { await navigator.clipboard.writeText(myUrl); } catch {}
    };

    const others = clients.filter(c => c.conn_id !== myConnId);

    return html`
        <div class="card">
            <h3>This device</h3>
            <div class="form-group">
                <label>Name shown to spectators</label>
                <input value=${label} placeholder="e.g. Living-room phone"
                    onInput=${e => onLabelChange(e.target.value)} />
            </div>
            <div class="form-group">
                <label>Spectator URL</label>
                <input value=${myUrl} readonly
                    style="font-family:var(--mono,monospace);font-size:12px" />
            </div>
            <div style="display:flex;gap:8px">
                <button class="btn btn-primary btn-block"
                    onclick=${copyMyUrl} disabled=${!myUrl}>Copy URL</button>
                <a class="btn btn-block" target="_blank" rel="noopener"
                    href=${myUrl || '#'} style=${myUrl ? '' : 'pointer-events:none;opacity:0.4'}>
                    Open mirror →
                </a>
            </div>
            <p style="font-size:12px;color:var(--text-dim);margin-top:10px">
                Drop the URL into OBS Browser Source to stream this
                device's UI. Mirroring stays dormant until someone
                opens it, so it costs nothing when nobody is watching.
            </p>
        </div>
        <div class="card">
            <h3>Spectate another device</h3>
            ${others.length === 0
                ? html`<p style="color:var(--text-dim);font-size:13px">
                    No other devices connected. Open the app on a
                    phone or tablet over WiFi or USB and it will
                    appear here.</p>`
                : html`<ul class="spectator-clients">
                    ${others.map(c => {
                        const url = `/?spectate=${encodeURIComponent(c.conn_id)}&touches=1`;
                        const name = c.label || c.conn_id.slice(0, 8);
                        const age = c.age_sec;
                        const ageStr = age == null ? 'never'
                            : age < 5 ? 'live'
                            : age < 60 ? `${Math.round(age)} s ago`
                            : `${Math.round(age / 60)} min ago`;
                        const vp = c.viewport
                            ? `${c.viewport.w}×${c.viewport.h}` : '—';
                        return html`<li key=${c.conn_id}>
                            <a href=${url} target="_blank" rel="noopener"
                                class="spectator-client-link">
                                <span class="spectator-client-name">${name}</span>
                                <span class="spectator-client-meta">${vp} · ${ageStr}</span>
                            </a>
                        </li>`;
                    })}
                </ul>`}
        </div>
    `;
}

// --- Network MIDI ----------------------------------------------------
//
// Export local devices as RTP-MIDI (AppleMIDI) sessions and (phase 3)
// mirror a peer hub's exports into the matrix. Exports are visible to
// anything that speaks RTP-MIDI: a second RaspiMIDIHub, macOS Audio
// MIDI Setup, iPads, rtpmidid.

function SettingsNetworkMidi({ showToast }) {
    const [nm, setNm] = useState(null);
    const [devices, setDevices] = useState([]);
    const [busy, setBusy] = useState(false);
    const [peerInput, setPeerInput] = useState('');

    const reload = async () => {
        try { setNm(await api('/network-midi')); }
        catch { setNm({ available: false, reason: 'unreachable' }); }
        try {
            const d = await api('/devices');
            setDevices(Array.isArray(d) ? d : []);
        } catch { setDevices([]); }
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
                    body: JSON.stringify({ conn_id, events: [
                        'network-midi-changed', 'device-connected',
                        'device-disconnected'], instances: [] }),
                }).catch(() => {});
            } catch {}
        };
        const onChange = () => reload();
        es.addEventListener('connection', onConn);
        es.addEventListener('network-midi-changed', onChange);
        es.addEventListener('device-connected', onChange);
        es.addEventListener('device-disconnected', onChange);
        return () => es.close();
    }, []);

    if (nm === null) {
        return html`<div class="card"><p style="color:var(--text-dim)">Loading...</p></div>`;
    }
    if (!nm.available) {
        return html`<div class="card">
            <h3>Network MIDI</h3>
            <p style="color:var(--text-dim);font-size:13px">
                Not available on this system${nm.reason === 'no-zeroconf'
                    ? ' — the python3-zeroconf package is missing.'
                    : '.'}
            </p>
        </div>`;
    }

    const setEnabled = async (enabled) => {
        setBusy(true);
        const res = await api('/network-midi/enable', {
            method: 'POST', body: JSON.stringify({ enabled }) });
        setBusy(false);
        if (res.error) showToast(res.error);
        else reload();
    };

    const setExport = async (stableId, exported) => {
        const res = await api('/network-midi/export', {
            method: 'POST',
            body: JSON.stringify({ stable_id: stableId, exported }) });
        if (res.error) showToast(res.error);
        else reload();
    };

    const setMirrored = async (service, mirrored) => {
        const res = await api(`/network-midi/${mirrored ? 'mirror' : 'unmirror'}`, {
            method: 'POST', body: JSON.stringify({ service }) });
        if (res.error) showToast(res.error);
        else reload();
    };

    const stateDot = (s) => s.state === 'connected'
        ? html`<span style="color:var(--success);font-size:11px">●</span>`
        : s.state === 'connecting'
            ? html`<span style="color:var(--warn-soft);font-size:11px">●</span>`
            : html`<span style="color:var(--text-dim);font-size:11px">○</span>`;

    const sessionRow = (s) => html`
        <div key=${s.service} style="display:flex;align-items:center;gap:8px;padding:6px 0">
            ${stateDot(s)}
            <div style="flex:1;min-width:0">
                <div style="font-size:13px">${s.name}</div>
                <div style="font-size:11px;color:var(--text-dim)">
                    ${s.mirrored ? s.state : 'not mirrored'}${s.latency_ms != null ? ` · ${s.latency_ms.toFixed(1)} ms` : ''}${s.addr ? ` · ${s.addr}:${s.port}` : ''}
                </div>
            </div>
            <button class="btn btn-secondary" style="font-size:12px;padding:4px 10px"
                onclick=${() => setMirrored(s.service, !s.mirrored)}>
                ${s.mirrored ? 'Unmirror' : 'Mirror'}
            </button>
        </div>`;

    // Sessions by stable_id for the "advertised as" sub-line.
    const sessions = {};
    (nm.exports || []).forEach(s => { sessions[s.stable_id] = s; });
    const exportable = devices.filter(d =>
        d.online && d.stable_id && !d.is_network);

    return html`
        <div class="card">
            <h3>Network MIDI</h3>
            <label class="msg-toggle">
                <input type="checkbox" data-testid="network-midi-enable"
                    checked=${nm.enabled} disabled=${busy}
                    onchange=${e => setEnabled(e.target.checked)} />
                <span>Share devices over the network</span>
            </label>
            <p style="font-size:11px;color:var(--text-dim);margin-top:6px">
                Exported devices appear to other hubs (and Macs, iPads,
                anything speaking RTP-MIDI) as "Name @${nm.hostname}".
                Direct cable between two hubs? No router needed.
            </p>
        </div>
        ${nm.enabled && html`<div class="card">
            <h3>Exported devices</h3>
            ${exportable.length === 0 && html`
                <p style="color:var(--text-dim);font-size:13px">No local devices online.</p>`}
            ${exportable.map(d => {
                const sess = sessions[d.stable_id];
                return html`
                    <label key=${d.stable_id} class="msg-toggle" style="margin-bottom:6px">
                        <input type="checkbox"
                            checked=${!!d.exported}
                            onchange=${e => setExport(d.stable_id, e.target.checked)} />
                        <div style="flex:1;min-width:0">
                            <div>${d.name}</div>
                            ${sess && html`
                                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">
                                    advertised as "${sess.name}"${sess.participants.length
                                        ? ` · ${sess.participants.length} connected` : ''}
                                </div>`}
                        </div>
                    </label>`;
            })}
        </div>`}
        ${nm.enabled && html`<div class="card">
            <h3>Remote hubs</h3>
            ${(nm.hubs || []).length === 0 && html`
                <p style="color:var(--text-dim);font-size:13px">
                    No hubs discovered. Connect a second RaspiMIDIHub to the
                    same network (a direct Ethernet cable works) and export
                    devices on it — they appear here and in the matrix
                    automatically.
                </p>`}
            ${(nm.hubs || []).map(hub => html`
                <div key=${hub.hub} style="margin-bottom:10px">
                    <div style="font-size:12px;font-weight:600;margin-bottom:2px">
                        @${hub.host}
                    </div>
                    ${hub.sessions.map(s => sessionRow(s))}
                </div>
            `)}
            ${(nm.foreign || []).length > 0 && html`
                <div style="font-size:11px;text-transform:uppercase;color:var(--text-dim);letter-spacing:1px;margin:12px 0 4px;font-weight:600">Other sessions</div>
                <p style="font-size:11px;color:var(--text-dim);margin-bottom:4px">
                    RTP-MIDI sessions from Macs, iPads or DAWs. These never
                    mirror automatically — add the ones you want.
                </p>
                ${(nm.foreign || []).map(s => sessionRow(s))}
            `}
        </div>`}
        ${nm.enabled && html`<div class="card">
            <h3>Manual peers</h3>
            <p style="font-size:11px;color:var(--text-dim);margin-bottom:8px">
                Only needed when mDNS discovery doesn't reach the other
                hub (routed networks that swallow multicast). The hub
                polls each entry directly for its exported devices.
            </p>
            ${(nm.manual_peers || []).map(host => html`
                <div key=${host} style="display:flex;align-items:center;gap:8px;padding:4px 0">
                    <span style="flex:1;font-size:13px">${host}</span>
                    <button class="btn btn-secondary" style="font-size:12px;padding:4px 10px"
                        onclick=${async () => {
                            const r = await api(`/network-midi/peers/${encodeURIComponent(host)}`, { method: 'DELETE' });
                            if (r.error) showToast(r.error); else reload();
                        }}>Remove</button>
                </div>
            `)}
            <div style="display:flex;gap:8px;margin-top:8px">
                <input type="text" placeholder="IP or hostname"
                    style="flex:1;min-width:0"
                    value=${peerInput}
                    oninput=${e => setPeerInput(e.target.value)} />
                <button class="btn btn-secondary" style="font-size:12px"
                    disabled=${!peerInput.trim()}
                    onclick=${async () => {
                        const r = await api('/network-midi/peers', {
                            method: 'POST',
                            body: JSON.stringify({ host: peerInput.trim() }) });
                        if (r.error) showToast(r.error);
                        else { setPeerInput(''); reload(); }
                    }}>Add</button>
            </div>
        </div>`}
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
    { key: 'backup',      title: 'Backup',                  hint: 'Restore or download a saved config checkpoint' },
    { key: 'network-midi', title: 'Network MIDI',           hint: 'Share devices with a second hub or DAW via RTP-MIDI' },
    { key: 'spectator',   title: 'Spectator mirroring',     hint: 'Stream this device into OBS, or mirror another device' },
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
            case 'backup':      body = html`<${SettingsBackup} showToast=${showToast} />`; break;
            case 'network-midi': body = html`<${SettingsNetworkMidi} showToast=${showToast} />`; break;
            case 'spectator':   body = html`<${SettingsSpectator} />`; break;
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
