"""Prefill the topic tracker with subjects already announced on Mastodon.

The source-based dedup fix (``features._topic_id``) and the now-active topic
tracker both start from a clean slate. Without this seeding the announcer would
re-post the very subjects the timeline is already full of (link-local, MIDI 2.0,
runs-on-any-computer, the 1983 origin story, ...): the old title-based dedupe
keys don't match the new source-based ones, and ``topic_state.json`` is empty.

This scans the recent Mastodon history, classifies each post with
``extract_topic()`` against every source that has a tracked vocabulary, and
marks each subject as just-posted so its gap window (``TOPIC_GAPS``) counts from
now. It over-seeds slightly (a post is classified against several vocabularies),
which is the safe direction — it errs toward *less* repetition, and every gap
expires on its own within 5-14 days.

    python -m announce.seed_topics            # seed from Mastodon (curated fallback)
    python -m announce.seed_topics --show     # print current tracker state
    python -m announce.seed_topics --count 60 # scan N posts (default 40)

Idempotent: re-running refreshes each subject's last_post to now.
"""
import re
import sys
import time

from .mastodon_client import MastodonPoster
from .topic_tracker import TopicTracker, extract_topic

# Sources whose extract_topic() has a keyword vocabulary worth seeding.
_CLASSIFIABLE = ('features', 'midi_history', 'quick_tips')

# Fallback when Mastodon can't be reached — the subjects visible in the recent
# timeline at the time of writing (2026-07-15).
_CURATED = [
    ('features', 'link_local'), ('features', 'midi_2_0'),
    ('features', 'local_run'), ('features', 'wifi'),
    ('features', 'rack_view'), ('features', 'mirroring'),
    ('midi_history', 'midi_creation'), ('midi_history', 'midi_2_0'),
    ('quick_tips', 'cables'),
]


def _from_mastodon(count: int):
    """Classify the last ``count`` posts into (source, topic) pairs, or None."""
    m = MastodonPoster()
    if not m.configured():
        return None
    statuses = m.fetch_statuses(count=count, exclude_replies=True)
    if not statuses:
        return None
    pairs = set()
    for s in statuses:
        text = re.sub(r'<[^>]+>', ' ', s.get('content', ''))
        for source in _CLASSIFIABLE:
            topic = extract_topic(text, source)
            if topic != 'general':
                pairs.add((source, topic))
    return sorted(pairs)


def seed(count: int = 40):
    pairs = _from_mastodon(count)
    origin = f'Mastodon history (last {count} posts)'
    if not pairs:
        pairs, origin = _CURATED, 'curated fallback (Mastodon unavailable)'
    tt = TopicTracker()
    for source, topic in pairs:
        tt.mark_topic(source, topic)
        print(f"  seeded {source}:{topic}")
    tt.save()
    print(f"\ntopic tracker seeded from {origin}: "
          f"{len(pairs)} subjects -> {tt.path}")


def show():
    tt = TopicTracker()
    if not tt.data:
        print("topic tracker is empty")
        return
    for key, d in sorted(tt.data.items()):
        ago = (time.time() - d.get('last_post', 0)) / 86400
        print(f"  {key}: last posted {ago:.1f} days ago")


def main():
    args = sys.argv[1:]
    if '--show' in args:
        show()
        return
    count = 40
    if '--count' in args:
        count = int(args[args.index('--count') + 1])
    seed(count)


if __name__ == '__main__':
    main()
