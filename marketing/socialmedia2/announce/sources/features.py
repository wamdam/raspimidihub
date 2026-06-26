"""Features source — rotate through recent features & improvements, with a
matching screenshot, LLM-polished.

Unlike youtube/github (detect *new* items), this *rotates*: it picks the next
not-yet-posted feature/improvement from the recent changelog, and once the pool
is exhausted it starts the cycle over.

Both the copy and the screenshot are grounded in the user manual: the manual
embeds every screenshot with a written caption, so we let the LLM pick the best
shot from that captioned catalog (instead of brittle keyword matching), then
feed the surrounding chapter prose back in so the post describes the feature
accurately rather than as an advertisement.
"""
import hashlib
import re

from .. import config, content
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = (
    "You announce a feature of RaspiMIDIHub, an open-source Raspberry Pi USB "
    "MIDI hub, in the plain voice of its developer talking to fellow musicians. "
    "Describe concretely what the feature does and why it is useful, grounded "
    "in the reference notes from the manual. ONE or TWO short sentences. Do NOT "
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


def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class FeaturesSource(Source):
    name = 'features'

    def _candidates(self) -> list:
        """Parse recent CHANGELOG 'Added'/'Improved' lines into items."""
        text = content.read_text('CHANGELOG.txt') or ''
        items = []
        for block in re.split(r'\n(?=\d{4}-\d{2}-\d{2})', text)[:25]:
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

    def _select_screenshot(self, item, llm, catalog):
        """Ask the LLM to pick the best-matching screenshot from the captioned
        catalog. Returns a catalog entry or None (no shot beats no shot)."""
        if not catalog:
            return None
        listing = "\n".join(f"{c['name']} — {c['caption']}" for c in catalog)
        user = (f"Feature: {item['text']}\n\n"
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

    def render(self, item, llm) -> Post:
        shot = self._select_screenshot(item, llm, content.screenshot_catalog())
        notes = self._manual_notes(shot)
        kind = 'feature' if item['kind'] == 'added' else 'improvement'
        user = f"Announce this {kind} (RaspiMIDIHub v{item['version']}):\n{item['text']}\n"
        if notes:
            user += ("\nReference notes from the user manual (for accuracy — "
                     "summarise in your own words, do not quote):\n"
                     f'"""\n{notes}\n"""\n')
        user += "\nWrite only the post text."
        text = llm_or_template(llm, _SYSTEM, user, fallback=item['text'],
                               max_len=280, temperature=0.5)
        post = Post(text=append_link(text, config.SITE_URL),
                    source=self.name, dedupe_key=item['key'])
        if shot:
            data = content.read_bytes(shot['file'])
            if data:
                post.media_bytes = data
                post.media_mime = 'image/png'
                post.media_desc = shot['caption'][:400]
        return post
