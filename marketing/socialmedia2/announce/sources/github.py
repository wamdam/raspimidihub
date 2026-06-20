"""GitHub source — announce new releases via the public REST API (no auth).

60 unauthenticated requests/hour is plenty for an hourly check. Set
SOCIAL_GITHUB_TOKEN in the env if you ever hit the limit.
"""
import json
import os
import urllib.request

from .. import config
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = (
    "You write concise, exciting Mastodon release announcements for "
    "RaspiMIDIHub, an open-source Raspberry Pi USB MIDI hub. 2-3 sentences, "
    "highlight the 1-2 most user-facing changes, at most one emoji, NO "
    "hashtags, under 420 characters. Do not include any URL."
)


class GithubSource(Source):
    name = 'github'

    def _fetch(self) -> list:
        url = (f'https://api.github.com/repos/{config.GITHUB_REPO}'
               '/releases?per_page=10')
        headers = {'Accept': 'application/vnd.github+json',
                   'User-Agent': 'raspimidihub-social/1.0'}
        token = os.environ.get('SOCIAL_GITHUB_TOKEN')
        if token:
            headers['Authorization'] = f'Bearer {token}'
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        return [{
            'tag': x['tag_name'],
            'name': x.get('name') or x['tag_name'],
            'body': x.get('body') or '',
            'url': x['html_url'],
        } for x in data if not x.get('draft')]  # newest first

    def find_new(self, state) -> list:
        releases = self._fetch()
        if not state.seeded(self.name):
            state.seed(self.name, [r['tag'] for r in releases])
            return []
        fresh = [r for r in releases if not state.is_announced(self.name, r['tag'])]
        fresh.reverse()
        return fresh

    def latest(self) -> list:
        return self._fetch()[:1]

    def render(self, item, llm) -> Post:
        user = (f"New release {item['name']}.\n\n"
                f"Release notes:\n{item['body'][:2000]}\n\n"
                "Write only the announcement text.")
        text = llm_or_template(
            llm, _SYSTEM, user,
            fallback=f"RaspiMIDIHub {item['name']} is out!", max_len=420)
        return Post(text=append_link(f"🚀 {text}", item['url']),
                    source=self.name, dedupe_key=item['tag'])
