# PLAN: Config backups + autosave (resume across power cuts)

Implementation plan for the config **backup** + **autosave** feature and its
performance refinements. Read alongside the "Config persistence, autosave &
backups" section in `CLAUDE.md` for the *why* behind every decision.

> Status when this plan was written: the **v1** (rolling backups + single-file
> JSON ping-pong autosave + boot-prefers-autosave + Settings → Backup panel)
> is **implemented but uncommitted** in the working tree and was deployed to
> the Pi (`user@10.1.1.2`) and end-to-end tested. The Pi has since been
> restored to the user's real config (no leftover backup/autosave artefacts).
> This plan covers (a) removing temporary debug code, (b) the performance
> refinements so it scales to ~8 trackers, (c) the autosave-after-load/restore
> behaviour, (d) docs, and (e) commit.

---

## Goal & constraints (recap)

- The Pi sits in a synth rig and is **hard-power-cut** at the wall — a normal,
  expected operation, with **no clean shutdown**. We must resume the last
  edited state on boot.
- There is **no RTC** → wall-clock time is never trustworthy.
- The asyncio loop carries **filtered/mapped MIDI** + SSE + REST. `json.dumps`
  holds the GIL, so a big encode on a worker thread **still stalls the loop**.
  Measured on the Pi: **~60 ms** to JSON-encode the current ~235 KB config;
  with ~8 trackers this would be **~400–500 ms** — unacceptable mid-set.
- Disk I/O (`mount remount`, `sync`) and `gzip` **release the GIL** → they do
  not stall the loop; only the encode does.

---

## Current state (v1, uncommitted in working tree)

Files modified (do **not** re-do these; refine them):

- `src/raspimidihub/config.py`
  - `uptime_seconds()`, `boot_id()` helpers (relative-time, no RTC).
  - `summarize_config_diff(old, new)` → "+1 instrument · −18 mappings".
  - `save(make_backup=False)` — writes `config.json` + (optional) a rolling
    gzipped backup in the **same** rw-remount window.
  - Backups: `BACKUP_DIR/backup-NNNNN.json.gz` + `backups/index.json`, pruned
    to `MAX_BACKUPS = 50`. `list_backups()` returns
    `{seq, summary, bytes, age_seconds, same_session}` (age relative to uptime,
    `None` for a different `boot_id`). `backup_data(seq)`.
  - Autosave: single-file **ping-pong** `autosave-0/1.json.gz` carrying
    `{seq, data}`, gzip-CRC = validity. `write_autosave()`, `_read_autosave()`.
  - `load()` = boot: **prefer newest valid autosave** → `config.json` →
    `.bak` → defaults. `load_manual()` / `aload_manual()` = the deliberate
    save only (backs the "Load" button).
  - **TEMP `AUTOSAVE-TIMING` logging in `write_autosave()` — REMOVE (Phase 1).**
- `src/raspimidihub/midi_engine.py`
  - `_change_seq` + `_last_change_t`, bumped on **every** `mark_dirty`
    (even while already dirty) so the autosaver can debounce.
- `src/raspimidihub/api.py`
  - `_snapshot_into_config()` — serialize live engine → `config.data`
    (shared by Save, autosave, shutdown flush).
  - `_Autosaver` — polling/debounced loop (`POLL=3 DEBOUNCE=6 MIN_INTERVAL=15
    MAX_WAIT=30`), `run()` + `flush()` (shutdown). Attached as
    `engine._autosaver`.
  - **TEMP `AUTOSAVE-TIMING snapshot=` logging in `_Autosaver.run` — REMOVE.**
  - Save route → `_snapshot_into_config()` + `asave(make_backup=True)`.
  - Load route → `aload_manual()` + `_apply_current_config()` (extracted,
    shared with restore).
  - Backup routes: `GET /api/backups`, `POST /api/backups/<seq>/restore`,
    `GET /api/backups/<seq>/download`.
- `src/raspimidihub/__main__.py` — flush-on-shutdown in the `finally` block
  (before plugins are torn down).
