"""Pattern-slot bank for play-surface plugins.

Both the Arpeggiator and the Euclidean plugin carry 8 pattern slots
that snapshot every play_only param. Switching slots replaces the
live state with the snapshot for the chosen slot. Edits to any
snapshotted param auto-write into the active slot (Tracker-style
"live working slot" semantics) — there is no separate Store action.

The helper here owns the snapshot / load / record-edit primitives;
the plugin defines `SLOT_PARAM_NAMES` (the play_only param names to
track) and forwards `on_param_change` calls plus the slot-trigger
hook from `on_note_on`.

Held notes, sustain state and clock position survive a slot switch —
the helper never touches `_held_notes`, `_physically_pressed`,
`_sustain_active`, the playhead counters, or anything else outside
the snapshot set.
"""

from __future__ import annotations

from typing import Any

# Number of slots in the bank. Matches the Tracker so the on-screen
# strip and the trigger-note list are the same shape across the three
# play-surface plugins.
SLOT_COUNT = 8


def init_slot_bank(plugin, snapshot_names: list[str]) -> None:
    """Ensure `_param_values["pattern_slots"]` is a list of SLOT_COUNT
    dicts, each carrying a snapshot of the play_only params in
    `snapshot_names`. Called from the plugin's `on_start` after legacy
    migrations. New installs get 8 clones of the current defaults so
    every slot is "full" from the first switch — there is no empty
    state. Existing saved configs keep whatever slots they stored.

    Also clamps `active_slot` to [0, SLOT_COUNT-1].
    """
    pv = plugin._param_values
    slots = pv.get("pattern_slots")
    if not isinstance(slots, list):
        slots = []
    # Grow / truncate to SLOT_COUNT.
    if len(slots) < SLOT_COUNT:
        default_snap = _current_snapshot(plugin, snapshot_names)
        while len(slots) < SLOT_COUNT:
            slots.append(dict(default_snap))
    elif len(slots) > SLOT_COUNT:
        slots = slots[:SLOT_COUNT]
    # Make sure each entry is a dict and covers every snapshot key.
    # Missing keys are filled from the current live value so a slot
    # written under an older plugin version still loads cleanly.
    for i, s in enumerate(slots):
        if not isinstance(s, dict):
            slots[i] = _current_snapshot(plugin, snapshot_names)
            continue
        for k in snapshot_names:
            if k not in s:
                s[k] = pv.get(k)
    pv["pattern_slots"] = slots

    try:
        idx = int(pv.get("active_slot") or 0)
    except (TypeError, ValueError):
        idx = 0
    pv["active_slot"] = max(0, min(SLOT_COUNT - 1, idx))


def _current_snapshot(plugin, snapshot_names: list[str]) -> dict[str, Any]:
    """Snapshot every param in `snapshot_names` from the plugin's
    current live values. Values are passed through dict() / list()
    deep-copy idioms so nested mutables (the StepEditor grid is a
    list of dicts) don't end up sharing references between slots."""
    pv = plugin._param_values
    out: dict[str, Any] = {}
    for k in snapshot_names:
        v = pv.get(k)
        if isinstance(v, list):
            out[k] = [dict(x) if isinstance(x, dict) else x for x in v]
        elif isinstance(v, dict):
            out[k] = dict(v)
        else:
            out[k] = v
    return out


def record_edit(plugin, snapshot_names: list[str],
                name: str, value: Any) -> None:
    """Called from the plugin's `on_param_change` for every param
    update. Writes the new value into the active slot's snapshot so
    the bank stays in sync with live state. No-op for params outside
    the snapshot set, and a no-op while a slot is mid-load (the load
    path sets `_loading_slot` to suppress feedback edits)."""
    if name not in snapshot_names:
        return
    if getattr(plugin, "_loading_slot", False):
        return
    pv = plugin._param_values
    slots = pv.get("pattern_slots")
    if not isinstance(slots, list) or not slots:
        return
    idx = int(pv.get("active_slot") or 0)
    if not (0 <= idx < len(slots)):
        return
    if not isinstance(slots[idx], dict):
        slots[idx] = {}
    # Deep-copy mutables so a future edit doesn't bleed into the
    # snapshot via the same reference.
    if isinstance(value, list):
        slots[idx][name] = [dict(x) if isinstance(x, dict) else x
                            for x in value]
    elif isinstance(value, dict):
        slots[idx][name] = dict(value)
    else:
        slots[idx][name] = value


def load_slot(plugin, snapshot_names: list[str], new_idx: int) -> None:
    """Switch to slot `new_idx`: write the slot's stored value back
    into every snapshotted param (broadcasts each via `set_param`
    plus invokes the plugin's `on_param_change` so side-effect logic
    — programmed-mode bookkeeping, algo-cache invalidation, etc. —
    stays in sync). Held notes, sustain state and the playhead are
    untouched.

    `_loading_slot` is set for the duration of the load so
    `record_edit` calls triggered downstream don't write the just-
    loaded value back into the slot (idempotent, just wasted)."""
    pv = plugin._param_values
    slots = pv.get("pattern_slots") or []
    new_idx = max(0, min(SLOT_COUNT - 1, int(new_idx)))
    if new_idx >= len(slots):
        return
    snap = slots[new_idx] or {}
    # Pre-set active_slot so any downstream record_edit writes to
    # the destination slot (suppressed via _loading_slot, but kept
    # consistent in case future code paths probe `active_slot`).
    pv["active_slot"] = new_idx
    plugin._loading_slot = True
    try:
        for k in snapshot_names:
            if k not in snap:
                continue
            plugin.set_param(k, snap[k])
            try:
                plugin.on_param_change(k, snap[k])
            except Exception:
                # Plugin-side side effects shouldn't break the load
                # — log via the plugin's own logger if it has one,
                # otherwise swallow.
                pass
    finally:
        plugin._loading_slot = False
    # Broadcast active_slot last so the UI animates the new
    # highlight after the rest of the surface has reflowed.
    plugin.set_param("active_slot", new_idx)


def trigger_note_index(plugin, channel: int, note: int) -> int | None:
    """If `note` on `channel` matches the slot-trigger setup (the
    pattern_ctrl_ch + per-slot pattern_note_N), return the slot index
    (0..SLOT_COUNT-1). Otherwise return None.

    The check mirrors the Tracker's pattern-trigger machinery: a
    dedicated control channel reserves the entire channel for slot
    selection, and a per-slot NoteSelect lets the user MIDI-Learn an
    individual note for each slot. Trigger notes are *consumed* by
    the caller — they don't reach the held-notes buffer."""
    ctrl_ch = int(plugin.get_param("pattern_ctrl_ch") or 0)
    if ctrl_ch == 0 or ctrl_ch - 1 != channel:
        return None
    for i in range(SLOT_COUNT):
        n = plugin.get_param(f"pattern_note_{i}")
        if n is None:
            continue
        if int(n) == int(note):
            return i
    return None
