/**
 * TrackerGrid — Tracker step-sequencer surface.
 *
 * 16 step rows × 1..N voice columns, paged up to 16 pages. Rows are
 * labelled `<page-hex><row-hex>` (00..0F on page 0, 10..1F on page 1,
 * …, F0..FF on page F) so the user sees one continuous address space
 * even though only the current page renders at a time.
 *
 * Cursor wraps across page boundaries: ↓ on row F advances to row 0
 * of the next page, ↑ on row 0 retreats to row F of the previous
 * page, both looping at page 0 / last page. PgUp / PgDn keep the
 * row index and just move the page (also looped). Arrow keys on the
 * keyboard mirror the on-screen cursor cluster.
 *
 * State is read from / written to sibling auxiliary params named on
 * the TrackerGrid Param. All edits flow through the standard
 * `onChange(name, value)` callback so SSE keeps multi-browser views
 * in sync.
 */

import { html } from '../ui/common.js';
import { useCallback, useEffect, useRef } from '../lib/hooks.module.js';

const HEX = '0123456789ABCDEF';
const HOLD = '---';
const CC_HOLD = '--';
const CC_NONE = '.';

// ------------------------------------------------------------------
// Cell rendering
// ------------------------------------------------------------------

function fmt2hex(n) {
    if (typeof n !== 'number') return CC_HOLD;
    return n.toString(16).toUpperCase().padStart(2, '0');
}

function fmtNote(note) {
    if (typeof note !== 'string') return HOLD;
    if (note.length === 3) return note;
    return HOLD;
}

function fmtCcNum(num) {
    if (typeof num === 'number') return num.toString(16).toUpperCase().padStart(2, '0');
    if (num === CC_NONE) return '. ';
    return CC_HOLD;
}

function fmtVoice(v) {
    if (!v) return `${HOLD} ${CC_HOLD} ${CC_HOLD}${CC_HOLD}`;
    return `${fmtNote(v.note)} ${typeof v.vel === 'number' ? fmt2hex(v.vel) : CC_HOLD} ${fmtCcNum(v.cc_num)}${typeof v.cc_val === 'number' ? fmt2hex(v.cc_val) : CC_HOLD}`;
}

// ------------------------------------------------------------------
// Page operations
// ------------------------------------------------------------------

function emptyVoice() {
    return { note: HOLD, vel: CC_HOLD, cc_num: CC_NONE, cc_val: CC_HOLD };
}

function emptyRow(trackCount) {
    return { voices: Array.from({ length: trackCount }, emptyVoice) };
}

function emptyPage(trackCount, maxRows) {
    return { rows: Array.from({ length: maxRows }, () => emptyRow(trackCount)) };
}

function clonePage(p) {
    return JSON.parse(JSON.stringify(p));
}

// ------------------------------------------------------------------
// Help row text
// ------------------------------------------------------------------

const HELP_STATIC = 'Help:  Note  |  Velocity  |  CC#  |  CC Val';

// Same rate set as the Arpeggiator — kept in sync with
// raspimidihub/tracker_base.py:RATE_OPTIONS.
const RATE_OPTIONS = [
    '4/1', '4/1T', '2/1', '2/1T', '1/1', '1/1T',
    '1/2', '1/2T', '1/4', '1/4T', '1/8', '1/8T',
    '1/16', '1/16T', '1/32',
];

// ------------------------------------------------------------------
// Main component
// ------------------------------------------------------------------

