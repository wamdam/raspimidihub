/**
 * PatternBank — unified pattern-slot row for the Tracker and for
 * the Arpeggiator / Euclidean play surfaces.
 *
 * Renders a row of `count` tappable buttons (P1..Pn). Tap to
 * switch; long-press (≥500 ms) opens a menu with two items:
 *   - Overwrite from current  → copy active slot into this one
 *   - Reset to default        → wipe this slot back to defaults
 *
 * Tracker-specific extras are opt-in via props:
 *   - `status`           : bool[] — per-slot "has content" flag.
 *                          Slots with status=false render dashed-
 *                          empty.
 *   - `queued`           : int    — the slot pending a switch at
 *                          the next bar boundary (Tracker queue);
 *                          renders pulsing outline. Pass -1 / omit
 *                          to disable.
 *   - `playing`          : bool   — true while transport is
 *                          running; selected+playing renders in
 *                          the warm accent rather than the cool
 *                          one. Strip plugins never set this.
 *   - `shiftEngagedRef`  : ref    — Tracker reads its on-screen
 *                          Shift state from this; tap-with-shift
 *                          dispatches `{shift: true}`.
 *
 * The parent owns the dispatch shape — pass:
 *   - `onTap(idx, opts)`    where opts = `{shift: bool}`. Always
 *                           fires on a short tap.
 *   - `onCmd(idx, mode)`    where mode = `'clone' | 'clear'`. If
 *                           undefined, the long-press menu is
 *                           suppressed (no commands available).
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html, tickFeedback } from './common.js';

const LONG_PRESS_MS = 500;

export function PluginPatternBank({
    count,
    selected,
    queued,
    status,
    playing,
    shiftEngagedRef,
    onTap,
    onCmd,
}) {
    const total = Math.max(1, count | 0);
    const safeSel = Math.max(0, Math.min(total - 1, parseInt(selected) || 0));
    const queuedIdx = (typeof queued === 'number' && queued >= 0 && queued < total)
        ? queued : -1;
    const hasMenu = typeof onCmd === 'function';
    const pressRef = useRef({ idx: -1, startTs: 0, longFired: false });
    const [menuFor, setMenuFor] = useState(-1);

    // Close the menu on outside pointerdown.
    useEffect(() => {
        if (menuFor < 0) return undefined;
        const onDown = (ev) => {
            if (ev.target && ev.target.closest &&
                ev.target.closest('.pattern-bank-menu')) {
                return;
            }
            setMenuFor(-1);
        };
        const id = setTimeout(() => {
            window.addEventListener('pointerdown', onDown, true);
        }, 0);
        return () => {
            clearTimeout(id);
            window.removeEventListener('pointerdown', onDown, true);
        };
    }, [menuFor]);

    const onPointerDown = (idx) => (ev) => {
        if (ev.button === 2) {
            ev.preventDefault();
            if (hasMenu) setMenuFor(idx);
            return;
        }
        pressRef.current = { idx, startTs: Date.now(), longFired: false };
        if (!hasMenu) return;
        setTimeout(() => {
            const s = pressRef.current;
            if (s.idx === idx && s.startTs > 0 && !s.longFired &&
                (Date.now() - s.startTs) >= LONG_PRESS_MS - 5) {
                s.longFired = true;
                setMenuFor(idx);
            }
        }, LONG_PRESS_MS);
    };

    const onPointerUp = (idx) => (ev) => {
        const s = pressRef.current;
        const wasLong = s.longFired;
        pressRef.current = { idx: -1, startTs: 0, longFired: false };
        if (wasLong) return;  // menu opened; ignore the short-press path
        tickFeedback();
        const shift = !!(ev.shiftKey || (shiftEngagedRef && shiftEngagedRef.current));
        if (typeof onTap === 'function') onTap(idx, { shift });
    };

    const onPointerLeave = () => {
        pressRef.current = { idx: -1, startTs: 0, longFired: false };
    };

    const onContextMenu = (idx) => (ev) => {
        ev.preventDefault();
        if (hasMenu) setMenuFor(idx);
    };

    const slots = [];
    for (let i = 0; i < total; i++) {
        const isSel = i === safeSel;
        const isQueued = i === queuedIdx;
        // status=undefined => caller has no notion of empty vs filled
        // (Arp / Euclidean case where every slot is always populated).
        const isEmpty = Array.isArray(status) ? !status[i] : false;
        const isPlaying = isSel && !!playing;
        const cls = [
            'pattern-bank-slot',
            isSel ? 'selected' : '',
            isPlaying ? 'playing' : '',
            isQueued ? 'queued' : '',
            isEmpty ? 'empty' : '',
        ].filter(Boolean).join(' ');
        const menu = (hasMenu && menuFor === i) ? html`
            <div class="pattern-bank-menu">
                <button type="button" class="pattern-bank-menu-item"
                    onclick=${(e) => {
                        e.stopPropagation();
                        onCmd(i, 'clone');
                        setMenuFor(-1);
                    }}>Overwrite from current</button>
                <button type="button"
                    class="pattern-bank-menu-item danger"
                    onclick=${(e) => {
                        e.stopPropagation();
                        onCmd(i, 'clear');
                        setMenuFor(-1);
                    }}>Reset to default</button>
            </div>` : null;
        slots.push(html`<div class="pattern-bank-slot-wrap" key=${i}>
            <button type="button" class=${cls}
                onpointerdown=${onPointerDown(i)}
                onpointerup=${onPointerUp(i)}
                onpointerleave=${onPointerLeave}
                onpointercancel=${onPointerLeave}
                oncontextmenu=${onContextMenu(i)}
                title=${`P${i + 1}${isEmpty ? ' — empty' : ''}`}>
                P${i + 1}
            </button>
            ${menu}
        </div>`);
    }
    return html`<div class="pattern-bank">${slots}</div>`;
}
