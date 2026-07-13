---
name: mastodon-fetch
description: Fetch posts from the RaspiMIDIHub Mastodon account. Use when you need to view recent posts, check engagement, or analyze content performance.
---

# Mastodon Fetch Skill

Use this skill when you need to fetch posts from the RaspiMIDIHub Mastodon account.

## Usage

This skill fetches the last N posts from the configured Mastodon account and displays them.

### Command

```bash
python -m announce --fetch-mastodon N
```

Where `N` is the number of posts to fetch (e.g., 10, 50, 100).

### Example

```bash
python -m announce --fetch-mastodon 50
```

## What It Does

1. **Fetches** the last N posts from your configured Mastodon account (using `MASTODON_ACCESS_TOKEN` from `.env`)
2. **Excludes replies** by default (only shows original posts)
3. **Displays** each post with:
   - Timestamp
   - Engagement stats (views, reblogs, likes, replies)
   - Post content (HTML stripped, truncated to 300 chars)
   - Media attachments count

## Implementation

The fetch functionality is implemented in:

- `announce/mastodon_client.py` - `MastodonPoster.fetch_statuses()` method
- `announce/__main__.py` - CLI argument `--fetch-mastodon`

### Key Methods

```python
# In mastodon_client.py
def fetch_statuses(self, count: int = 50, exclude_replies: bool = True) -> list:
    """Fetch the last N statuses from the authenticated account."""
    
def get_account_id(self) -> str | None:
    """Get the account ID (numeric) for the authenticated user."""
```

## Requirements

- `MASTODON_ACCESS_TOKEN` must be set in `.env`
- `mastodon.py` package must be installed

## Output Format

```
Found 40 posts:
================================================================

1. 2026-07-12 06:26:55.449000+00:00
   👁 0 🔁 | ❤ 0 💬 0
   Did you know? MIDI 2.0's Universal MIDI Packets swap the old 3-byte messages...
----------------------------------------------------------------

2. 2026-07-12 05:56:53.571000+00:00
   👁 0 🔁 | ❤ 0 💬 0
   Why did the MIDI cable become a detective? Because it could trace any connection...
----------------------------------------------------------------
```

## With Analysis

Add `--analyze` flag to get detailed engagement analysis:

```bash
python -m announce --fetch-mastodon 50 --analyze
```

This provides:
- Engagement metrics and averages
- Content category breakdown
- Media impact analysis
- Time-based patterns
- Insights and recommendations

## Related

- Use `mastodon-analyze` skill to analyze engagement patterns and content performance
- Use `python -m announce --help` to see all available CLI options
- Use `--analyze` flag with fetch for detailed analysis