- `src/raspimidihub/static/pages/settings.js` — Settings → **Backup** sub-page
  (list with relative "n ago" / "before last reboot", Restore, Download).
- `tests/test_config_backups.py` — 14 tests (diff, prune, ping-pong, corrupt-
  slot fallback, boot-prefers-autosave, load-manual-ignores-autosave,
  uptime/boot-id relative time). **Keep + extend.**

---

## TODO

> **Progress (2026-06-04):** Phases 1–6 **done** (code + tests + docs +
> CHANGELOG + version bump to **4.7.0**; 582 tests green, `ruff check src
> plugins` clean). **Phase 7 done on the Pi (`user@10.1.1.2`)**: deployed
> the 4.7.0 deb, ran the full matrix — Save→backup, list, +1/−1 diff
> summary, Restore (6 instances, no corruption, forced autosave), Load
> reverts to manual save + clears dirty, debounced autosave captured an
> unsaved edit, clean restart resumed from autosave, **SIGKILL hard-cut
> resumed from the periodic autosave**, **corrupt newest slot fell back
> to the older good slot**, autosave-after-Load/Restore confirmed. Then
> cleanup: restored the user's pristine `config.json` (md5
> `03e640e6…` re-verified after a full boot cycle), wiped all test
> backups/autosave/.bak, confirmed boot loads from disk (6 instances,
> not dirty). Screenshots: a `32-settings-backup` scene + the refreshed
> `04-settings` hub are wired into `scripts/screenshots/run.py` but NOT
> captured against the live rig (the screenshot run swaps in the demo
> set) — ch.16 has a "pending capture" note. Remaining: **Phase 8**
> (commit, when the user asks). Note: there is no
> `E-appendix-rest-and-sse-api.md` in the manual, so the backup endpoints
> are documented as prose in ch.16 instead.

### Phase 1 — strip temporary instrumentation
- [x] Remove the two `AUTOSAVE-TIMING` log blocks (`config.write_autosave`,
      `api._Autosaver.run`). They were only for measuring the ~60 ms.

### Phase 2 — Lever 1: pattern selection must NOT dirty (nor invalidate cache)
Stem launches (Trigger Mode One-shot/Hold/Toggle) and Switch-mode taps call
`_launch_start` / `_handle_pattern_command → _switch_pattern`, which sets
`selected_pattern` + `pages`. Today those are non-transient → they `mark_dirty`
→ autosave fires during a live set (and the asterisk goes dirty on a Hold
press). A pattern **selection** only moves the pointer + the live *mirror*; it
does **not** change saveable **content** (the `patterns` bank).

Chosen approach (per the user — simplest): **pattern selection simply does not
mark the tracker dirty.** A per-call *quiet* write, NOT a transient/per-param
reclassification — so `selected_pattern`/`pages` stay **serialized** and the
active pattern is still saved on a deliberate Save (no `default_pattern` field
needed). This is also why a per-param `transient`/`persist_changed` scheme is
unnecessary: `pages` is changed by both launches (quiet) and recording (must
dirty), so the distinction must be **per-call**, not per-param.

- [x] Add a per-call quiet path: `set_param(name, value, persist=True)` on
      `PluginBase`/host. `persist=False` → update the value **and SSE-broadcast
      it** (so the display still follows the launch) but **skip** the dirty hook
      *and* the encode-seq bump (Phase 3). Done: `PluginBase.set_param` threads
      `persist` to `_notify_param_change(name, value, persist)`; the host's
      `_on_param_change` closure gates dirty + encode-seq on
      `saveable = persist and name not in transient_params`, SSE always fires.
- [x] `_switch_pattern` writes `selected_pattern` + `pages` (and the
      `reset_cursor` page/cursor jump) with `persist=False` — pure *selection*
      (launches, Switch-mode tap, Shift+Tap). **Recording, clone, clear
      untouched.** No `persist_changed` mechanism.
