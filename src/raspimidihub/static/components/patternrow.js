/**
 * PatternRow — N (default 8) numbered pattern slots below the
 * Tracker's action row.
 *
 * Each slot is a stored grid (pages + their cells) on the Tracker.
 * Exactly one slot is "selected" -- the one whose grid is on screen
 * and which playback runs. Tapping a different slot either switches
 * immediately (stopped) or queues the switch to fire at the next
 * pattern boundary (playing). Shift+Tap switches immediately even
 * while playing, preserving the playhead. Long-press opens a context
 * menu for Overwrite-from-selected / Clear.
 *
 * Backend protocol (see TrackerBase._handle_pattern_command):
 *   onChange({ pattern: int, mode: "tap"|"shift"|"clone"|"clear" })
 *
 * Visual states (CSS classes):
 *   .empty      -- slot stores a single default page; render as outline
 *   .selected   -- the currently-loaded pattern; filled accent
 *   .playing    -- selected AND the playhead is running
 *   .queued     -- pending switch on the next boundary; pulsing
 *
 * Layout intent: a low-key row tucked under the Shift / Cut / Copy /
 * Paste action row. Always 8 (or N) slots so the row is rhythmically
 * regular; empty slots are still tappable.
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html, tickFeedback } from './common.js';

const LONG_PRESS_MS = 500;

export function PluginPatternRow({
    count,
    selected,
    queued,
    status,
    playing,
    shiftEngagedRef,
    onChange,
}) {
    const total = Math.max(1, count | 0);
    // Long-press tracking: which slot is the user pressing, when did
    // they start. A timer fires the menu open at LONG_PRESS_MS unless
    // the press is released first.
    const pressRef = useRef({ idx: -1, startTs: 0, longFired: false });
    // Open-menu state: the slot index of the slot whose context
    // menu is currently visible, or -1.
    const [menuFor, setMenuFor] = useState(-1);

    // Close the menu on outside-click.
    useEffect(() => {
        if (menuFor < 0) return undefined;
        const onDown = (ev) => {
            if (ev.target && ev.target.closest &&
                ev.target.closest('.tracker-pattern-menu')) {
                return;
            }
            setMenuFor(-1);
        };
        // Defer one tick so the long-press release doesn't immediately
        // close the just-opened menu.
        const id = setTimeout(() => {
            window.addEventListener('pointerdown', onDown, true);
        }, 0);
        return () => {
            clearTimeout(id);
            window.removeEventListener('pointerdown', onDown, true);
        };
    }, [menuFor]);

    const fire = (idx, mode) => {
        if (typeof onChange === 'function') onChange({ pattern: idx, mode });
    };

    const onPointerDown = (idx) => (ev) => {
        // Right-click jumps straight to the context menu.
        if (ev.button === 2) {
            ev.preventDefault();
            setMenuFor(idx);
            return;
        }
        pressRef.current = {
            idx, startTs: Date.now(), longFired: false,
        };
        // Schedule the long-press menu.
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
        if (wasLong) return;  // Menu already open; ignore the short-press path.
        // Short tap.
        tickFeedback();
        const shift = ev.shiftKey || (shiftEngagedRef && shiftEngagedRef.current);
        fire(idx, shift ? 'shift' : 'tap');
    };

    const onPointerLeave = () => {
        pressRef.current = { idx: -1, startTs: 0, longFired: false };
    };

    const onContextMenu = (idx) => (ev) => {
        ev.preventDefault();
        setMenuFor(idx);
    };

    const renderSlot = (idx) => {
        const isSelected = idx === selected;
        const isQueued = idx === queued;
        const isEmpty = !(status && status[idx]);
        const isPlaying = isSelected && playing;
        const cls = [
            'tracker-pattern-slot',
            isSelected ? 'selected' : '',
            isPlaying ? 'playing' : '',
            isQueued ? 'queued' : '',
            isEmpty ? 'empty' : '',
        ].filter(Boolean).join(' ');
        const menu = menuFor === idx ? html`
            <div class="tracker-pattern-menu">
                <button type="button" class="tracker-pattern-menu-item"
                    onclick=${(e) => {
                        e.stopPropagation();
                        fire(idx, 'clone');
                        setMenuFor(-1);
                    }}>Overwrite from selected</button>
                <button type="button"
                    class="tracker-pattern-menu-item danger"
                    onclick=${(e) => {
                        e.stopPropagation();
                        fire(idx, 'clear');
                        setMenuFor(-1);
                    }}>Clear pattern</button>
            </div>` : null;
        return html`<div class="tracker-pattern-slot-wrap">
            <button type="button" class=${cls}
                onpointerdown=${onPointerDown(idx)}
                onpointerup=${onPointerUp(idx)}
                onpointerleave=${onPointerLeave}
                onpointercancel=${onPointerLeave}
                oncontextmenu=${onContextMenu(idx)}
                aria-label=${`Pattern ${idx + 1}${isEmpty ? ' (empty)' : ''}`}
                title=${`Pattern ${idx + 1}${isEmpty ? ' — empty' : ''}\nTap: ${playing ? 'queue switch' : 'load'}\nShift+Tap: switch now\nLong-press: copy/clear`}>${idx + 1}</button>
            ${menu}
        </div>`;
    };

    const slots = [];
    for (let i = 0; i < total; i++) slots.push(renderSlot(i));

    return html`<div class="tracker-pattern-row">
        <div class="tracker-pattern-label">PATTERN</div>
        <div class="tracker-pattern-slots">${slots}</div>
    </div>`;
}
