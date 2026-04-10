"""Configuration persistence for RaspiMIDIHub.

Config is stored on the boot partition (FAT32) and operated from a tmpfs copy.
Save flow: write tmpfs temp -> validate -> remount rw -> copy -> sync -> remount ro -> backup
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

PERSISTENT_DIR = Path("/boot/firmware/raspimidihub")
PERSISTENT_CONFIG = PERSISTENT_DIR / "config.json"
RUNTIME_DIR = Path("/run/raspimidihub")
RUNTIME_CONFIG = RUNTIME_DIR / "config.json"

MAX_PRESETS = 100
MAX_PRESET_SIZE = 64 * 1024  # 64 KB

DEFAULT_CONFIG = {
    "version": 1,
    "mode": "all-to-all",
    "default_routing": "all",
    "connections": [],
    "disconnected": [],
    "presets": {},
    "wifi": {
        "mode": "ap",
        "ap_ssid": "",
        "ap_password": "midihub1",
        "client_ssid": "",
        "client_password": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, returning new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    """Manages configuration with persistent storage on the boot partition."""

    def __init__(self):
        self._data: dict = DEFAULT_CONFIG.copy()
        self._fallback_active = False

    @property
    def data(self) -> dict:
        return self._data

    @property
    def fallback_active(self) -> bool:
        return self._fallback_active

    @property
    def mode(self) -> str:
        return self._data.get("mode", "all-to-all")

    @property
    def default_routing(self) -> str:
        return self._data.get("default_routing", "all")

    @property
    def connections(self) -> list:
        return self._data.get("connections", [])

    @property
    def disconnected(self) -> list:
        return self._data.get("disconnected", [])

    @property
    def presets(self) -> dict:
        return self._data.get("presets", {})

    @property
    def wifi(self) -> dict:
        return self._data.get("wifi", DEFAULT_CONFIG["wifi"])

    def load(self) -> bool:
        """Load config from runtime copy, falling back to persistent, then defaults.
        Returns True if config loaded successfully, False if fell back to defaults.
        """
        # Try runtime copy first
        for path in (RUNTIME_CONFIG, PERSISTENT_CONFIG, PERSISTENT_CONFIG.with_suffix(".json.bak")):
            if path.is_file():
                try:
                    raw = path.read_text()
                    data = json.loads(raw)
                    if not isinstance(data, dict) or "version" not in data:
                        log.warning("Invalid config at %s, trying next", path)
                        continue
                    self._data = _deep_merge(DEFAULT_CONFIG, data)
                    self._fallback_active = False
                    log.info("Loaded config from %s", path)
                    return True
                except (json.JSONDecodeError, OSError) as e:
                    log.warning("Failed to load %s: %s", path, e)
                    continue

        # Fall back to defaults
        log.warning("No valid config found, using defaults (all-to-all)")
        self._data = DEFAULT_CONFIG.copy()
        self._fallback_active = True
        return False

    def save(self) -> bool:
        """Save config to persistent storage with rw/ro remount cycle.
        Returns True on success.
        """
        try:
            config_json = json.dumps(self._data, indent=2, ensure_ascii=False)

            # Validate by re-parsing
            json.loads(config_json)

            # Write to runtime copy first
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            tmp = RUNTIME_CONFIG.with_suffix(".tmp")
            tmp.write_text(config_json)
            tmp.replace(RUNTIME_CONFIG)

            # Remount boot partition rw, copy, remount ro
            try:
                subprocess.run(["mount", "-o", "remount,rw", "/boot/firmware"],
                               check=True, capture_output=True, timeout=5)
                PERSISTENT_DIR.mkdir(parents=True, exist_ok=True)

                # Backup existing config
                if PERSISTENT_CONFIG.is_file():
                    shutil.copy2(PERSISTENT_CONFIG, PERSISTENT_CONFIG.with_suffix(".json.bak"))

                # Write new config
                tmp_persistent = PERSISTENT_CONFIG.with_suffix(".tmp")
                tmp_persistent.write_text(config_json)
                tmp_persistent.replace(PERSISTENT_CONFIG)
                subprocess.run(["sync"], timeout=5)

            finally:
                subprocess.run(["mount", "-o", "remount,ro", "/boot/firmware"],
                               capture_output=True, timeout=5)

            self._fallback_active = False
            log.info("Config saved to %s", PERSISTENT_CONFIG)
            return True

        except Exception:
            log.exception("Failed to save config")
            return False

    def init_runtime_copy(self):
        """Copy persistent config to runtime tmpfs (called at boot via ExecStartPre)."""
        try:
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            if PERSISTENT_CONFIG.is_file():
                shutil.copy2(PERSISTENT_CONFIG, RUNTIME_CONFIG)
                log.info("Copied config to runtime: %s", RUNTIME_CONFIG)
        except PermissionError:
            log.warning("Cannot create %s (not root?), using in-memory config", RUNTIME_DIR)
            log.info("Copied config to runtime: %s", RUNTIME_CONFIG)

    def set_mode(self, mode: str):
        self._data["mode"] = mode

    def set_connections(self, connections: list):
        self._data["connections"] = connections

    # --- Presets ---

    def list_presets(self) -> list[str]:
        return list(self._data.get("presets", {}).keys())

    def get_preset(self, name: str) -> dict | None:
        return self._data.get("presets", {}).get(name)

    def save_preset(self, name: str, connections: list, plugins: list | None = None) -> bool:
        if len(self._data.get("presets", {})) >= MAX_PRESETS:
            return False
        if "presets" not in self._data:
            self._data["presets"] = {}
        preset = {"connections": connections}
        if plugins:
            preset["plugins"] = plugins
        self._data["presets"][name] = preset
        return True

    def delete_preset(self, name: str) -> bool:
        if name in self._data.get("presets", {}):
            del self._data["presets"][name]
            return True
        return False

    def export_preset(self, name: str) -> dict | None:
        preset = self.get_preset(name)
        if preset is None:
            return None
        result = {"name": name, "version": 1, "connections": preset.get("connections", [])}
        if "plugins" in preset:
            result["plugins"] = preset["plugins"]
        return result

    def import_preset(self, data: dict) -> str | None:
        """Import a preset from JSON data. Returns preset name or None on error."""
        name = data.get("name")
        connections = data.get("connections")
        if not name or not isinstance(connections, list):
            return None
        raw = json.dumps(data)
        if len(raw) > MAX_PRESET_SIZE:
            return None
        plugins = data.get("plugins", [])
        self.save_preset(name, connections, plugins=plugins)
        return name
