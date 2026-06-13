/**
 * Rack-view interaction engine (imperative).
 *
 * Owns the SVG cable layer and every dynamic visual on the rack:
 * drawing/animating cables, port-activity LEDs, the patch gestures
 * (tap-tap + drag with edge auto-scroll), the peek/spread/sticky
 * highlight, and the drag-over "insert here" ripple. It mutates classes
 * directly on the Preact-rendered jacks; see pages/rack.js for why that
 * doesn't fight Preact's diff.
 *
 * The host (RackView) assigns `engine.ctx` every render with the latest
 * { devices, connections, portMap, deviceKey, midiRates, clockQuarters,
 *   clockSources, onToggle, getCellMenuItems, getHeaderMenuItems,
 *   showContextMenu }. The engine reads ctx at draw/event time, so it
 * always sees current data and clipboard-aware menu builders.
 *
 * Connect/disconnect/filter/clipboard all route through the callbacks
 * RoutingPage already uses for the matrix — this engine adds no new
 * server semantics, only the gestures that drive them.
 */

const SVGNS = 'http://www.w3.org/2000/svg';
const HOLD_MS = 350;          // press-hold → peek
const DEVICE_HOLD_MS = 500;   // press-hold on faceplate → device menu
const DRAG_THRESH = 8;        // px before a press becomes a drag
const EDGE = 48, MAX_SPEED = 18;