export function PluginTrackerGrid({ param, values, onChange }) {
    const trackCount = param.track_count || 8;
    const maxPages = param.max_pages || 16;
    const maxRows = param.max_rows || 16;

    const pages = values[param.pages_param] || [];
    const pageCount = Math.max(1, pages.length);
    const currentPage = clamp(values[param.current_page_param] ?? 0, 0, pageCount - 1);
    const cursorRow = clamp(values[param.cursor_row_param] ?? 0, 0, maxRows - 1);
    const cursorTrack = clamp(values[param.cursor_track_param] ?? 0, 0, trackCount - 1);
    const rate = values[param.rate_param] || '1/16';

    const page = pages[currentPage] || emptyPage(trackCount, maxRows);
    const rows = page.rows || [];

    // Refs that mirror the live cursor/page state so move-* callbacks
    // can be referenced from a long-running press-and-hold timer
    // without going stale through closure capture. Without this, the
    // 60ms repeat would always re-read the cursor position from the
    // first press, so holding ↓ would only advance one row.
    const cursorRowRef = useRef(cursorRow);
    const cursorTrackRef = useRef(cursorTrack);
    const currentPageRef = useRef(currentPage);
    cursorRowRef.current = cursorRow;
    cursorTrackRef.current = cursorTrack;
    currentPageRef.current = currentPage;

    // ---- Cursor moves with page-boundary wrap on row ↑/↓. ----
    // Wrapping rules:
    //   ↓ on row F  → next page, row 0 (wraps to page 0 from last page)
    //   ↑ on row 0  → previous page, row F (wraps to last page from page 0)
    //   →/← wrap within trackCount (T8 → T1 on right; T1 → T8 on left).
    const moveRow = useCallback((d) => {
        const cr = cursorRowRef.current;
        const cp = currentPageRef.current;
        let nextRow = cr + d;
        let nextPage = cp;
        if (nextRow >= maxRows) {
            nextRow = 0;
            nextPage = (cp + 1) % pageCount;
        } else if (nextRow < 0) {
            nextRow = maxRows - 1;
            nextPage = (cp - 1 + pageCount) % pageCount;
        }
        if (nextRow !== cr) onChange(param.cursor_row_param, nextRow);
        if (nextPage !== cp) onChange(param.current_page_param, nextPage);
    }, [maxRows, pageCount, onChange, param]);

    const moveTrack = useCallback((d) => {
        const cur = cursorTrackRef.current;
        const next = ((cur + d) % trackCount + trackCount) % trackCount;
        if (next !== cur) onChange(param.cursor_track_param, next);
    }, [trackCount, onChange, param]);

    // PgUp / PgDn — keep the row, change page (looped).
    const movePage = useCallback((d) => {
        const cp = currentPageRef.current;
        const nextPage = (cp + d + pageCount) % pageCount;
        if (nextPage !== cp) onChange(param.current_page_param, nextPage);
    }, [pageCount, onChange, param]);

    // Press-and-hold key-repeat for the on-screen cursor cluster.
    // First fire is immediate; after 350 ms the action starts repeating
    // every 60 ms until the user releases / leaves the button.
    // Single timer slot — only one button can be held at a time.
    const repeatRef = useRef({ to: null, iv: null });
    const stopRepeat = useCallback(() => {
        const r = repeatRef.current;
        if (r.to) { clearTimeout(r.to); r.to = null; }
        if (r.iv) { clearInterval(r.iv); r.iv = null; }
    }, []);
    const startRepeat = useCallback((action) => {
        stopRepeat();
        action();
        repeatRef.current.to = setTimeout(() => {
            repeatRef.current.iv = setInterval(action, 60);
        }, 350);
    }, [stopRepeat]);
    useEffect(() => () => stopRepeat(), [stopRepeat]);

    const focusCell = useCallback((row, track) => {
        if (row !== cursorRow) onChange(param.cursor_row_param, row);
        if (track !== cursorTrack) onChange(param.cursor_track_param, track);
    }, [cursorRow, cursorTrack, onChange, param]);

    // ---- Page management. ----
    const addPage = useCallback(() => {
        if (pages.length >= maxPages) return;
        const next = pages.slice();
        next.splice(currentPage + 1, 0, emptyPage(trackCount, maxRows));
        onChange(param.pages_param, next);
        onChange(param.current_page_param, currentPage + 1);
    }, [pages, currentPage, maxPages, trackCount, maxRows, onChange, param]);

    const delPage = useCallback(() => {
        if (pages.length <= 1) return;
        const next = pages.slice();
        next.splice(currentPage, 1);
        onChange(param.pages_param, next);
        const nextIdx = Math.min(currentPage, next.length - 1);
        onChange(param.current_page_param, nextIdx);
    }, [pages, currentPage, onChange, param]);

    const copyPage = useCallback(() => {
        // Session-local clipboard on window so /play unmount doesn't
        // lose it. Single typed slot.
        window.__trackerPageClipboard = clonePage(pages[currentPage] || emptyPage(trackCount, maxRows));
    }, [pages, currentPage, trackCount, maxRows]);

    const pastePage = useCallback(() => {
        const clip = window.__trackerPageClipboard;
        if (!clip) return;
        const next = pages.slice();
        next[currentPage] = clonePage(clip);
        onChange(param.pages_param, next);
    }, [pages, currentPage, onChange, param]);

    // ---- Keyboard support (window-level). ----
    // Active only while this component is mounted. Skips when an
    // input/select/textarea has focus so the rate dropdown still
    // works as expected.
    useEffect(() => {
        const onKey = (e) => {
            const tag = (e.target && e.target.tagName) || '';
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            switch (e.key) {
                case 'ArrowUp':    moveRow(-1); e.preventDefault(); break;
                case 'ArrowDown':  moveRow(+1); e.preventDefault(); break;
                case 'ArrowLeft':  moveTrack(-1); e.preventDefault(); break;
                case 'ArrowRight': moveTrack(+1); e.preventDefault(); break;
                case 'PageUp':     movePage(-1); e.preventDefault(); break;
                case 'PageDown':   movePage(+1); e.preventDefault(); break;
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [moveRow, moveTrack, movePage]);

    // Scroll the focused cell into view on cursor / page changes.
    const gridRef = useRef(null);
    useEffect(() => {
        const grid = gridRef.current;
        if (!grid) return;
        const focused = grid.querySelector('.tracker-cell.focused');
        if (focused && focused.scrollIntoView) {
            focused.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        }
    }, [cursorRow, cursorTrack, currentPage]);

    // ---- Header (Rate dropdown + page actions only) ----
    const header = html`<div class="tracker-header">
        <div class="tracker-header-row">
            <span class="tracker-header-label">Rate</span>
            <select class="tracker-rate-select"
                value=${rate}
                onchange=${(e) => onChange(param.rate_param, e.target.value)}>
                ${RATE_OPTIONS.map((r) => html`<option value=${r}>${r}</option>`)}
            </select>

            <button class="tracker-page-btn"
                disabled=${pages.length >= maxPages}
                onclick=${addPage}>+ Add</button>
            <button class="tracker-page-btn"
                disabled=${pages.length <= 1}
                onclick=${delPage}>− Del</button>
            <button class="tracker-page-btn" onclick=${copyPage}>Copy</button>
            <button class="tracker-page-btn" onclick=${pastePage}>Paste</button>
        </div>
    </div>`;

    // ---- Track-header row (above the steps) ----
    const trackHeader = html`<div class="tracker-track-header">
        <span class="tracker-track-step-col"></span>
        ${range(0, trackCount).map((t) => html`<span
            class="tracker-track-label ${t === cursorTrack ? 'cursor' : ''}">T${t + 1}</span>`)}
    </div>`;

    // ---- Step rows ----
    // Row label = page-hex + row-hex (00..0F on page 0, 10..1F on
    // page 1, ...). The grid only renders the current page's data,
    // but the prefix tells the user where they are in the song.
    const pagePrefix = HEX[currentPage];
    const stepRows = html`<div class="tracker-rows">
        ${range(0, maxRows).map((rowIdx) => {
            const row = rows[rowIdx] || emptyRow(trackCount);
            const isCursorRow = rowIdx === cursorRow;
            // Beat-marker every 4 rows (00, 04, 08, 0C) — visually
            // groups steps into beats so the eye lands on quarter
            // boundaries at a glance.
            const isBeat = (rowIdx & 3) === 0;
            return html`<div class="tracker-row ${isCursorRow ? 'cursor' : ''}">
                <span class="tracker-row-num ${isBeat ? 'beat' : ''}">${pagePrefix}${HEX[rowIdx]}</span>
                ${range(0, trackCount).map((t) => {
                    const v = row.voices[t];
                    const focused = isCursorRow && t === cursorTrack;
                    return html`<span
                        class="tracker-cell ${focused ? 'focused' : ''}"
                        onclick=${() => focusCell(rowIdx, t)}>${fmtVoice(v)}</span>`;
                })}
            </div>`;
        })}
    </div>`;

    // ---- Help row (static for now; live-value in keypad commit) ----
    const helpRow = html`<div class="tracker-help">${HELP_STATIC}</div>`;

    // ---- Cursor cluster: PgUp / ↑ / PgDn on top, ← / ↓ / → on bottom ----
    // Each button uses pointer events so press-and-hold repeats while
    // the touch is held; click-only (mouse) still works because pointer
    // events fire for the mouse too.
    const arrow = (action, label, title, extraClass = '') => html`<button
        class="tracker-arrow ${extraClass}"
        title=${title}
        onpointerdown=${(e) => { e.preventDefault(); startRepeat(action); }}
        onpointerup=${stopRepeat}
        onpointerleave=${stopRepeat}
        onpointercancel=${stopRepeat}>${label}</button>`;
    const cursor = html`<div class="tracker-cursor-cluster">
        <div class="tracker-arrow-row">
            ${arrow(() => movePage(-1), '⇞', 'Page up (PgUp)', 'tracker-arrow-page')}
            ${arrow(() => moveRow(-1), '↑', 'Up (↑)')}
            ${arrow(() => movePage(+1), '⇟', 'Page down (PgDn)', 'tracker-arrow-page')}
        </div>
        <div class="tracker-arrow-row">
            ${arrow(() => moveTrack(-1), '←', 'Left (←)')}
            ${arrow(() => moveRow(+1), '↓', 'Down (↓)')}
            ${arrow(() => moveTrack(+1), '→', 'Right (→)')}
        </div>
    </div>`;

    return html`<div class="trackergrid">
        ${header}
        <div class="tracker-grid-area" ref=${gridRef}>
            ${trackHeader}
            ${stepRows}
        </div>
        ${helpRow}
        <div class="tracker-keypad-stub">
            <div style="color:var(--text-dim);font-size:11px;text-align:center;padding:8px">
                Note · Octave · Velocity · CC# · CC Val keypad — coming next commit
            </div>
            ${cursor}
        </div>
    </div>`;
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function clamp(n, lo, hi) {
    n = n | 0;
    if (n < lo) return lo;
    if (n > hi) return hi;
    return n;
}

function range(start, end) {
    const out = [];
    for (let i = start; i < end; i++) out.push(i);
    return out;
}
