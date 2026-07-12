# Social Media Posting Architecture

This document describes the architecture and patterns for the RaspiMIDIHub social media posting system (`announce/`).

## Key Decisions

### Deduplication Pattern

**Hash the SOURCE text, not the LLM output.**

The dedupe key is computed on the raw source material (CHANGELOG entry, fact text, joke text), not on the LLM's rewritten version. This ensures:
- Same source → same hash → no reposting
- LLM can vary the wording without breaking deduplication
- Cycle rotation works correctly

### Features Source: LLM-Driven Topic Consolidation

**Group related changelog entries into topics, not individual posts.**

The features source uses LLM clustering to prevent repetition:
- Parses the 50 most recent CHANGELOG entries (not all 375+)
- Asks the LLM to group entries into coherent topics (e.g., "Link-local IP", "MIDI 2.0", "Network MIDI")
- Each topic contains 3-5 related entries spanning multiple versions
- Tracks **topics** in state, not individual entries
- Renders ONE consolidated post per topic that tells the complete story

**Why topic consolidation?**

Without consolidation, the same bug fix story gets posted multiple times:
- v5.0.0: "link-local fallback self-assigns"
- v5.0.2: "Network MIDI didn't set up link-local"
- v5.0.3: "direct cable still didn't come up"
- v5.1.0: "removed leftover link-local setting"
- v5.1.2: "link-local kept at all times"
- v5.1.5: "direct cable keeps link-local indefinitely"

With consolidation, this becomes ONE topic:
> "Direct Ethernet cables now work reliably. The link-local IP fallback (169.254.x.x) on eth0 has been stabilized across multiple releases—survives reboots, coexists with DHCP, and is advertised correctly for mirroring."

**LLM clustering prompt:**
- Temperature: 0.2 (deterministic, consistent grouping)
- Output format: JSON object `{topic_title: description}`
- Keyword matching assigns entries to topics
- Fallback: each entry becomes its own topic if LLM fails

**Rendering consolidated topics:**
- The LLM writes ONE post that tells the RESOLVED state, not the journey
- For bug fixes: "Direct cables now work" not "We fixed this 5 times"
- For features: Highlights the final capability, not incremental changes

### Evergreen Features Source: Core Feature Spotlights

**Rotate through documented features, not just changelog entries.**

The evergreen source ensures the channel talks about what the software DOES, not just what changed:
- 12 curated features from the user manual
- Each feature has a screenshot and manual context
- Rotates through all features before cycling
- LLM renders each feature with grounding in the manual

**Evergreen feature list:**
1. Routing Matrix
2. Network MIDI Mirroring
3. Rack View
4. Play Surfaces (Cartesian, Euclidean, Arpeggiator)
5. Tracker
6. Filters & Mappings
7. Plugins (CC LFO, Smoother, Velocity Curve, etc.)
8. Autosave & Backup
9. Spectator Mirroring
10. MIDI Learn
11. Bluetooth MIDI
12. Light/Dark Themes

### Jokes Source: Curated List Pattern

**Use a fixed list of 100 jokes, not LLM generation on-the-fly.**

The jokes source:
- Stores 100 pre-written MIDI-themed jokes in a Python list
- Posts one joke per 9-hour interval
- Hashes the SOURCE joke text for deduplication
- LLM can polish each joke before posting (optional enhancement)
- Cycle restarts after all 100 jokes are posted

**Why not generate on-the-fly?**
- LLM-generated jokes can't be deduplicated (output varies)
- Curated list ensures quality and variety
- Proper state tracking works correctly
- 100 jokes = ~375 days of content at 1 per 9 hours

## Target Audience

**Hardware enthusiasts, not DAW/software users.**

The RaspiMIDIHub audience consists of:
- Musicians who build and tinker with their own gear
- Hardware synth owners and enthusiasts
- People who value physical MIDI connections (5-pin DIN, TRS, USB)
- Electronics hobbyists working with Raspberry Pi, GPIO, opto-isolators
- Users of THRU boxes, patch bays, and hardware routing
- People who appreciate the tactile nature of hardware music gear

**What resonates:**
- Physical cables, connectors, and adapters
- Hardware routing and signal flow
- Raspberry Pi and electronics tinkering
- Classic MIDI concepts (16 channels, baud rate, cable length limits)
- The joy of connecting physical gear together

