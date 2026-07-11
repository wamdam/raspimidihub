# Topic Tracking Implementation

## Problem

After reviewing the last 40 posts, I identified significant repetition:

1. **MIDI 2.0 topics**: 3 posts in 2 days
2. **Link-local/169.254 IP fixes**: 4 posts 
3. **Cable-related tips**: Multiple posts
4. **Dave Smith history**: Multiple posts about the same topic

## Solution

Added **topic-level tracking** to prevent repetition within specific topics, even across different sources.

### New File: `announce/topic_tracker.py`

Tracks specific topics and enforces minimum gaps:

| Topic | Minimum Gap | Sources |
|-------|-------------|---------|
| `midi_2_0` | 14 days | midi_history, midi_facts |
| `midi_creation` | 7 days | midi_history |
| `cables` | 5 days | quick_tips |
| `link_local` | 10 days | features |
| `network_midi` | 7 days | features |
| `bug_fix` | 5 days | features |
| `routing` | 7 days | quick_tips |
| `timing` | 7 days | quick_tips |

### How It Works

1. **Topic Extraction**: Each post is analyzed for keywords to determine its topic
2. **Topic Tracking**: Topics are stored in `~/.raspimidihub/socialmedia2/topic_state.json`
3. **Scheduler Integration**: Before selecting a source, the scheduler checks if the topic was recently posted
4. **Skip Recent Topics**: If a topic is too recent, the scheduler tries the next source

### Example

```python
# MIDI 2.0 was posted 2 days ago
topic_tracker.is_topic_recent('midi_facts', 'midi_2_0')  # True

# Scheduler will skip midi_facts and try midi_history instead
```

### Topic Keyword Detection

```python
# midi_history
'dave smith', '1981', '1982', 'kakehashi' -> midi_creation
'midi 2.0', '14-bit', 'per-note' -> midi_2_0

# quick_tips
'cable' -> cables
'thru', 'routing' -> routing
'clock', 'timing' -> timing

# features
'link-local', '169.254' -> link_local
'network midi' -> network_midi
'fix', 'bug' -> bug_fix
```

## Files Modified

| File | Changes |
|------|---------|
| `announce/topic_tracker.py` | NEW - Topic tracking logic |
| `announce/scheduler.py` | Updated to use topic_tracker |
| `announce/dispatch.py` | Updated to save topic_tracker |
| `announce/__main__.py` | Updated test mode to use topic_tracker |

## Testing

```bash
# Test scheduler with topic tracking
python -m announce --test

# Check topic state
cat ~/.raspimidihub/socialmedia2/topic_state.json

# View topic statistics
python3 -c "from announce.topic_tracker import TopicTracker; t=TopicTracker(); print(t.get_topic_stats())"
```

## Expected Behavior

After this change:
- **MIDI 2.0**: Max 1 post per 14 days
- **Link-local fixes**: Max 1 post per 10 days
- **Cable tips**: Max 1 post per 5 days
- **Dave Smith history**: Max 1 post per 7 days

This will significantly reduce repetition while maintaining content variety.

## Future Improvements

1. **Cross-source topic tracking**: Track topics across all sources (not just per-source)
2. **Dynamic topic gaps**: Adjust gaps based on content pool size
3. **Topic diversity scoring**: Prefer sources that cover under-represented topics
4. **User feedback integration**: Adjust gaps based on engagement metrics
