/**
 * CartesianGrid plugin control — a 2D step grid.
 *
 * Value is a flat row-major array of {on, accent, offset}, fixed
 * `cols`-wide (16 cells). The rendered/played sub-grid is side×side
 * where `side` comes from the sibling size param. Cell at grid (x,y)
 * lives at flat index y*cols + x, so shrinking the grid keeps the
 * top-left cells. A sibling playhead param (flat index) highlights the
 * cell currently under the X-clock.
 */

import { html, tickFeedback } from './common.js';
import { MiniWheel } from './stepeditor.js';

export function PluginCartesianGrid({ name, label, value, onChange, cols,
                                      sizeParam, sizes, playheadParam,
                                      defaultOn, allValues }) {
    const width = cols || 4;
    const sizeList = Array.isArray(sizes) && sizes.length ? sizes : [2, 3, 4];
    const sizeIdx = (sizeParam && allValues && allValues[sizeParam] != null)
        ? parseInt(allValues[sizeParam]) : sizeList.length - 1;
    const side = sizeList[Math.max(0, Math.min(sizeList.length - 1, sizeIdx))] || width;
    const playhead = (playheadParam && allValues && allValues[playheadParam] != null)
        ? parseInt(allValues[playheadParam]) : -1;

    const cells = value || [];
    const emptyCell = () => ({ on: !!defaultOn, offset: 0 });

    const writeCell = (idx, mut) => {
        const next = [];
        for (let i = 0; i < width * width; i++) next.push(cells[i] || emptyCell());
        next[idx] = mut({ ...next[idx] });
        onChange(name, next);
    };

    const toggleCell = (idx) => {
        tickFeedback();
        writeCell(idx, (s) => {
            // Plain cycle: off → on → accent → off
            if (!s.on) { s.on = true; s.accent = false; }
            else if (!s.accent) { s.accent = true; }
            else { s.on = false; s.accent = false; }
            return s;
        });
    };

    const setOffset = (idx, offset) =>
        writeCell(idx, (s) => { s.offset = Math.max(-24, Math.min(24, offset)); return s; });

    const cellClass = (cell, idx) => {
        const on = cell.on ? (cell.accent ? 'on accent' : 'on') : '';
        const playing = idx === playhead ? ' playing' : '';
        return `${on}${playing}`;
    };

    // Build rows top-to-bottom so the visual grid matches (x = column,
    // y = row), reading offsets from flat index y*width + x.
    const rows = [];
    for (let y = 0; y < side; y++) {
        const row = [];
        for (let x = 0; x < side; x++) {
            const idx = y * width + x;
            const cell = cells[idx] || emptyCell();
            row.push(html`
                <div class="step-cell ${cellClass(cell, idx)}" key=${idx}>
                    <div class="step-head" onclick=${() => toggleCell(idx)}></div>
                    <${MiniWheel} value=${cell.offset || 0}
                        onChange=${(v) => { tickFeedback(); setOffset(idx, v); }} />
                </div>`);
        }
        rows.push(row);
    }

    return html`<div class="step-editor">
        <div style="font-size:13px;color:var(--text-dim);margin-bottom:8px">${label}</div>
        <div class="cartesian-grid"
             style="grid-template-columns: repeat(${side}, 1fr)">
            ${rows}
        </div>
    </div>`;
}