**What to avoid:**
- DAW references (Pro Tools, Logic, Ableton, etc.)
- Software plugins, VSTs, virtual instruments
- Computer-centric music production workflows
- Purely digital/synthetic content

This audience values the hands-on, physical aspect of music technology.

## Overview

The system autonomously posts to Mastodon and Discord using a modular, source-based architecture. Each source knows how to find content, render it with an LLM, and post to configured publishers.

## Architecture

```
announce/
├── config.py           # .env loading, schedules, publisher routing
├── state.py            # JSON store: announced keys, last-run timestamps
├── llm.py              # LLMClient - OpenAI-compatible API wrapper
├── mastodon_client.py  # Mastodon publisher + fetch
├── mastodon_analyzer.py # Post engagement analyzer
├── discord_client.py   # Discord publisher
├── post.py             # Post dataclass (text, media, dedupe_key)
├── text.py             # Markdown strip, length trim, llm_or_template
├── dispatch.py         # The "tick" - runs due sources
├── scheduler.py        # Smart scheduling with categories
├── topic_tracker.py    # Topic-level anti-repetition
├── __main__.py         # CLI for manual testing
└── sources/
    ├── base.py         # Source contract (find_new, latest, render)
    ├── features.py     # LLM-clustered CHANGELOG topics
    ├── evergreen.py    # Core feature spotlights from manual
    ├── youtube.py      # YouTube playlist updates
    ├── github.py       # GitHub release announcements
    ├── jokes.py        # MIDI-themed jokes (Mastodon only)
    ├── midi_facts.py   # "Did you know?" MIDI facts (Mastodon only)
    ├── midi_history.py # MIDI history facts (Mastodon only)
    ├── quick_tips.py   # Practical MIDI tips (Mastodon only)
    ├── creative_uses.py # Creative application ideas (Mastodon only)
    └── behind_the_code.py # Development stories (Mastodon only)
```

## Core Abstractions

### 1. Source Contract

Every source implements:

```./.venv/bin/python3
class Source(ABC):
    name: str = ''  # Unique identifier, used in state and routing

    def find_new(self, state, llm=None) -> list:
        """Return items to announce now (may mutate/seed state). [] if nothing.
        
        Note: features.py requires llm for topic clustering.
        """

    def latest(self) -> list:
        """Return the most recent item(s) ignoring state (for --force testing)."""

    def render(self, item, llm) -> Post:
        """Turn one item into a publishable Post."""
```

**Key patterns:**
- `find_new()` handles deduplication and state seeding
- `latest()` enables `--force` testing without state changes
- `render()` transforms raw content into a `Post` with LLM assistance
- **features.py**: `find_new(state, llm)` clusters topics before returning

### 2. Post Value Object

```./.venv/bin/python3
@dataclass
class Post:
    text: str              # The post content (≤280 chars for Mastodon)
    source: str            # Source name (e.g., 'jokes', 'features')
    dedupe_key: str        # SHA1 hash for deduplication
    media_bytes: Optional[bytes] = None  # Optional image attachment
    media_mime: Optional[str] = None
    media_desc: Optional[str] = None     # Alt text for accessibility
```

### 3. State Management

State is stored in `~/.raspimidihub/socialmedia2/state.json`:

```json
{
  "jokes": {
    "announced": ["hash1", "hash2"],
    "last_run": 1234567890.0
  },
  "features": {
    "announced": ["topic_hash_1", "topic_hash_2"],
    "last_run": 1234567900.0
  },
  "evergreen": {
    "announced": ["feature_hash_1"],
    "last_run": 1234567910.0
  }
}
```

**State methods:**
- `is_announced(source, key)` - Check if item was posted
- `mark(source, key)` - Mark item as announced
- `mark_delivered(source, key, publisher)` - Track per-publisher delivery
- `reset(source)` - Reset state (cycle exhausted)
- `due(source, interval)` - Check if source is due to run

**Note:** For `features`, the key is a topic hash, not an individual entry hash.

### 4. Scheduling

Scheduling is a **stateless tick** - no long-running process:

