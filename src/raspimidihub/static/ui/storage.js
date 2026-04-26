/**
 * localStorage hygiene — prevents per-device keys from growing
 * unboundedly over the lifetime of a long-running browser session.
 *
 * Single fixed-size keys (midiBar, raspimidihub:lastController,
 * raspimidihub:soundsEnabled) don't need pruning — they're
 * overwritten in place. The concern is per-device keys like
 * `sender_<stable_id>` that get one entry per device the user has
 * ever opened the test-sender on. Over years, that's a slow leak.
 *
 * `pruneByPrefix(prefix, {maxAgeDays, maxCount})` walks localStorage,
 * drops entries older than `maxAgeDays`, then keeps only the
 * most-recent `maxCount`. Each entry is JSON with an optional `_ts`
 * field; missing or unparseable entries are treated as ancient
 * (timestamp 0) and pruned first.
 */

const MS_PER_DAY = 24 * 60 * 60 * 1000;

export function touchTs(obj) {
    return { ...obj, _ts: Date.now() };
}

export function pruneByPrefix(prefix, { maxAgeDays = 90, maxCount = 50 } = {}) {
    let keys = [];
    try {
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            if (k && k.startsWith(prefix)) keys.push(k);
        }
    } catch { return 0; }

    const now = Date.now();
    const cutoff = now - maxAgeDays * MS_PER_DAY;
    const entries = [];
    for (const k of keys) {
        let ts = 0;
        try {
            const o = JSON.parse(localStorage.getItem(k) || '{}');
            ts = (typeof o._ts === 'number') ? o._ts : 0;
        } catch {}
        entries.push({ k, ts });
    }
    let removed = 0;
    for (const e of entries) {
        if (e.ts < cutoff) {
            try { localStorage.removeItem(e.k); removed++; } catch {}
        }
    }
    const fresh = entries.filter(e => e.ts >= cutoff).sort((a, b) => b.ts - a.ts);
    if (fresh.length > maxCount) {
        for (const e of fresh.slice(maxCount)) {
            try { localStorage.removeItem(e.k); removed++; } catch {}
        }
    }
    return removed;
}

// Run all known cleanups. Called once on app startup.
export function runStorageCleanup() {
    try {
        pruneByPrefix('sender_', { maxAgeDays: 90, maxCount: 50 });
    } catch {}
}
