"""Jokes source — generates MIDI-themed jokes via LLM every 9 hours.

This bot uses the LLM to create original MIDI/music-themed jokes for
Mastodon. No hardcoded jokes - the LLM generates fresh content each time.
"""
import hashlib

from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = (
    "You are a witty music technology comedian. Write a short, original joke "
    "about MIDI, synthesizers, DAWs, or music production. Keep it under 280 "
    "characters. No hashtags, no URLs. At most one emoji if it fits naturally."
)


def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class JokesSource(Source):
    name = 'jokes'

    def find_new(self, state) -> list:
        """Generate one new joke (state is used only for deduplication)."""
        # We always generate a new joke, but check if we've posted it before
        # The actual generation happens in render()
        return [{'seed': 'new_joke'}]

    def latest(self) -> list:
        return self.latest_joke()

    def latest_joke(self) -> list:
        """Generate the latest joke for --force testing."""
        return [{'seed': 'new_joke'}]

    def render(self, item, llm) -> Post:
        """Generate a MIDI-themed joke using the LLM."""
        user = "Write a short, funny MIDI-themed joke. Keep it under 280 characters."
        text = llm_or_template(
            llm, _SYSTEM, user,
            fallback="Why did the MIDI cable cross the road? To get to the other side! 🎹",
            max_len=280,
            temperature=0.8  # More creativity for jokes
        )
        dedupe_key = _key(text)
        return Post(
            text=append_link(text, "https://raspimidihub.com"),
            source=self.name,
            dedupe_key=dedupe_key
        )
