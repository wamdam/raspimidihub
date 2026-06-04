"""Backup + autosave storage logic (config.py). The remount/FS bits are
redirected to a tmp dir and the boot rw/ro cycle is stubbed, so these
exercise the pure logic: diff summaries, rolling-backup pruning, and the
ping-pong autosave slot selection."""

import contextlib

import pytest

import raspimidihub.config as cfg


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point all persistent paths at a tmp dir and no-op the remount."""
    monkeypatch.setattr(cfg, "PERSISTENT_DIR", tmp_path)
    monkeypatch.setattr(cfg, "PERSISTENT_CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(cfg, "RUNTIME_DIR", tmp_path / "run")
    monkeypatch.setattr(cfg, "RUNTIME_CONFIG", tmp_path / "run" / "config.json")
    monkeypatch.setattr(cfg, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(cfg, "BACKUP_INDEX", tmp_path / "backups" / "index.json")
    monkeypatch.setattr(cfg, "AUTOSAVE_SLOTS",
                        (tmp_path / "autosave-0.json.gz", tmp_path / "autosave-1.json.gz"))
    monkeypatch.setattr(cfg, "_boot_rw", lambda: contextlib.nullcontext())
    return tmp_path


def _cfg(version=1, plugins=0, connections=0, mappings=0):
    conns = []
    for i in range(connections):
        m = [{"type": "channel_map", "src_channel": 1, "dst_channel": 2}
             for _ in range(mappings if i == 0 else 0)]
        conns.append({"src_client": i, "mappings": m})
    return {"version": version, "mode": "custom",
            "plugins": [{"id": f"p{i}"} for i in range(plugins)],
            "connections": conns}


# ---- diff summary -------------------------------------------------------

def test_diff_initial_when_no_prior():
    assert cfg.summarize_config_diff({}, _cfg()) == "(initial)"


def test_diff_no_changes():
    a = _cfg(plugins=2, connections=1)
    assert cfg.summarize_config_diff(a, dict(a)) == "(no changes)"


def test_diff_settings_changed_when_only_nonstructural():
    # Same instrument / connection / mapping / device-name counts, but a
    # plugin param differs (a renamed cell, a rebind, a knob edit…). The
    # four counts don't move, yet the config genuinely changed.
    a = _cfg(plugins=2, connections=1)
    b = _cfg(plugins=2, connections=1)
    b["plugins"][0]["params"] = {"rate": "1/8"}
    assert cfg.summarize_config_diff(a, b) == "settings changed"


def test_diff_structural_wins_over_settings_changed():
    # A structural delta is reported even if other things also changed.
    a = _cfg(plugins=2, connections=1)
    b = _cfg(plugins=3, connections=1)
    b["plugins"][0]["params"] = {"rate": "1/8"}
    assert cfg.summarize_config_diff(a, b) == "+1 instrument"


def test_diff_counts_added_and_removed():
    old = _cfg(plugins=2, connections=2, mappings=20)
    new = _cfg(plugins=3, connections=1, mappings=2)
    s = cfg.summarize_config_diff(old, new)
    assert "+1 instrument" in s
    assert "-1 connection" in s
    assert "-18 mappings" in s


def test_diff_singular_plural():
    assert "+1 mapping" in cfg.summarize_config_diff(_cfg(mappings=0, connections=1),
                                                     _cfg(mappings=1, connections=1))
    assert "+2 mappings" in cfg.summarize_config_diff(_cfg(mappings=0, connections=1),
                                                      _cfg(mappings=2, connections=1))


# ---- rolling backups ----------------------------------------------------

def test_backup_writes_index_and_summary(store):
    c = cfg.Config()
    c._data = _cfg(plugins=1)
    with cfg._boot_rw():
        c._write_backup_locked()
    c._data = _cfg(plugins=2, connections=1)
    with cfg._boot_rw():
        c._write_backup_locked()
    backups = c.list_backups()
    assert len(backups) == 2
    # Newest first; its summary reflects the change since the prior backup.
    assert backups[0]["seq"] == 2
    assert "+1 instrument" in backups[0]["summary"]
    assert "+1 connection" in backups[0]["summary"]
    # First backup has no prior → "(initial)".
    assert backups[1]["summary"] == "(initial)"


def test_backup_stores_uptime_not_walltime(store, monkeypatch):
    monkeypatch.setattr(cfg, "boot_id", lambda: "boot-AAA")
    monkeypatch.setattr(cfg, "uptime_seconds", lambda: 1000.0)
    c = cfg.Config()
    c._data = _cfg(plugins=1)
    with cfg._boot_rw():
        c._write_backup_locked()
    raw = c._read_backup_index()[0]
    assert raw["up"] == 1000 and raw["boot"] == "boot-AAA"
    assert "ts" not in raw  # no wall-clock date stored


def test_backup_relative_age_same_session(store, monkeypatch):
    monkeypatch.setattr(cfg, "boot_id", lambda: "boot-AAA")
    monkeypatch.setattr(cfg, "uptime_seconds", lambda: 1000.0)
    c = cfg.Config()
    c._data = _cfg(plugins=1)
    with cfg._boot_rw():
        c._write_backup_locked()
    # Same boot, 125s later → "125s ago".
    monkeypatch.setattr(cfg, "uptime_seconds", lambda: 1125.0)
    b = c.list_backups()[0]
    assert b["same_session"] is True
    assert b["age_seconds"] == 125


def test_backup_relative_age_other_session_is_none(store, monkeypatch):
    monkeypatch.setattr(cfg, "boot_id", lambda: "boot-AAA")
    monkeypatch.setattr(cfg, "uptime_seconds", lambda: 50.0)
    c = cfg.Config()
    c._data = _cfg(plugins=1)
    with cfg._boot_rw():
        c._write_backup_locked()
    # A reboot → different boot id, smaller uptime: no honest relative time.
    monkeypatch.setattr(cfg, "boot_id", lambda: "boot-BBB")
    monkeypatch.setattr(cfg, "uptime_seconds", lambda: 10.0)
    b = c.list_backups()[0]
    assert b["same_session"] is False
    assert b["age_seconds"] is None


def test_backup_roundtrip_data(store):
    c = cfg.Config()
    c._data = _cfg(plugins=3, connections=2, mappings=5)
    with cfg._boot_rw():
        c._write_backup_locked()
    seq = c.list_backups()[0]["seq"]
    assert c.backup_data(seq)["plugins"] == c._data["plugins"]


def test_backup_prunes_to_max(store, monkeypatch):
    monkeypatch.setattr(cfg, "MAX_BACKUPS", 5)
    c = cfg.Config()
    for i in range(8):
        c._data = _cfg(plugins=i)
        with cfg._boot_rw():
            c._write_backup_locked()
    backups = c.list_backups()
    assert len(backups) == 5
    # Kept the newest 5 (seq 4..8); oldest pruned.
    assert [b["seq"] for b in backups] == [8, 7, 6, 5, 4]
    assert not (store / "backups" / "backup-00001.json.gz").exists()


# ---- ping-pong autosave -------------------------------------------------

def test_autosave_alternates_slots_and_picks_newest(store):
    c = cfg.Config()
    c._data = _cfg(plugins=1)
    assert c.write_autosave()           # seq 1 → slot 1
    s1 = cfg.AUTOSAVE_SLOTS[1]
    c._data = _cfg(plugins=2)
    assert c.write_autosave()           # seq 2 → slot 0
    s0 = cfg.AUTOSAVE_SLOTS[0]
    assert s0.exists() and s1.exists()  # both slots populated (ping-pong)
    seq, data = c._read_autosave()
    assert seq == 2 and len(data["plugins"]) == 2


def test_autosave_falls_back_to_other_slot_when_newest_corrupt(store):
    c = cfg.Config()
    c._data = _cfg(plugins=1)
    c.write_autosave()                  # seq 1 → slot 1 (good)
    c._data = _cfg(plugins=2)
    c.write_autosave()                  # seq 2 → slot 0 (we corrupt it)
    cfg.AUTOSAVE_SLOTS[0].write_bytes(b"\x1f\x8b corrupt not-a-valid-gzip")
    seq, data = c._read_autosave()
    assert seq == 1 and len(data["plugins"]) == 1  # recovered the older good slot


def test_boot_load_prefers_autosave_over_saved(store):
    # Deliberate save on disk (plugins=1)...
    c = cfg.Config()
    c._data = _cfg(plugins=1)
    c.save()
    # ...plus a newer autosave (plugins=5).
    c._data = _cfg(plugins=5)
    c.write_autosave()
    fresh = cfg.Config()
    assert fresh.load() is True
    assert fresh._loaded_from_autosave is True
    assert len(fresh._data["plugins"]) == 5


def test_load_manual_ignores_autosave(store):
    c = cfg.Config()
    c._data = _cfg(plugins=1)
    c.save()                            # deliberate save = plugins 1
    c._data = _cfg(plugins=5)
    c.write_autosave()                  # autosave = plugins 5
    fresh = cfg.Config()
    assert fresh.load_manual() is True
    assert len(fresh._data["plugins"]) == 1   # the committed checkpoint, not autosave


# ---- autosave per-instance fragment cache -------------------------------

def _seqs(plugins):
    """Map each plugin's id → a starting encode_seq of 0."""
    return {p["id"]: 0 for p in plugins}