- [x] `selected_pattern`/`pages` stay **non-transient** (serialized → active
      pattern persisted on Save).
- [x] Tests (`test_tracker_base.py`): Hold/One-shot/Toggle launch *and*
      Switch-mode tap leave `config_dirty` False and bump no encode-seq (via a
      fake notify mirroring the host gating); recording sets both;
      `selected_pattern` stays serialized.

### Phase 3 — per-instrument in-memory encode cache (scales to N trackers)
Keep the **single-file** ping-pong autosave (no per-file store → no orphan
cleanup, no manifest, no per-file A/B). Avoid re-encoding **unchanged**
instruments by caching their JSON fragments. **JSON (not pickle)** because
JSON fragments concatenate trivially into the `plugins` array; pickle blobs do
not. The cache (not the format) is the real win, so this needs no dependency.

- [ ] Per-instance encode counter: add `instance._encode_seq` (int). Bump it in
      `PluginHost.set_param` for non-transient params **except quiet
      (`persist=False`) writes** (Phase 2). Transient *and* quiet changes
      (launches/selection, playhead, cursor) must **not** bump it, so they don't
      invalidate the cache.
- [ ] Encode cache in the snapshot/autosave path: `{instance_id: (encode_seq,
      json_fragment_bytes)}`. On autosave, for each instance reuse the cached
      fragment if its `encode_seq` is unchanged, else re-encode that instance and
      update the cache. Assemble the `plugins` array as
      `b"[" + b",".join(fragments) + b"]"`; encode the small top-level fields
      (mode, connections, disconnected, device_names, version) fresh; splice;
      gzip; write to the next ping-pong slot.
- [ ] Manual Save + backups stay **full JSON** (`config.json`, indented) and may
      reuse the same fragment cache to cut the Save hiccup too (optional; Save is
      infrequent so not required).
- [ ] Tests: editing one of N instruments re-encodes only that one (assert via
      a spy/counter on the per-instance encoder); pure-launch performance
      re-encodes nothing.

