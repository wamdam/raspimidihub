# Social Media Posting Architecture

This document describes the architecture and patterns for the RaspiMIDIHub social media posting system (`announce/`).

## Key Decisions

### Deduplication Pattern

**Hash the SOURCE text, not the LLM output.**

The dedupe key is computed on the raw source material (CHANGELOG entry, fact text, joke text), not on the LLM's rewritten version. This ensures:
- Same source → same hash → no reposting
- LLM can vary the wording without breaking deduplication
- Cycle rotation works correctly

### Features Source: Full CHANGELOG Coverage

**Parse ALL versions, not just recent ones.**

The features source parses all 67 versions from v5.2.0 to v1.0.0 (375 candidates):
- Includes "Added", "Improved", AND "Fix" entries
- Handles both CHANGELOG formats:
  - New: `2026-07-01 — Version 5.2.0` (em-dash)
  - Old: `2026-04-25 - Version 2.0.9` (single dash)
- Regex: `r'(\d{4}-\d{2}-\d{2}) —?-? Version ([\d.a-z]+)'`

**Why include fixes?**
Many fixes are user-visible improvements worth announcing:
- "Network MIDI mirroring over a direct cable"
- "WiFi always survives a reboot"
- "Bluetooth MIDI section no longer disappears"

**Why include old versions?**
Major features from early releases:
- Spectator mirroring (v4.3.0)
- Light/Dark theme (v4.2.0)
- User-bindable MIDI CC (v4.1.0)
- Euclidean plugin (v4.0.0)
- Autosave/Backup (v4.7.0)
- First stable release features (v1.0.0)

At 1 post per 4 hours, this gives ~62 days of unique content before cycling.

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
├── mastodon_client.py  # Mastodon publisher
├── discord_client.py   # Discord publisher
├── post.py             # Post dataclass (text, media, dedupe_key)
├── text.py             # Markdown strip, length trim, llm_or_template
├── dispatch.py         # The "tick" - runs due sources
├── __main__.py         # CLI for manual testing
└── sources/
    ├── base.py         # Source contract (find_new, latest, render)
    ├── features.py     # Feature spotlights from CHANGELOG
    ├── youtube.py      # YouTube playlist updates
    ├── github.py       # GitHub release announcements
    ├── jokes.py        # MIDI-themed jokes (Mastodon only)
    └── midi_facts.py   # "Did you know?" MIDI facts (Mastodon only)
```

## Core Abstractions

### 1. Source Contract

Every source implements:

```python
class Source(ABC):
    name: str = ''  # Unique identifier, used in state and routing

    def find_new(self, state) -> list:
        """Return items to announce now (may mutate/seed state). [] if nothing."""

    def latest(self) -> list:
        """Return the most recent item(s) ignoring state (for --force testing)."""

    def render(self, item, llm) -> Post:
        """Turn one item into a publishable Post."""
