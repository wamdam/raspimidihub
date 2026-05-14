/**
 * Wheel plugin control.
 */

import { html, tickFeedback, thudFeedback, _activeWheelTouch } from './common.js';
import { useEffect, useRef } from '../lib/hooks.module.js';

// =======================================================================
// WHEEL — scrollable drum wheel (pixel-offset based, matching controls-demo.html)
// =======================================================================
export function PluginWheel({ name, label, min, max, value, onChange, suffix, tickLabel, mini, wide }) {
    const containerRef = useRef(null);
    const innerRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    // Mini variant: half-height container (32px instead of 52px) with
    // a proportionally-shorter tick row. Same scroll/drag math, just
    // smaller. Used in dense edit panels (per-cell Ch / CC / On / Off,
    // XY pad spring config) where the full-size wheel would crowd
    // the row.
    const TICK_H = mini ? 12 : 20;
    const CONTAINER_H = mini ? 32 : 52;
    const CENTER = CONTAINER_H / 2 - TICK_H / 2;
    // Persistent state across renders (not React state — direct DOM manipulation)
    const s = useRef({
        value, offset: 0, startY: 0, startOffset: 0, lastY: 0, lastT: 0,
        velocity: 0, animId: null, atBoundary: false, lastWheel: 0,
    }).current;

    const valueToOffset = (v) => CENTER - (v - min) * TICK_H;
    const offsetToValue = (off) => Math.round(min + (CENTER - off) / TICK_H);
    const minOffset = valueToOffset(max); // max value = minimum offset (scrolled up)
    const maxOffset = valueToOffset(min); // min value = maximum offset
    const clampOffset = (off) => Math.max(minOffset, Math.min(maxOffset, off));

    const updateTicks = () => {
        const el = innerRef.current;
        if (!el) return;
        const children = el.children;
        for (let i = 0; i < children.length; i++) {
            const dist = Math.abs(min + i - s.value);
            children[i].className = 'wheel-tick' + (dist === 0 ? ' active' : dist === 1 ? ' near' : '');
        }
    };

    const setOffset = (off) => {
        s.offset = off;
        if (innerRef.current) innerRef.current.style.transform = `translateY(${off}px)`;
    };

    const snapToValue = () => {
        const target = valueToOffset(s.value);
        const snap = () => {
            s.offset += (target - s.offset) * 0.3;
            setOffset(s.offset);
            if (Math.abs(target - s.offset) > 0.5) s.animId = requestAnimationFrame(snap);
            else setOffset(target);
        };
        if (Math.abs(target - s.offset) < 0.5) { setOffset(target); return; }
        s.animId = requestAnimationFrame(snap);
    };

    // Sync from prop changes (e.g. MIDI Learn updating value)
    useEffect(() => {
        s.value = value;
        setOffset(valueToOffset(value));
        updateTicks();
    }, [value]);

    // Attach native event listeners for passive:false + stopPropagation
    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;

        const oc = onChangeRef;

        // Common move-step that runs from both touch and mouse paths.
        function applyMove(clientY) {
            const now = Date.now(); const dt = now - s.lastT;
            if (dt > 0) s.velocity = (clientY - s.lastY) / dt;
            s.lastY = clientY; s.lastT = now;
            let raw = s.startOffset + (clientY - s.startY);
            const clamped = clampOffset(raw);
            const hitBound = raw !== clamped;
            s.offset = clamped;
            if (hitBound && !s.atBoundary) { thudFeedback(); s.velocity = 0; s.atBoundary = true; }
            else if (!hitBound) s.atBoundary = false;
            const nv = offsetToValue(s.offset);
            if (nv !== s.value) { tickFeedback(); s.value = nv; updateTicks(); oc.current(name, nv); }
            setOffset(s.offset);
        }
        function startGesture(clientY) {
            if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; }
            s.atBoundary = false;
            s.startY = clientY; s.startOffset = s.offset;
            s.lastY = clientY; s.lastT = Date.now(); s.velocity = 0;
        }
        function endGesture() {
            if (Math.abs(s.velocity) > 0.2) animateMomentum();
            else snapToValue();
        }

        // --- Touch path: pin the gesture to a single Touch.identifier so
        // simultaneous drags on multiple wheels don't read e.touches[0]
        // for everyone.
        let activeTouchId = null;
        function findTouch(e, id) {
            for (const t of e.touches) if (t.identifier === id) return t;
            return null;
        }
        function onTouchStart(e) {
            e.preventDefault(); e.stopPropagation();
            const t = e.changedTouches[0];
            if (_activeWheelTouch.has(t.identifier)) return;
            _activeWheelTouch.set(t.identifier, el);
            activeTouchId = t.identifier;
            s._touchId = t.identifier;
            startGesture(t.clientY);
            el.addEventListener('touchmove', onTouchMove, { passive: false });
            window.addEventListener('touchend', onTouchEnd);
            window.addEventListener('touchcancel', onTouchEnd);
        }
        function onTouchMove(e) {
            e.preventDefault(); e.stopPropagation();
            const t = findTouch(e, activeTouchId);
            if (t) applyMove(t.clientY);
        }
        function onTouchEnd(e) {
            if (e) e.stopPropagation();
            for (const t of e.changedTouches) {
                if (t.identifier === activeTouchId) {
                    _activeWheelTouch.delete(activeTouchId);
                    activeTouchId = null;
                    s._touchId = null;
                    el.removeEventListener('touchmove', onTouchMove);
                    window.removeEventListener('touchend', onTouchEnd);
                    window.removeEventListener('touchcancel', onTouchEnd);
                    endGesture();
                    break;
                }
            }
        }

        // --- Mouse path: separate from touch (no multitouch concerns).
        function onMouseDown(e) {
            e.preventDefault();
            startGesture(e.clientY);
            const mm = (ev) => applyMove(ev.clientY);
            const mu = () => {
                window.removeEventListener('mousemove', mm);
                window.removeEventListener('mouseup', mu);
                endGesture();
            };
            window.addEventListener('mousemove', mm);
            window.addEventListener('mouseup', mu);
        }
        function animateMomentum() {
            const friction = 0.95;
            function frame() {
                s.velocity *= friction;
                let raw = s.offset + s.velocity * 16;
                const clamped = clampOffset(raw);
                if (raw !== clamped) { s.offset = clamped; s.velocity = 0; thudFeedback(); setOffset(s.offset); snapToValue(); return; }
                s.offset = clamped;
                const nv = offsetToValue(s.offset);
                if (nv !== s.value) { tickFeedback(); s.value = nv; updateTicks(); oc.current(name, nv); }
                setOffset(s.offset);
                if (Math.abs(s.velocity) > 0.05) s.animId = requestAnimationFrame(frame);
                else snapToValue();
            }
            s.animId = requestAnimationFrame(frame);
        }
        function onWheel(e) {
            e.preventDefault();
            const now = Date.now();
            if (now - s.lastWheel < 80) return;
            s.lastWheel = now;
            if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; }
            const delta = e.deltaY > 0 ? -1 : 1;
            const nv = Math.max(min, Math.min(max, s.value + delta));
            if (nv !== s.value) {
                s.value = nv; setOffset(valueToOffset(nv)); updateTicks(); oc.current(name, nv);
                (nv === min || nv === max) ? thudFeedback() : tickFeedback();
            }
        }
        el.addEventListener('touchstart', onTouchStart, { passive: false });
        el.addEventListener('mousedown', onMouseDown);
        el.addEventListener('wheel', onWheel, { passive: false });
        return () => {
            el.removeEventListener('touchstart', onTouchStart);
            el.removeEventListener('mousedown', onMouseDown);
            el.removeEventListener('wheel', onWheel);
        };
    }, [min, max, name]);

    const ticks = [];
    for (let i = min; i <= max; i++) {
        ticks.push(html`<div class="wheel-tick" key=${i}>${tickLabel ? tickLabel(i) : suffix ? i + suffix : i}</div>`);
    }

    // Compose class names from the mini / wide flags. They're
    // independent: mini = half-height, wide = wider face for long
    // string labels (e.g. "programmed" / "1/16T"). Either flag can be
    // present alone; both together would be unusual but valid.
    const groupCls = `wheel-group${mini ? ' mini' : ''}${wide ? ' wide' : ''}`;
    const containerCls = `wheel-container${mini ? ' mini' : ''}${wide ? ' wide' : ''}`;
    return html`<div class=${groupCls}>
        ${label ? html`<span class="wheel-label">${label}</span>` : null}
        <div class=${containerCls} ref=${containerRef}>
            <div class="wheel-inner" ref=${innerRef}>${ticks}</div>
        </div>
    </div>`;
}

