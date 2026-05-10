"""Regression: configs from 3.0.7 and earlier carry a `presets` dict.
The Presets feature was removed; loading such a config must still
succeed and the legacy key must be silently dropped so it doesn't
get re-persisted on the next save."""

import json

from raspimidihub import config as config_mod


def _write_legacy_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "version": 1,
        "mode": "all-to-all",
        "default_routing": "all",
        "connections": [
            {"src_client": 14, "src_port": 0, "dst_client": 20, "dst_port": 0},
        ],
        "disconnected": [],
        "presets": {
            "Live Set A": {
                "connections": [{"src_client": 14, "src_port": 0,
                                 "dst_client": 24, "dst_port": 0}],
                "plugins": [],
            },
        },
        "wifi": {"mode": "ap", "ap_password": "midihub1"},
    }))
    return path


def test_legacy_config_with_presets_loads_cleanly(tmp_path, monkeypatch):
    legacy = _write_legacy_config(tmp_path)
    monkeypatch.setattr(config_mod, "RUNTIME_CONFIG", legacy)
    monkeypatch.setattr(config_mod, "PERSISTENT_CONFIG", tmp_path / "absent.json")

    cfg = config_mod.Config()
    assert cfg.load() is True
    assert cfg.fallback_active is False
    assert cfg.connections == [
        {"src_client": 14, "src_port": 0, "dst_client": 20, "dst_port": 0},
    ]
    # Legacy key dropped from in-memory state so it won't be re-saved.
    assert "presets" not in cfg.data
