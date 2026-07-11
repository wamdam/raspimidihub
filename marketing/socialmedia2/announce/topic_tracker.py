"""Topic tracking to prevent repetition within categories.

Tracks specific topics within each source to avoid posting similar content
too frequently (e.g., multiple MIDI 2.0 facts, multiple link-local fixes).
"""
import hashlib
import time
from pathlib import Path

from . import config


class TopicTracker:
    """Track topics within sources to prevent repetition."""
    
    # Topics to track and their minimum gap (in seconds)
    TOPIC_GAPS = {
        # MIDI History topics
        'midi_creation': 7 * 86400,      # 7 days
        'midi_2_0': 14 * 86400,          # 14 days
        'midi_hardware': 7 * 86400,      # 7 days
        'midi_specification': 10 * 86400, # 10 days
        
        # Quick Tips topics
        'cables': 5 * 86400,             # 5 days
        'routing': 7 * 86400,            # 7 days
        'troubleshooting': 7 * 86400,    # 7 days
        'timing': 7 * 86400,             # 7 days
        
        # Feature topics
        'network_midi': 7 * 86400,       # 7 days
        'link_local': 10 * 86400,        # 10 days
        'wifi': 7 * 86400,               # 7 days
        'bug_fix': 5 * 86400,            # 5 days
    }
    
    def __init__(self):
        self.path = Path(config.STATE_DIR) / 'topic_state.json'
        self.data = self._load()
    
    def _load(self) -> dict:
        if self.path.exists():
            try:
                return __import__('json').loads(self.path.read_text())
            except:
                pass
        return {}
    
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(__import__('json').dumps(self.data, indent=2))
    
    def _topic_key(self, source: str, topic: str) -> str:
        return f"{source}:{topic}"
    
    def is_topic_recent(self, source: str, topic: str) -> bool:
        """Check if a topic was recently posted."""
        key = self._topic_key(source, topic)
        topic_data = self.data.get(key, {})
        last_post = topic_data.get('last_post', 0)
        gap = self.TOPIC_GAPS.get(topic, 7 * 86400)
        return (time.time() - last_post) < gap
    
    def mark_topic(self, source: str, topic: str):
        """Mark a topic as posted."""
        key = self._topic_key(source, topic)
        if key not in self.data:
            self.data[key] = {}
        self.data[key]['last_post'] = time.time()
        self.data[key]['topic'] = topic
        self.data[key]['source'] = source
    
    def get_topic_stats(self) -> dict:
        """Get statistics on topic usage."""
        stats = {}
        for key, data in self.data.items():
            source = data.get('source', 'unknown')
            topic = data.get('topic', 'unknown')
            if source not in stats:
                stats[source] = {}
            if topic not in stats[source]:
                stats[source][topic] = {'count': 0, 'last_post': 0}
            stats[source][topic]['count'] += 1
            stats[source][topic]['last_post'] = data.get('last_post', 0)
        return stats


def extract_topic(text: str, source: str) -> str:
    """Extract topic from text based on keywords."""
    text_lower = text.lower()
    
    if source == 'midi_history':
        if any(w in text_lower for w in ['dave smith', '1981', '1982', 'kakehashi', 'namw']):
            return 'midi_creation'
        if any(w in text_lower for w in ['midi 2.0', 'midi2', '14-bit', 'per-note']):
            return 'midi_2_0'
        if any(w in text_lower for w in ['5-pin', 'din', 'connector', 'opto-isolator']):
            return 'midi_hardware'
        if any(w in text_lower for w in ['specification', 'spec', '44 pages']):
            return 'midi_specification'
    
    elif source == 'quick_tips':
        if 'cable' in text_lower:
            return 'cables'
        if any(w in text_lower for w in ['thru', 'routing', 'merge', 'filter']):
            return 'routing'
        if any(w in text_lower for w in ['troubleshoot', 'error', 'problem', 'fix']):
            return 'troubleshooting'
        if any(w in text_lower for w in ['clock', 'timing', 'ppqn', 'drift']):
            return 'timing'
    
    elif source == 'features':
        if any(w in text_lower for w in ['network midi', 'network-midi']):
            return 'network_midi'
        if any(w in text_lower for w in ['link-local', '169.254', '169.254.x.x']):
            return 'link_local'
        if any(w in text_lower for w in ['wifi', 'ap', 'access point']):
            return 'wifi'
        if any(w in text_lower for w in ['fix', 'bug', 'issue', 'problem']):
            return 'bug_fix'
    
    return 'general'
