/**
 * ScrollAssist — bottom-right floating button stack that scrolls
 * `.main` by a fixed amount when there's content past the visible
 * area. Stacked: up button sits above the down button. Each button
 * is independently visible based on overflow direction.
 *
 * Mounts once inside `.main` (so the CSS variable cascade for
 * --nav-pad reaches it) and listens to the parent's scroll +
 * resize events.
 */

import { useEffect, useRef, useState } from '../lib/hooks.module.js';
import { html, tickFeedback } from './common.js';

// Per-tap step. Fixed so the feel is the same across every screen
// size — taller pages just need a few more taps.
const STEP_PX = 200;
// Don't show the affordance for trivial overflow.
const SHOW_AT_PX = 30;

export function ScrollAssist() {
    const wrapRef = useRef(null);
    const [canUp, setCanUp] = useState(false);
    const [canDown, setCanDown] = useState(false);

    useEffect(() => {
        // Walk up to find the scrolling .main — it's our parent in
        // the tree, but the ref reaches into the rendered DOM after
        // mount.
        const wrap = wrapRef.current;
        if (!wrap) return;
        const main = wrap.closest('.main');
        if (!main) return;
        let raf = 0;
        const update = () => {
            raf = 0;
            const top = main.scrollTop;
            const max = main.scrollHeight - main.clientHeight;
            setCanUp(top > SHOW_AT_PX);
            setCanDown(top < max - SHOW_AT_PX);
        };
        const onScroll = () => {
            if (raf) return;
            raf = requestAnimationFrame(update);
        };
        main.addEventListener('scroll', onScroll, { passive: true });
        window.addEventListener('resize', onScroll);
        // Watch the scroll container AND its first child so content
        // height changes (page swaps, plugin params expanding, slot
        // loads) re-evaluate visibility immediately.
        const ro = new ResizeObserver(update);
        ro.observe(main);
        if (main.firstElementChild) ro.observe(main.firstElementChild);
        update();
        return () => {
            main.removeEventListener('scroll', onScroll);
            window.removeEventListener('resize', onScroll);
            ro.disconnect();
            if (raf) cancelAnimationFrame(raf);
        };
    }, []);

    const scrollBy = (dir) => {
        const wrap = wrapRef.current;
        if (!wrap) return;
        const main = wrap.closest('.main');
        if (!main) return;
        tickFeedback();
        main.scrollBy({ top: dir * STEP_PX, behavior: 'smooth' });
    };

    // Render the wrapper always (it's an invisible anchor for the
    // `.closest('.main')` lookup); the FABs themselves render
    // conditionally on overflow.
    return html`<div class="scroll-fab-stack" ref=${wrapRef}>
        ${canUp ? html`<button class="scroll-fab"
            aria-label="Scroll up"
            onclick=${() => scrollBy(-1)}>▲</button>` : null}
        ${canDown ? html`<button class="scroll-fab"
            aria-label="Scroll down"
            onclick=${() => scrollBy(1)}>▼</button>` : null}
    </div>`;
}