def test_autosave_fragment_payload_roundtrips(store):
    c = cfg.Config()
    c._data = _cfg(plugins=3, connections=2, mappings=4)
    assert c.write_autosave(_seqs(c._data["plugins"])) is True
    seq, data = c._read_autosave()
    # The hand-spliced payload must decode to exactly the same document.
    assert seq == 1
    assert data == c._data


def test_autosave_reencodes_only_changed_instance(store):
    c = cfg.Config()
    c._data = _cfg(plugins=4)
    calls = []
    orig = c._encode_instance
    c._encode_instance = lambda inst: calls.append(inst["id"]) or orig(inst)

    seqs = _seqs(c._data["plugins"])
    c.write_autosave(seqs)
    assert sorted(calls) == ["p0", "p1", "p2", "p3"]  # cold cache → all encoded

    # Edit one instance: bump its encode_seq + change its content.
    calls.clear()
    seqs["p2"] += 1
    c._data["plugins"][2]["edited"] = True
    c.write_autosave(seqs)
    assert calls == ["p2"]  # only the changed instance re-encoded

    # The reused fragments + the fresh one still roundtrip correctly.
    _, data = c._read_autosave()
    assert data["plugins"][2]["edited"] is True
    assert len(data["plugins"]) == 4


def test_autosave_pure_launch_reencodes_nothing(store):
    """A pure stem launch bumps no encode_seq → the next autosave reuses
    every cached fragment (zero re-encode), the scaling guarantee."""
    c = cfg.Config()
    c._data = _cfg(plugins=8)
    seqs = _seqs(c._data["plugins"])
    c.write_autosave(seqs)  # warm the cache
    calls = []
    orig = c._encode_instance
    c._encode_instance = lambda inst: calls.append(inst["id"]) or orig(inst)
    c.write_autosave(seqs)  # same seqs → nothing changed
    assert calls == []


