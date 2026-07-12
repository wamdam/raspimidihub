"""Features source — LLM clusters changelog entries into topics, then renders
one consolidated post per topic.

Instead of posting individual changelog entries (which causes repetition like
the 6 link-local IP posts), we:
1. Ask the LLM to cluster all entries into coherent topics
2. Track topics (not entries) in state
3. Render ONE consolidated post per topic that tells the complete story
"""
import hashlib
import json
import re

from .. import config, content
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = (
    "You announce a change in RaspiMIDIHub, an open-source Raspberry Pi USB "
    "MIDI hub, in the plain voice of its developer talking to fellow musicians. "
    "For features: describe concretely what it does and why it is useful. "
    "For fixes: explain what problem was solved. Ground your description in "
    "the reference notes from the manual. ONE or TWO short sentences. Do NOT "
    "write like an advertisement: no hype words (seamless, effortless, "
    "instantly, unleash, transform, supercharge, elevate, experience, "
    "game-changer), no second-person sales pitch ('turn your...', 'expand "
    "your...'). No hashtags, no URL. At most one emoji, only if it fits "
    "naturally. Stay under 280 characters."
)

# Pick the single best screenshot for a feature from the captioned catalog.
_SELECT_SYSTEM = (
    "You match a software feature to the single most relevant screenshot from a "
    "fixed list. Reply with ONLY the exact filename from the list, or the word "
    "NONE if no screenshot genuinely shows this feature. Output nothing else."
)

# Cluster changelog entries into topics
_CLUSTER_SYSTEM = (
    "You are a technical content curator. Your job is to GROUP changelog entries "
    "into coherent announcement topics.\n\n"
    "CRITICAL: Multiple entries about the SAME topic must be grouped together.\n"
    "Examples:\n"
    "- All entries about 'link-local IP' or '169.254' = ONE topic\n"
    "- All entries about 'Network MIDI' = ONE topic\n"
    "- All entries about 'MIDI 2.0' = ONE topic\n"
    "- All entries about 'WiFi' or 'AP' = ONE topic\n\n"
    "Output format: A JSON object where keys are topic titles and values are "
    "brief descriptions. Example:\n"
    '{\n  "Link-local IP for direct Ethernet cables": "Fixed across multiple versions",\n'
    '  "MIDI 2.0 groundwork": "32-bit resolution and UMP support"\n}'
)

_CLUSTER_USER = """
Here are the recent changelog entries grouped by version. GROUP them into topics.

{changelog_json}

Return ONLY a JSON object. Keys are topic titles, values are brief descriptions.
Do NOT return an array.
"""

# Render a topic into a post
_TOPIC_RENDER_SYSTEM = (
    "You announce RaspiMIDIHub changes to hardware enthusiasts and musicians. "
    "You are given a TOPIC that may span multiple versions and entries. Write ONE "
    "engaging post that tells the complete story without repetition.\n\n"
    "Guidelines:\n"
    "- ONE or TWO short sentences (≤280 chars)\n"
    "- Concrete: what does it do, what problem was solved?\n"
    "- Tone: developer talking to fellow tinkerers, not marketing\n"
    "- No hype words (seamless, unleash, transform, game-changer)\n"
    "- No second-person sales pitch\n"
    "- No hashtags, no URLs\n"
    "- At most one emoji, only if natural\n"
    "- If this is a bug fix story across versions, tell the RESOLVED state, "
    "not the journey (e.g., 'Direct Ethernet cables now work reliably' not "
    "'We fixed this three times')\n\n"
    "Output: Only the post text."
)

_TOPIC_RENDER_USER = """
Announce this topic (RaspiMIDIHub):

Topic: {topic_title}

Entries in this topic:
{entries_text}

Write ONE consolidated post that captures the full story without repetition.
"""


