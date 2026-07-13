# Social Media Redesign Summary

## Problem Statement

The previous social media stream had critical issues:
1. **Repetitive content**: Same features posted multiple times
2. **Generic jokes**: Not funny, forced humor
3. **LLM-driven inconsistency**: Features source clustered changelog entries, causing repetition
4. **Limited coverage**: Only 12 evergreen features, missing 70+ documented features

## Solution

### New Source: `manual-features`

**Architecture:**
- **Database**: 74 features extracted from ALL manual chapters by subagent
- **Rotation**: Random selection from unposted features
- **Schedule**: Every 12 hours (configurable via `SOCIAL_INTERVAL_MANUAL_FEATURES`)
- **Deduplication**: Feature ID-based (deterministic, no reposting)
- **Rendering**: LLM generates posts from manual text + optional screenshots

**Key Features:**
1. **Comprehensive coverage**: All 74 features from the manual
2. **Random order**: No predictable pattern, keeps content fresh
3. **Cycle-based**: Each feature posts once per 74-post cycle (~37 days at 12h intervals)
4. **Manual-grounded**: Posts are based on actual manual text, not LLM generation
5. **Screenshot support**: Automatic matching to manual screenshots

### Database Structure

```json
{
  "meta": {
    "title": "RaspiMIDIHub Feature Database",
    "source": "User Manual",
    "total_features": 74,
    "categories": ["routing", "plugins", "controllers", "play-surfaces", ...]
  },
  "features": [
    {
      "id": "routing-matrix",
      "title": "Routing Matrix",
      "category": "routing",
      "description": "A tap-to-edit grid of connections...",
      "detailed_text": "Full 200-400 word description from manual...",
      "chapter": "05-routing-matrix.md",
      "keywords": ["matrix", "routing", "grid", ...],
      "screenshot": "01-routing.png"
    },
    ...
  ]
}
```

### Integration

**Configuration:**
```python
# announce/config.py
SOURCE_TARGETS = {
    'manual-features': ['mastodon'],  # Mastodon-only
}

SCHEDULE = {
    'manual-features': 43200,  # 12 hours
}
```

**Scheduler:**
- Added to 'product' category in smart scheduler
- Time-based weights: Afternoon focus on product content
- Anti-repetition: Minimum 3-hour gap between product posts

**Sources Retained:**
All existing sources remain active:
- `creative_uses`, `midi_facts`, `midi_history`, `quick_tips` (educational)
- `jokes`, `behind_the_code` (entertainment)
- `features` (LLM-clustered changelog topics)
- `evergreen` (12 curated features)
- `youtube`, `github` (real-time updates)

## Benefits

1. **No repetition**: 74 features × 1 post each = 37 days before cycle restarts
2. **Comprehensive**: Every manual feature gets highlighted
3. **Random**: Unpredictable order keeps content fresh
4. **Grounded**: Posts based on actual manual text
5. **Deterministic**: Same feature always produces same post
6. **Maintainable**: Add new features to database, auto-rotates in

## Testing

```bash
# Preview a random feature
python -m announce manual-features

# Force render first feature (for testing)
python -m announce manual-features --force

# Run full dispatch tick
python -m announce.dispatch

# Check state
cat ~/.raspimidihub/socialmedia2/state.json
```

## Future Improvements

1. **Feature prioritization**: Weight certain features higher
2. **Seasonal content**: Highlight relevant features by season/event
3. **User feedback**: Track engagement per feature type
4. **Multi-language**: Support international manual versions
5. **Video integration**: Add video thumbnails for complex features

## Files Changed

- `announce/sources/manual_features.py` - New source implementation
- `announce/features_database.json` - 74-feature database
- `announce/__main__.py` - Registered new source
- `announce/config.py` - Added schedule and routing
- `announce/scheduler.py` - Added to 'product' category

## Commit History

```
edd50c3 Redesign: Manual-driven feature database with random rotation
b2c8002 Redesign: Manual-driven feature database with random rotation  
e94807b Current socialmedia2 state before redesign
```

## Next Steps

1. Monitor engagement on manual-features posts
2. Compare with evergreen source performance
3. Consider deprecating evergreen (redundant with manual-features)
4. Add more features as manual expands
5. Implement feature categorization for smarter rotation
