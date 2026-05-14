/**
 * Shared helpers for plugin UI components.
 */

import { h } from '../lib/preact.module.js';
import htm from '../lib/htm.module.js';

export const html = htm.bind(h);

// --- Haptic feedback ---
let audioCtx = null;
function ensureAudio() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    return audioCtx;
}

// User-disable-able tick / thud sounds. Persisted in localStorage so
// the toggle survives reloads. Default ON (matches prior behaviour).
const SOUND_KEY = 'raspimidihub:soundsEnabled';
function soundsEnabled() {
    try { return localStorage.getItem(SOUND_KEY) !== '0'; }
    catch { return true; }
}

export function tickFeedback() {
    if (!soundsEnabled()) { try { navigator.vibrate(2); } catch {} return; }
    try {
        const ctx = ensureAudio();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'square';
        osc.frequency.value = 3500;
        gain.gain.value = 0.03;
        osc.connect(gain).connect(ctx.destination);
        osc.start(); osc.stop(ctx.currentTime + 0.02);
    } catch {}
    try { navigator.vibrate(2); } catch {}
}

export function thudFeedback() {
    if (!soundsEnabled()) { try { navigator.vibrate(30); } catch {} return; }
    try {
        const ctx = ensureAudio();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = 150;
        gain.gain.value = 0.08;
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.08);
        osc.connect(gain).connect(ctx.destination);
        osc.start(); osc.stop(ctx.currentTime + 0.08);
    } catch {}
    try { navigator.vibrate(30); } catch {}
}

export function getSoundsEnabled() { return soundsEnabled(); }
export function setSoundsEnabled(v) {
    try { localStorage.setItem(SOUND_KEY, v ? '1' : '0'); } catch {}
}

// Layout density preference — picks how tightly the chrome (header,
// main padding, bottom-nav, controller bar) is spaced. Per-device,
// stored in localStorage so it travels with the browser, NOT in the
// saved config — what counts as cramped depends on the device the UI
// is viewed from. Extensible: today 'default' / 'small', a 'tablet'
// option can join later with its own class-driven CSS rules.
const DENSITY_KEY = 'raspimidihub:layoutDensity';
export const DENSITY_OPTIONS = [
    { value: 'default', label: 'Default' },
    { value: 'small',   label: 'Small screen (tighter)' },
];
const VALID_DENSITIES = new Set(DENSITY_OPTIONS.map(o => o.value));

export function getLayoutDensity() {
    try {
        const v = localStorage.getItem(DENSITY_KEY);
        return VALID_DENSITIES.has(v) ? v : 'default';
    } catch { return 'default'; }
}
export function setLayoutDensity(v) {
    if (!VALID_DENSITIES.has(v)) v = 'default';
    try { localStorage.setItem(DENSITY_KEY, v); } catch {}
    applyLayoutDensity(v);
}
export function applyLayoutDensity(v) {
    if (typeof document === 'undefined') return;
    const el = document.documentElement;
    // Strip any previous density-* class, then re-apply the current
    // one. 'default' adds no class (matches the un-toggled baseline so
    // the same CSS path serves both legacy and explicit-default cases).
    for (const opt of DENSITY_OPTIONS) {
        el.classList.remove('density-' + opt.value);
    }
    if (v && v !== 'default') el.classList.add('density-' + v);
}

const NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
export function noteName(n) { return `${NOTE_NAMES[n % 12]}${Math.floor(n / 12) - 2}`; }

// Global touch lock: only one wheel active per touch
export const _activeWheelTouch = new Map();
