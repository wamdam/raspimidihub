# Project rules

Project-specific rules that apply to every change made in this
repository. Override defaults; layered on top of `~/.claude/CLAUDE.md`.

## Keep the user manual in sync with the software

The user manual under `docs/manual/` is the canonical, end-user-facing
description of how RaspiMIDIHub behaves. Every software change that
adds, removes, or alters user-visible behaviour **must** ship with the
matching manual change in the same PR / commit.

This applies to (non-exhaustive):

- New features, new plugins, new controller templates
- New UI controls, new screens, new tabs, new menu entries
- Removed or renamed features (the manual entry is updated or
  deleted -- never left dangling)
- Behaviour changes (a control that does something different, a
  default that flipped, a shortcut that moved)
- New REST / SSE endpoints, new event types, new query parameters
- New settings, new config keys, new hardware requirements

When the change is purely internal (refactor, test, build system,
performance optimisation that is invisible to the user) the manual
does not need to move. If the perf optimisation *is* user-visible
(e.g. a new stats row, a new "we're alive" indicator), it does.

### Where to look first -- the chapter map

| You are touching... | The chapter(s) that move |
|---------------------|--------------------------|
| The routing matrix UI (cell menu, headers, Add overlay, bottom bar) | `05-routing-matrix.md` |
| Filter panel, mapping types, MIDI Learn flow | `06-filters-and-mappings.md`, `C-appendix-midi-mapping-reference.md` |
| **A built-in plugin** (params, behaviour) | `07-plugins.md` (table + concept), `A-appendix-plugin-reference.md` (param table) |
| **A new built-in plugin** | `07-plugins.md` (add table row, summary), new section in `A-appendix-plugin-reference.md` |
| **A controller template** (cells, drop buttons) | `08-controllers.md`, `B-appendix-controller-reference.md` |
| Play surfaces (Tracker / Arpeggiator / Euclidean / Cartesian) | `09-play-surfaces.md`, `A-appendix-plugin-reference.md` (per-plugin param tables; shared Setup params live in the appendix preamble) |
| Bluetooth pairing / bridge | `10-bluetooth-midi.md` |
| Save / Load / Export / Import Config, autosave, **Backup checkpoints** | `11-saving-and-exporting-configs.md`, `05-routing-matrix.md` §5.10 |
| Settings page (hub, sub-pages, Plugin Control Mappings) | `12-settings.md` (Backup sub-page content lives in chapter 11) |
| Long-press CC binding popup / `default_cc` semantics | `07-plugins.md` §"CC Automation", `08-controllers.md` "Play Surface" |
| WiFi modes, captive portal, USB tether, update path, **WiFi fallback / `reset-wifi`** | `13-connectivity-and-updates.md` |
| Read-only FS, LEDs, watchdog, failure modes | `14-appliance-reliability.md` |
| New REST endpoint, SSE event type, or API behaviour | `E-appendix-rest-and-sse-api.md` |
| Config schema (`DEFAULT_CONFIG`, new top-level key) | `17-technical-reference.md` |
| Architecture (new module, moved boundary) | `17-technical-reference.md` (UI-implementation notes: `docs/UI-INTERNALS.md`) |
| Pi model support, USB topology, BLE adapter handling | `02-hardware-and-connectors.md` (single home; `17-technical-reference.md` only points there) |
| Keyboard shortcut added / removed (Tracker note entry, ESC, ...) | `D-appendix-keyboard-shortcuts.md` |
| New tab in the bottom nav, or a tab made conditional | `03-interacting-with-the-web-ui.md` §3.2 |
| New UI control type (a new wheel-variant, a new editor) | `03-interacting-with-the-web-ui.md` §"The Controls" |
| **MIDI 2.0 / UMP** (badge, FB ports, Use-MIDI-2.0 toggle, MIDI-CI card) | `05-routing-matrix.md` (grid + device detail), `17-technical-reference.md` (UMP note + "MIDI 2.0 Kernel Requirements") |
| MIDI 2.0 resolution behaviour (filters, mappings, fine params) | `06-filters-and-mappings.md` + appendix C, `03-interacting-with-the-web-ui.md` (fine faders), `07-plugins.md` §"CC Automation" |
| `midi2` config keys (`force_midi1`, `ci_enabled`, `ci_disabled`) | `17-technical-reference.md` |

