---
name: mastodon-analyze
description: Analyze Mastodon engagement patterns and content performance. Use when you need insights on posting effectiveness, content strategy, or audience engagement.
---

# Mastodon Analyze Skill

Use this skill when you need to analyze engagement patterns, content performance, and posting effectiveness from the RaspiMIDIHub Mastodon account.

## Usage

This skill fetches posts and provides analysis on:
- Engagement metrics (likes, reblogs, replies)
- Content type distribution
- Posting frequency patterns
- Top performing posts
- Content category breakdown
- Media impact analysis
- Time-based patterns

### Command

```bash
python -m announce --fetch-mastodon N --analyze
```

Where `N` is the number of posts to analyze (recommended: 50-100 for meaningful patterns).

## Analysis Categories

### 1. Engagement Metrics

- **Total engagement**: Sum of likes + reblogs + replies
- **Average engagement per post**
- **Top 10 most engaging posts**
- **Engagement rate by content type**

### 2. Content Type Distribution

Auto-categorized into:
- **Features**: Version announcements, changelog items
- **Jokes**: MIDI-themed humor
- **Facts**: "Did you know?" MIDI trivia
- **Creative Uses**: How-to guides and use cases
- **History**: MIDI history and background
- **Quick Tips**: Short practical advice
- **Behind the Code**: Developer stories

### 3. Posting Patterns

- **Time of day analysis**: When do posts perform best?
- **Day of week analysis**: Which days get more engagement?
- **Frequency**: Posts per day/hour

### 4. Content Performance

- **Best performing source**: Which content type gets most engagement?
- **Worst performing source**: Which content type needs improvement?
- **Media impact**: Do posts with images perform better?

### 5. Variety Analysis

- **Content diversity**: Number of different content categories
- **Repetition detection**: Identifies similar content that may cause audience fatigue
- **Balance score**: Assesses if content mix is well-distributed

## Output Format

```
======================================================================
MASTODON POST ANALYSIS
======================================================================

Total Posts Analyzed: 20
Date Range: 2026-07-12 to 2026-07-12

ENGAGEMENT SUMMARY
----------------------------------------------------------------------
Total Engagement: 6
  - Likes: 5
  - Reblogs: 1
  - Replies: 0
Average per Post: 0.30

TOP 10 POSTS BY ENGAGEMENT
----------------------------------------------------------------------
1. [2026-07-12 09:13] 2 engagement - Build a MIDI-controlled 3D printer...
2. [2026-07-12 09:13] 1 engagement - Fix MIDI clock drift by designating...
...

CONTENT BREAKDOWN
----------------------------------------------------------------------
facts: 4 posts (20.0%) - Avg engagement: 0.00
jokes: 2 posts (10.0%) - Avg engagement: 0.00
features: 8 posts (40.0%) - Avg engagement: 0.25
creative_uses: 2 posts (10.0%) - Avg engagement: 1.00
quick_tips: 1 posts (5.0%) - Avg engagement: 1.00
other: 2 posts (10.0%) - Avg engagement: 0.50
history: 1 posts (5.0%) - Avg engagement: 0.00

MEDIA ANALYSIS
----------------------------------------------------------------------
Posts with media: 5 (25.0%)
  - Avg engagement: 0.00
Posts without media: 15 (75.0%)
  - Avg engagement: 0.40
Media posts perform 0.0x better

TIME ANALYSIS
----------------------------------------------------------------------
Best posting hour: 09:00 (avg 0.30 engagement)
Best posting day: Sunday (avg 0.30 engagement)

INSIGHTS & RECOMMENDATIONS
----------------------------------------------------------------------
• Best performing content: creative_uses (avg 1.00 engagement)
• Lowest performing content: facts (avg 0.00 engagement)
• ✓ Good content variety (7 categories)
• ⚠️  Low average engagement (0.30). Consider adjusting content strategy.
```

## Implementation

The analysis functionality is implemented in:

- `announce/mastodon_analyzer.py` - `analyze_posts()` function
- `announce/__main__.py` - CLI argument `--analyze`

### Key Features

```python
# Auto-categorization
def _categorize_post(text: str) -> str:
    """Categorize a post by its content type."""
    # Detects: features, jokes, facts, creative_uses, history, quick_tips, behind_the_code

# Full analysis
def analyze_posts(statuses: list) -> None:
    """Analyze engagement patterns and content performance."""
    # - Categorize posts by source type
    # - Calculate engagement metrics
    # - Identify top performers
    # - Analyze media impact
    # - Time-based patterns
    # - Generate insights and recommendations
```

## Recommendations

Based on analysis, the skill provides actionable recommendations:

1. **Content Mix**: Adjust posting frequency by content type based on engagement
2. **Timing**: Optimize posting schedule based on hour/day analysis
3. **Media Strategy**: Increase media attachments for high-performing categories
4. **Engagement Boosters**: Identify what resonates with your audience
5. **Variety Check**: Warns if content diversity is low (prevents audience fatigue)
6. **Quality Alerts**: Flags low engagement for strategy adjustment

## Related

- Use `mastodon-fetch` skill to simply fetch and view posts
- Use `python -m announce --help` to see all CLI options
