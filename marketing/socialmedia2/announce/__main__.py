"""CLI: run a single source by hand or test the smart scheduler.

    python -m announce youtube              # preview (dry-run, default)
    python -m announce youtube --post       # publish to Mastodon
    python -m announce features --force      # render the latest item, no state change
    python -m announce all --post            # every source once
    python -m announce --test                # test smart scheduler (simulate)

Dry-run never publishes and never marks items announced. First-run seeding of
youtube/github (establishing the baseline) does persist, so a later --post only
announces genuinely new items.
"""
import argparse
import sys

from . import config, content
from .discord_client import DiscordPoster
from .llm import LLMClient
from .mastodon_client import MastodonPoster
from .scheduler import get_scheduled_sources, SOURCE_TO_CATEGORY
from .sources.behind_the_code import BehindTheCodeSource
from .sources.creative_uses import CreativeUsesSource
from .sources.evergreen import EvergreenSource
from .sources.features import FeaturesSource
from .sources.github import GithubSource
from .sources.jokes import JokesSource
from .sources.manual_features import ManualFeaturesSource
from .sources.midi_facts import MidiFactsSource
from .sources.midi_history import MidiHistorySource
from .sources.quick_tips import QuickTipsSource
from .sources.youtube import YouTubeSource
from .state import State
from .topic_tracker import TopicTracker

SOURCES = {s.name: s for s in (
    YouTubeSource(), GithubSource(), FeaturesSource(), 
    ManualFeaturesSource(),  # New: 87 features from manual, random order
    JokesSource(), MidiFactsSource(), CreativeUsesSource(), MidiHistorySource(),
    QuickTipsSource(), BehindTheCodeSource()
)}


def build_publishers() -> list:
    """Every configured publisher. Add a class here to gain a new target."""
    return [p for p in (MastodonPoster(), DiscordPoster()) if p.configured()]


def run_source(name, *, do_post, force, state, llm, publishers) -> int:
    src = SOURCES[name]
    # Restrict to the publishers this source is allowed to post to.
    allowed = config.SOURCE_TARGETS.get(name)
    pubs = publishers if allowed is None else [p for p in publishers if p.name in allowed]

    # One source's fetch/render blowing up (e.g. YouTube's RSS endpoint
    # intermittently 404ing — a known YouTube-side issue) must never abort a
    # multi-source run. Isolate the failure here, report it, and let the other
    # sources proceed; this source retries on the next run.
    try:
        # FeaturesSource needs llm for topic clustering
        if name == 'features' and not force:
            items = src.find_new(state, llm)
        else:
            items = src.latest() if force else src.find_new(state)
    except Exception as e:  # noqa: BLE001 — deliberately broad: keep the tick alive
        print(f"⚠️  [{name}] fetch failed: {e.__class__.__name__}: {e} "
              f"— skipping this source, will retry next run.")
        return 1
    if not items:
        print(f"[{name}] nothing to announce.")
        return 0
    rc = 0
    for item in items:
        try:
            post = src.render(item, llm)
        except Exception as e:  # noqa: BLE001 — one bad item must not skip the rest
            print(f"⚠️  [{name}] render failed for one item: "
                  f"{e.__class__.__name__}: {e} — skipping it.")
            rc = 1
            continue
        print("=" * 64)
        print(f"[{name}] {post.dedupe_key}"
              + (f"  (+image {len(post.media_bytes)}B)" if post.media_bytes else ""))
        print(f"targets: {', '.join(p.name for p in pubs) or 'none'}")
        category = SOURCE_TO_CATEGORY.get(name, 'unknown')
        print(f"category: {category}")
        print("=" * 64)
        print(post.text)
        print()
        if not do_post:
            print("(dry-run — use --post to publish)\n")
            continue
        if not pubs:
            print("⚠️  no publishers configured for this source; nothing posted.\n")
            return 1
        key = post.dedupe_key
        for pub in pubs:
            if not force and pub.name in state.delivered(name, key):
                print(f"↷ {pub.name}: already delivered, skipping.")
                continue
            if pub.post(post):
                print(f"✅ {pub.name}: posted.")
                if not force:
                    state.mark_delivered(name, key, pub.name)
                    # Log for performance tracking
                    state.log_post(name, category, {})
            else:
                print(f"❌ {pub.name}: failed (will retry next run).")
                rc = 1
        # Mark announced only once every allowed target has it.
        if not force and all(p.name in state.delivered(name, key) for p in pubs):
            state.mark(name, key)
        print()
    return rc