The README under `docs/manual/README.md` is the editor-facing
overview of the layout. Keep its file list current if you add or
remove chapters.

### How to apply

1. While implementing the change, open the relevant chapter(s)
   from the table above and edit them in the same commit. Do not
   defer "I'll update the docs later" -- it never happens.
2. If full prose for that section already exists, rewrite it to
   match the new behaviour. Outline-only sections (rare now) just
   get bullet edits.
3. **Cross-references.** When a chapter cross-links to another
   ("see chapter X.Y"), check that the target still says what you
   referenced. Renumbering or restructuring across chapters is
   the most common source of subtly-broken docs.
4. **Screenshots.**
   - If the UI moved enough that an existing screenshot is now
     misleading, regenerate it: `make screenshots`. By default this
     spins up a throwaway local demo (real ALSA + `snd-virmidi`
     virtual ports — no Pi needed) and shoots against it; override
     with `make screenshots TARGET=http://10.1.1.2` to shoot a running
     Pi instead. The script in `scripts/screenshots/run.py` factory-
     resets via the API, wires a curated cable scenario + populates the
     tracker, then walks a curated set of scenes — capturing light for
     every scene plus dark for the `DARK_SCENES` subset the website and
     manual reference (keep that set in sync with
     `website/index.html`'s `data-dark-src` entries). New captures fall
     under that flow when the scene is added.
   - If a screenshot is needed but cannot be regenerated by the
     existing scenes (hardware photos, theme grids, mid-edit
     states), add a `Screenshots needed` entry at the bottom of
     the chapter with the proposed filename and what the shot
     should show. Capture later from real hardware.
5. **Version bump.** When a release goes out, bump `version:` in
   `docs/manual/metadata.yaml` and the `Documented release` line
   in `docs/manual/README.md`. Bumping mid-development is also
   fine -- the field tracks the *running* build the manual was
   last verified against.
6. **CHANGELOG + manual are complementary.** The changelog is the
   terse one-liner per release; the manual is the prose. Both
   need to move together for user-visible changes.

### When the README conflicts with the manual

The manual under `docs/manual/` is the source of truth for
user-facing behaviour. `README.md` is the marketing-style overview
and links to the manual; when the README drifts, bring it back
in line with the manual or trim the duplication.

### Common drift traps -- learned the hard way

- **Stale screenshot filenames.** A feature got removed and the
  screenshot it referenced got deleted, but a doc still says
  `![Foo](screenshots/02-foo.png)`. Grep for the filename before
  deleting a screenshot.
- **"There is no X tab" / "Y was removed".** If a feature is
  removed, find every reference to it across the manual and the
  README. The grep target is the *feature name*, not the chapter
  title.
- **Plugin parameter ranges drift from code.** Appendix A tables
  are written from the plugin's `__init__.py` declarations.
  Bump the table when ranges or defaults change.
- **API reference is self-generating -- don't hand-copy routes.**
  The canonical endpoint list is served live at `/docs` +
  `/api/routes.json`, built by `WebServer.api_manifest()` from the
  registered routes. Each route carries `summary`, and (auto-derived
  live from the handler source) `params` (best-effort body fields +
  path actions, via `_extract_params`) and `source` (`file:line`, via
  `_source_ref`). Appendix E documents *that mechanism*, not a
  hand-maintained table. **`params` and `source` need no upkeep** --
  they are read from the live code every time. Only two things a code
  change must touch, in the same commit:
    - a new `@server.route(...)` needs a `summary="..."` argument
      (method + path alone still list, but write the summary);
    - a new `send_sse("...")` event needs a line in the `SSE_EVENTS`
      registry in `web.py` (a missing one is warn-logged at emit time).
  Never re-hand-write the route table into an appendix row.

### Why this matters

The manual exists because the README and the UI guide aren't
enough for a feature-dense appliance. A manual that drifts from
the software is worse than no manual at all -- users stop
trusting it and start relying on the source. Keeping it in sync
change-by-change is cheap; catching it up after months of drift
is not.

## Coding behaviour

The user-level rules from `~/.claude/CLAUDE.md` (check existing
code first, object to silent architectural sprawl, recommend a
refactor first when the goal is easier with one) apply here
unchanged.

## Python dependencies

The user-level rule from `~/.claude/CLAUDE.md` -- add new Python
packages to `requirements.txt` (this project uses
`pyproject.toml` `optional-dependencies`) and install into the
local `.venv`, never globally -- applies here unchanged.

## Config persistence, autosave & backups (design decisions)

Shipped in 4.7.0. These decisions were worked out carefully;
honour them unless the user revisits.

**Hard constraints of this appliance**
- **Hard power cuts are normal.** The Pi is switched off at the
  wall with no clean shutdown. We must resume the last edited
  state on boot, and any persistent write must survive a cut
  mid-write. (This is why the root + boot FS are read-only and we
  remount-rw only for the brief write window.)
- **No RTC.** Wall-clock time is never trustworthy. Never store an
  absolute date for user-facing "when" info -- store **uptime**
  (`/proc/uptime`) + **`boot_id`** (`/proc/sys/kernel/random/boot_id`)
  and show a relative "n ago" that is only valid within the current
  boot; older items show "before last reboot" and rely on a
  monotonic `#seq` for ordering.
- **The asyncio loop carries filtered/mapped MIDI + SSE + REST.**
  `json.dumps` (and pickle/orjson) **hold the GIL**, so a big encode
  blocks the loop *even on a worker thread* (a worker thread releases
  the GIL only *between* `json.dumps` calls, never inside one big C
  encode). Disk I/O (`mount`, `sync`) and `gzip` **release** the GIL,
  so they don't. Measured: a full config encode reached **~750 ms**
  on the Pi with a few trackers — enough to audibly jitter a
  filtered/mapped live part. So the cost to remove from the loop is
  **the encode**, not the I/O. The fix is to run it in a **forked
  child** with its own GIL on a non-isolated core (see *fork-on-save*
  below), so the loop never executes the encode at all.

**The three persistence tiers**
1. **`config.json`** -- the deliberate manual Save (single full
   JSON) + `config.json.bak`. The "committed checkpoint." The
   **"Load" button loads this**, not the autosave.
2. **`backups/backup-NNNNN.json.gz`** (+ `index.json`) -- rolling
   gzipped checkpoints written on each manual Save, last 50,
   each with a coarse **diff summary** vs the previous (counts of
   instruments / connections / mappings / device-names changed --
   *not* which knob). Restore + Download from Settings → Backup.
3. **`autosave-0/1.json.gz`** -- a **single-file ping-pong** resume
   snapshot, written debounced while editing, on clean shutdown,
   and **immediately after Load/Restore/Import**. Boot prefers the
   newest valid autosave → `config.json` → `.bak` → defaults.

**Why these specific choices**
- **Ping-pong (two slots), not one file.** A power cut can corrupt
  only the slot being written; the other holds the previous good
  state. gzip's CRC is the validity check (a torn write fails to
  decompress → use the other slot). This is the power-cut
  guarantee; keep it.
