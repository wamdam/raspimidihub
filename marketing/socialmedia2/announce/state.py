"""JSON state store: per-source announced keys, seed flag, last-run timestamp.

Runs on a workstation/server with a real clock, so plain wall-clock time is
fine (unlike the appliance, which has no RTC).

Extended with category tracking and performance metrics for smart scheduling.
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

    # === Smart Scheduling Extensions ===

    def get_category_history(self, source: str) -> list:
        """Get the category history for a source."""
        return self.src(source).get('category_history', [])

    def log_post(self, source: str, category: str, performance: dict = None):
        """Log a post for performance tracking."""
        s = self.src(source)
        
        if 'category_history' not in s:
            s['category_history'] = []
        
        s['category_history'].append({
            'category': category,
            'timestamp': time.time(),
            'performance': performance or {},
        })
        
        # Keep last 100 posts
        s['category_history'] = s['category_history'][-100:]

    def get_category_stats(self, category: str) -> dict:
        """Get performance statistics for a category."""
        cat_key = f'{category}_stats'
        stats = self.data.get(cat_key, {'total_posts': 0, 'total_engagement': 0})
        
        if stats['total_posts'] > 0:
            stats['avg_engagement'] = stats['total_engagement'] / stats['total_posts']
        else:
            stats['avg_engagement'] = 0
        
        return stats

    def adjust_weights(self, category: str, hour: int, performance: dict):
        """Adjust category weights based on performance."""
        engagement = performance.get('likes', 0) + performance.get('reblogs', 0)
        
        stats = self.get_category_stats(category)
        if stats['avg_engagement'] > 0:
            multiplier = min(2.0, max(0.5, engagement / stats['avg_engagement']))
        else:
            multiplier = 1.0
        
        # Store adjusted weight
        if 'adjusted_weights' not in self.data:
            self.data['adjusted_weights'] = {}
        
        adj_key = f'{category}_{hour}'
        base_weight = 0.25  # Default base weight
        adjustment = (multiplier - 1.0) * 0.1
        self.data['adjusted_weights'][adj_key] = max(0.05, min(0.8, base_weight + adjustment))

    def get_adjusted_weight(self, category: str, hour: int) -> float:
        """Get adjusted weight for a category at a given hour."""
        adj_key = f'{category}_{hour}'
        return self.data.get('adjusted_weights', {}).get(adj_key, 0.25)