```./.venv/bin/python3
# config.py
SCHEDULE = {
    'jokes': 32400,        # 9 hours
    'midi_facts': 43200,   # 12 hours
    'features': 14400,     # 4 hours
    'evergreen': 14400,    # 4 hours (product category)
    'youtube': 3600,       # 1 hour
    'github': 3600,        # 1 hour
}
```

The `dispatch.py` tick:
1. Runs every ~10 minutes via systemd timer
2. Checks each source's `last_run` against its interval
3. Runs due sources, updates `last_run`
4. Survives crashes and machine downtime (Persistent=true)

### 5. Publisher Routing

```./.venv/bin/python3
# config.py
SOURCE_TARGETS = {
    'features': ['mastodon'],
    'evergreen': ['mastodon'],
    'jokes': ['mastodon'],
    'midi_facts': ['mastodon'],
    # 'youtube' / 'github' omitted -> all publishers
}
```

- Sources **not listed** post to **all configured publishers**
- Sources **listed** post only to specified publishers
- Add a new publisher class to `build_publishers()` in `__main__.py`

### 6. Smart Scheduling

The scheduler uses content categories and time-of-day weights:

```./.venv/bin/python3
# scheduler.py
CATEGORIES = {
    'educational': ['midi_facts', 'creative_uses', 'midi_history', 'quick_tips'],
    'product': ['features', 'evergreen', 'github'],
    'entertainment': ['jokes', 'behind_the_code'],
    'community': ['youtube'],
}
```

**Time-based weights:**
- Morning (8-11): Educational focus
- Afternoon (12-17): Product focus
- Evening (18-22): Entertainment focus
- Night (23-7): Minimal, mostly entertainment

**Anti-repetition:**
- Minimum gap between same-category posts (3-6 hours)
- Topic tracking prevents similar content within categories

## Creating a New Source

### Step 1: Create the source file

```./.venv/bin/python3
# announce/sources/my_source.py
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = "Your system prompt for the LLM..."

class MySource(Source):
    name = 'my_source'

    def find_new(self, state, llm=None) -> list:
        # 1. Fetch/collect candidate items
        # 2. Filter out already announced (state.is_announced)
        # 3. Return up to N items (usually 1)
        # 4. If none left, state.reset(self.name) and start over
        #
        # Note: If using LLM for clustering/selection, accept llm parameter
        pass

    def latest(self) -> list:
        # Return the most recent item(s) for --force testing
        pass

    def render(self, item, llm) -> Post:
        # Transform one item into a Post using the LLM
        text = llm_or_template(llm, _SYSTEM, user_prompt, fallback, max_len=280)
        return Post(
            text=append_link(text, "https://raspimidihub.com"),
            source=self.name,
            dedupe_key=hashlib.sha1(item['text'].encode()).hexdigest()[:12]
        )
```

### Step 2: Register the source

```./.venv/bin/python3
# announce/__main__.py
from .sources.my_source import MySource

SOURCES = {s.name: s for s in (
    YouTubeSource(), GithubSource(), FeaturesSource(), EvergreenSource(),
    JokesSource(), MidiFactsSource(), MySource()
)}
```

### Step 3: Add to schedule

```./.venv/bin/python3
# announce/config.py
SCHEDULE = {
    # ... existing ...
    'my_source': int(_env('SOCIAL_INTERVAL_MY_SOURCE', 86400)),  # 24h
}
```

### Step 4: Configure routing (optional)

```./.venv/bin/python3
# announce/config.py
SOURCE_TARGETS = {
    # ... existing ...
    'my_source': ['mastodon'],  # or omit for all publishers
}
```

### Step 5: Test

```bash
# Dry-run (preview)
./.venv/bin/python3 -m announce my_source

# Publish
./.venv/bin/python3 -m announce my_source --post

# Force render latest (no state change)
./.venv/bin/python3 -m announce my_source --force

# Run dispatch tick
./.venv/bin/python3 -m announce.dispatch
```

## LLM Integration

### System Prompts

Keep system prompts concise and specific:

```./.venv/bin/python3
_SYSTEM = (
    "You write engaging 'Did you know?' facts about MIDI for musicians and "
    "tech enthusiasts. One or two short sentences, conversational tone. "
    "No emoji, no source attribution, no URLs, no hashtags. "
    "Stay under 280 characters."
)
```

### Fallback Strategy

Always provide a fallback for when the LLM is unavailable:

