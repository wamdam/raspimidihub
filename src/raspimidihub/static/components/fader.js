/**
 * Fader plugin control.
 */

import { html, tickFeedback, thudFeedback } from './common.js';
import { useState, useEffect, useRef } from '../lib/hooks.module.js';

// =======================================================================
// FADER — mixer-strip style
// =======================================================================
export function PluginFader({ name, label, min, max, value, onChange, vertical, suffix, displayFactor, displayFormat }) {
    const trackRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
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
            el.addEventListener('touchmove', onTouchMove, { passive: false });
            window.addEventListener('touchend', onTouchEnd);
            window.addEventListener('touchcancel', onTouchEnd);
        }
        function onTouchMove(e) {
            e.preventDefault(); e.stopPropagation();
            const t = findTouch(e, activeTouchId);
            if (t) handleMove(t.clientX, t.clientY);
        }
        function onTouchEnd(e) {
            if (e) e.stopPropagation();
            // Only release if our touch ended
            for (const t of e.changedTouches) {
                if (t.identifier === activeTouchId) {
                    activeTouchId = null;
                    el.removeEventListener('touchmove', onTouchMove);
                    window.removeEventListener('touchend', onTouchEnd);
                    window.removeEventListener('touchcancel', onTouchEnd);
                    break;
                }
            }
        }
        function onMouseDown(e) {
            e.preventDefault(); handleMove(e.clientX, e.clientY);
            const mm = (ev) => handleMove(ev.clientX, ev.clientY);
            const mu = () => { window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu); };
            window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu);
        }

        el.addEventListener('touchstart', onTouchStart, { passive: false });
        el.addEventListener('mousedown', onMouseDown);
        return () => { el.removeEventListener('touchstart', onTouchStart); el.removeEventListener('mousedown', onMouseDown); };
    }, [min, max, name, vertical]);

    const ratio = (val - min) / (max - min || 1);
    // Clamp thumb inside track (thumb: 64px horiz, 22px vert)
    const thumbStyle = vertical
        ? { bottom: `calc(3px + ${ratio} * (100% - 28px))` }
        : { left: `calc(2px + ${ratio} * (100% - 68px))` };
    const fillStyle = vertical
        ? { height: `${ratio * 100}%` }
        : { width: `calc(34px + ${ratio} * (100% - 68px))` };

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

