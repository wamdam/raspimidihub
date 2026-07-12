"""Evergreen feature spotlights — highlight core features from the manual,
not just changelog entries.

This source rotates through the best features documented in the user manual,
ensuring new users and casual followers learn what the hub can do beyond
just bug fixes and version updates.
"""
import hashlib
import re

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


class EvergreenSource(Source):
    """Source that rotates through evergreen features from the manual."""
    name = 'evergreen'

    def _features_catalog(self) -> list:
        """Build a catalog of features from the manual.
        
        Each feature is a curated entry with:
        - id: unique identifier
        - title: short name
        - chapter: which manual chapter it's from
        - description: the core description
        - context: surrounding prose for grounding
        """
        catalog = []
        manual = content.manual_chapters()
        
        # Curated list of evergreen features to highlight
        # These are the "big ideas" worth posting about repeatedly
        feature_definitions = [
            {
                'id': 'routing-matrix',
                'title': 'Routing Matrix',
                'chapter': '05-routing-matrix.md',
                'description': (
                    "The Routing Matrix connects any MIDI source to any destination, "
                    "with per-connection filtering, channel remapping, and message-type "
                    "control. Hardware, Bluetooth, Network MIDI, and plugins all live "
                    "in the same grid."
                ),
                'keywords': ['matrix', 'routing', 'connection', 'filter', 'channel']
            },
            {
                'id': 'network-midi',
                'title': 'Network MIDI Mirroring',
                'chapter': '05-routing-matrix.md',
                'description': (
                    "Network MIDI exports any local device as an RTP-MIDI session, "
                    "automatically discovered by other hubs on the network. Mirror "
                    "devices from a second hub and route them as if they were local."
                ),
                'keywords': ['network', 'mirror', 'rtp-midi', 'remote', 'hub']
            },
            {
                'id': 'rack-view',
                'title': 'Rack View',
                'chapter': '05-routing-matrix.md',
                'description': (
                    "Rack view shows your MIDI gear as a 19-inch rack with cables "
                    "hanging between jacks. Tap or drag to patch, with live highlights "
                    "for spectators. Same connections as the matrix, just a different view."
                ),
                'keywords': ['rack', 'cable', 'patch', 'view', 'hardware']
            },
            {
                'id': 'play-surfaces',
                'title': 'Play Surfaces',
                'chapter': '09-play-surfaces.md',
                'description': (
                    "Three built-in play surfaces: Cartesian (2D grid sequencer), "
                    "Euclidean (Bjorklund rhythm generator), and Arpeggiator. All "
                    "share an 8-slot pattern bank for live performance switching."
                ),
                'keywords': ['arp', 'euclidean', 'cartesian', 'sequencer', 'pattern']
            },
            {
                'id': 'tracker',
                'title': 'Tracker',
                'chapter': '09-play-surfaces.md',
                'description': (
                    "The Tracker records and plays back MIDI with real note durations, "
                    "per-track release handling, and trigger modes that launch phrases "
                    "in sync without waiting for the bar. Free-run or sync to transport."
                ),
                'keywords': ['tracker', 'record', 'phrase', 'trigger', 'loop']
            },
            {
                'id': 'filters-mappings',
                'title': 'Filters & Mappings',
                'chapter': '06-filters-and-mappings.md',
                'description': (
                    "Per-connection filters control which messages pass through. "
                    "Mappings transform events: remap channels, transpose notes, "
                    "convert note velocity to CC, or apply velocity curves."
                ),
                'keywords': ['filter', 'mapping', 'transform', 'transpose', 'cc']
            },
            {
                'id': 'plugins',
                'title': 'Plugins',
                'chapter': '07-plugins.md',
                'description': (
                    "Built-in plugins: CC LFO, CC Smoother, Velocity Curve, Velocity "
                    "Equalizer, Pitch CC, MIDI Delay, Chord Generator, Clock Divider, "
                    "Master Clock, Latency, Note Splitter, Scale Remapper, Channel Selector."
                ),
                'keywords': ['plugin', 'lfo', 'smoother', 'velocity', 'delay']
            },
            {
                'id': 'autosave-backup',
                'title': 'Autosave & Backup',
                'chapter': '11-saving-and-exporting-configs.md',
                'description': (
                    "Autosave writes your live state in the background with double-buffered "
                    "ping-pong validation. Backup keeps the last 50 checkpoints with "
                    "structural diff summaries. Restore any checkpoint or download as JSON."
                ),
                'keywords': ['autosave', 'backup', 'restore', 'checkpoint', 'save']
            },
            {
                'id': 'spectator-mirroring',
                'title': 'Spectator Mirroring',
                'chapter': '04-quick-start.md',
                'description': (
                    "Spectator mirroring streams your UI to a browser tab or OBS. "
                    "Viewers see your exact screen with touches, scroll position, "
                    "and popups in real time. Optional phone bezel and chroma key."
                ),
                'keywords': ['spectator', 'mirror', 'stream', 'obs', 'view']
            },
            {
                'id': 'midi-learn',
                'title': 'MIDI Learn',
                'chapter': '08-controllers.md',
                'description': (
                    "MIDI Learn binds hardware controls to any plugin parameter or "
                    "controller cell. Long-press a control, hit Learn, move your knob. "
                    "Factory defaults documented; user bindings persist across reboots."
                ),
                'keywords': ['learn', 'bind', 'controller', 'knob', 'cc']
            },
            {
                'id': 'bluetooth-midi',
                'title': 'Bluetooth MIDI',
                'chapter': '10-bluetooth-midi.md',
                'description': (
                    "Bluetooth MIDI connects wirelessly to phones, tablets, and "
                    "controllers. The hub scans, pairs, and routes BLE MIDI devices "
                    "just like USB. Radio survives reboots; connections persist."
                ),
                'keywords': ['bluetooth', 'ble', 'wireless', 'pair', 'mobile']
            },
            {
                'id': 'light-dark-theme',
                'title': 'Light & Dark Themes',
                'chapter': '12-settings.md',
                'description': (
                    "Light and dark themes switch the entire UI, including canvas "
                    "drawings and control renderings. Theme tokens drive every color; "
                    "your choice persists in the browser."
                ),
                'keywords': ['theme', 'light', 'dark', 'color', 'display']
            },
        ]
        
        # Build catalog entries
        for feat in feature_definitions:
            chapter_text = content.read_text(f"docs/manual/{feat['chapter']}") or ''
            
            catalog.append({
                'id': feat['id'],
                'title': feat['title'],
                'chapter': f"docs/manual/{feat['chapter']}",
                'description': feat['description'],
                'context': chapter_text[:4000],  # Full chapter context
                'keywords': feat['keywords'],
                'key': _key(feat['id']),
            })
        
        return catalog

    def find_new(self, state) -> list:
        """Find the next unposted feature."""
        catalog = self._features_catalog()
        unposted = [f for f in catalog if not state.is_announced(self.name, f['key'])]
        
        if not unposted:
            state.reset(self.name)
            unposted = catalog
        
        return unposted[:1]

    def latest(self) -> list:
        """Return the first feature for --force testing."""
        return self._features_catalog()[:1]

    def _select_screenshot(self, feature, llm, catalog) -> dict | None:
        """Ask the LLM to pick the best screenshot for this feature."""
        if not catalog:
            return None
        
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

    def _manual_notes(self, shot) -> str:
        """Get the manual chapter context for the chosen screenshot."""
        if not shot or not shot.get('chapter'):
            return ''
        txt = content.read_text(shot['chapter']) or ''
        if not txt:
            return ''
        idx = txt.find(shot['name'])
        if idx == -1:
            return txt[:3500]
        return txt[max(0, idx - 3000):idx + 1200]

    def render(self, feature, llm) -> Post:
        """Render a feature into a post."""
        # Try to find a matching screenshot
        shot = self._select_screenshot(feature, llm, content.screenshot_catalog())
        notes = self._manual_notes(shot)
        
        # Build the user prompt
        user = f"Spotlight this RaspiMIDIHub feature:\n{feature['title']}\n\n"
        user += f"Core description:\n{feature['description']}\n\n"
        
        if notes:
            user += (f"Reference notes from the manual (summarize in your own words):\n"
                     f'"""\n{notes}\n"""\n')
        
        user += "\nWrite only the post text."
        
        text = llm_or_template(llm, _SYSTEM, user, 
                               fallback=feature['description'], 
                               max_len=280, temperature=0.5)
        
        post = Post(
            text=append_link(text, config.SITE_URL),
            source=self.name,
            dedupe_key=feature['key']
        )
        
        if shot:
            data = content.read_bytes(shot['file'])
            if data:
                post.media_bytes = data
                post.media_mime = 'image/png'
                post.media_desc = shot['caption'][:400]
        
        return post
