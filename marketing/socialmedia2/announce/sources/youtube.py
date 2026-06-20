"""YouTube source — announce new playlist uploads via the public RSS feed.

The feed needs no API key and already carries the video description, so there's
nothing to scrape.
"""
import urllib.request
import xml.etree.ElementTree as ET

from .. import config
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'yt': 'http://www.youtube.com/xml/schemas/2015',
    'media': 'http://search.yahoo.com/mrss/',
}

_SYSTEM = (
    "You write short, upbeat Mastodon posts for RaspiMIDIHub, an open-source "
    "Raspberry Pi USB MIDI hub. 1-2 sentences, friendly and concrete, at most "
    "one emoji, NO hashtags, under 380 characters. Do not include any URL."
)


class YouTubeSource(Source):
    name = 'youtube'

    def _fetch(self) -> list:
        url = ('https://www.youtube.com/feeds/videos.xml?playlist_id='
               + config.YOUTUBE_PLAYLIST_ID)
        req = urllib.request.Request(
            url, headers={'User-Agent': 'raspimidihub-social/1.0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            root = ET.fromstring(r.read())
        videos = []
        for entry in root.findall('atom:entry', _NS):
            vid = entry.findtext('yt:videoId', namespaces=_NS)
            if not vid:
                continue
            group = entry.find('media:group', _NS)
            desc = (group.findtext('media:description', default='', namespaces=_NS)
                    if group is not None else '')
            videos.append({
                'id': vid,
                'title': (entry.findtext('atom:title', namespaces=_NS) or '').strip(),
                'description': (desc or '').strip(),
                'url': f'https://www.youtube.com/watch?v={vid}',
            })
        return videos  # newest first

    def find_new(self, state) -> list:
        videos = self._fetch()
        if not state.seeded(self.name):
            state.seed(self.name, [v['id'] for v in videos])
            return []  # first run: establish baseline, announce nothing
        fresh = [v for v in videos if not state.is_announced(self.name, v['id'])]
        fresh.reverse()  # oldest-first so a backlog posts in order
        return fresh

    def latest(self) -> list:
        return self._fetch()[:1]

    def render(self, item, llm) -> Post:
        user = (f"New YouTube video.\nTitle: {item['title']}\n\n"
                f"Description:\n{item['description'][:1200]}\n\n"
                "Write only the announcement text.")
        text = llm_or_template(
            llm, _SYSTEM, user,
            fallback=f"New video: {item['title']}", max_len=380)
        return Post(text=append_link(f"📺 {text}", item['url']),
                    source=self.name, dedupe_key=item['id'])
