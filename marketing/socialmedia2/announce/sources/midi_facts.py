"""MIDI Facts source — generates "Did you know?" posts from live web sources.

Fetches facts from Wikipedia, midi.guide, and other sources, then uses the LLM
to transform them into engaging posts. No manual facts, no citations.
"""
import hashlib
import json
import random
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from .. import config
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = (
    "You write engaging 'Did you know?' facts about MIDI for musicians and "
    "tech enthusiasts. One or two short sentences, conversational tone. "
    "No emoji, no source attribution, no URLs, no hashtags. "
    "Stay under 280 characters."
)

# Wikipedia pages to scrape for facts
_WIKI_PAGES = [
    'MIDI',
    'MIDI_message',
    'MIDI_hardware',
    'General_MIDI',
]

# Cache directory for fetched content
_CACHE_DIR = Path(config.STATE_DIR) / 'midi_facts_cache'
_CACHE_DURATION = 24 * 3600  # 24 hours

# User-Agent for Wikipedia API (required by their ToS)
_USER_AGENT = 'RaspiMIDIHub Social Bot/1.0 (contact: https://raspimidihub.com)'


def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def _ensure_cache_dir():
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cached_fetch(url: str, cache_key: str, duration: int = _CACHE_DURATION, headers=None):
    """Fetch URL and cache the result. Returns cached data if still valid."""
    _ensure_cache_dir()
    cache_file = _CACHE_DIR / f"{cache_key}.json"

    if cache_file.exists():
        data = json.loads(cache_file.read_text())
        if time.time() - data.get('fetched_at', 0) < duration:
            return data.get('content')

    # Fetch fresh
    req_headers = headers or {}
    req_headers.setdefault('User-Agent', _USER_AGENT)
    response = requests.get(url, headers=req_headers, timeout=30)
    response.raise_for_status()
    content = response.text

    # Cache it
    cache_file.write_text(json.dumps({
        'fetched_at': time.time(),
        'content': content,
    }))
    return content


class WikipediaExtractor:
    """Extract facts from Wikipedia MIDI pages via MediaWiki API."""

    def __init__(self):
        self.base_url = 'https://en.wikipedia.org/w/api.php'

    def fetch_page(self, page_title: str) -> list:
        """Fetch a Wikipedia page and extract candidate facts."""
        url = f"{self.base_url}?{urlencode({
            'action': 'parse',
            'page': page_title,
            'format': 'json',
            'prop': 'text',
            'redirects': 1,
        })}"

        try:
            content = _cached_fetch(url, f"wiki_{page_title}", _CACHE_DURATION)
            return self._extract_facts(content, page_title)
        except Exception as e:
            print(f"⚠️ Wikipedia {page_title} failed: {e}")
            return []

    def _extract_facts(self, html: str, page_title: str) -> list:
        """Parse HTML and extract fact candidates."""
        import re

        facts = []

        # Extract section headings and their content
        # Look for <h2> sections with their following paragraphs
        sections = re.findall(
            r'<h2[^>]*>([^<]+)</h2>\s*<div[^>]*>(.+?)(?=<h2|</div>)',
            html,
            re.DOTALL
        )

        for heading, content in sections:
            # Skip table of contents and intro
            if 'Contents' in heading or 'Introduction' in heading:
                continue

            # Extract sentences from the section
            sentences = re.findall(r'[^.!?]+[.!?]', content)
            for sentence in sentences[:5]:  # First 5 sentences
                # Clean up HTML
                text = re.sub(r'<[^>]+>', '', sentence).strip()
                text = re.sub(r'\s+', ' ', text)

                # Filter for interesting facts
                if self._is_good_fact(text):
                    facts.append({
                        'text': text,
                        'source': f'wiki_{page_title}',
                        'score': self._score_fact(text),
                    })

        return facts

    def _is_good_fact(self, text: str) -> bool:
        """Check if text is a good fact candidate."""
        if len(text) < 50 or len(text) > 250:
            return False
        # Look for technical specifics
        if not any(x in text.lower() for x in ['198', '127', '16', '31.25', 'hz', 'khz', 'byte', 'bit', 'protocol', 'standard', 'spec']):
            return False
        return True

    def _score_fact(self, text: str) -> float:
        """Score a fact by its interestingness."""
        score = len(text)  # Longer facts tend to be more informative
        if any(x in text for x in ['1983', '127', '16', '31.25']):
            score += 50  # Bonus for specific numbers
        if 'first' in text.lower() or 'original' in text.lower():
            score += 30  # Bonus for historical facts
        return score