def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class FeaturesSource(Source):
    name = 'features'

    def _candidates(self) -> list:
        """Parse all CHANGELOG 'Added'/'Improved'/'Fix' lines into items."""
        text = content.read_text('CHANGELOG.txt') or ''
        items = []
        for block in re.split(r'\n(?=\d{4}-\d{2}-\d{2})', text):
            m = re.match(r'(\d{4}-\d{2}-\d{2}) —?-? Version ([\d.a-z]+)', block, re.I)
            if not m:
                continue
            version = m.group(2)
            for line in block.splitlines():
                lm = re.match(r'-\s*(Added|Improved|Fix):\s*(.+)', line.strip(), re.S)
                if not lm:
                    continue
                body = lm.group(2).strip()
                items.append({
                    'kind': lm.group(1).lower(),
                    'version': version,
                    'text': body,
                    'key': _key(body),
                })
        return items

    def _cluster_topics(self, llm) -> list:
        """Ask LLM to group all changelog entries into topics."""
        entries = self._candidates()
        
        # Limit to recent entries to avoid overwhelming the LLM
        # (CHANGELOG has 390+ entries, we only need the most recent ~50)
        entries = entries[:50]
        
        # Format entries for the LLM
        by_version = {}
        for entry in entries:
            v = entry['version']
            if v not in by_version:
                by_version[v] = []
            by_version[v].append(entry)
        
        changelog_json = json.dumps(by_version, indent=2)
        user = _CLUSTER_USER.format(changelog_json=changelog_json)
        
        try:
            out = llm.generate(_CLUSTER_SYSTEM, user, temperature=0.2, max_tokens=2000)
        except Exception:
            out = None
        
        if not out:
            # Fallback: return each entry as its own topic
            return [{'id': _key(e['text']), 'title': e['text'][:50], 'entries': [e]} 
                    for e in entries[:10]]
        
        # Parse JSON response
        try:
            data = json.loads(out)
            
            # Handle both object format {title: description} and array format
            validated = []
            if isinstance(data, dict):
                # Object format: {topic_title: topic_description}
                for title, desc in data.items():
                    # Find entries that match this topic
                    matching_entries = []
                    topic_lower = title.lower()
                    for entry in entries:
                        text_lower = entry['text'].lower()
                        # Simple keyword matching to assign entries to topics
                        if any(word in text_lower for word in topic_lower.split() if len(word) > 3):
                            matching_entries.append(entry)
                    
                    if not matching_entries:
                        # Fallback: assign first few entries
                        matching_entries = entries[:3]
                    
                    validated.append({
                        'id': _key(title),
                        'title': title,
                        'description': desc if isinstance(desc, str) else '',
                        'entries': matching_entries[:5]  # Limit entries per topic
                    })
            elif isinstance(data, list):
                # Array format: [{id, title, entries}, ...]
                for topic in data:
                    if isinstance(topic, dict) and 'id' in topic and 'entries' in topic:
                        validated.append(topic)
            
            return validated if validated else [{'id': _key(e['text']), 'title': e['text'][:50], 'entries': [e]} 
                                               for e in entries[:10]]
        except (json.JSONDecodeError, TypeError):
            # Fallback: return each entry as its own topic
            return [{'id': _key(e['text']), 'title': e['text'][:50], 'entries': [e]} 
                    for e in entries[:10]]

    def find_new(self, state, llm) -> list:
        """Find new topics to announce (not individual entries)."""
        topics = self._cluster_topics(llm)
        
        # Filter out already-posted topics
        unposted = [t for t in topics if not state.is_announced(self.name, t['id'])]
        
        if not unposted:  # cycle exhausted -> start over
            state.reset(self.name)
            unposted = topics
        
        return unposted[:1]  # One topic per run

    def latest(self) -> list:
        """Return the most recent topic for --force testing."""
        # Just return the first entry as a single-topic fallback
        items = self._candidates()
        if items:
            return [{'id': _key(items[0]['text']), 'title': items[0]['text'][:50], 
                     'entries': [items[0]]}]
        return []

    def _select_screenshot(self, item, llm, catalog):
        """Ask the LLM to pick the best-matching screenshot from the captioned
        catalog. Returns a catalog entry or None (no shot beats no shot)."""
        if not catalog:
            return None
        
        # Use the first entry's text for screenshot matching
        entry_text = item['entries'][0]['text'] if item['entries'] else item.get('title', '')
        
        listing = "\n".join(f"{c['name']} — {c['caption']}" for c in catalog)
        user = (f"Feature: {entry_text}\n\n"
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

    def _manual_notes(self, shot) -> str:
        """Prose around the chosen screenshot in its manual chapter — the
        accurate description we ground the post copy in."""
        if not shot or not shot.get('chapter'):
            return ''
        txt = content.read_text(shot['chapter']) or ''
        if not txt:
            return ''
        idx = txt.find(shot['name'])
        if idx == -1:
            return txt[:3500]
        return txt[max(0, idx - 3000):idx + 1200]

    def render(self, topic, llm) -> Post:
        """Render a topic (consolidated entries) into a single post."""
        # Select screenshot based on the first entry
        shot = self._select_screenshot(topic, llm, content.screenshot_catalog())
        notes = self._manual_notes(shot)
        
        # Build consolidated entries text
        entries_text = "\n".join(
            f"v{e['version']} ({e['kind']}): {e['text']}"
            for e in topic['entries']
        )
        
        # Add topic description if available
        user = f"Announce this topic (RaspiMIDIHub):\n\n"
        user += f"Topic: {topic['title']}\n"
        if topic.get('description'):
            user += f"Description: {topic['description']}\n\n"
        user += f"Related changelog entries:\n{entries_text}\n\n"
        user += "Write ONE consolidated post that captures the full story without repetition."
        
        text = llm_or_template(llm, _TOPIC_RENDER_SYSTEM, user, 
                               fallback=topic['title'], max_len=280, temperature=0.5)
        
        post = Post(
            text=append_link(text, config.SITE_URL),
            source=self.name,
            dedupe_key=topic['id']  # Track by topic, not entry
        )
        
        if shot:
            data = content.read_bytes(shot['file'])
            if data:
                post.media_bytes = data
                post.media_mime = 'image/png'
                post.media_desc = shot['caption'][:400]
        
        return post