```

**Key patterns:**
- `find_new()` handles deduplication and state seeding
- `latest()` enables `--force` testing without state changes
- `render()` transforms raw content into a `Post` with LLM assistance

### 2. Post Value Object

```python
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
  "midi_facts": {
    "announced": ["hash3"],
    "last_run": 1234567900.0
  }
}
```

**State methods:**
- `is_announced(source, key)` - Check if item was posted
- `mark(source, key)` - Mark item as announced
- `mark_delivered(source, key, publisher)` - Track per-publisher delivery
- `reset(source)` - Reset state (cycle exhausted)
- `due(source, interval)` - Check if source is due to run

### 4. Scheduling

Scheduling is a **stateless tick** - no long-running process:

```python
# config.py
SCHEDULE = {
    'jokes': 32400,        # 9 hours
    'midi_facts': 43200,   # 12 hours
    'features': 14400,     # 4 hours
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

```python
# config.py
SOURCE_TARGETS = {
    'features': ['mastodon'],
    'jokes': ['mastodon'],
    'midi_facts': ['mastodon'],
    # 'youtube' / 'github' omitted -> all publishers
}
```

- Sources **not listed** post to **all configured publishers**
- Sources **listed** post only to specified publishers
- Add a new publisher class to `build_publishers()` in `__main__.py`

## Creating a New Source

### Step 1: Create the source file

```python
# announce/sources/my_source.py
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = "Your system prompt for the LLM..."

class MySource(Source):
    name = 'my_source'

    def find_new(self, state) -> list:
        # 1. Fetch/collect candidate items
        # 2. Filter out already announced (state.is_announced)
        # 3. Return up to N items (usually 1)
        # 4. If none left, state.reset(self.name) and start over
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

```python
# announce/__main__.py
from .sources.my_source import MySource

SOURCES = {s.name: s for s in (
    YouTubeSource(), GithubSource(), FeaturesSource(), MySource()
)}
```

### Step 3: Add to schedule

```python
# announce/config.py
SCHEDULE = {
    # ... existing ...
    'my_source': int(_env('SOCIAL_INTERVAL_MY_SOURCE', 86400)),  # 24h
}
```

### Step 4: Configure routing (optional)

```python
# announce/config.py
SOURCE_TARGETS = {
    # ... existing ...
    'my_source': ['mastodon'],  # or omit for all publishers
}
```

### Step 5: Test

```bash
# Dry-run (preview)
python -m announce my_source

# Publish
python -m announce my_source --post

# Force render latest (no state change)
python -m announce my_source --force

# Run dispatch tick
python -m announce.dispatch
```

## LLM Integration

### System Prompts

Keep system prompts concise and specific:

```python
_SYSTEM = (
    "You write engaging 'Did you know?' facts about MIDI for musicians and "
    "tech enthusiasts. One or two short sentences, conversational tone. "
    "No emoji, no source attribution, no URLs, no hashtags. "
    "Stay under 280 characters."
)
```

### Fallback Strategy

Always provide a fallback for when the LLM is unavailable:

```python
text = llm_or_template(
    llm, _SYSTEM, user,
    fallback="Default text if LLM unavailable",
    max_len=280,
    temperature=0.6
)
```

### Temperature Settings

- **0.0-0.3**: Deterministic, consistent (facts, specs)
- **0.5-0.7**: Balanced creativity (feature descriptions)
- **0.7-0.9**: High creativity (jokes, creative content)

## Caching

For web scraping, cache content to avoid rate limits:

```python
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

```python
def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]
```

- Hash the **raw source text**, not the LLM output
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

### Don't

- **Don't hardcode URLs in posts**: Use `append_link()` with config.SITE_URL
- **Don't skip deduplication**: Always check `state.is_announced()`
- **Don't make sources time-sensitive**: Use state intervals, not wall-clock time
- **Don't forget to register**: Add source to `SOURCES` dict in `__main__.py`
- **Don't ignore errors**: Log failures but keep the tick running

## Adding a New Publisher

1. Create `announce/my_publisher.py`:

```python
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

```python
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
ExecStart=<install_dir>/marketing/socialmedia2/.venv/bin/python -m announce.dispatch
```

### Manual Testing

```bash
# Preview a source
python -m announce jokes

# Publish a source
python -m announce jokes --post

# Force render (no state change)
python -m announce midi_facts --force

# Run full dispatch tick
python -m announce.dispatch
```

## Current Sources

| Source | Schedule | Target | Content |
|--------|----------|--------|---------|
| jokes | 9h | Mastodon | MIDI-themed jokes (curated list of 100) |
| midi_facts | 12h | Mastodon | "Did you know?" facts from Wikipedia/midi.guide |
| features | 4h | Mastodon | Feature spotlights from CHANGELOG (all 375 entries) |
| youtube | 1h | Mastodon + Discord | New YouTube uploads |
| github | 1h | Mastodon + Discord | GitHub releases |

## Troubleshooting

### Source not posting

1. Check `state.json` - is the item already announced?
2. Run with `--force` to test rendering
3. Check logs for fetch/render errors
4. Verify source is registered in `SOURCES` dict

### LLM not responding

1. Check `SOCIAL_LLM_ENABLED` and `SOCIAL_LLM_BASE_URL`
2. Test connectivity: `curl <LLM_URL>`
3. Verify fallback text is reasonable

### Rate limiting

1. Increase cache duration
2. Add User-Agent headers
3. Check source-specific rate limits

### State corruption

1. Delete `state.json` (will re-seed on next run)
2. Or reset specific source: `state.reset(source_name)`
