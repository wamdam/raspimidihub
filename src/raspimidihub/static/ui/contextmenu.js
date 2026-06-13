/**
 * Matrix context menu — Phase 6.
 *
 * The menu is a single shared popover anchored at the click point.
 * One menu instance lives at the App level (see App.js), and any
 * cell / header / row that wants to show one calls
 * `showContextMenu(x, y, items)`.
 *
 * ## Triggering
 *
 * Single tap or right-click opens the menu — there is no separate
 * "primary tap" action anywhere in the matrix any more. Every action
 * (Add, Remove, Edit, Copy, Paste, Rename, Delete, ...) is a menu
 * item, which removes the old "tap toggles, long-press opens menu"
 * dual mode that confused users on phones.
 *
 * ## Items
 *
 * `items: [{ label, action, danger?, disabled? } | { divider: true } |
 *          { header: true, label }]`.
 * `action` is called when the user picks the item; the menu closes
 * automatically afterwards. Pass `disabled: true` for items that show
 * but aren't clickable (typical for Paste when the clipboard is empty).
 * Pass `header: true` for a non-clickable styled header — used to
 * surface the full name of a row whose visible label is abbreviated
 * in the matrix.
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html } from './common.js';

/**
 * Returns event handlers that open the context menu on click OR
 * right-click. Spread onto any element you want to host the menu:
 *
 *   const trigger = useTapMenu(showContextMenu, () => itemsForCell(cell));
 *   <td onClick=${trigger.onClick} onContextMenu=${trigger.onContextMenu}>…</td>
 *
 * No long-press timer — single tap is enough. Items list is computed
 * lazily so it always reflects the latest props/state at trigger time
 * (clipboard, mapping list, etc.).
 */
export function useTapMenu(showContextMenu, getItems) {
    const open = (clientX, clientY) => {
        const items = getItems();
        if (items && items.length) showContextMenu(clientX, clientY, items);
    };
    return {
        onClick: (e) => {
            e.preventDefault();
            open(e.clientX, e.clientY);
        },
        onContextMenu: (e) => {
            e.preventDefault();
            open(e.clientX, e.clientY);
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
                ${menu.items.map((item, i) => {
                    if (item.divider) {
                        return html`<div key=${i} style="height:1px;background:var(--surface2);margin:6px 0"></div>`;
                    }
                    if (item.header) {
                        // Styled as a caption — dim, uppercase, smaller — so it
                        // reads as a title for the menu, not another tappable
                        // row like "Edit" right beneath it.
                        return html`<div key=${i} data-testid="menu-header"
                            style="padding:6px 16px 8px;font-size:11px;
                                   font-weight:700;color:var(--text-dim);
                                   text-transform:uppercase;letter-spacing:0.06em;
                                   white-space:nowrap;
                                   border-bottom:1px solid var(--surface2);
                                   margin-bottom:4px;
                                   max-width:280px;overflow:hidden;
                                   text-overflow:ellipsis;
                                   display:flex;align-items:center;gap:7px">
                            ${item.color ? html`<span style="flex:none;width:10px;height:10px;border-radius:50%;background:${item.color};border:1.5px solid rgba(255,255,255,0.35)"></span>` : ''}
                            <span style="overflow:hidden;text-overflow:ellipsis">${item.label}</span>
                        </div>`;
                    }
                    return html`<button key=${i}
                        data-testid=${'menu-item-' + (item.testId || item.label.toLowerCase().replace(/[^a-z0-9]+/g, '-'))}
                        disabled=${item.disabled}
                        onclick=${() => { if (typeof item.action === 'function') item.action(); onClose(); }}
                        style="display:block;width:100%;text-align:left;
                               background:none;border:none;
                               color:${item.disabled ? 'var(--text-dim)' : (item.danger ? 'var(--danger)' : 'var(--text)')};
                               padding:12px 16px;font-size:15px;
                               cursor:${item.disabled ? 'default' : 'pointer'};
                               border-radius:6px;
                               line-height:1.2">
                        ${item.label}
                    </button>`;
                })}
            </div>
        </div>
    `;
}