- **Single autosave file**, **not** per-instrument files + a
  tar.gz/zip container. Per-file would need an on-FAT transactional
  store (manifest commit, orphan GC when instruments are
  deleted/restored-away, per-file A/B) -- a real bug surface. One
  ping-pong file has **zero cleanup story**.
- **fork-on-save, not an on-loop encode cache.** The background
  autosave `os.fork()`s; the **child** (its own interpreter → its own
  GIL) does the `json.dumps` + gzip + slot write, then `os._exit`.
  The child inherits the parent's memory **copy-on-write**, so
  `config._data` is visible with **no IPC and no serialisation on the
  loop** — the parent's only cost is the `fork()` syscall. The child
  first drops the loop's isolated-core affinity (inherited across
  fork) onto the housekeeping cores, so even a 750 ms encode steals
  nothing from MIDI. The parent advances the ping-pong seq at fork
  time, so a child that dies mid-write just leaves a torn slot that
  gzip-CRC rejects on boot — the prior good slot still wins.
  **This replaced an earlier per-instance JSON-fragment encode
  cache** (reuse the cached bytes of instruments whose `encode_seq`
  hadn't moved). The cache existed only to shrink the encode *while it
  ran on the loop's GIL*; once the encode moved off-process there was
  nothing left to shrink, so the whole cache + `encode_seq` plumbing
  was deleted. Fork-safety rules for the child: no asyncio, no logging
  (its lock may be held at fork time), no ALSA; exit via `os._exit`.
  The clean-shutdown flush stays **in-process synchronous** (the loop
  is going away; an in-process write can't be orphaned by the process
  exiting before a child finishes).
  **The deliberate Save and Load/Restore/Import fork too, but fork
  *and wait*** (`asave` → `_fork_save_and_wait`, `autosave_now`): the
  encode runs in the child off-core, the parent blocks on `waitpid`
  **on a worker thread** (a GIL-releasing syscall, so the loop keeps
  pumping MIDI), and the request returns only once the write is
  durable — the Save button reports the real outcome, never
  fire-and-forget. The Save child does the full `save()` work
  (config.json + `.bak` + a rolling backup), all GIL-heavy, all
  off-core.
- **One cross-process flock guards `_boot_rw`.** The autosave child
  and the Save child can now each open their own rw/ro remount window
  in parallel; two overlapping windows would let one remount the FS
  read-only while the other is mid-write. `_boot_rw` takes an `flock`
  on a tmpfs lockfile so the second writer waits for the first. It
  blocks only the child/worker doing the write, never the loop, and
  **must not be nested** within one process (the second flock would
  wait on the first's own fd forever).
- **JSON, not pickle/orjson.** Human-readable, dependency-free, and
  the encode is no longer on the hot path anyway. orjson/pickle were
  considered and rejected (orjson = a compiled arch+pyver-locked dep
  on an `_all` deb).
- **Pattern selection must not dirty (Lever 1).** A Trigger-Mode stem
  launch (and a Switch-mode tap) moves the pattern *pointer*
  (`selected_pattern`) + live *mirror* (`pages`) but does **not**
  change saveable content (the `patterns` bank). Decision (per the
  user, simplest): pattern **selection simply does not mark the tracker
  dirty** -- a **per-call quiet write** (`set_param(..., persist=False)`)
  that still SSE-broadcasts the value (display follows the launch) but
  skips the dirty hook.
  `selected_pattern`/`pages` stay **non-transient (serialised)**, so the
  active pattern is still saved on a deliberate Save (no `default_pattern`
  field). It must be per-call, **not** a per-param `transient` flag,
  because `pages` is changed by both launches (quiet) and recording
  (must dirty). Recording/clone/clear use normal `set_param` → they
  dirty as usual; no `persist_changed` mechanism.
  Net: pure stem-launching during a set triggers **no** autosave and
  **no** asterisk; only real edits do. (This is *not* the rejected idea
  of launches not switching the display -- the display still follows.)
- **Autosave after Load/Restore/Import is mandatory.** After those,
  the live state *is* the new state and the user expects it to be the
  resume point; a force-autosave closes the window where a cut would
  otherwise resume the pre-Load state.

**Threading**: MIDI routing is kernel ALSA port subscriptions;
plugins run on their own threads; clock/scheduled sends are
pre-queued to the ALSA queue (kernel-timed). So even before
fork-on-save an autosave encode only ever blipped **filtered/mapped
connections + the UI**, never clock/plugin/kernel-routed timing —
and fork-on-save removes that last blip too. The snapshot is still
built on the loop (cheap, shallow, race-free vs hotplug, which is
also on the loop); only `os.fork()` runs on the loop, after which
the encode+gzip+write happen in the forked child off the isolated
core.

## MIDI 2.0 / UMP (design decisions)

Implemented 2026-07, released as v6.0.0a1 (Steps 0–6 of the
PLAN-MIDI2.0 planning package — the directory was removed after the
merge; its README, FSDs and research annexes live in git history at
the `v6.0.0a1` tag if the spec details or kernel findings are ever
needed again). Honour these unless revisited:

**Hard invariants**
- **MIDI 1.0 behaviour is byte-identical, always.** Every hi-res path
  is golden-tested against the legacy path over the full 7-bit domain
  (`test_ump_filter_path.py`, `test_ump_cc_binding.py`,
  `test_hires_send.py`). Two projection rules keep this true, and
  they are NOT interchangeable: paths whose legacy code *rounded*
  use `from_midi_units` (mappings), paths whose legacy code
  *truncated* with `int()` use `midi_scale.lattice_interp`
  (generators). cc_smoother stayed 7-bit precisely because its
  legacy projection is round() and no floor-compatible flip exists
  yet — don't "fix" that without adding a round-compatible interp.
- **Graceful degradation is structural, not a flag.** Everything
  gates on `alsa_seq.probe_ump_support()` at runtime; on stock
  Raspberry Pi kernels (which ship ALL MIDI 2.0 configs off —
  upstream request: raspberrypi/linux#7474) the hub runs the
  untouched legacy code paths. Verified empirically on the 5A5D
  reference Pi. Never add a code path that assumes UMP exists.

**Architecture (D1/D2/D3 from the plan, approved)**
- Internal format is MIDI 2.0 width: the main seq client, the hi-res
  monitor client, and every plugin client run `midi_version=2` on
  capable kernels; the KERNEL does all 1.0↔2.0 conversion per
  receiving client (`seq_ump_convert.c` — spec-compliant, verified:
  velocity 100 → 0xC924). UMP events shim back to legacy-shaped
  events via `ump.to_monitor_shim` so downstream code is agnostic.
- User-facing scale is fractional 0–127 "MIDI units" (`63.5`), never
  raw 32-bit. Whole numbers serialise as ints → no config migration.
- The plugin API stays 0–127 ints (26 plugins + third parties);
  hi-res is opt-in per param (`fine=True, decimals=N`) and via float
  values to `send_cc`/`send_note_on`.

**Testing without MIDI 2.0 hardware**
- `scripts/fake_midi2_synth.py` is a full virtual MIDI 2.0 device
  (UMP endpoint + function blocks + hi-res CC sweep + MIDI-CI
  responder incl. Property Exchange). The device scan deliberately
  opts in user seq clients that declare a UMP endpoint with function
  blocks; the registry keys them `ump-<name>`. Use it for every
  MIDI 2.0 UX verification; two 3B+ test Pis cannot form a UMP link
  (host-only USB) and RTP-MIDI is 7-bit on the wire.
- MIDI-CI is point-to-point by design: `midi_ci.CiSession` uses a
  dedicated seq client subscribed to ONE device at a time. Never
  route CI SysEx through the routed graph (fan-out corrupts CI
  conversations) and never persist MUIDs (random per power-cycle;
  identity keys on `device_id.py` stable ids).

**Traps learned the hard way**
- ALSA constants: verify numeric values against the kernel uapi
  headers on the Pi, not against plausible-looking names —
  `SND_SEQ_EVENT_LENGTH_VARIABLE` was 0x01 (the TIME_STAMP_REAL bit)
  for the project's whole life and silently broke all SysEx TX until
  MIDI-CI hit it (fixed to 1<<2, 2026-07).
- `make kernelrelease` lies until `modules_prepare` regenerates
  `include/config/auto.conf`; kernel-module builds for the Pi live
  in `scripts/build-ump-modules.sh` + `scripts/kernel-build-notes.md`
  (vermagic, version-exact apt source, cross-M= symvers — all
  already solved there, don't re-derive). Re-run on the test Pi
  after every kernel upgrade, or MIDI 2.0 silently goes dormant.
  Upstream config request: raspberrypi/linux#7474 — answered
  2026-07-05 by PR raspberrypi/linux#7476 (adds
  `CONFIG_SND_USB_AUDIO_MIDI_V2=y` to all Pi defconfigs; `SND_UMP`
  and `SND_SEQ_UMP` follow via Kconfig select/defaults; trial build
  `sudo rpi-update pulls/7476`, test Pi only). Once merged and in
  the apt kernels, the module rebuild becomes unnecessary.
- `pkill -f` over ssh matches the ssh command line itself — use a
  `[b]racket` pattern.
