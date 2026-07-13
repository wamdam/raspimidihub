# Social Media Redesign - Manual-Driven Features

## Problem

The previous social media stream had several issues:
1. **Repetitive content**: The same features were posted multiple times
2. **Generic jokes**: The jokes were not funny and felt forced
3. **LLM-driven inconsistency**: Features were clustered by LLM, leading to unpredictable content
4. **Missing manual coverage**: Many documented features were never highlighted

## Solution

A completely redesigned system that:

### 1. Manual-Only Feature Database

**All 87 features** from the user manual are extracted into a structured JSON database (`features_database.json`). Each feature includes:
- Unique ID
- Short title
- 1-2 sentence description
- 200-400 word detailed explanation (from the manual)
- Source chapter reference
- Keywords for filtering
- Screenshot filename (if available)

**No LLM generation** - just extraction and organization of existing manual content.

### 2. Random Rotation System

The `manual-features` source:
- Posts **one feature every 12 hours**
- Picks features in **random order** from unposted features
- Uses **SHA1 hashing** for deterministic deduplication
- **Resets the cycle** when all features are posted, then starts over
- **Never repeats** a feature until the full cycle is complete

### 3. Deterministic Rendering

Each feature is rendered using:
- The exact description from the manual
- The detailed text from the manual as context
- LLM (optional) to write a 280-character post
- Fallback to the description if LLM is unavailable
- Screenshot matching (if available)

### 4. Comprehensive Coverage

The 87 features cover:
- **Routing** (13 features): Matrix, Rack View, Cell Clipboard, Device Renaming, etc.
- **Plugins** (16 features): CC LFO, CC Smoother, Chord Generator, etc.
- **Play Surfaces** (7 features): Tracker, Arpeggiator, Euclidean, Cartesian
- **Controllers** (7 features): Mixer 8, FX 6, Performance 16, XY 4
- **Connectivity** (2 features): Bluetooth MIDI, Network MIDI
- **System** (8 features): MIDI Monitor, Test Sender, MIDI 2.0 Support
- **Settings** (10 features): Save Config, Sys Info, Updates, etc.
- **Workflow** (2 features): Captive Portal, mDNS Discovery

## Architecture

```
announce/
├── features_database.json          # 87 features extracted from manual
├── sources/
│   └── manual_features.py          # New source: random rotation
├── config.py                       # Updated: manual-features schedule
├── scheduler.py                    # Updated: added to 'product' category
└── __main__.py                     # Updated: registered new source
```

## Configuration

```python
# config.py
SCHEDULE = {
    'manual-features': 43200,  # 12 hours
}

SOURCE_TARGETS = {
    'manual-features': ['mastodon'],  # Mastodon-only
}
```

## Usage

```bash
# Preview a feature (dry-run)
python -m announce manual-features

# Publish a feature
python -m announce manual-features --post

# Force render the first feature (for testing)
python -m announce manual-features --force

# Run the dispatch tick (automated)
python -m announce.dispatch
```

## Benefits

1. **No repetition**: Each feature posted once per 87-post cycle (~435 days at 1/12h)
2. **Comprehensive**: All manual features get highlighted eventually
3. **Deterministic**: Same feature always produces same post
4. **Manual-grounded**: Content comes directly from documentation
5. **Random order**: Unpredictable posting keeps feed fresh
6. **Quality control**: Curated features, no LLM hallucination

## Migration Notes

- Old `evergreen` source is deprecated (replaced by `manual-features`)
- Old `features` source continues (LLM-clustered changelog topics)
- State file will have new `manual-features` section
- No manual intervention needed - just deploy and run

## Future Enhancements

1. **Feature categories**: Group features by type for themed weeks
2. **Screenshot rotation**: Multiple screenshots per feature
3. **User feedback**: Track which features get most engagement
4. **Seasonal features**: Highlight relevant features at appropriate times
