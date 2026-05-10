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

// The voice cell renders as two halves so the cursor highlight can
// fall on just the note slice (note + vel) or just the cc slice
// (cc-num + cc-val). The two strings live in adjacent inline spans.
function fmtVoiceNote(v) {
    if (!v) return `${HOLD} ${CC_HOLD}`;
    const vel = typeof v.vel === 'number' ? fmt2hex(v.vel) : CC_HOLD;
    return `${fmtNote(v.note)} ${vel}`;
}
function fmtVoiceCc(v) {
    if (!v) return `${CC_HOLD}${CC_HOLD}`;
    const ccVal = typeof v.cc_val === 'number' ? fmt2hex(v.cc_val) : CC_HOLD;
    return `${fmtCcNum(v.cc_num)}${ccVal}`;
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
// adjacent Octave wheel (composeNote).
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
// Sub-cell math: each voice is two sub-cells (note half, cc half).
// sub_index = voice * 2 + (0 for note, 1 for cc). 8 voices = 16 subs.
// ------------------------------------------------------------------

function subOf(track, half) { return track * 2 + (half === 'cc' ? 1 : 0); }
function trackOfSub(sub) { return Math.floor(sub / 2); }
function halfOfSub(sub) { return sub % 2 === 0 ? 'note' : 'cc'; }

// Selection rectangle = anchor → cursor (both on the same page).
// Returns null when there's no anchor or anchor is on a different
// page from the visible one — the rectangle is per-page.
function makeSelectionRect(anchor, currentPage, cursorRow, cursorSub) {
    if (!anchor || anchor.page !== currentPage) return null;
    return {
        minRow: Math.min(anchor.row, cursorRow),
        maxRow: Math.max(anchor.row, cursorRow),
        minSub: Math.min(anchor.sub, cursorSub),
        maxSub: Math.max(anchor.sub, cursorSub),
    };
}

function rectIsSingleCell(r) {
    return r && r.minRow === r.maxRow && r.minSub === r.maxSub;
}

function rectArea(r) {
    return r ? (r.maxRow - r.minRow + 1) * (r.maxSub - r.minSub + 1) : 0;
}

function isInRect(rect, row, sub) {
    return rect && row >= rect.minRow && row <= rect.maxRow
        && sub >= rect.minSub && sub <= rect.maxSub;
}

// ------------------------------------------------------------------
// Area capture / clear / paste — operate on a Page object.
// ------------------------------------------------------------------

function captureArea(page, rect, trackCount) {
    const cells = [];
    for (let r = rect.minRow; r <= rect.maxRow; r++) {
        const row = (page.rows || [])[r] || emptyRow(trackCount);
        for (let s = rect.minSub; s <= rect.maxSub; s++) {
            const t = trackOfSub(s);
            const h = halfOfSub(s);
            const v = (row.voices || [])[t] || emptyVoice();
            const dr = r - rect.minRow;
            const ds = s - rect.minSub;
            if (h === 'note') {
                cells.push({ dr, ds, half: 'note', note: v.note, vel: v.vel });
            } else {
                cells.push({ dr, ds, half: 'cc', cc_num: v.cc_num, cc_val: v.cc_val });
            }
        }
    }
    return {
        type: 'area',
        height: rect.maxRow - rect.minRow + 1,
        width: rect.maxSub - rect.minSub + 1,
        firstHalf: halfOfSub(rect.minSub),
        cells,
    };
}

function clearAreaInPage(page, rect, trackCount) {
    const newRows = (page.rows || []).slice();
    for (let r = rect.minRow; r <= rect.maxRow; r++) {
        const row = newRows[r] || emptyRow(trackCount);
        const voices = (row.voices || []).slice();
        for (let s = rect.minSub; s <= rect.maxSub; s++) {
            const t = trackOfSub(s);
            const h = halfOfSub(s);
            const v = { ...(voices[t] || emptyVoice()) };
            if (h === 'note') {
                v.note = HOLD;
                v.vel = CC_HOLD;
            } else {
                v.cc_num = CC_NONE;
                v.cc_val = CC_HOLD;
            }
            voices[t] = v;
        }
        newRows[r] = { ...row, voices };
    }
    return { ...page, rows: newRows };
}

function pasteAreaIntoPage(page, clip, atRow, atSub, trackCount, maxRows) {
    const newRows = (page.rows || []).slice();
    for (const cell of clip.cells) {
        const tr = atRow + cell.dr;
        const ts = atSub + cell.ds;
        if (tr < 0 || tr >= maxRows) continue;
        const t = trackOfSub(ts);
        if (t < 0 || t >= trackCount) continue;
        const row = newRows[tr] || emptyRow(trackCount);
        const voices = (row.voices || []).slice();
        const voice = { ...(voices[t] || emptyVoice()) };
        if (cell.half === 'note') {
            voice.note = cell.note;
            voice.vel = cell.vel;
        } else {
            voice.cc_num = cell.cc_num;
            voice.cc_val = cell.cc_val;
        }
        voices[t] = voice;
        newRows[tr] = { ...row, voices };
    }
    return { ...page, rows: newRows };
}

// ------------------------------------------------------------------
// Note-typing keyboard map — q..u for white keys, 2/3/5/6/7 for the
// black keys above them.  We listen to `event.code` (physical key
// position, layout-agnostic) so QWERTY *and* QWERTZ both work
// without a settings switch — pressing the physical key labelled "Y"
// on QWERTY / "Z" on QWERTZ produces event.code = 'KeyY' on both.
// ------------------------------------------------------------------

const NOTE_KEY_MAP = {
    KeyQ: 'C',  Digit2: 'C#',
    KeyW: 'D',  Digit3: 'D#',
    KeyE: 'E',
    KeyR: 'F',  Digit5: 'F#',
    KeyT: 'G',  Digit6: 'G#',
    KeyY: 'A',  Digit7: 'A#',
    KeyU: 'B',
};

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
    // Playhead — broadcast by the engine on every step. `playing`
    // false = no row gets a ▶; otherwise only the row whose page
    // matches the visible page gets it (no auto-jump). Defensive
    // shape coercion in case the SSE payload arrives malformed.
    const ph = values[param.playhead_param];
    const playhead = (ph && typeof ph === 'object') ? ph : null;
    const playheadOnView = playhead && playhead.playing && playhead.page === currentPage;
    // cursor_half: which slice of the focused voice the keypad is
    // editing — "note" (Note + Octave + Vel) or "cc" (CC# + CC Val).
    // The two halves swap in place; the cursor cluster stays pinned
    // right so the layout never jumps.
    const cursorHalf = values[param.cursor_half_param] === 'cc' ? 'cc' : 'note';
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
    const cursorHalfRef = useRef(cursorHalf);
    const currentPageRef = useRef(currentPage);
    cursorRowRef.current = cursorRow;
    cursorTrackRef.current = cursorTrack;
    cursorHalfRef.current = cursorHalf;
    currentPageRef.current = currentPage;

    // ---- Selection: anchor + shift-engaged state. ----
    // Anchor = (row, sub, page) where the user first pressed Shift.
    // Selection rectangle is computed every render from anchor +
    // current cursor. shiftEngaged is true whenever the on-screen
    // Shift button OR keyboard Shift key is held.
    const [anchor, setAnchor] = useState(null);
    const anchorRef = useRef(null);
    anchorRef.current = anchor;

    const [keyboardShift, setKeyboardShift] = useState(false);
    const [buttonShift, setButtonShift] = useState(false);
    const shiftEngaged = keyboardShift || buttonShift;
    const shiftEngagedRef = useRef(false);
    shiftEngagedRef.current = shiftEngaged;

    const cursorSub = subOf(cursorTrack, cursorHalf);
    const selectionRect = makeSelectionRect(anchor, currentPage, cursorRow, cursorSub);

    // First Shift engage captures the anchor at the current cursor.
    // Subsequent moves with shift held just extend; releasing Shift
    // freezes the rectangle (anchor stays). Cursor moves WITHOUT
    // shift clear the anchor (handled in the move wrapper below).
    const engageShift = useCallback(() => {
        if (anchorRef.current) return;
        const sub = subOf(cursorTrackRef.current, cursorHalfRef.current);
        const next = {
            row: cursorRowRef.current,
            sub,
            page: currentPageRef.current,
        };
        anchorRef.current = next;
        setAnchor(next);
    }, []);

    const clearAnchor = useCallback(() => {
        if (!anchorRef.current) return;
        anchorRef.current = null;
        setAnchor(null);
    }, []);

    // Wraps a cursor-move action with selection extension /
    // clearing. Pass `extending=true` (shift held) to keep the
    // anchor in place; `false` to clear it before the move.
    const cursorMove = useCallback((action, extending) => {
        if (extending) {
            engageShift();
        } else if (anchorRef.current) {
            clearAnchor();
        }
        action();
    }, [engageShift, clearAnchor]);

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

    // ←/→ now navigates *columns* — each voice is two sub-cells
    // (note half, cc half). Right from note → cc on the same voice;
    // right from cc → note on the next voice (wrapping T8 → T1).
    // Left mirrors. Lets the keypad halves rotate in / out without
    // doubling the cursor's job.
    const moveColumn = useCallback((d) => {
        const v = cursorTrackRef.current;
        const h = cursorHalfRef.current;
        if (d > 0) {
            if (h === 'note') {
                onChange(param.cursor_half_param, 'cc');
            } else {
                const nextV = (v + 1) % trackCount;
                onChange(param.cursor_track_param, nextV);
                onChange(param.cursor_half_param, 'note');
            }
        } else if (d < 0) {
            if (h === 'cc') {
                onChange(param.cursor_half_param, 'note');
            } else {
                const nextV = (v - 1 + trackCount) % trackCount;
                onChange(param.cursor_track_param, nextV);
                onChange(param.cursor_half_param, 'cc');
            }
        }
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

    // Tap a half directly to focus that half. With Shift held, the
    // tap extends the selection from the anchor to the tapped
    // sub-cell instead of clearing.
    const focusCell = useCallback((row, track, half = 'note', extending = false) => {
        if (extending) {
            engageShift();
        } else if (anchorRef.current) {
            clearAnchor();
        }
        if (row !== cursorRow) onChange(param.cursor_row_param, row);
        if (track !== cursorTrack) onChange(param.cursor_track_param, track);
        if (cursorHalf !== half) onChange(param.cursor_half_param, half);
    }, [cursorRow, cursorTrack, cursorHalf, onChange, param, engageShift, clearAnchor]);

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
    // Always-recording semantics: every wheel/knob change writes
    // straight to the focused voice cell. When the cell shows a hold
    // sentinel ('--' or '.'), the keypad still needs a numeric to
    // display, so we keep last-touched values in refs that stick
    // across cells. As soon as the user moves the control, the cell
    // gets the new value.
    const focusedRow = rows[cursorRow] || emptyRow(trackCount);
    const focusedCell = focusedRow.voices[cursorTrack] || emptyVoice();
    // OCT wheel: prefer the octave of the focused cell's note when
    // the cell holds a real pitch — that way the wheel always
    // mirrors what's in the cell. The sticky param only kicks in
    // for cells with sentinels (---/Off/End) so the next note
    // entered remembers the user's last-touched octave.
    const stickyOctave = clamp(values[param.octave_param] ?? 3, 0, 9);
    const focusedOctave = getOctavePart(focusedCell.note);
    const octave = focusedOctave != null ? focusedOctave : stickyOctave;

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
    // Note + Vel travel together — picking a real pitch also writes
    // the current sticky velocity so the cell isn't left with `--`
    // (which would silently override the playback default at the
    // engine). Picking a sentinel (---/Off/End) clears velocity to
    // `--` so the cell shape matches the meaning.
    const onNoteWheel = useCallback((_, idx) => {
        if (idx === 0) {
            setVoiceFields({ note: HOLD, vel: CC_HOLD });
            showHelp(`Note  ${HOLD}`);
        } else if (idx === 1) {
            setVoiceFields({ note: 'End', vel: CC_HOLD });
            showHelp('Note  End');
        } else if (idx === 2) {
            setVoiceFields({ note: 'Off', vel: CC_HOLD });
            showHelp('Note  Off');
        } else {
            const note = composeNote(NOTE_WHEEL_PITCHES[idx - 3], octave);
            const vel = typeof focusedCell.vel === 'number'
                ? focusedCell.vel : stickyVelRef.current;
            setVoiceFields({ note, vel });
            showHelp(`Note  ${note}`);
        }
    }, [octave, focusedCell.vel, setVoiceFields, showHelp]);

    const onOctave = useCallback((_, oct) => {
        onChange(param.octave_param, oct);
        showHelp(`Octave  ${oct}`);
        // If the focused cell currently holds a real pitch, rewrite
        // its octave digit so what you see in the cell matches the
        // wheel. Sentinels (---/End/Off) stay as-is — the wheel just
        // sticks for next entry. Vel goes along with the rewrite so
        // the cell never carries a real pitch with `--` velocity.
        const pitch = getPitchPart(focusedCell.note);
        if (pitch) {
            const vel = typeof focusedCell.vel === 'number'
                ? focusedCell.vel : stickyVelRef.current;
            setVoiceFields({ note: composeNote(pitch, oct), vel });
        }
    }, [focusedCell.note, focusedCell.vel, onChange, param, setVoiceFields, showHelp]);

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

    // ---- Unified Del / Copy / Paste action handlers ----
    // All three are selection-aware. With a selection rectangle:
    //   Del   → clear every sub-cell in the rectangle
    //   Copy  → capture the rectangle to a session-local clipboard
    //   Paste → place the rectangle's top-left at the cursor sub-cell,
    //           rejecting the paste if the cursor's half doesn't match
    //           the clipboard's first-cell half.
    // Without a selection:
    //   Del   → clear just the focused sub-cell (note half clears
    //           note + vel; cc half clears cc_num + cc_val).
    //   Copy  → grab the whole current page.
    //   Paste → page-clipboard replaces the current page; area-
    //           clipboard pastes at the cursor (with half-match check).

    const onDel = useCallback(() => {
        const rect = makeSelectionRect(anchorRef.current, currentPageRef.current,
                                       cursorRowRef.current,
                                       subOf(cursorTrackRef.current, cursorHalfRef.current));
        if (rect && !rectIsSingleCell(rect)) {
            const newPages = pages.slice();
            newPages[currentPage] = clearAreaInPage(
                pages[currentPage] || emptyPage(trackCount, maxRows),
                rect, trackCount,
            );
            onChange(param.pages_param, newPages);
            showHelp(`Cleared selection (${rect.maxRow - rect.minRow + 1} × ${rect.maxSub - rect.minSub + 1})`);
        } else {
            const half = cursorHalfRef.current;
            if (half === 'note') {
                setVoiceFields({ note: HOLD, vel: CC_HOLD });
                showHelp('Cleared Note + Vel');
            } else {
                setVoiceFields({ cc_num: CC_NONE, cc_val: CC_HOLD });
                showHelp('Cleared CC# + CC Val');
            }
        }
    }, [pages, currentPage, trackCount, maxRows, onChange, param, setVoiceFields, showHelp]);

    const onCopy = useCallback(() => {
        const rect = makeSelectionRect(anchorRef.current, currentPageRef.current,
                                       cursorRowRef.current,
                                       subOf(cursorTrackRef.current, cursorHalfRef.current));
        if (rect && !rectIsSingleCell(rect)) {
            const buffer = captureArea(
                pages[currentPage] || emptyPage(trackCount, maxRows),
                rect, trackCount,
            );
            window.__trackerClipboard = buffer;
            showHelp(`Copied selection (${rect.maxRow - rect.minRow + 1} × ${rect.maxSub - rect.minSub + 1})`);
        } else {
            window.__trackerClipboard = {
                type: 'page',
                page: clonePage(pages[currentPage] || emptyPage(trackCount, maxRows)),
            };
            showHelp('Copied page');
        }
    }, [pages, currentPage, trackCount, maxRows, showHelp]);

    const onPaste = useCallback(() => {
        const clip = window.__trackerClipboard;
        if (!clip) {
            showHelp('Clipboard empty');
            return;
        }
        if (clip.type === 'page') {
            const next = pages.slice();
            next[currentPage] = clonePage(clip.page);
            onChange(param.pages_param, next);
            showHelp('Pasted page');
            return;
        }
        // Area clip — half-compatibility check before walking cells.
        const at = subOf(cursorTrackRef.current, cursorHalfRef.current);
        const cursorHalfNow = halfOfSub(at);
        if (clip.firstHalf !== cursorHalfNow) {
            showHelp(`Can't paste — clipboard starts on ${clip.firstHalf} column`);
            return;
        }
        const newPages = pages.slice();
        newPages[currentPage] = pasteAreaIntoPage(
            pages[currentPage] || emptyPage(trackCount, maxRows),
            clip, cursorRowRef.current, at,
            trackCount, maxRows,
        );
        onChange(param.pages_param, newPages);
        showHelp(`Pasted selection (${clip.height} × ${clip.width})`);
    }, [pages, currentPage, trackCount, maxRows, onChange, param, showHelp]);

    // Typed note from the keyboard — same write semantics as turning
    // the Note wheel + the chord auto-advance from MIDI input. One
    // key press = one note + sticky velocity + cursor advances.
    const writeTypedNote = useCallback((pitch) => {
        const note = composeNote(pitch, octave);
        const vel = typeof focusedCell.vel === 'number'
            ? focusedCell.vel : stickyVelRef.current;
        setVoiceFields({ note, vel });
        // Auto-advance one row, with page-boundary wrap.
        const cr = cursorRowRef.current;
        const cp = currentPageRef.current;
        let nextRow = cr + 1;
        let nextPage = cp;
        if (nextRow >= maxRows) {
            nextRow = 0;
            nextPage = (cp + 1) % pageCount;
        }
        if (nextRow !== cr) onChange(param.cursor_row_param, nextRow);
        if (nextPage !== cp) onChange(param.current_page_param, nextPage);
        showHelp(`Note  ${note}`);
    }, [octave, focusedCell.vel, setVoiceFields, maxRows, pageCount, onChange, param, showHelp]);

    // ---- Keyboard support (window-level). ----
    // Active only while this component is mounted. Skips when an
    // input/select/textarea has focus so the rate dropdown still
    // works as expected. Note-typing keys use event.code (physical
    // position) so QWERTY and QWERTZ both work without a settings
    // toggle — both layouts share the same physical positions for
    // q/w/e/r/t/u and 2/3/5/6/7; only the y/z key is labelled
    // differently and event.code = 'KeyY' for both.
    useEffect(() => {
        const onKeyDown = (e) => {
            const tag = (e.target && e.target.tagName) || '';
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

            // Shift modifier: track key state so the on-screen Shift
            // and the keyboard Shift compose (either source can hold
            // selection mode).
            if (e.key === 'Shift') {
                setKeyboardShift(true);
                engageShift();
                return;
            }

            // Cursor + page navigation, with shift-extends-selection.
            switch (e.key) {
                case 'ArrowUp':    cursorMove(() => moveRow(-1), e.shiftKey); e.preventDefault(); return;
                case 'ArrowDown':  cursorMove(() => moveRow(+1), e.shiftKey); e.preventDefault(); return;
                case 'ArrowLeft':  cursorMove(() => moveColumn(-1), e.shiftKey); e.preventDefault(); return;
                case 'ArrowRight': cursorMove(() => moveColumn(+1), e.shiftKey); e.preventDefault(); return;
                case 'PageUp':     cursorMove(() => movePage(-1), e.shiftKey); e.preventDefault(); return;
                case 'PageDown':   cursorMove(() => movePage(+1), e.shiftKey); e.preventDefault(); return;
                case 'Delete':
                case 'Backspace':  onDel(); e.preventDefault(); return;
            }

            // Ctrl/Cmd + C / V — clipboard ops.
            if (e.ctrlKey || e.metaKey) {
                if (e.code === 'KeyC') { onCopy(); e.preventDefault(); return; }
                if (e.code === 'KeyV') { onPaste(); e.preventDefault(); return; }
                return;
            }

            // Note-typing keys (no modifier).
            const pitch = NOTE_KEY_MAP[e.code];
            if (pitch) {
                writeTypedNote(pitch);
                e.preventDefault();
            }
        };
        const onKeyUp = (e) => {
            if (e.key === 'Shift') setKeyboardShift(false);
        };
        window.addEventListener('keydown', onKeyDown);
        window.addEventListener('keyup', onKeyUp);
        return () => {
            window.removeEventListener('keydown', onKeyDown);
            window.removeEventListener('keyup', onKeyUp);
        };
    }, [moveRow, moveColumn, movePage, cursorMove, engageShift,
        onDel, onCopy, onPaste, writeTypedNote]);

    // Tick label for the Note wheel — sentinels then 12 pitches with
    // the current Octave wheel value baked in so each detent shows
    // what it will commit ("F#3", not "F#").
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
        const focused = grid.querySelector('.tracker-cell.focus-note, .tracker-cell.focus-cc');
        if (focused && focused.scrollIntoView) {
            focused.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        }
    }, [cursorRow, cursorTrack, cursorHalf, currentPage]);

    // ---- Header (Rate + Play/Stop + page actions) ----
    // Play / Stop write trigger-style booleans to cmd_play / cmd_stop;
    // the plugin's on_param_change fires the local transport handler
    // and resets the flag back to False. Lets the user start the
    // tracker without an external clock+Start signal.
    const isPlaying = !!(playhead && playhead.playing);
    const onPlay = () => onChange(param.cmd_play_param, true);
    const onStop = () => onChange(param.cmd_stop_param, true);
    const header = html`<div class="tracker-header">
        <div class="tracker-header-row">
            <span class="tracker-header-label">Rate</span>
            <select class="tracker-rate-select"
                value=${rate}
                onchange=${(e) => onChange(param.rate_param, e.target.value)}>
                ${RATE_OPTIONS.map((r) => html`<option value=${r}>${r}</option>`)}
            </select>

            <button class="tracker-page-btn tracker-transport-btn ${isPlaying ? 'active' : ''}"
                title="Play (transport start)" onclick=${onPlay}>▶ Play</button>
            <button class="tracker-page-btn tracker-transport-btn"
                title="Stop (transport stop)" onclick=${onStop}>■ Stop</button>

            <button class="tracker-page-btn"
                disabled=${pages.length >= maxPages}
                onclick=${addPage}>+ Add</button>
            <button class="tracker-page-btn"
                disabled=${pages.length <= 1}
                onclick=${delPage}>− Del</button>
        </div>
    </div>`;

    // ---- Track-header row (above the steps) ----
    // The empty step-col reserves the row-num + playhead gutter so
    // T1..Tn align with the data columns below. Each track's label
    // also shows its configured output channel — defaults to 1, set
    // per-track in the device-detail config panel.
    const trackHeader = html`<div class="tracker-track-header">
        <span class="tracker-row-playhead"></span>
        <span class="tracker-track-step-col"></span>
        ${range(0, trackCount).map((t) => {
            const ch = clamp(values[`track_ch_${t}`] ?? 1, 1, 16);
            return html`<span
                class="tracker-track-label ${t === cursorTrack ? 'cursor' : ''}">T${t + 1}<span class="tracker-track-ch">[Ch ${ch}]</span></span>`;
        })}
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
            const isPlayhead = playheadOnView && playhead.row === rowIdx;
            return html`<div class="tracker-row ${isCursorRow ? 'cursor' : ''} ${isPlayhead ? 'playing' : ''}">
                <span class="tracker-row-playhead">${isPlayhead ? '▶' : ''}</span>
                <span class="tracker-row-num ${isBeat ? 'beat' : ''}">${pagePrefix}${HEX[rowIdx]}</span>
                ${range(0, trackCount).map((t) => {
                    const v = row.voices[t];
                    const focused = isCursorRow && t === cursorTrack;
                    const cls = focused
                        ? (cursorHalf === 'cc' ? 'focus-cc' : 'focus-note')
                        : '';
                    const noteSel = isInRect(selectionRect, rowIdx, subOf(t, 'note'));
                    const ccSel = isInRect(selectionRect, rowIdx, subOf(t, 'cc'));
                    return html`<span class="tracker-cell ${cls}">
                        <span class="tracker-cell-note ${noteSel ? 'sel' : ''}"
                            onclick=${(ev) => focusCell(rowIdx, t, 'note',
                                ev.shiftKey || shiftEngagedRef.current)}>${fmtVoiceNote(v)}</span>
                        <span class="tracker-cell-cc ${ccSel ? 'sel' : ''}"
                            onclick=${(ev) => focusCell(rowIdx, t, 'cc',
                                ev.shiftKey || shiftEngagedRef.current)}>${fmtVoiceCc(v)}</span>
                    </span>`;
                })}
            </div>`;
        })}
    </div>`;

    // ---- Help row ----
    const helpRow = html`<div class="tracker-help">${liveHelp ? `Help: ${liveHelp}` : HELP_STATIC}</div>`;

    // ---- Cursor cluster: PgUp / ↑ / PgDn on top, ← / ↓ / → on bottom ----
    // Each button uses pointer events so press-and-hold repeats while
    // the touch is held; click-only (mouse) still works because pointer
    // events fire for the mouse too. Each repeated action call wraps
    // in cursorMove(action, shiftEngagedRef.current) so the on-screen
    // Shift button (or held keyboard Shift) extends the selection
    // live as the cursor walks.
    const arrow = (action, label, title, extraClass = '') => html`<button
        class="tracker-arrow ${extraClass}"
        title=${title}
        oncontextmenu=${(e) => e.preventDefault()}
        onpointerdown=${(e) => {
            e.preventDefault();
            startRepeat(() => cursorMove(action, shiftEngagedRef.current));
        }}
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
            ${arrow(() => moveColumn(-1), '←', 'Left (←)')}
            ${arrow(() => moveRow(+1), '↓', 'Down (↓)')}
            ${arrow(() => moveColumn(+1), '→', 'Right (→)')}
        </div>
    </div>`;

    // ---- Action row (left side of each keypad half): ----
    // Del / Shift / Copy / Paste — generic across both halves. Shift
    // is press-and-hold (pointerdown engages, pointerup disengages);
    // Del/Copy/Paste are taps. The whole row sits below the controls
    // and aligns its bottom with the cursor cluster's ←↓→ row.
    const actionBtn = (label, onClick, title, extraClass = '') => html`<button
        class="tracker-keypad-action-btn ${extraClass}"
        title=${title}
        oncontextmenu=${(e) => e.preventDefault()}
        onclick=${onClick}>${label}</button>`;
    const shiftBtn = html`<button
        class="tracker-keypad-action-btn ${buttonShift ? 'active' : ''}"
        title="Hold to extend selection (or hold keyboard Shift)"
        oncontextmenu=${(e) => e.preventDefault()}
        onpointerdown=${(e) => {
            e.preventDefault();
            setButtonShift(true);
            engageShift();
        }}
        onpointerup=${() => setButtonShift(false)}
        onpointerleave=${() => setButtonShift(false)}
        onpointercancel=${() => setButtonShift(false)}>Shift</button>`;
    const actionRow = html`<div class="tracker-keypad-actions">
        ${actionBtn('Del', onDel, 'Clear focused cell or selection')}
        ${shiftBtn}
        ${actionBtn('Copy', onCopy, 'Copy selection or page')}
        ${actionBtn('Paste', onPaste, 'Paste at cursor')}
    </div>`;

    // ---- Keypad: split between two halves of the focused voice. ----
    // Each half is a vertical stack: controls (top) + action row
    // (bottom). The bottom action row is generic (Del/Shift/Copy/
    // Paste) and replaces the per-wheel Del that used to live under
    // each wheel. The cursor cluster is pinned right via
    // margin-left:auto and aligns its top + bottom rows to the
    // half's top + bottom areas.
    const noteHalfControls = html`<div class="tracker-keypad-controls">
        <div class="tracker-keypad-col">
            <div class="tracker-keypad-label">NOTE</div>
            <${PluginWheel} name="note_wheel" label="" min=${0} max=${14}
                value=${noteWheelIdx}
                onChange=${onNoteWheel} tickLabel=${noteTickLabel} />
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
    </div>`;

    const ccHalfControls = html`<div class="tracker-keypad-controls">
        <div class="tracker-keypad-col">
            <div class="tracker-keypad-label">CC#</div>
            <${PluginWheel} name="cc_num_wheel" label="" min=${-1} max=${127}
                value=${ccNumValue}
                onChange=${onCcNum} tickLabel=${ccNumTickLabel} />
        </div>
        <div class="tracker-keypad-col">
            <div class="tracker-keypad-label">CC VAL</div>
            <${PluginKnob} name="cc_val" label="" min=${0} max=${127}
                value=${ccValValue} labels=${HEX_LABELS_128}
                onChange=${onCcVal} />
        </div>
    </div>`;

    const keypad = html`<div class="tracker-keypad">
        <div class="tracker-keypad-half">
            ${cursorHalf === 'note' ? noteHalfControls : ccHalfControls}
            ${actionRow}
        </div>
        <div class="tracker-keypad-col tracker-keypad-cursor-col">
            <div class="tracker-keypad-label">${cursorHalf === 'note' ? 'CURSOR · NOTE' : 'CURSOR · CC'}</div>
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