```./.venv/bin/python3
text = llm_or_template(
    llm, _SYSTEM, user,
    fallback="Default text if LLM unavailable",
    max_len=280,
    temperature=0.6
)
```

### Temperature Settings

- **0.0-0.3**: Deterministic, consistent (topic clustering, facts, specs)
- **0.5-0.7**: Balanced creativity (feature descriptions, renderings)
- **0.7-0.9**: High creativity (jokes, creative content)

### LLM-Driven Topic Clustering (features.py)

```./.venv/bin/python3
# Cluster system prompt
_CLUSTER_SYSTEM = (
    "You are a technical content curator. Your job is to GROUP changelog entries "
    "into coherent announcement topics.\n\n"
    "CRITICAL: Multiple entries about the SAME topic must be grouped together.\n"
    "Examples:\n"
    "- All entries about 'link-local IP' or '169.254' = ONE topic\n"
    "- All entries about 'Network MIDI' = ONE topic\n"
    "- All entries about 'MIDI 2.0' = ONE topic\n\n"
    "Output format: A JSON object where keys are topic titles and values are "
    "brief descriptions."
)

# Usage
def _cluster_topics(self, llm) -> list:
    entries = self._candidates()[:50]  # Limit to recent entries
    # Format entries by version
    # Call llm.generate(_CLUSTER_SYSTEM, _CLUSTER_USER, temperature=0.2)
    # Parse JSON, match entries to topics by keyword
    # Return list of {id, title, description, entries}
```

## Caching

For web scraping, cache content to avoid rate limits:

```./.venv/bin/python3
_CACHE_DIR = Path(config.STATE_DIR) / 'my_source_cache'
_CACHE_DURATION = 24 * 3600  # 24 hours

def _cached_fetch(url: str, cache_key: str, duration: int = _CACHE_DURATION):
    # Check cache first
    # Fetch if expired or missing
    # Store with timestamp
    pass
```

## Deduplication

Use SHA1 hashing for deduplication keys:

```./.venv/bin/python3
def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]
```

- Hash the **raw source text**, not the LLM output
- For `features`: hash the **topic title**, not individual entries
- This prevents reposting the same fact even if rewritten differently
- Reset state when cycle is exhausted (rotate through all items)

## Best Practices

### Do

- **Keep sources focused**: One type of content per source
- **Use state properly**: Deduplicate, track last_run, reset on cycle exhaustion
- **Provide fallbacks**: Always have a template fallback for LLM failures
- **Cache external content**: Avoid rate limits and speed up execution
- **Score and rank**: If multiple candidates, pick the best one
- **Test with --force**: Verify rendering without state changes
- **Handle errors gracefully**: One source failing shouldn't break the tick
- **Use LLM for clustering**: Group related entries to prevent repetition
- **Tell the resolved state**: For bug fixes, describe the solution, not the journey

### Don't

- **Don't hardcode URLs in posts**: Use `append_link()` with config.SITE_URL
- **Don't skip deduplication**: Always check `state.is_announced()`
- **Don't make sources time-sensitive**: Use state intervals, not wall-clock time
- **Don't forget to register**: Add source to `SOURCES` dict in `__main__.py`
- **Don't ignore errors**: Log failures but keep the tick running
- **Don't post incremental fixes**: Consolidate related bug fixes into one story
- **Don't rely on keyword extraction**: Use LLM for topic detection

## Adding a New Publisher

1. Create `announce/my_publisher.py`:

```./.venv/bin/python3
class MyPublisher:
    name = 'my_publisher'

    def __init__(self):
        # Load credentials from config

    def configured(self) -> bool:
        # Return True if properly configured

    def post(self, post) -> bool:
        # Post to the platform
        # Return True on success, False on failure
```

2. Add to `build_publishers()` in `__main__.py`:

```./.venv/bin/python3
def build_publishers() -> list:
    return [p for p in (MastodonPoster(), DiscordPoster(), MyPublisher()) if p.configured()]
```

3. Optionally add routing in `SOURCE_TARGETS`

## Environment Variables

