/**
 * Wheel plugin control.
 */

import { html, tickFeedback, thudFeedback, _activeWheelTouch } from './common.js';

// =======================================================================
// WHEEL — scrollable drum wheel (pixel-offset based, matching controls-demo.html)
// =======================================================================
export function PluginWheel({ name, label, min, max, value, onChange, suffix, tickLabel }) {
    const containerRef = useRef(null);
    const innerRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    const TICK_H = 20;
    const CENTER = 30 - TICK_H / 2;
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

        function onStart(e) {
            e.preventDefault(); e.stopPropagation();
            // Touch lock: claim this touch, skip if another wheel owns it
            if (e.touches) {
                const tid = e.touches[0].identifier;
                if (_activeWheelTouch.has(tid)) return;
                _activeWheelTouch.set(tid, el);
                s._touchId = tid;
            }
            if (s.animId) { cancelAnimationFrame(s.animId); s.animId = null; }
            s.atBoundary = false;
            const pt = e.touches ? e.touches[0] : e;
            s.startY = pt.clientY; s.startOffset = s.offset;
            s.lastY = pt.clientY; s.lastT = Date.now(); s.velocity = 0;
            el.addEventListener('touchmove', onMove, { passive: false });
            window.addEventListener('mousemove', onMove);
            window.addEventListener('touchend', onEnd);
            window.addEventListener('mouseup', onEnd);
        }
        function onMove(e) {
            e.preventDefault();
            if (e.touches) e.stopPropagation();
            const pt = e.touches ? e.touches[0] : e;
            const now = Date.now(); const dt = now - s.lastT;
            if (dt > 0) s.velocity = (pt.clientY - s.lastY) / dt;
            s.lastY = pt.clientY; s.lastT = now;
            let raw = s.startOffset + (pt.clientY - s.startY);
            const clamped = clampOffset(raw);
            const hitBound = raw !== clamped;
            s.offset = clamped;
            if (hitBound && !s.atBoundary) { thudFeedback(); s.velocity = 0; s.atBoundary = true; }
            else if (!hitBound) s.atBoundary = false;
            const nv = offsetToValue(s.offset);
            if (nv !== s.value) { tickFeedback(); s.value = nv; updateTicks(); oc.current(name, nv); }
            setOffset(s.offset);
        }
        function onEnd(e) {
            if (e && e.touches) e.stopPropagation();
            // Release touch lock
            if (s._touchId != null) { _activeWheelTouch.delete(s._touchId); s._touchId = null; }
            el.removeEventListener('touchmove', onMove);
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('touchend', onEnd);
            window.removeEventListener('mouseup', onEnd);
            if (Math.abs(s.velocity) > 0.2) animateMomentum();
            else snapToValue();
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
        el.addEventListener('touchstart', onStart, { passive: false });
        el.addEventListener('mousedown', onStart);
        el.addEventListener('wheel', onWheel, { passive: false });
        return () => {
            el.removeEventListener('touchstart', onStart);
            el.removeEventListener('mousedown', onStart);
            el.removeEventListener('wheel', onWheel);
        };
    }, [min, max, name]);

    const ticks = [];
    for (let i = min; i <= max; i++) {
        ticks.push(html`<div class="wheel-tick" key=${i}>${tickLabel ? tickLabel(i) : suffix ? i + suffix : i}</div>`);
    }

    return html`<div class="wheel-group">
        <span class="wheel-label">${label}</span>
        <div class="wheel-container" ref=${containerRef}>
            <div class="wheel-inner" ref=${innerRef}>${ticks}</div>
        </div>
    </div>`;
}

