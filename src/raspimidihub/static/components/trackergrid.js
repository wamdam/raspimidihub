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
import { useCallback, useEffect, useRef, useState } from '../lib/hooks.module.js';
import { PluginWheel } from './wheel.js';
import { PluginKnob } from './knob.js';

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

// Note wheel — 15 positions. Sentinels at the start so they're a
// thumb-flick away from "no entry"; the 12 chromatic pitches follow
// at indices 3..14. The actual cell.note string is composed with the
// sticky octave knob (composeNote).
const NOTE_WHEEL_LABELS = ['---', 'End', 'Off',
    'C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const NOTE_WHEEL_PITCHES = NOTE_WHEEL_LABELS.slice(3);
const NOTE_SENTINELS = new Set([HOLD, 'End', 'Off']);

function isRealPitch(note) {
    return typeof note === 'string' && note.length === 3
        && !NOTE_SENTINELS.has(note);
}

function getPitchPart(note) {
    if (!isRealPitch(note)) return null;
    if (note[1] === '-') return note[0];
    if (note[1] === '#') return note.slice(0, 2);
    return null;
}

function getOctavePart(note) {
    if (!isRealPitch(note)) return null;
    const oct = parseInt(note[2], 10);
    return Number.isFinite(oct) ? oct : null;
}

function composeNote(pitch, octave) {
    return pitch.length === 1 ? `${pitch}-${octave}` : `${pitch}${octave}`;
}

function noteToWheelIdx(note) {
    if (note === HOLD) return 0;
    if (note === 'End') return 1;
    if (note === 'Off') return 2;
    const pitch = getPitchPart(note);
    if (!pitch) return 0;
    const idx = NOTE_WHEEL_PITCHES.indexOf(pitch);
    return idx >= 0 ? idx + 3 : 0;
}

// 2-char hex labels 00..7F so the VEL / CC-VAL knobs match what
// the cell rows show. PluginKnob.labels[i - min] → display string.
const HEX_LABELS_128 = Array.from({ length: 128 },
    (_, i) => i.toString(16).toUpperCase().padStart(2, '0'));

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

    // ---- Help row (live-value while a control is touched). ----
    // Reverts to the static four-column key after 2 s of inactivity.
    const [liveHelp, setLiveHelp] = useState(null);
    const helpTimerRef = useRef(null);
    const showHelp = useCallback((text) => {
        setLiveHelp(text);
        if (helpTimerRef.current) clearTimeout(helpTimerRef.current);
        helpTimerRef.current = setTimeout(() => setLiveHelp(null), 2000);
    }, []);
    useEffect(() => () => {
        if (helpTimerRef.current) clearTimeout(helpTimerRef.current);
    }, []);

    // ---- Keypad: derived state + sticky-default refs. ----
    // Always-recording semantics: every wheel/fader change writes
    // straight to the focused voice cell. When the cell shows a hold
    // sentinel ('--' or '.'), the keypad still needs a numeric to
    // display, so we keep last-touched values in refs that stick
    // across cells. As soon as the user moves the control, the cell
    // gets the new value.
    const focusedRow = rows[cursorRow] || emptyRow(trackCount);
    const focusedCell = focusedRow.voices[cursorTrack] || emptyVoice();
    const octave = clamp(values[param.octave_param] ?? 3, 0, 9);

    const stickyVelRef = useRef(80);
    const stickyCcNumRef = useRef(1);
    const stickyCcValRef = useRef(64);
    if (typeof focusedCell.vel === 'number') stickyVelRef.current = focusedCell.vel;
    if (typeof focusedCell.cc_num === 'number') stickyCcNumRef.current = focusedCell.cc_num;
    if (typeof focusedCell.cc_val === 'number') stickyCcValRef.current = focusedCell.cc_val;

    const noteWheelIdx = noteToWheelIdx(focusedCell.note);
    const velValue = typeof focusedCell.vel === 'number'
        ? focusedCell.vel : stickyVelRef.current;
    const ccNumValue = focusedCell.cc_num === CC_NONE ? -1
        : (typeof focusedCell.cc_num === 'number'
            ? focusedCell.cc_num : stickyCcNumRef.current);
    const ccValValue = typeof focusedCell.cc_val === 'number'
        ? focusedCell.cc_val : stickyCcValRef.current;

    // Cell mutation — immutable update of pages → page → row → voice.
    const setVoiceFields = useCallback((updates) => {
        const r = rows[cursorRow] || emptyRow(trackCount);
        const v = r.voices[cursorTrack] || emptyVoice();
        const newVoices = r.voices.slice();
        newVoices[cursorTrack] = { ...v, ...updates };
        const newRows = rows.slice();
        newRows[cursorRow] = { ...r, voices: newVoices };
        const newPages = pages.slice();
        newPages[currentPage] = { ...page, rows: newRows };
        onChange(param.pages_param, newPages);
    }, [pages, page, rows, cursorRow, cursorTrack, currentPage, trackCount, onChange, param]);

    // ---- Keypad handlers ----
    const onNoteWheel = useCallback((_, idx) => {
        if (idx === 0) {
            setVoiceFields({ note: HOLD });
            showHelp(`Note  ${HOLD}`);
        } else if (idx === 1) {
            setVoiceFields({ note: 'End' });
            showHelp('Note  End');
        } else if (idx === 2) {
            setVoiceFields({ note: 'Off' });
            showHelp('Note  Off');
        } else {
            const note = composeNote(NOTE_WHEEL_PITCHES[idx - 3], octave);
            setVoiceFields({ note });
            showHelp(`Note  ${note}`);
        }
    }, [octave, setVoiceFields, showHelp]);

    const onOctave = useCallback((_, oct) => {
        onChange(param.octave_param, oct);
        showHelp(`Octave  ${oct}`);
        // If the focused cell currently holds a real pitch, rewrite
        // its octave digit so what you see in the cell matches the
        // knob. Sentinels (---/End/Off) stay as-is — the knob just
        // sticks for next entry.
        const pitch = getPitchPart(focusedCell.note);
        if (pitch) setVoiceFields({ note: composeNote(pitch, oct) });
    }, [focusedCell.note, onChange, param, setVoiceFields, showHelp]);

    const onVel = useCallback((_, v) => {
        setVoiceFields({ vel: v });
        showHelp(`Velocity  ${fmt2hex(v)} (${v})`);
    }, [setVoiceFields, showHelp]);

    const onCcNum = useCallback((_, v) => {
        if (v === -1) {
            setVoiceFields({ cc_num: CC_NONE });
            showHelp('CC#  .  (no event)');
        } else {
            setVoiceFields({ cc_num: v });
            showHelp(`CC#  ${fmt2hex(v)} (${v})`);
        }
    }, [setVoiceFields, showHelp]);

    const onCcVal = useCallback((_, v) => {
        setVoiceFields({ cc_val: v });
        showHelp(`CC Val  ${fmt2hex(v)} (${v})`);
    }, [setVoiceFields, showHelp]);

    const onDelNote = useCallback(() => {
        setVoiceFields({ note: HOLD, vel: CC_HOLD });
        showHelp('Cleared Note + Vel');
    }, [setVoiceFields, showHelp]);

    const onDelCc = useCallback(() => {
        setVoiceFields({ cc_num: CC_NONE, cc_val: CC_HOLD });
        showHelp('Cleared CC# + CC Val');
    }, [setVoiceFields, showHelp]);

    // Tick label for the Note wheel — pitches show with the current
    // sticky octave so you can read what each detent will commit.
    const noteTickLabel = useCallback((idx) => {
        if (idx <= 2) return NOTE_WHEEL_LABELS[idx];
        return composeNote(NOTE_WHEEL_PITCHES[idx - 3], octave);
    }, [octave]);

    // Tick label for the CC# wheel — `.` at -1, hex elsewhere.
    const ccNumTickLabel = useCallback((v) => v === -1 ? '.' : fmt2hex(v), []);

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

    // ---- Help row ----
    const helpRow = html`<div class="tracker-help">${liveHelp ? `Help: ${liveHelp}` : HELP_STATIC}</div>`;

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

    // ---- Keypad: Note + Octave + Vel + CC# + CC Val + cursor ----
    const keypad = html`<div class="tracker-keypad">
        <div class="tracker-keypad-col">
            <div class="tracker-keypad-label">NOTE</div>
            <${PluginWheel} name="note_wheel" label="" min=${0} max=${14}
                value=${noteWheelIdx}
                onChange=${onNoteWheel} tickLabel=${noteTickLabel} />
            <button class="tracker-keypad-del" onclick=${onDelNote}
                title="Clear Note + Velocity">Del</button>
        </div>
        <div class="tracker-keypad-col">
            <div class="tracker-keypad-label">OCT</div>
            <${PluginWheel} name="octave_wheel" label="" min=${0} max=${9}
                value=${octave} onChange=${onOctave} />
        </div>
        <div class="tracker-keypad-col">
            <div class="tracker-keypad-label">VEL</div>
            <${PluginKnob} name="vel" label="" min=${0} max=${127}
                value=${velValue} labels=${HEX_LABELS_128}
                onChange=${onVel} />
        </div>
        <div class="tracker-keypad-col">
            <div class="tracker-keypad-label">CC#</div>
            <${PluginWheel} name="cc_num_wheel" label="" min=${-1} max=${127}
                value=${ccNumValue}
                onChange=${onCcNum} tickLabel=${ccNumTickLabel} />
            <button class="tracker-keypad-del" onclick=${onDelCc}
                title="Clear CC# + CC Val">Del</button>
        </div>
        <div class="tracker-keypad-col">
            <div class="tracker-keypad-label">CC VAL</div>
            <${PluginKnob} name="cc_val" label="" min=${0} max=${127}
                value=${ccValValue} labels=${HEX_LABELS_128}
                onChange=${onCcVal} />
        </div>
        <div class="tracker-keypad-col tracker-keypad-cursor-col">
            <div class="tracker-keypad-label">CURSOR</div>
            ${cursor}
        </div>
    </div>`;

    return html`<div class="trackergrid">
        ${header}
        <div class="tracker-grid-area" ref=${gridRef}>
            ${trackHeader}
            ${stepRows}
        </div>
        ${helpRow}
        ${keypad}
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