### Phase 4 — autosave immediately after Load / Restore / Import  ← user-emphasised
After a Load (→ `config.json`), Restore (→ a backup), or Import, the live state
**is** the new state and the user expects *that* to be the resume point. Today
Load clears dirty (so the periodic autosaver won't fire) → a power cut right
after Load would resume the **pre-Load** state. Fix:
- [ ] Add a **force** autosave (e.g. `_Autosaver.flush(force=True)` or
      `autosave_now()`) that snapshots + `write_autosave()` regardless of the
      change-seq check.
- [ ] Call it at the end of the Load, backup-Restore, and Import routes (after
      `_apply_current_config()` / the import apply). After this the newest
      autosave slot holds the loaded/restored state.
- [ ] Test: Load → the newest autosave slot decodes to the loaded config (not
      the prior live state); a simulated reboot then resumes the loaded state.

### Phase 5 — MUST NOT BREAK: config loading regressions
Verify (unit + on Pi) that all existing load paths still work:
- [ ] **Fresh install / existing config, no autosave slots** → `load()` falls
      through to `config.json` (then `.bak`, then defaults). (Already tested —
      keep the test.)
- [ ] **"Load" button** (`POST /api/config/load`) → loads `config.json`
      (manual), **not** the autosave, and applies cleanly (plugins restored,
      edge-diff applied, `clear_dirty`).
- [ ] **Export** (`GET /api/config/export`) unchanged; **Import**
      (`POST /api/config/import`) applies + saves + (Phase 4) force-autosaves.
- [ ] **Backup restore** rebuilds the live engine via the shared
      `_apply_current_config()` and marks dirty.
- [ ] All pre-existing config/engine tests still green.

### Phase 6 — docs (ship with the change, per CLAUDE.md)
- [ ] `docs/manual/15-saving-and-exporting-configs.md` — backups + autosave +
      Load-vs-autosave semantics.
- [ ] `docs/manual/16-settings.md` — the new **Backup** sub-page.
- [ ] `docs/manual/18-appliance-reliability.md` — autosave resumes across hard
      power cuts (ping-pong, no-RTC relative time, debounced, launches free).
- [ ] `docs/manual/E-appendix-rest-and-sse-api.md` — `GET /api/backups`,
      `POST /api/backups/<seq>/restore`, `GET /api/backups/<seq>/download`.
- [ ] `CHANGELOG.txt` — new `Unreleased` entry.
- [ ] Decide the release version (this is post-4.6.0 work → likely **4.7.0**).
- [ ] **Screenshots** (new UI → required by the manual rules):
  - [ ] **Settings → Backup sub-page** — a new screen. Add a scene to
        `scripts/screenshots/run.py` that navigates to `/settings/backup`. It
        must show a **populated** list (a few backups with diff summaries +
        relative "n ago"), so the scene setup needs to create a couple of
        backups first (POST `/api/config/save` a few times after the demo
        population) — otherwise the panel is the empty state. Embed in ch.16
        (and reference from ch.15). If scripting a populated list is awkward,
        fall back to a **`Screenshots needed`** note in ch.16 with the proposed
        filename + what it should show, to capture from real hardware.
  - [ ] **Settings hub** — the hub now has a new **Backup** row, so any existing
        hub screenshot is stale; regenerate it (or note it).
  - [ ] Capture happens **after** the final UI is deployed (do it in Phase 7,
        when the Pi already has the build). Remember `make screenshots
        TARGET=http://10.1.1.2` **swaps the live plugin set for the demo set**
        (runtime only) — restore the user's config via Load Config / the API
        afterwards, and commit only the changed PNGs.

### Phase 7 — deploy + thorough Pi test (user has exported their config → safe)
- [ ] Hot-swap changed files to `user@10.1.1.2`, restart, smoke-check.
- [ ] Re-run the v1 end-to-end matrix: Save→backup, list, Restore (content +
      no corruption), diff summary on a structural change, autosave captures an
      unsaved change, **clean restart resumes from autosave**, Load reverts to
      manual save, **SIGKILL (hard-cut) resumes from periodic autosave**,
      **corrupt newest slot → falls back to older slot**.
- [ ] New: **autosave-after-Load/Restore** resumes the loaded state on reboot.
- [ ] **Capture the Phase-6 screenshots** now that the final UI is on the Pi
      (Settings → Backup sub-page + refreshed Settings hub); restore the user's
      config afterwards and commit only the changed PNGs.
- [ ] Re-measure the encode time with the cache (expect launch≈0, one recorded
      tracker ≈ one-instrument encode, not the whole config).
- [ ] **Cleanup**: restore `/tmp/USER_CONFIG_SAVE.json` (or have the user
      re-import), wipe test `backups/` + `autosave-*.json.gz`, restart, confirm
      md5 of `config.json` matches the user's original and instance count is 6.

### Phase 8 — commit (only when the user asks)
- [ ] One commit (code + tests + docs + CHANGELOG together).

---

## Open decisions to confirm with the user
1. **Release version** for this work (4.7.0?).
2. Whether the manual-Save full-JSON encode should also use the fragment cache
   (only matters once there are many trackers; Save is infrequent).

(Resolved: pattern selection is quiet/non-dirtying but `selected_pattern`
stays serialized, so the active pattern is still saved on Save — no
`default_pattern` field, and load keeps whatever was saved.)

## Explicitly NOT doing (decided against earlier)
- **No per-instrument files / tar.gz container** — would add an on-FAT
  transactional store (manifest commit, orphan GC, per-file A/B). The in-memory
  fragment cache gets the same scaling win with a single file and zero cleanup.
- **No sidecar process / IPC** — would fully remove the encode from the main
  process but adds a delta protocol, state mirror, fork-safety, and funnelling
  all writes through it. Reserve only if cache + Lever 1 prove insufficient.
- **No orjson dependency** — the cache is the real win; JSON-fragment
  concatenation needs no dep. Revisit only if a manual Save with many trackers
  is itself a problem.