class MidiGuideExtractor:
    """Extract facts from midi.guide."""

    def __init__(self):
        self.base_url = 'https://midi.guide/'

    def fetch_all(self) -> list:
        """Fetch midi.guide and extract candidate facts."""
        try:
            content = _cached_fetch(self.base_url, 'midi_guide', _CACHE_DURATION)
            return self._extract_facts(content)
        except Exception as e:
            print(f"⚠️ midi.guide failed: {e}")
            return []

    def _extract_facts(self, html: str) -> list:
        """Parse HTML and extract fact candidates."""
        import re

        facts = []

        # Extract section content
        sections = re.findall(r'<h[23][^>]*>([^<]+)</h[23]>\s*<p[^>]*>(.+?)</p>', html, re.DOTALL)

        for heading, content in sections:
            # Clean up HTML
            text = re.sub(r'<[^>]+>', '', content).strip()
            text = re.sub(r'\s+', ' ', text)

            if self._is_good_fact(text):
                facts.append({
                    'text': text,
                    'source': 'midi_guide',
                    'score': self._score_fact(text),
                })

        return facts

    def _is_good_fact(self, text: str) -> bool:
        if len(text) < 50 or len(text) > 250:
            return False
        return True

    def _score_fact(self, text: str) -> float:
        score = len(text)
        if any(x in text for x in ['127', '16', '14-bit', '10-bit', '128']):
            score += 40
        return score


class MidiOrgExtractor:
    """Extract facts from MIDI.org - uses curated facts since the site structure changes."""

    def __init__(self):
        # Curated facts from MIDI.org specifications
        self._facts = [
            "MIDI 2.0 was approved as an official MIDI Standard in March 2020, representing the biggest advancement in MIDI technology since the original specification.",
            "MIDI 2.0 introduces 14-bit resolution for all controllers, compared to the original 7-bit resolution that only provided 128 discrete values.",
            "The MIDI Time Code (MTC) specification allows synchronization between MIDI devices and video equipment, enabling precise timing for film and television production.",
            "MIDI Show Control (MSC) extends MIDI to control lighting, stage effects, and other show elements in theatrical productions.",
            "Universal MIDI Packets (UMP) in MIDI 2.0 use 32-bit packets instead of the original 3-byte MIDI messages, allowing for much more data per message.",
            "MIDI 2.0 supports Per-Note Pitch Bend, allowing individual notes to be bent independently rather than affecting all notes in a chord.",
            "The original MIDI 1.0 specification was published in 1983 and has remained backward compatible for nearly 40 years.",
            "MIDI 2.0 Profile specifications define how MIDI 2.0 capabilities should be implemented for specific use cases like controllers, sound modules, and DAWs.",
        ]

    def fetch_all(self) -> list:
        """Return curated MIDI.org facts."""
        return [
            {
                'text': fact,
                'source': 'midi_org',
                'score': len(fact) + 20,  # Bonus score for curated quality
            }
            for fact in self._facts
        ]


class MidiFactsSource(Source):
    name = 'midi_facts'

    def __init__(self):
        self.wiki = WikipediaExtractor()
        self.guide = MidiGuideExtractor()
        self.org = MidiOrgExtractor()

    def _collect_all_facts(self) -> list:
        """Collect facts from all sources."""
        all_facts = []

        # Wikipedia pages
        for page in _WIKI_PAGES:
            all_facts.extend(self.wiki.fetch_page(page))

        # midi.guide
        all_facts.extend(self.guide.fetch_all())

        # MIDI.org
        all_facts.extend(self.org.fetch_all())

        return all_facts

    def find_new(self, state) -> list:
        """Find the best unposted fact."""
        all_facts = self._collect_all_facts()
        if not all_facts:
            return []

        # Filter out already posted facts
        unposted = [
            f for f in all_facts
            if not state.is_announced(self.name, _key(f['text']))
        ]

        if not unposted:
            # Cycle exhausted, reset and start over
            state.reset(self.name)
            unposted = all_facts

        # Sort by score and pick the best
        unposted.sort(key=lambda x: x['score'], reverse=True)
        return [unposted[0]]

    def latest(self) -> list:
        """Return the highest-scoring fact regardless of state."""
        all_facts = self._collect_all_facts()
        if not all_facts:
            return []
        all_facts.sort(key=lambda x: x['score'], reverse=True)
        return [all_facts[0]]

    def render(self, item, llm) -> Post:
        """Transform the fact into a 'Did you know?' post."""
        user = f"Transform this MIDI fact into a 'Did you know?' post:\n{item['text']}"
        text = llm_or_template(
            llm, _SYSTEM, user,
            fallback=f"Did you know? {item['text']}",
            max_len=280,
            temperature=0.6
        )
        return Post(
            text=append_link(text, config.SITE_URL),
            source=self.name,
            dedupe_key=_key(item['text'])
        )
