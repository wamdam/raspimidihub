/**
 * PatternStrip — end-of-play-surface bank selector.
 *
 * Renders a row of `count` tappable buttons (P1..Pn). Tap to switch
 * to that slot. Long-press (≥500 ms) opens a menu with two items:
 *   - Paste from current → overwrite this slot with the active
 *                          slot's snapshot
 *   - Reset to default   → wipe this slot back to plugin defaults
 *
 * The active-slot int (`name`) is updated on tap. Menu picks
 * dispatch through `cmdParam` as `{slot, mode}` payloads; the
 * plugin's `on_param_change` routes them via
 * `raspimidihub.slot_bank.handle_command`. Held notes, sustain
 * and the playhead are untouched by either action; only slot
 * contents change.
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html, tickFeedback } from './common.js';

const LONG_PRESS_MS = 500;

export function PluginPatternStrip({ name, value, onChange, count, cmdParam }) {
    const active = Math.max(0, Math.min(count - 1, parseInt(value) || 0));
    const pressRef = useRef({ idx: -1, startTs: 0, longFired: false });
    const [menuFor, setMenuFor] = useState(-1);

    // Close the menu on any outside pointerdown.
    useEffect(() => {
        if (menuFor < 0) return undefined;
        const onDown = (ev) => {
            if (ev.target && ev.target.closest &&
                ev.target.closest('.pattern-strip-menu')) {
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

    const fireCmd = (idx, mode) => {
        if (cmdParam && typeof onChange === 'function') {
            onChange(cmdParam, { slot: idx, mode });
        }
    };

    const onPointerDown = (idx) => (ev) => {
        if (ev.button === 2) {
            ev.preventDefault();
            setMenuFor(idx);
            return;
        }
        pressRef.current = { idx, startTs: Date.now(), longFired: false };
        setTimeout(() => {
            const s = pressRef.current;
            if (s.idx === idx && s.startTs > 0 && !s.longFired &&
                (Date.now() - s.startTs) >= LONG_PRESS_MS - 5) {
                s.longFired = true;
                setMenuFor(idx);
            }
        }, LONG_PRESS_MS);
    };

    const onPointerUp = (idx) => () => {
        const s = pressRef.current;
        const wasLong = s.longFired;
        pressRef.current = { idx: -1, startTs: 0, longFired: false };
        if (wasLong) return;  // menu open; ignore the short-press path
        if (idx === active) return;
        tickFeedback();
        onChange(name, idx);
    };

    const onPointerLeave = () => {
        pressRef.current = { idx: -1, startTs: 0, longFired: false };
    };

    const onContextMenu = (idx) => (ev) => {
        ev.preventDefault();
        setMenuFor(idx);
    };

    const slots = [];
    for (let i = 0; i < count; i++) {
        const isActive = i === active;
        const menu = (menuFor === i && cmdParam) ? html`
            <div class="pattern-strip-menu">
                <button type="button" class="pattern-strip-menu-item"
                    onclick=${(e) => {
                        e.stopPropagation();
                        fireCmd(i, 'clone');
                        setMenuFor(-1);
                    }}>Paste from current</button>
                <button type="button"
                    class="pattern-strip-menu-item danger"
                    onclick=${(e) => {
                        e.stopPropagation();
                        fireCmd(i, 'clear');
                        setMenuFor(-1);
                    }}>Reset to default</button>
            </div>` : null;
        slots.push(html`<div class="pattern-strip-btn-wrap" key=${i}>
            <button type="button"
                class="pattern-strip-btn ${isActive ? 'active' : ''}"
                onpointerdown=${onPointerDown(i)}
                onpointerup=${onPointerUp(i)}
                onpointerleave=${onPointerLeave}
                onpointercancel=${onPointerLeave}
                oncontextmenu=${onContextMenu(i)}
                title=${`P${i + 1} — tap: switch, long-press: menu`}>
                P${i + 1}
            </button>
            ${menu}
        </div>`);
    }
    return html`<div class="pattern-strip">${slots}</div>`;
}
