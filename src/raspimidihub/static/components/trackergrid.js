/**
 * TrackerGrid — placeholder render.
 *
 * The full UI (16-row × N-voice grid, page header, always-visible
 * data-entry keypad with Note/Octave/Vel/CC#/CC-Val controls and
 * inverted-T cursor) lands in a follow-up commit. This stub just
 * shows enough state so that creating a Tracker plugin instance and
 * navigating to /play renders something real instead of "Unknown
 * param trackergrid".
 *
 * Reads the sibling-param data via `param.pages_param` etc and
 * shows a hex-numbered row dump plus the current cursor + keypad
 * coordinates so we can verify state plumbing end-to-end before
 * fleshing out the visual layer.
 */

import { html } from '../ui/common.js';

const HEX = '0123456789ABCDEF';

function fmtVoiceCell(v) {
    if (!v) return '... .. ....';
    const note = (v.note || '---').padEnd(3, ' ').slice(0, 3);
    const vel = typeof v.vel === 'number' ? v.vel.toString(16).toUpperCase().padStart(2, '0') : (v.vel || '--');
    const ccNum = typeof v.cc_num === 'number' ? v.cc_num.toString(16).toUpperCase().padStart(2, '0')
        : (v.cc_num === '.' ? '. ' : (v.cc_num || '--'));
    const ccVal = typeof v.cc_val === 'number' ? v.cc_val.toString(16).toUpperCase().padStart(2, '0') : (v.cc_val || '--');
    return `${note} ${vel} ${ccNum.replace(' ', '.')}${ccVal}`;
}

export function PluginTrackerGrid({ param, values }) {
    const pages = values[param.pages_param] || [];
    const currentPage = values[param.current_page_param] ?? 0;
    const cursorRow = values[param.cursor_row_param] ?? 0;
    const cursorTrack = values[param.cursor_track_param] ?? 0;
    const octave = values[param.octave_param] ?? 3;

    const page = pages[currentPage] || { rows: [] };
    const rows = page.rows || [];

    return html`<div class="trackergrid-stub" style="font-family:monospace;font-size:12px;padding:12px;color:var(--text)">
        <div style="margin-bottom:6px;color:var(--text-dim)">
            tracker · page ${currentPage + 1}/${pages.length} ·
            cursor R${HEX[cursorRow]} T${cursorTrack + 1} ·
            oct ${octave} ·
            tracks ${param.track_count}
        </div>
        <pre style="margin:0;line-height:1.35;white-space:pre">${rows.map((row, i) => {
            const cells = (row.voices || []).slice(0, param.track_count).map(fmtVoiceCell).join('  ');
            const cursor = i === cursorRow ? '>' : ' ';
            return `${cursor} ${HEX[i]}  ${cells}`;
        }).join('\n')}</pre>
        <div style="margin-top:12px;color:var(--text-dim);font-size:11px">
            Full Tracker UI (keypad, color highlight, page nav, auto-learn) coming in
            the next commit.
        </div>
    </div>`;
}
