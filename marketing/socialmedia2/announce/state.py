"""JSON state store: per-source announced keys, seed flag, last-run timestamp.

Runs on a workstation/server with a real clock, so plain wall-clock time is
fine (unlike the appliance, which has no RTC).
"""
import json
import time

from . import config


class State:
    def __init__(self):
        self.path = config.STATE_FILE
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except (OSError, ValueError):
                pass
        return {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    def src(self, name: str) -> dict:
        return self.data.setdefault(
            name, {'announced': [], 'seeded': False, 'last_run': 0}
        )

    def is_announced(self, name: str, key: str) -> bool:
        return key in self.src(name)['announced']

    def mark(self, name: str, key: str):
        """Mark an item fully announced (delivered to every configured target)."""
        s = self.src(name)
        if key not in s['announced']:
            s['announced'].append(key)
            s['announced'] = s['announced'][-500:]
        s['seeded'] = True
        s.get('delivered', {}).pop(key, None)  # in-flight record no longer needed

    # Per-target delivery tracking, so a partial failure (e.g. Mastodon OK but
    # Discord down) retries only the target that failed — no double-posting.
    def delivered(self, name: str, key: str) -> list:
        return self.src(name).setdefault('delivered', {}).get(key, [])

    def mark_delivered(self, name: str, key: str, target: str):
        d = self.src(name).setdefault('delivered', {})
        d.setdefault(key, [])
        if target not in d[key]:
            d[key].append(target)

    def seed(self, name: str, keys: list):
        """First-run baseline: mark everything currently present as known, so we
        don't backfire a storm of old items. Announce only what appears later."""
        s = self.src(name)
        s['announced'] = list(dict.fromkeys(keys))[-500:]
        s['seeded'] = True

    def seeded(self, name: str) -> bool:
        return self.src(name)['seeded']

    def reset(self, name: str):
        self.src(name)['announced'] = []

    def due(self, name: str, interval: int) -> bool:
        return (time.time() - self.src(name)['last_run']) >= interval

    def touch(self, name: str):
        self.src(name)['last_run'] = time.time()
