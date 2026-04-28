/**
 * Matrix context menu — Phase 6.
 *
 * The menu is a single shared popover anchored at the touch / click
 * point the user triggered it from. One menu instance lives at the
 * App level (see App.js), and any cell / header / row that wants to
 * show one calls `showContextMenu(event, items)`.
 *
 * ## Triggering
 *
 * - Mobile: long-press (≥500 ms) → `showContextMenu(touch, items)`.
 * - Desktop: native `contextmenu` event → `showContextMenu(e, items)`.
 *
 * Both shapes are produced by the `useContextTrigger` hook below — pass
 * its returned handler dict to any element that wants to host the menu.
 *
 * ## Items
 *
 * `items: [{ label, action, danger?, disabled? } | { divider: true }]`.
 * `action` is called when the user picks the item; the menu closes
 * automatically afterwards. Pass `disabled: true` for items that show
 * but are not clickable (typical for "Paste" when the clipboard is
 * empty).
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html } from './common.js';

// --- Long-press / right-click wiring -------------------------------------

const LONG_PRESS_MS = 500;

/**
 * Returns a set of event handlers to attach to any element that should
 * surface a context menu on long-press OR right-click. The element's
 * normal `onClick` keeps working unless the menu was just triggered
 * (in which case the click is suppressed via `data-suppress-click`
 * — the element's own click handler should ignore the event when the
 * suppression flag is set).
 *
 *   const trigger = useContextTrigger(showContextMenu, () => itemsForCell(cell));
 *   <td onClick=${onTap} ...trigger}>...</td>
 *
 * For elements that don't have a tap action, just spread the trigger
 * props and ignore the suppression bit.
 */
export function useContextTrigger(showContextMenu, getItems) {
    const timer = useRef(null);
    const triggered = useRef(false);

    const start = (clientX, clientY) => {
        triggered.current = false;
        timer.current = setTimeout(() => {
            triggered.current = true;
            timer.current = null;
            const items = getItems();
            if (items && items.length) showContextMenu(clientX, clientY, items);
        }, LONG_PRESS_MS);
    };
    const cancel = () => {
        if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    };

    return {
        onTouchStart: (e) => {
            const t = e.touches && e.touches[0];
            if (t) start(t.clientX, t.clientY);
        },
        onTouchMove: cancel,
        onTouchEnd: cancel,
        onTouchCancel: cancel,
        onMouseDown: (e) => {
            // Only react to primary button so right-click goes through
            // the contextmenu handler below instead of starting a long-
            // press timer that would then fire alongside it.
            if (e.button === 0) start(e.clientX, e.clientY);
        },
        onMouseUp: cancel,
        onMouseLeave: cancel,
        onContextMenu: (e) => {
            e.preventDefault();
            cancel();
            triggered.current = true;
            const items = getItems();
            if (items && items.length) showContextMenu(e.clientX, e.clientY, items);
        },
        // Read this on click to know whether to suppress the click.
        wasTriggered: () => {
            const v = triggered.current;
            triggered.current = false;
            return v;
        },
    };
}

// --- The menu itself -----------------------------------------------------

const MENU_PADDING = 8;       // pixels between menu and viewport edge
const MENU_MIN_WIDTH = 200;

export function ContextMenu({ menu, onClose }) {
    const ref = useRef(null);
    const [pos, setPos] = useState(null);

    // After mount we can measure the actual rendered size and clamp the
    // position so the menu never lands offscreen — which is otherwise
    // easy to do near the right / bottom edges, especially on phones.
    useEffect(() => {
        if (!menu || !ref.current) { setPos(null); return; }
        const rect = ref.current.getBoundingClientRect();
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        let x = menu.x;
        let y = menu.y;
        if (x + rect.width + MENU_PADDING > vw) x = vw - rect.width - MENU_PADDING;
        if (y + rect.height + MENU_PADDING > vh) y = vh - rect.height - MENU_PADDING;
        x = Math.max(MENU_PADDING, x);
        y = Math.max(MENU_PADDING, y);
        setPos({ x, y });
    }, [menu]);

    // Esc closes — same key the rest of the app uses for "dismiss panel".
    useEffect(() => {
        if (!menu) return;
        const onKey = (e) => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [menu, onClose]);

    if (!menu) return null;

    // While we're computing the clamped position the menu renders
    // offscreen at (-9999, -9999) so the user never sees a flash at
    // the wrong location.
    const left = pos ? pos.x : -9999;
    const top = pos ? pos.y : -9999;

    return html`
        <div data-testid="context-menu-bg" onclick=${onClose}
            onContextMenu=${(e) => { e.preventDefault(); onClose(); }}
            style="position:fixed;inset:0;z-index:1100">
            <div ref=${ref} data-testid="context-menu" onclick=${e => e.stopPropagation()}
                style="position:absolute;left:${left}px;top:${top}px;
                       background:var(--surface);border-radius:8px;padding:6px;
                       min-width:${MENU_MIN_WIDTH}px;
                       box-shadow:0 8px 24px rgba(0,0,0,0.6);
                       border:1px solid var(--surface2);
                       visibility:${pos ? 'visible' : 'hidden'}">
                ${menu.items.map((item, i) => item.divider
                    ? html`<div key=${i} style="height:1px;background:var(--surface2);margin:6px 0"></div>`
                    : html`<button key=${i}
                        data-testid=${'menu-item-' + (item.testId || item.label.toLowerCase().replace(/[^a-z0-9]+/g, '-'))}
                        disabled=${item.disabled}
                        onclick=${() => { item.action(); onClose(); }}
                        style="display:block;width:100%;text-align:left;
                               background:none;border:none;
                               color:${item.disabled ? 'var(--text-dim)' : (item.danger ? 'var(--danger)' : 'var(--text)')};
                               padding:12px 16px;font-size:15px;
                               cursor:${item.disabled ? 'default' : 'pointer'};
                               border-radius:6px;
                               line-height:1.2">
                        ${item.label}
                    </button>`
                )}
            </div>
        </div>
    `;
}