export function createRackEngine() {
    let root = null, svg = null, scrollEl = null;
    const engine = { ctx: null };

    // ---- geometry helpers -------------------------------------------
    function originRect() { return root.getBoundingClientRect(); }

    // dkey → group id, matching pages/rack.js group ids, so a cable to a
    // device hidden inside a collapsed group can anchor at the group
    // blende instead of a (non-existent) jack.
    function groupIdOf(d) {
        return d.is_plugin ? 'plugins' : d.is_network ? 'net:' + (d.remote_hub || '') : 'hardware';
    }
    function dkeyGroupMap() {
        const m = {};
        for (const d of (engine.ctx.devices || [])) m[engine.ctx.deviceKey(d)] = groupIdOf(d);
        return m;
    }

    // Resolve a jack key (`dkey:port:role`) to a point in the SVG's
    // coordinate space + the element it anchored to. Falls back to the
    // collapsed group's anchor jack when the unit isn't rendered.
    function anchor(key, groupMap) {
        let el = root.querySelector(`[data-jack="${cssEsc(key)}"]`);
        if (!el || !el.offsetParent) {
            const parts = key.split(':'); parts.pop(); parts.pop();
            const dkey = parts.join(':');
            const gid = groupMap[dkey];
            if (gid) {
                const g = root.querySelector(`[data-ganchor="${cssEsc(gid)}"]`);
                if (g && g.offsetParent) el = g;
            }
        }
        if (!el || !el.offsetParent) return null;
        const b = el.getBoundingClientRect(), o = originRect();
        return { x: b.left + b.width / 2 - o.left, y: b.top + b.height / 2 - o.top, el };
    }
    // CSS.escape isn't safe for attribute *values* with colons in all
    // engines via template; quote-escaping is enough here (keys are our
    // own ascii). Kept tiny on purpose.
    function cssEsc(s) { return s.replace(/"/g, '\\"'); }

    // ---- cable path (hanging, Reason-style deep sag) ----------------
    function hangCps(a, b, idx) {
        const dist = Math.hypot(b.x - a.x, b.y - a.y);
        const sag = Math.min(300, 70 + dist * 0.35) + (idx % 5) * 14;
        const bow = ((idx % 7) - 3) * 8;
        return { c1x: a.x + bow, c1y: a.y + sag, c2x: b.x + bow, c2y: b.y + sag };
    }
    function cpsPath(a, b, cp) {
        return `M ${a.x} ${a.y} C ${cp.c1x} ${cp.c1y}, ${cp.c2x} ${cp.c2y}, ${b.x} ${b.y}`;
    }
    function mk(tag, attrs) {
        const el = document.createElementNS(SVGNS, tag);
        for (const k in attrs) el.setAttribute(k, attrs[k]);
        return el;
    }

    // ---- connection ↔ key helpers -----------------------------------
    function srcKeyOf(c) { return (c.offline ? 's:' + c.src_stable_id : 'c' + c.src_client) + ':' + c.src_port + ':out'; }
    function dstKeyOf(c) { return (c.offline ? 's:' + c.dst_stable_id : 'c' + c.dst_client) + ':' + c.dst_port + ':in'; }
    function srcStableOf(c) { return c.offline ? c.src_stable_id : srcStableFromClient(c.src_client); }
    function srcStableFromClient(cid) {
        for (const d of (engine.ctx.devices || [])) if (d.client_id === cid) return d.stable_id;
        return '' + cid;
    }
    function connId(c) {
        if (c.id) return c.id;
        return c.offline
            ? `offline:${c.src_stable_id}:${c.src_port}|${c.dst_stable_id}:${c.dst_port}`
            : `${c.src_client}:${c.src_port}-${c.dst_client}:${c.dst_port}`;
    }
    function cableColor(stableId, portId) {
        const s = (stableId || '') + ':' + portId;
        let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
        return `hsl(${h % 360} 75% 60%)`;
    }

    // Descriptors for a connection's two endpoints, for the cell menu.
    function endpointDescs(c) {
        return { src: engine.ctx.portMap[srcKeyOf(c)] || null, dst: engine.ctx.portMap[dstKeyOf(c)] || null };
    }

    // ---- draw all cables --------------------------------------------
    let selectedConn = null;
    function drawCables() {
        if (!svg || !root || !engine.ctx) return;
        // remember an active sticky peek so a structural redraw doesn't
        // leave everything dimmed (see peekJack restore at the end).
        const prevPeek = svg.classList.contains('peek') ? peekKey : null;
        spreadItems = null; peekKey = null;
        svg.classList.remove('peek');
        svg.innerHTML = '';

        const w = root.scrollWidth || root.clientWidth, h = root.scrollHeight || root.clientHeight;
        svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
        svg.style.width = w + 'px'; svg.style.height = h + 'px';

        const groupMap = dkeyGroupMap();
        const dots = [];
        (engine.ctx.connections || []).forEach((c, idx) => {
            const a = anchor(srcKeyOf(c), groupMap);
            const b = anchor(dstKeyOf(c), groupMap);
            if (!a || !b || a.el === b.el) return;     // both inside one collapsed group
            const cp = hangCps(a, b, idx);
            const d = cpsPath(a, b, cp);
            const color = cableColor(srcStableOf(c), c.src_port);
            const id = connId(c);
            const offline = !!c.offline;
            const wire = mk('path', { d, class: 'wire' + (offline ? ' offline' : '') + (selectedConn === id ? ' sel' : ''), stroke: color });
            wire.style.color = color; wire.dataset.conn = id;
            const hit = mk('path', { d, class: 'hit' }); hit.dataset.conn = id;
            svg.appendChild(wire); svg.appendChild(hit);
            svg.appendChild(mk('circle', { cx: a.x, cy: a.y, r: 7, class: 'plug', fill: color, 'data-conn': id }));
            svg.appendChild(mk('circle', { cx: b.x, cy: b.y, r: 7, class: 'plug', fill: color, 'data-conn': id }));
            if (c.filtered || (c.mappings && c.mappings.length)) {
                const mid = wire.getPointAtLength(wire.getTotalLength() / 2);
                dots.push(makeFilterBadge(c, mid.x, mid.y));
            }
        });
        dots.forEach(d => svg.appendChild(d));

        if (prevPeek) { const el = jackForKey(prevPeek); if (el) peekJack(el, true, true); }
    }

    function makeFilterBadge(c, x, y) {
        const g = mk('g', { class: 'fdot', 'data-conn': connId(c), transform: `translate(${x} ${y})` });
        g.appendChild(mk('circle', { r: 8.5, class: 'fdot-bg' }));
        g.appendChild(mk('path', { class: 'fdot-glyph', d: 'M -5 -4.2 L 5 -4.2 L 1.5 0.3 L 1.5 4.6 L -1.5 4.6 L -1.5 0.3 Z' }));
        g.addEventListener('click', (e) => { e.stopPropagation(); openCableMenu(c, e.clientX, e.clientY); });
        return g;
    }

    // ---- activity (LEDs + clock) ------------------------------------
    const beatSeen = {};
    function updateActivity() {
        if (!root || !engine.ctx) return;
        const rates = engine.ctx.midiRates || {};
        const clockIds = engine.ctx.clockSources ? Object.keys(engine.ctx.clockSources).map(Number) : [];
        const quarters = engine.ctx.clockQuarters || {};
        for (const jack of root.querySelectorAll('.jack[data-jack]')) {
            const key = jack.dataset.jack;
            const parts = key.split(':'); const role = parts.pop(); const port = parts.pop();
            const dkey = parts.join(':');
            const cid = dkey[0] === 'c' ? Number(dkey.slice(1)) : null;
            const rate = cid != null ? rates[cid + ':' + port] : 0;
            jack.classList.toggle('live', !!rate);
            // Clock: source (out) jacks of a clock-sending device get a
            // steady ring; a quarter-note tick replays a one-shot pulse.
            if (role === 'out' && cid != null && clockIds.includes(cid)) {
                jack.classList.add('clock');
                const q = quarters[cid];
                if (q && beatSeen[key] !== q) {
                    beatSeen[key] = q;
                    jack.classList.remove('clock-beat'); void jack.offsetWidth; jack.classList.add('clock-beat');
                }
            } else {
                jack.classList.remove('clock');
            }
        }
    }

    // ---- magnet spread (radial fan at the shared jack) --------------
    let spreadItems = null;
    function startSpread(ids, instant) {
        endSpread();
        const items = [];
        (engine.ctx.connections || []).forEach((c, idx) => {
            const id = connId(c); if (!ids.has(id)) return;
            const wire = svg.querySelector(`path.wire[data-conn="${cssEsc(id)}"]`);
            const hit = svg.querySelector(`path.hit[data-conn="${cssEsc(id)}"]`);
            if (!wire || !hit) return;
            const groupMap = dkeyGroupMap();
            const a = anchor(srcKeyOf(c), groupMap), b = anchor(dstKeyOf(c), groupMap);
            if (!a || !b || a.el === b.el) return;
            const fdot = svg.querySelector(`g.fdot[data-conn="${cssEsc(id)}"]`);
            items.push({ a, b, idx, wire, hit, fdot });
        });
        if (!items.length) return;
        items.forEach(it => { it.base = hangCps(it.a, it.b, it.idx); it.target = { ...it.base }; });
        const sharedA = items.every(it => it.a.el === items[0].a.el);
        const sharedB = items.every(it => it.b.el === items[0].b.el);
        if (sharedA || sharedB) {
            const S = sharedA ? items[0].a : items[0].b;
            const free = it => sharedA ? it.b : it.a;
            items.forEach(it => { const F = free(it); it.ang = Math.atan2(F.y - S.y, F.x - S.x); });
            items.sort((p, q) => p.ang - q.ang);
            const n = items.length, span = Math.min(2.5, 0.7 + n * 0.24);
            items.forEach((it, i) => {
                const F = free(it), dist = Math.hypot(F.x - S.x, F.y - S.y);
                const frac = n > 1 ? i / (n - 1) - 0.5 : 0;
                const dep = Math.PI / 2 + frac * span, r = Math.min(200, 60 + dist * 0.22);
                const fx = S.x + Math.cos(dep) * r, fy = S.y + Math.sin(dep) * r;
                if (sharedA) { it.target.c1x = fx; it.target.c1y = fy; }
                else { it.target.c2x = fx; it.target.c2y = fy; }
            });
        } else {
            items.forEach((it, i) => {
                const s = i - (items.length - 1) / 2;
                it.target.c1x += s * 68; it.target.c2x += s * 68;
                it.target.c1y += Math.abs(s) * 26; it.target.c2y += Math.abs(s) * 26;
            });
        }
        spreadItems = items;
        if (instant) { applyCps(items, 1); return; }
        animateSpread(items, 0, 1, true);
    }
    function endSpread() { if (spreadItems) { animateSpread(spreadItems, 1, 0, false); spreadItems = null; } }
    function applyCps(items, f) {
        for (const it of items) {
            if (!it.wire.isConnected) continue;
            const cp = {
                c1x: it.base.c1x + (it.target.c1x - it.base.c1x) * f,
                c1y: it.base.c1y + (it.target.c1y - it.base.c1y) * f,
                c2x: it.base.c2x + (it.target.c2x - it.base.c2x) * f,
                c2y: it.base.c2y + (it.target.c2y - it.base.c2y) * f,
            };
            const d = cpsPath(it.a, it.b, cp);
            it.wire.setAttribute('d', d); it.hit.setAttribute('d', d);
            if (it.fdot) { const m = it.wire.getPointAtLength(it.wire.getTotalLength() / 2); it.fdot.setAttribute('transform', `translate(${m.x} ${m.y})`); }
        }
    }
    function animateSpread(items, from, to, overshoot) {
        let start = null;
        function frame(ts) {
            if (start === null) start = ts;
            const t = Math.min(1, (ts - start) / 280);
            const c1 = 1.70158, c3 = c1 + 1;
            const e = overshoot ? 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2) : 1 - Math.pow(1 - t, 3);
            applyCps(items, from + (to - from) * e);
            if (t < 1) requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
    }

    // ---- peek (highlight a jack's cables) ----------------------------
    let peekKey = null, stickyKey = null;
    function jackForKey(key) {
        return key && key.startsWith('g:')
            ? root.querySelector(`[data-ganchor="${cssEsc(key.slice(2))}"]`)
            : root.querySelector(`[data-jack="${cssEsc(key)}"]`);
    }
    function jackKey(el) { return el.dataset.jack || ('g:' + el.dataset.ganchor); }
    function connsForJack(el) {
        const conns = engine.ctx.connections || [];
        if (el.dataset.ganchor) {
            const gid = el.dataset.ganchor, groupMap = dkeyGroupMap();
            const inG = (dk) => groupMap[dk] === gid;
            return conns.filter(c => inG(srcDkey(c)) !== inG(dstDkey(c)));
        }
        const key = el.dataset.jack;
        const parts = key.split(':'); const role = parts.pop(); const port = parts.pop(); const dkey = parts.join(':');
        return conns.filter(c => role === 'out'
            ? (srcDkey(c) === dkey && c.src_port === Number(port))
            : (dstDkey(c) === dkey && c.dst_port === Number(port)));
    }
    function srcDkey(c) { return c.offline ? 's:' + c.src_stable_id : 'c' + c.src_client; }
    function dstDkey(c) { return c.offline ? 's:' + c.dst_stable_id : 'c' + c.dst_client; }

    function peekJack(el, on, instant) {
        const key = on ? jackKey(el) : null;
        if (on && peekKey === key) return;
        endSpread();
        svg.querySelectorAll('.hl').forEach(x => x.classList.remove('hl'));
        peekKey = key;
        const conns = on ? connsForJack(el) : [];
        if (!on || !conns.length) {
            svg.classList.remove('peek'); peekKey = null;
            if (on && key === stickyKey) stickyKey = null;
            return;
        }
        svg.classList.add('peek');
        const ids = new Set(conns.map(connId));
        svg.querySelectorAll('[data-conn]').forEach(x => { if (ids.has(x.dataset.conn)) x.classList.add('hl'); });
        startSpread(ids, instant);
    }
    function applySticky() {
        if (!stickyKey) return;
        const el = jackForKey(stickyKey);
        if (el) peekJack(el, true); else stickyKey = null;
    }

    // ---- hold timers -------------------------------------------------
    let hold = null;       // press-hold on a jack → peek
    function startHold(el) {
        cancelHold();
        hold = { el, active: false, timer: setTimeout(() => { hold.active = true; peekJack(el, true); }, HOLD_MS) };
    }
    function cancelHold() { if (hold) { clearTimeout(hold.timer); if (hold.active) { peekJack(hold.el, false); applySticky(); } hold = null; } }
    function endHold() {
        if (!hold) return false;
        const wasActive = hold.active; clearTimeout(hold.timer);
        if (wasActive) {
            const key = jackKey(hold.el);
            if (stickyKey === key) { stickyKey = null; peekJack(hold.el, false); }
            else stickyKey = key;
        }
        hold = null; return wasActive;
    }

    // ---- patch gestures (tap-tap + drag) ----------------------------
    let armed = null;      // { key:'dkey:port', dir:'out'|'in' }
    let drag = null;
    let unitHold = null;
    let suppressClick = false;
    const opp = d => d === 'out' ? 'in' : 'out';

    function setArmed(a) {
        armed = a;
        root.querySelectorAll('.jack.armed').forEach(j => j.classList.remove('armed'));
        root.querySelectorAll('.jack.target-hint').forEach(j => j.classList.remove('target-hint'));
        if (a) {
            const j = root.querySelector(`[data-jack="${cssEsc(a.key + ':' + a.dir)}"]`); if (j) j.classList.add('armed');
            root.querySelectorAll('.jack.' + opp(a.dir)).forEach(t => t.classList.add('target-hint'));
        }
    }
    function finishPatch(outKey, inKey) {
        const src = engine.ctx.portMap[outKey + ':out'] || engine.ctx.portMap[outKey];
        const dst = engine.ctx.portMap[inKey + ':in'] || engine.ctx.portMap[inKey];
        if (!src || !dst) return;
        if (src.client_id != null && src.client_id === dst.client_id) return;  // same device
        engine.ctx.onToggle(src, dst, true);
    }
    // outKey/inKey here are full data-jack strings; normalise to the
    // (source=out, dest=in) order onToggle expects.
    function patchByDir(aKey, aDir, bKey, bDir) {
        const outFull = aDir === 'out' ? aKey : bKey;     // includes :role
        const inFull = aDir === 'in' ? aKey : bKey;
        finishPatchFull(outFull, inFull);
    }
    function finishPatchFull(outFull, inFull) {
        const src = engine.ctx.portMap[outFull], dst = engine.ctx.portMap[inFull];
        if (!src || !dst) return;
        if (src.client_id != null && src.client_id === dst.client_id) return;
        engine.ctx.onToggle(src, dst, true);
    }

    // ---- cable / device menu openers --------------------------------
    function openCableMenu(c, x, y) {
        const { src, dst } = endpointDescs(c);
        if (!src || !dst || !engine.ctx.getCellMenuItems) return;
        const items = engine.ctx.getCellMenuItems(src, dst, c);
        if (items && items.length) engine.ctx.showContextMenu(x, y, items);
    }
    function openDeviceMenu(dev, x, y) {
        if (!engine.ctx.getHeaderMenuItems) return;
        const item = { client_id: dev.client_id, stable_id: dev.stable_id, dev_name: dev.name,
            online: dev.online !== false, is_plugin: !!dev.is_plugin, is_bluetooth: !!dev.is_bluetooth,
            is_network: !!dev.is_network, remote_hub: dev.remote_hub || '', plugin_type: dev.plugin_type };
        const items = engine.ctx.getHeaderMenuItems(item, 'input', dev.name);
        if (items && items.length) engine.ctx.showContextMenu(x, y, items);
    }
    function deviceForUnit(unitEl) {
        const dkey = unitEl.dataset.dkey;
        return (engine.ctx.devices || []).find(d => engine.ctx.deviceKey(d) === dkey) || null;
    }

    // ---- cable hit-testing (cables have pointer-events:none) --------
    function cableAtPoint(x, y) {
        const pt = new DOMPoint(x, y).matrixTransform(svg.getScreenCTM().inverse());
        const hits = [...svg.querySelectorAll('path.hit')];
        const hlIds = new Set([...svg.querySelectorAll('path.wire.hl')].map(w => w.dataset.conn));
        const peeking = svg.classList.contains('peek');
        for (const hit of hits) {
            if (peeking && !hlIds.has(hit.dataset.conn)) continue;   // dimmed cables aren't hittable
            if (hit.isPointInStroke(pt)) return (engine.ctx.connections || []).find(c => connId(c) === hit.dataset.conn) || null;
        }
        return null;
    }

    // ---- auto-scroll zones ------------------------------------------
    let zoneTop = null, zoneBot = null, rubber = null;
    function showZones(show) {
        if (!zoneTop) {
            zoneTop = document.createElement('div'); zoneTop.className = 'rack-scrollzone top';
            zoneBot = document.createElement('div'); zoneBot.className = 'rack-scrollzone bottom';
            document.body.appendChild(zoneTop); document.body.appendChild(zoneBot);
        }
        const r = scrollEl === document.scrollingElement
            ? { left: 0, right: innerWidth, top: 0, bottom: innerHeight }
            : scrollEl.getBoundingClientRect();
        for (const z of [zoneTop, zoneBot]) { z.style.left = r.left + 'px'; z.style.width = (r.right - r.left) + 'px'; z.style.display = show ? 'block' : 'none'; }
        zoneTop.style.top = r.top + 'px';
        zoneBot.style.top = (r.bottom - EDGE) + 'px';
    }
    function edgeRect() {
        return scrollEl === document.scrollingElement
            ? { top: 0, bottom: innerHeight } : scrollEl.getBoundingClientRect();
    }
    function startEdgeScroll() {
        function step() {
            if (!drag || !drag.moved) return;
            const r = edgeRect(); let dy = 0;
            if (drag.y < r.top + EDGE) dy = -MAX_SPEED * (1 - (drag.y - r.top) / EDGE);
            else if (drag.y > r.bottom - EDGE) dy = MAX_SPEED * (1 - (r.bottom - drag.y) / EDGE);
            if (dy) { if (scrollEl === document.scrollingElement) scrollBy(0, dy); else scrollEl.scrollTop += dy; updateRubber(); }
            requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
    }
    function updateRubber() {
        if (!drag || !rubber) return;
        const groupMap = dkeyGroupMap();
        const a = anchor(drag.from + ':' + drag.dir, groupMap);
        const o = originRect();
        const bx = drag.x - o.left, by = drag.y - o.top;
        if (a) rubber.setAttribute('d', `M ${a.x} ${a.y} C ${a.x} ${a.y + 40}, ${bx} ${by + 40}, ${bx} ${by}`);
    }

    // ---- pointer / mouse handlers -----------------------------------
    function inRack(e) { return e.target.closest && e.target.closest('.rack-view'); }

    const onPointerDown = (e) => {
        if (!inRack(e)) return;
        const j = e.target.closest('.jack');
        if (j) {
            startHold(j);
            if (!j.dataset.jack) return;                 // group anchor: peek only
            e.preventDefault();
            const parts = j.dataset.jack.split(':'); const dir = parts.pop();
            drag = { from: parts.join(':'), dir, startX: e.clientX, startY: e.clientY, moved: false, x: e.clientX, y: e.clientY };
            return;
        }
        const u = e.target.closest('.unit');
        if (u && !inEarZone(u, e.clientX)) {
            cancelUnitHold();
            unitHold = { x: e.clientX, y: e.clientY, fired: false, timer: setTimeout(() => {
                unitHold.fired = true; const dev = deviceForUnit(u); if (dev) openDeviceMenu(dev, unitHold.x, unitHold.y);
            }, DEVICE_HOLD_MS) };
        }
    };
    function inEarZone(u, x) { const r = u.getBoundingClientRect(); return x < r.left + 46 || x > r.right - 46; }
    function cancelUnitHold() { if (unitHold) { clearTimeout(unitHold.timer); unitHold = null; } }

    const onPointerMove = (e) => {
        if (unitHold && !unitHold.fired && Math.hypot(e.clientX - unitHold.x, e.clientY - unitHold.y) > DRAG_THRESH) cancelUnitHold();
        if (!drag) return;
        drag.x = e.clientX; drag.y = e.clientY;
        if (!drag.moved && Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > DRAG_THRESH) {
            cancelHold();
            drag.moved = true; document.body.classList.add('rack-dragging');
            rubber = mk('path', { class: 'rubber' }); svg.appendChild(rubber);
            root.querySelectorAll('.jack.' + opp(drag.dir)).forEach(t => t.classList.add('target-hint'));
            showZones(true); startEdgeScroll();
        }
        if (drag.moved) {
            updateRubber();
            root.querySelectorAll('.jack.drag-over').forEach(x => x.classList.remove('drag-over'));
            const t = document.elementFromPoint(e.clientX, e.clientY);
            const tj = t && t.closest && t.closest('.jack.' + opp(drag.dir));
            if (tj) tj.classList.add('drag-over');
        }
    };

    const onPointerUp = (e) => {
        if (unitHold) { clearTimeout(unitHold.timer); if (unitHold.fired) suppressClick = true; unitHold = null; }
        if (endHold()) { drag = null; return; }
        if (!drag) { if (armed && !(e.target.closest && e.target.closest('.jack'))) setArmed(null); return; }
        const d = drag; drag = null;
        document.body.classList.remove('rack-dragging');
        if (rubber) { rubber.remove(); rubber = null; }
        showZones(false);
        root.querySelectorAll('.jack.drag-over').forEach(x => x.classList.remove('drag-over'));
        if (!d.moved) {                                  // tap on a jack
            const jel = root.querySelector(`[data-jack="${cssEsc(d.from + ':' + d.dir)}"]`);
            if (armed && armed.dir !== d.dir) {           // counterpart tapped → patch
                patchByDir(armed.key + ':' + armed.dir, armed.dir, d.from + ':' + d.dir, d.dir);
                setArmed(null); stickyKey = null;
            } else if (armed && armed.key === d.from && armed.dir === d.dir) {
                setArmed(null); stickyKey = null; if (jel) peekJack(jel, false);
            } else {
                setArmed({ key: d.from, dir: d.dir });
                if (jel) { stickyKey = jackKey(jel); peekJack(jel, true); }
            }
            return;
        }
        const t = document.elementFromPoint(e.clientX, e.clientY);     // drag-drop
        const tj = t && t.closest && t.closest('.jack.' + opp(d.dir));
        if (tj && tj.dataset.jack) {
            const parts = tj.dataset.jack.split(':'); const tdir = parts.pop();
            patchByDir(d.from + ':' + d.dir, d.dir, parts.join(':') + ':' + tdir, tdir);
        }
        setArmed(armed);
    };

    const onClick = (e) => {
        if (!inRack(e)) return;
        if (suppressClick) { suppressClick = false; return; }
        if (!e.target.isConnected) return;
        if (e.target.closest('.jack') || e.target.closest('.gpanel') || e.target.closest('.fdot')) return;
        const c = cableAtPoint(e.clientX, e.clientY);
        if (c) { e.stopPropagation(); openCableMenu(c, e.clientX, e.clientY); }
    };
    const onContextMenu = (e) => {
        if (!inRack(e)) return;
        const u = e.target.closest('.unit');
        if (u && !inEarZone(u, e.clientX)) { e.preventDefault(); cancelUnitHold(); const dev = deviceForUnit(u); if (dev) openDeviceMenu(dev, e.clientX, e.clientY); }
        else if (e.target.closest('.jack')) e.preventDefault();
    };
    const onMouseOver = (e) => { if (stickyKey || !inRack(e)) return; const j = e.target.closest('.jack'); if (j && j.dataset.jack) peekJack(j, true); };
    const onMouseOut = (e) => { if (stickyKey) return; const j = e.target.closest('.jack'); if (j && j.dataset.jack && (!hold || !hold.active)) peekJack(j, false); };

    // ---- lifecycle ---------------------------------------------------
    engine.mount = ({ rootEl, svgEl }) => {
        root = rootEl; svg = svgEl;
        scrollEl = findScrollParent(rootEl);
        document.addEventListener('pointerdown', onPointerDown);
        document.addEventListener('pointermove', onPointerMove);
        document.addEventListener('pointerup', onPointerUp);
        document.addEventListener('click', onClick);
        document.addEventListener('contextmenu', onContextMenu);
        document.addEventListener('mouseover', onMouseOver);
        document.addEventListener('mouseout', onMouseOut);
    };
    engine.drawCables = drawCables;
    engine.updateActivity = updateActivity;
    engine.destroy = () => {
        document.removeEventListener('pointerdown', onPointerDown);
        document.removeEventListener('pointermove', onPointerMove);
        document.removeEventListener('pointerup', onPointerUp);
        document.removeEventListener('click', onClick);
        document.removeEventListener('contextmenu', onContextMenu);
        document.removeEventListener('mouseover', onMouseOver);
        document.removeEventListener('mouseout', onMouseOut);
        if (zoneTop) zoneTop.remove(); if (zoneBot) zoneBot.remove();
        document.body.classList.remove('rack-dragging');
    };
    return engine;
}

function findScrollParent(el) {
    if (!el) return document.scrollingElement || document.documentElement;
    let n = el.parentElement;
    while (n) {
        const o = getComputedStyle(n).overflowY;
        if ((o === 'auto' || o === 'scroll') && n.scrollHeight > n.clientHeight) return n;
        n = n.parentElement;
    }
    return document.scrollingElement || document.documentElement;
}