```bash
# LLM Configuration
SOCIAL_LLM_ENABLED=1              # Enable LLM (0 = use templates only)
SOCIAL_LLM_BASE_URL=http://spark:8000/v1
SOCIAL_LLM_MODEL=qwen/qwen3.5-122b
SOCIAL_LLM_API_KEY=

# Publisher Configuration
MASTODON_INSTANCE=https://mastodon.social
MASTODON_ACCESS_TOKEN=your_token
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Content Sources
SOCIAL_GITHUB_REPO=wamdam/raspimidihub
SOCIAL_GITHUB_BRANCH=main
SOCIAL_YOUTUBE_PLAYLIST_ID=PL...

# Scheduling (optional overrides)
SOCIAL_INTERVAL_YOUTUBE=3600
SOCIAL_INTERVAL_GITHUB=3600
SOCIAL_INTERVAL_FEATURES=14400
SOCIAL_INTERVAL_EVERGREEN=14400
SOCIAL_INTERVAL_JOKES=32400
SOCIAL_INTERVAL_MIDI_FACTS=43200

# State and Cache
SOCIAL_STATE_DIR=~/.raspimidihub/socialmedia2
```

## Deployment

### Systemd Timer

```ini
# /etc/systemd/system/socialmedia2.timer
[Unit]
Description=RaspiMIDIHub Social Media Dispatcher

[Timer]
OnBootSec=5min
OnUnitActiveSec=10min
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/socialmedia2.service
[Unit]
Description=RaspiMIDIHub Social Media Service

[Service]
Type=oneshot
User=<user>
WorkingDirectory=<install_dir>/marketing/socialmedia2
Environment=PATH=<install_dir>/marketing/socialmedia2/.venv/bin
ExecStart=<install_dir>/marketing/socialmedia2/.venv/bin/./.venv/bin/python3 -m announce.dispatch
```

### Manual Testing

```bash
# Preview a source
./.venv/bin/python3 -m announce jokes

# Publish a source
./.venv/bin/python3 -m announce jokes --post

# Force render (no state change)
./.venv/bin/python3 -m announce features --force
./.venv/bin/python3 -m announce evergreen --force

# Run full dispatch tick
./.venv/bin/python3 -m announce.dispatch

# Fetch last N Mastodon posts
./.venv/bin/python3 -m announce --fetch-mastodon 50

# Fetch and analyze engagement patterns
./.venv/bin/python3 -m announce --fetch-mastodon 50 --analyze

# Test smart scheduler
./.venv/bin/python3 -m announce --test
```

## Current Sources

| Source | Schedule | Target | Content |
|--------|----------|--------|---------|
| jokes | 9h | Mastodon | MIDI-themed jokes (curated list of 100) |
| midi_facts | 12h | Mastodon | "Did you know?" facts from Wikipedia/midi.guide |
| features | 4h | Mastodon | LLM-clustered CHANGELOG topics (prevents repetition) |
| evergreen | 4h | Mastodon | Core feature spotlights from manual |
| youtube | 1h | Mastodon + Discord | New YouTube uploads |
| github | 1h | Mastodon + Discord | GitHub releases |
| midi_history | 8h | Mastodon | MIDI history facts |
| quick_tips | 8h | Mastodon | Practical MIDI tips |
| creative_uses | 12h | Mastodon | Creative application ideas |
| behind_the_code | 24h | Mastodon | Development stories |

## Troubleshooting

### Source not posting

1. Check `state.json` - is the item already announced?
2. Run with `--force` to test rendering
3. Check logs for fetch/render errors
4. Verify source is registered in `SOURCES` dict
5. For `features`: ensure LLM is available for clustering

### LLM not responding

1. Check `SOCIAL_LLM_ENABLED` and `SOCIAL_LLM_BASE_URL`
2. Test connectivity: `curl <LLM_URL>`
3. Verify fallback text is reasonable
4. Check LLM server logs for 500 errors

### Topic clustering failing

1. Check LLM response format (should be JSON object)
2. Verify entries are limited to 50 (larger payloads fail)
3. Fallback: each entry becomes its own topic
4. Check temperature setting (should be 0.2 for consistency)

### Rate limiting

1. Increase cache duration
2. Add User-Agent headers
3. Check source-specific rate limits

### State corruption

1. Delete `state.json` (will re-seed on next run)
2. Or reset specific source: `state.reset(source_name)`
3. For `features`: old entry-based state won't match new topic-based keys
