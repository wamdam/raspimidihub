"""Manual Features source — posts features directly from the manual database.

This source reads the features-database.json file and rotates through all 87
features in random order, posting one every 12 hours. No LLM clustering, no
changelog parsing — just pure manual content.

Each feature is posted once per cycle, then the cycle restarts. The system is
deterministic: the same feature always produces the same post.
"""
import hashlib
import json
import random
from pathlib import Path

from .. import config, content
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = (
    "You write engaging spotlights about RaspiMIDIHub features for hardware "
    "enthusiasts and musicians. Describe what the feature does and why it's "
    "useful in concrete terms. ONE or TWO short sentences. Do NOT write like "
    "an advertisement: no hype words (seamless, effortless, instantly, unleash, "
    "transform, supercharge, elevate, experience, game-changer), no second-person "
    "sales pitch ('turn your...', 'expand your...'). No hashtags, no URLs. "
    "At most one emoji, only if it fits naturally. Stay under 280 characters."
)

_SELECT_SYSTEM = (
    "You match a software feature to the single most relevant screenshot from a "
    "fixed list. Reply with ONLY the exact filename from the list, or the word "
    "NONE if no screenshot genuinely shows this feature. Output nothing else."
)


def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class ManualFeaturesSource(Source):
    """Source that posts features from the manual database in random order."""
    name = 'manual-features'

    def _load_database(self) -> list:
        """Load the features database from the manual."""
        # Path: announce/sources/manual_features.py -> ../features_database.json
        db_path = Path(config.PKG_DIR) / 'features_database.json'
        try:
            with open(db_path, 'r') as f:
                data = json.load(f)
            return data.get('features', [])
        except Exception as e:
            print(f"Warning: Failed to load features database: {e}")
            return []

    def _load_screenshot_catalog(self) -> list:
        """Load the screenshot catalog for matching."""
        return content.screenshot_catalog()

    def find_new(self, state) -> list:
        """Find the next unposted feature in random order."""
        features = self._load_database()
        if not features:
            return []
        
        # Filter out already posted features
        unposted = [f for f in features if not state.is_announced(self.name, f['id'])]
        
        if not unposted:
            # Cycle exhausted, reset and start over
            state.reset(self.name)
            unposted = features
        
        # Pick one random feature
        selected = random.choice(unposted)
        return [selected]

    def latest(self) -> list:
        """Return the first feature for --force testing."""
        features = self._load_database()
        return [features[0]] if features else []

    def _select_screenshot(self, feature, llm, catalog) -> dict | None:
        """Ask the LLM to pick the best screenshot for this feature."""
        if not catalog:
            return None
        
        # If the feature has a screenshot field, use it directly
        if feature.get('screenshot'):
            by_name = {c['name']: c for c in catalog}
            return by_name.get(feature['screenshot'])
        
        # Otherwise, ask LLM to match
        listing = "\n".join(f"{c['name']} — {c['caption']}" for c in catalog)
        user = (f"Feature: {feature['title']}\n"
                f"Description: {feature['description']}\n\n"
                "Screenshots (filename — what it shows):\n"
                f"{listing}\n\n"
                "Which ONE filename best shows this feature? "
                "Reply with the filename only, or NONE.")
        
        out = llm.generate(_SELECT_SYSTEM, user, temperature=0.0, max_tokens=40) or ''
        m = re.search(r'[A-Za-z0-9_-]+\.png', out)
        if not m:
            return None
        
        by_name = {c['name']: c for c in catalog}
        return by_name.get(m.group(0))

    def render(self, feature, llm) -> Post:
        """Render a feature into a post."""
        # Try to find a matching screenshot
        shot = self._select_screenshot(feature, llm, self._load_screenshot_catalog())
        
        # Build the user prompt with detailed text from the manual
        user = f"Spotlight this RaspiMIDIHub feature:\n{feature['title']}\n\n"
        user += f"Description:\n{feature['description']}\n\n"
        
        if feature.get('detailed_text'):
            user += (f"Reference from the manual:\n"
                     f'"""\n{feature["detailed_text"]}\n"""\n')
        
        user += "\nWrite only the post text."
        
        text = llm_or_template(llm, _SYSTEM, user, 
                               fallback=feature['description'], 
                               max_len=280, temperature=0.5)
        
        post = Post(
            text=append_link(text, config.SITE_URL),
            source=self.name,
            dedupe_key=feature['id']  # Use feature ID as dedupe key
        )
        
        if shot:
            data = content.read_bytes(shot['file'])
            if data:
                post.media_bytes = data
                post.media_mime = 'image/png'
                post.media_desc = shot['caption'][:400]
        
        return post
