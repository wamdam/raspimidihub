"""Features source — rotate through recent features & improvements, with a
matching screenshot, LLM-polished.

Unlike youtube/github (detect *new* items), this *rotates*: it picks the next
not-yet-posted feature/improvement from the recent changelog, and once the pool
is exhausted it starts the cycle over. The CHANGELOG one-liners are already
written as prose, so they make good LLM input; the manual is reachable via the
content layer (docs/manual/*.md) for richer spotlights later.
"""
import hashlib
import re

from .. import config, content
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

# Keyword -> screenshot filename fragment(s) (ported from the v1 generator).
_SCREENSHOT_MAP = {
    'routing': '01-routing',
    'matrix': '01-routing',
    'rack': '01-routing-rack',
    'arpeggiator': '09-plugin-arpeggiator',
    'lfo': '10-plugin-cc-lfo',
    'smoother': '11-plugin-cc-smoother',
    'chord': '12-plugin-chord',
    'clock': '13-plugin-master-clock',
    'delay': '14-plugin-midi-delay',
    'splitter': '15-plugin-note-splitter',
    'transpose': '16-plugin-note-transpose',
    'panic': '17-plugin-panic',
    'scale': '18-plugin-scale',
    'velocity': ['19-plugin-velocity', '20-plugin-velocity'],
    'controller': ['23-controller', '24-controller'],
    'xy': '24-controller-xy',
    'mixer': '23-controller-mixer',
    'settings': '04-settings',
    'filter': '05-filter',
    'mapping': ['07-mapping', '08-mapping'],
    'network': '06-device-detail',
    'plugin': ['09-plugin-', '10-plugin-'],
}

_SYSTEM = (
    "You write friendly, informative Mastodon posts spotlighting RaspiMIDIHub, "
    "an open-source Raspberry Pi USB MIDI hub. 1-2 sentences, lead with the "
    "concrete benefit to a musician, at most one emoji, NO hashtags, under 380 "
    "characters. Do not include any URL."
)


def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class FeaturesSource(Source):
    name = 'features'

    def _candidates(self) -> list:
        """Parse recent CHANGELOG 'Added'/'Improved' lines into items."""
        text = content.read_text('CHANGELOG.txt') or ''
        items = []
        for block in re.split(r'\n(?=\d{4}-\d{2}-\d{2})', text)[:8]:
            m = re.match(r'(\d{4}-\d{2}-\d{2}) — Version ([\d.a-z]+)', block, re.I)
            if not m:
                continue
            version = m.group(2)
            for line in block.splitlines():
                lm = re.match(r'-\s*(Added|Improved):\s*(.+)', line.strip(), re.S)
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

    def find_new(self, state) -> list:
        items = self._candidates()
        if not items:
            return []
        unposted = [it for it in items if not state.is_announced(self.name, it['key'])]
        if not unposted:                 # cycle exhausted -> start over
            state.reset(self.name)
            unposted = items
        return unposted[:1]              # one spotlight per run

    def latest(self) -> list:
        return self._candidates()[:1]

    def _screenshot(self, text: str):
        low = text.lower()
        shots = content.list_screenshots()
        for keyword, frag in _SCREENSHOT_MAP.items():
            if keyword not in low:
                continue
            for f in (frag if isinstance(frag, list) else [frag]):
                for path in shots:
                    if f in path.lower():
                        return path
        return None

    def render(self, item, llm) -> Post:
        kind = 'feature' if item['kind'] == 'added' else 'improvement'
        user = (f"Spotlight this {kind} (from v{item['version']}):\n{item['text']}\n\n"
                "Write only the post text.")
        text = llm_or_template(llm, _SYSTEM, user, fallback=item['text'], max_len=380)
        post = Post(text=append_link(text, config.SITE_URL),
                    source=self.name, dedupe_key=item['key'])
        rel = self._screenshot(item['text'])
        if rel:
            data = content.read_bytes(rel)
            if data:
                post.media_bytes = data
                post.media_mime = 'image/png'
                post.media_desc = f"RaspiMIDIHub screenshot: {item['text'][:120]}"
        return post