def test_autosave_cache_evicts_deleted_instance(store):
    c = cfg.Config()
    c._data = _cfg(plugins=3)
    c.write_autosave(_seqs(c._data["plugins"]))
    assert set(c._autosave_frag_cache) == {"p0", "p1", "p2"}
    # Delete one instance; its stale fragment must be evicted.
    c._data["plugins"] = c._data["plugins"][:2]
    c.write_autosave(_seqs(c._data["plugins"]))
    assert set(c._autosave_frag_cache) == {"p0", "p1"}


def test_clear_autosave_cache_forces_reencode(store):
    c = cfg.Config()
    c._data = _cfg(plugins=2)
    seqs = _seqs(c._data["plugins"])
    c.write_autosave(seqs)
    c.clear_autosave_cache()
    calls = []
    orig = c._encode_instance
    c._encode_instance = lambda inst: calls.append(inst["id"]) or orig(inst)
    c.write_autosave(seqs)  # cleared cache → re-encode despite unchanged seqs
    assert sorted(calls) == ["p0", "p1"]


def test_autosave_without_seqs_still_roundtrips(store):
    """Back-compat / no-plugin-host path: plugin_seqs=None falls back to
    a plain full-document encode."""
    c = cfg.Config()
    c._data = _cfg(plugins=2, connections=1)
    assert c.write_autosave(None) is True
    seq, data = c._read_autosave()
    assert data == c._data


# ---- autosave "last written n ago" status -------------------------------

def test_autosave_status_none_before_first_write(store):
    c = cfg.Config()
    assert c.autosave_status() is None


def test_autosave_status_same_session(store, monkeypatch):
    monkeypatch.setattr(cfg, "boot_id", lambda: "boot-AAA")
    monkeypatch.setattr(cfg, "uptime_seconds", lambda: 100.0)
    c = cfg.Config()
    c._data = _cfg(plugins=1)
    assert c.write_autosave(None) is True
    # 30s later, same boot → "30s ago".
    monkeypatch.setattr(cfg, "uptime_seconds", lambda: 130.0)
    st = c.autosave_status()
    assert st == {"seq": 1, "age_seconds": 30, "same_session": True}


def test_autosave_status_other_session_after_reboot(store, monkeypatch):
    monkeypatch.setattr(cfg, "boot_id", lambda: "boot-AAA")
    monkeypatch.setattr(cfg, "uptime_seconds", lambda: 500.0)
    c = cfg.Config()
    c._data = _cfg(plugins=2)
    c.write_autosave(None)                 # stamped boot-AAA @ uptime 500
    # Reboot: a fresh process loads the slot under a new boot id + low
    # uptime. No honest relative time → age_seconds None, but the status
    # still surfaces (so the UI shows "before last reboot", not "none").
    monkeypatch.setattr(cfg, "boot_id", lambda: "boot-BBB")
    monkeypatch.setattr(cfg, "uptime_seconds", lambda: 12.0)
    fresh = cfg.Config()
    assert fresh.load() is True
    st = fresh.autosave_status()
    assert st is not None
    assert st["same_session"] is False
    assert st["age_seconds"] is None


def test_autosave_status_survives_fragment_cache_path(store, monkeypatch):
    """The spliced (fragment-cache) payload must also carry up/boot so a
    boot-time load can report the autosave age."""
    monkeypatch.setattr(cfg, "boot_id", lambda: "boot-CCC")
    monkeypatch.setattr(cfg, "uptime_seconds", lambda: 200.0)
    c = cfg.Config()
    c._data = _cfg(plugins=3)
    c.write_autosave(_seqs(c._data["plugins"]))   # fragment-splice path
    monkeypatch.setattr(cfg, "uptime_seconds", lambda: 245.0)
    fresh = cfg.Config()
    assert fresh.load() is True
    st = fresh.autosave_status()
    assert st["same_session"] is True
    assert st["age_seconds"] == 45