def test_scheduler(state: State, llm: LLMClient, topic_tracker: TopicTracker, dry_run: bool = True):
    """Test the smart scheduler - show what would run in the next tick."""
    from datetime import datetime
    
    print("=" * 64)
    print("SMART SCHEDULER TEST")
    print("=" * 64)
    
    hour = datetime.now().hour
    print(f"Current hour: {hour:02d}:00")
    print()
    
    # Get scheduled sources
    scheduled = get_scheduled_sources(state, topic_tracker, llm)
    
    if not scheduled:
        print("No sources scheduled for this tick.")
        print("(All categories may be on cooldown)")
        return
    
    print(f"Scheduled sources: {', '.join(scheduled)}")
    print()
    
    # Show details for each scheduled source
    for source_name in scheduled:
        src = SOURCES[source_name]
        category = SOURCE_TO_CATEGORY.get(source_name, 'unknown')
        
        print(f"--- {source_name} ({category}) ---")
        
        try:
            # FeaturesSource needs llm for topic clustering
            if source_name == 'features':
                items = src.find_new(state, llm)
            else:
                items = src.find_new(state)
            
            if items:
                item = items[0]
                post = src.render(item, llm)
                print(f"Content preview:")
                print(f"  {post.text[:200]}...")
                print(f"  Dedupe key: {post.dedupe_key}")
            else:
                print("  Nothing to announce")
        except Exception as e:
            print(f"  Error: {e}")
        print()
    
    print("=" * 64)
    print("Use --post to actually publish these sources")
    print("=" * 64)


def main():
    p = argparse.ArgumentParser(
        prog='announce', description='RaspiMIDIHub social announcer')
    p.add_argument('source', nargs='?', choices=[*SOURCES, 'all'],
                   help='Source to run, or "all" for all sources')
    g = p.add_mutually_exclusive_group()
    g.add_argument('--dry-run', action='store_true',
                   help='preview without posting (default)')
    g.add_argument('--post', action='store_true', help='publish to Mastodon')
    p.add_argument('--force', action='store_true',
                   help='ignore state; render the latest item (no state change)')
    p.add_argument('--test', action='store_true',
                   help='test the smart scheduler (simulate next tick)')
    p.add_argument('--fetch-mastodon', type=int, metavar='N',
                   help='fetch last N Mastodon posts from the configured account')
    p.add_argument('--analyze', action='store_true',
                   help='analyze engagement patterns from fetched posts')
    args = p.parse_args()

    state = State()
    llm = LLMClient()
    publishers = build_publishers()
    print(f"content: {content.source_label()}  |  "
          f"llm: {'on' if config.LLM_ENABLED else 'off'} ({config.LLM_BASE_URL})  |  "
          f"publishers: {', '.join(p.name for p in publishers) or 'none'}")

    # Test mode: simulate scheduler without posting
    if args.test:
        topic_tracker = TopicTracker()
        test_scheduler(state, llm, topic_tracker, dry_run=True)
        return 0

    # Fetch Mastodon posts mode
    if args.fetch_mastodon:
        mastodon = MastodonPoster()
        if not mastodon.configured():
            print("⚠️  Mastodon not configured (need MASTODON_ACCESS_TOKEN).")
            return 1
        
        statuses = mastodon.fetch_statuses(count=args.fetch_mastodon, exclude_replies=True)
        
        if not statuses:
            print("No posts found or failed to fetch.")
            return 1
        
        if args.analyze:
            # Run analysis
            from .mastodon_analyzer import analyze_posts
            analyze_posts(statuses)
        else:
            # Just display posts
            print(f"Found {len(statuses)} posts:")
            print("=" * 64)
            
            for i, status in enumerate(statuses, 1):
                # Strip HTML from content
                import re
                text = re.sub(r'<[^>]+>', '', status['content'])
                # Truncate long posts
                if len(text) > 300:
                    text = text[:297] + "..."
                
                print(f"\n{i}. {status['created_at']}")
                print(f"   👁 {status['reblogs_count']} 🔁 | ❤ {status['favourites_count']} 💬 {status['replies_count']}")
                print(f"   {text}")
                if status['media_attachments']:
                    print(f"   📎 {len(status['media_attachments'])} attachment(s)")
                print("-" * 64)
        
        return 0

    names = list(SOURCES) if args.source == 'all' else ([args.source] if args.source else [])
    rc = 0
    for name in names:
        rc |= run_source(name, do_post=args.post, force=args.force,
                         state=state, llm=llm, publishers=publishers)
    state.save()
    sys.exit(rc)


if __name__ == '__main__':
    main()
