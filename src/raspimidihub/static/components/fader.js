/**
 * Fader plugin control.
 */

import { html, tickFeedback, thudFeedback, makeLongPress } from './common.js';
import { useState, useEffect, useRef } from '../lib/hooks.module.js';

// =======================================================================
// FADER — mixer-strip style
// =======================================================================
export function PluginFader({ name, label, min, max, value, onChange, vertical, suffix, displayFactor, displayFormat, onBindRequest }) {
    const trackRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    const onBindRef = useRef(onBindRequest);
    onBindRef.current = onBindRequest;
    const s = useRef({ val: value }).current;
    const [val, setVal] = useState(value);

    useEffect(() => { s.val = value; setVal(value); }, [value]);

    // Native event listeners for passive:false (multitouch compat)
    useEffect(() => {
        const el = trackRef.current;
        if (!el) return;

        const oc = onChangeRef;

        function calcValue(clientX, clientY) {
            const rect = el.getBoundingClientRect();
            let ratio = vertical
                ? 1 - (clientY - rect.top) / rect.height
                : (clientX - rect.left) / rect.width;
            ratio = Math.max(0, Math.min(1, ratio));
            return Math.round(min + ratio * (max - min));
        }

        function handleMove(clientX, clientY) {
            const nv = calcValue(clientX, clientY);
            if (nv !== s.val) { s.val = nv; setVal(nv); oc.current(name, nv); tickFeedback(); }
        }

        // Long-press on the fader opens the CC binding popup. The
        // touch-start already commits a value change (faders jump to
        // the touch point), so a long-press here will leave the
        // fader at the press position — acceptable; the popup is the
        // primary signal anyway.
        const lp = makeLongPress(() => {
            if (onBindRef.current) onBindRef.current(name);
        });

        let activeTouchId = null;
        function findTouch(e, id) {
            for (const t of e.touches) if (t.identifier === id) return t;
            return null;
        }
        function onTouchStart(e) {
            e.preventDefault(); e.stopPropagation();
            const t = e.changedTouches[0];
            activeTouchId = t.identifier;
            handleMove(t.clientX, t.clientY);
            lp.start(t.clientX, t.clientY);
            el.addEventListener('touchmove', onTouchMove, { passive: false });
            window.addEventListener('touchend', onTouchEnd);
            window.addEventListener('touchcancel', onTouchEnd);
        }
        function onTouchMove(e) {
            e.preventDefault(); e.stopPropagation();
            const t = findTouch(e, activeTouchId);
            if (!t) return;
            if (lp.moveDidFire(t.clientX, t.clientY)) return;
            handleMove(t.clientX, t.clientY);
        }
        function onTouchEnd(e) {
            if (e) e.stopPropagation();
            // Only release if our touch ended
            for (const t of e.changedTouches) {
                if (t.identifier === activeTouchId) {
                    activeTouchId = null;
                    lp.end();
                    el.removeEventListener('touchmove', onTouchMove);
                    window.removeEventListener('touchend', onTouchEnd);
                    window.removeEventListener('touchcancel', onTouchEnd);
                    break;
                }
            }
        }
        function onMouseDown(e) {
            if (e.button === 2) return;
            e.preventDefault(); handleMove(e.clientX, e.clientY);
            lp.start(e.clientX, e.clientY);
            const mm = (ev) => {
                if (lp.moveDidFire(ev.clientX, ev.clientY)) {
                    window.removeEventListener('mousemove', mm);
                    window.removeEventListener('mouseup', mu);
                    return;
                }
                handleMove(ev.clientX, ev.clientY);
            };
            const mu = () => {
                lp.end();
                window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu);
            };
            window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu);
        }
        function onContextMenu(e) {
            e.preventDefault();
            if (onBindRef.current) onBindRef.current(name);
        }

        el.addEventListener('touchstart', onTouchStart, { passive: false });
        el.addEventListener('mousedown', onMouseDown);
        el.addEventListener('contextmenu', onContextMenu);
        return () => {
            el.removeEventListener('touchstart', onTouchStart);
            el.removeEventListener('mousedown', onMouseDown);
            el.removeEventListener('contextmenu', onContextMenu);
        };
    }, [min, max, name, vertical]);

    const ratio = (val - min) / (max - min || 1);
    // Clamp thumb inside track (thumb: 40px horiz, 28px vert)
    const thumbStyle = vertical
        ? { bottom: `calc(3px + ${ratio} * (100% - 28px))` }
        : { left: `calc(2px + ${ratio} * (100% - 44px))` };
    // Vertical track has a 12px inset at top + bottom (the rounded ends),
    // so the fill must scale into the inner ~156px not the full 180px,
    // otherwise at ratio=1 it overshoots the top of the track.
    const fillStyle = vertical
        ? { height: `calc(${ratio} * (100% - 24px))` }
        : { width: `calc(22px + ${ratio} * (100% - 44px))` };

    return html`<div class="fader-group ${vertical ? 'vertical' : ''}">
        <span class="fader-label">${label}</span>
        <div class="fader-track ${vertical ? 'vertical' : ''}" ref=${trackRef}>
            <div class="fader-fill" style=${fillStyle}></div>
            <div class="fader-thumb" style=${thumbStyle}>
                <span class="fader-thumb-val">${displayFactor ? ((val * displayFactor) % 1 === 0 ? (val * displayFactor) : (val * displayFactor).toFixed(1)) + (displayFormat || '') : val + (suffix || '')}</span>
            </div>
        </div>
    </div>`;
}

