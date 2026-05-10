/**
 * TrackerGrid — Tracker step-sequencer surface.
 *
 * 16 hex-numbered step rows × 1..N voice columns, paged up to 16
 * pages, with an always-visible data-entry keypad below (separate
 * commit). This file ships the grid + header + cursor navigation +
 * page management + help row; the full keypad lands next.
 *
 * State is read from / written to sibling auxiliary params named on
 * the TrackerGrid Param (pages_param, current_page_param,
 * cursor_row_param, cursor_track_param, octave_param). All edits
 * flow through the standard `onChange(name, value)` callback so SSE
 * keeps multi-browser views in sync.
 */

import { html } from '../ui/common.js';
import { useCallback, useMemo } from '../lib/hooks.module.js';

const HEX = '0123456789ABCDEF';
const HOLD = '---';
const END = 'End';
const OFF = 'Off';
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

// Deep-clone a page so paste / mutation paths don't share references.
function clonePage(p) {
    return JSON.parse(JSON.stringify(p));
}

// ------------------------------------------------------------------
// Help row text
// ------------------------------------------------------------------

const HELP_STATIC = 'Help:  Note  |  Velocity  |  CC#  |  CC Val';

// ------------------------------------------------------------------
// Main component
// ------------------------------------------------------------------

export function PluginTrackerGrid({ param, values, onChange }) {
    const trackCount = param.track_count || 8;
    const maxPages = param.max_pages || 16;
    const maxRows = param.max_rows || 16;

    const pages = values[param.pages_param] || [];
    const currentPage = clamp(values[param.current_page_param] ?? 0, 0, Math.max(0, pages.length - 1));
    const cursorRow = clamp(values[param.cursor_row_param] ?? 0, 0, maxRows - 1);
    const cursorTrack = clamp(values[param.cursor_track_param] ?? 0, 0, trackCount - 1);
    const showTracks = parseInt(values.show_tracks || '4', 10);

    // Viewport — keep the cursor track in view.
    const viewport = useMemo(() => {
        const start = Math.max(0, Math.min(trackCount - showTracks,
            cursorTrack - Math.floor(showTracks / 2)));
        return { start, end: Math.min(trackCount, start + showTracks) };
    }, [trackCount, showTracks, cursorTrack]);

    const page = pages[currentPage] || emptyPage(trackCount, maxRows);
    const rows = page.rows || [];

    // ---- Cursor moves (Mapping X: ↑/↓ rows, ←/→ voices). ----
    const moveCursor = useCallback((dRow, dTrack) => {
        const nextRow = clamp(cursorRow + dRow, 0, maxRows - 1);
        const nextTrack = clamp(cursorTrack + dTrack, 0, trackCount - 1);
        if (nextRow !== cursorRow) onChange(param.cursor_row_param, nextRow);
        if (nextTrack !== cursorTrack) onChange(param.cursor_track_param, nextTrack);
    }, [cursorRow, cursorTrack, maxRows, trackCount, onChange, param]);

    const focusCell = useCallback((row, track) => {
        if (row !== cursorRow) onChange(param.cursor_row_param, row);
        if (track !== cursorTrack) onChange(param.cursor_track_param, track);
    }, [cursorRow, cursorTrack, onChange, param]);

    // ---- Page management. ----
    const setCurrentPage = useCallback((idx) => {
        const clamped = clamp(idx, 0, Math.max(0, pages.length - 1));
        onChange(param.current_page_param, clamped);
    }, [pages.length, onChange, param]);

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
        // Stay on same index if possible; otherwise the new tail.
        const nextIdx = Math.min(currentPage, next.length - 1);
        onChange(param.current_page_param, nextIdx);
    }, [pages, currentPage, onChange, param]);

    const copyPage = useCallback(() => {
        // Session-local clipboard lives on window so /play unmount
        // doesn't lose it. Single typed slot.
        window.__trackerPageClipboard = clonePage(pages[currentPage] || emptyPage(trackCount, maxRows));
    }, [pages, currentPage, trackCount, maxRows]);

    const pastePage = useCallback(() => {
        const clip = window.__trackerPageClipboard;
        if (!clip) return;
        const next = pages.slice();
        next[currentPage] = clonePage(clip);
        onChange(param.pages_param, next);
    }, [pages, currentPage, onChange, param]);

    // ---- Header ----
    const header = html`<div class="tracker-header">
        <div class="tracker-header-row">
            <span class="tracker-header-label">Rate</span>
            <span class="tracker-header-value">${values.rate || '1/16'}</span>

            <span class="tracker-header-label" style="margin-left:18px">Page</span>
            <button class="tracker-page-btn"
                disabled=${currentPage <= 0}
                onclick=${() => setCurrentPage(currentPage - 1)}>‹</button>
            <span class="tracker-page-idx">${HEX[currentPage]}</span>
            <span class="tracker-page-total">${currentPage + 1}/${pages.length}</span>
            <button class="tracker-page-btn"
                disabled=${currentPage >= pages.length - 1}
                onclick=${() => setCurrentPage(currentPage + 1)}>›</button>

            <button class="tracker-page-btn"
                disabled=${pages.length >= maxPages}
                onclick=${addPage}>+ Add</button>
            <button class="tracker-page-btn"
                disabled=${pages.length <= 1}
                onclick=${delPage}>− Del</button>
            <button class="tracker-page-btn" onclick=${copyPage}>Copy</button>
            <button class="tracker-page-btn" onclick=${pastePage}>Paste</button>

            <span class="tracker-header-label" style="margin-left:18px">Show</span>
            ${[2, 4, 8].map((n) => html`<button
                class="tracker-page-btn ${showTracks === n ? 'active' : ''}"
                onclick=${() => onChange('show_tracks', String(n))}>${n}</button>`)}
        </div>
    </div>`;

    // ---- Track-header row (above the steps) ----
    const trackHeader = html`<div class="tracker-track-header">
        <span class="tracker-track-step-col"></span>
        ${range(viewport.start, viewport.end).map((t) => html`<span
            class="tracker-track-label ${t === cursorTrack ? 'cursor' : ''}">T${t + 1}</span>`)}
    </div>`;

    // ---- Step rows ----
    const stepRows = html`<div class="tracker-rows">
        ${range(0, maxRows).map((rowIdx) => {
            const row = rows[rowIdx] || emptyRow(trackCount);
            const isCursorRow = rowIdx === cursorRow;
            return html`<div class="tracker-row ${isCursorRow ? 'cursor' : ''}">
                <span class="tracker-row-num">${HEX[rowIdx]}</span>
                ${range(viewport.start, viewport.end).map((t) => {
                    const v = row.voices[t];
                    const focused = isCursorRow && t === cursorTrack;
                    return html`<span
                        class="tracker-cell ${focused ? 'focused' : ''}"
                        onclick=${() => focusCell(rowIdx, t)}>${fmtVoice(v)}</span>`;
                })}
            </div>`;
        })}
    </div>`;

    // ---- Help row (static for now; live-value updates in keypad commit) ----
    const helpRow = html`<div class="tracker-help">${HELP_STATIC}</div>`;

    // ---- Cursor arrows (placeholder until full keypad lands) ----
    const cursor = html`<div class="tracker-cursor-cluster">
        <button class="tracker-arrow" onclick=${() => moveCursor(-1, 0)}>↑</button>
        <div class="tracker-arrow-bottom-row">
            <button class="tracker-arrow" onclick=${() => moveCursor(0, -1)}>←</button>
            <button class="tracker-arrow" onclick=${() => moveCursor(1, 0)}>↓</button>
            <button class="tracker-arrow" onclick=${() => moveCursor(0, 1)}>→</button>
        </div>
    </div>`;

    return html`<div class="trackergrid">
        ${header}
        <div class="tracker-grid-area">
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
