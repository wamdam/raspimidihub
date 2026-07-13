"""Smart scheduling with content categories, time-based weights, and anti-repetition.

This module replaces the simple interval-based scheduling with a smarter system that:
- Groups sources into content categories (educational, product, entertainment, community)
- Uses time-of-day weights to vary content mix
- Enforces anti-repetition constraints (min gaps between same-category posts)
- Tracks specific topics to prevent repetition (e.g., MIDI 2.0, link-local)
- Tracks performance metrics for future optimization
"""
import time
from datetime import datetime
from typing import Optional

from . import config
from .state import State
from .topic_tracker import TopicTracker, extract_topic

# Lazy import to avoid circular dependency
SOURCES = None


# Content categories and their sources
CATEGORIES = {
    'educational': ['midi_facts', 'creative_uses', 'midi_history', 'quick_tips'],
    'product': ['features', 'evergreen', 'github', 'manual-features'],  # manual-features = manual database
    'entertainment': ['jokes', 'behind_the_code'],
    'community': ['youtube'],
}

# Reverse mapping: source -> category
SOURCE_TO_CATEGORY = {}
for category, sources in CATEGORIES.items():
    for source in sources:
        SOURCE_TO_CATEGORY[source] = category


# Time-based weights for each category (hour -> weight)
# Higher weight = more likely to be selected
TIME_WEIGHTS = {
    # Morning (8-11): Educational focus
    8: {'educational': 0.4, 'product': 0.3, 'community': 0.2, 'entertainment': 0.1},
    9: {'educational': 0.4, 'product': 0.3, 'community': 0.2, 'entertainment': 0.1},
    10: {'educational': 0.3, 'product': 0.4, 'community': 0.2, 'entertainment': 0.1},
    11: {'educational': 0.3, 'product': 0.4, 'community': 0.2, 'entertainment': 0.1},
    
    # Afternoon (12-17): Product focus
    12: {'product': 0.4, 'educational': 0.3, 'community': 0.2, 'entertainment': 0.1},
    13: {'product': 0.4, 'educational': 0.3, 'community': 0.2, 'entertainment': 0.1},
    14: {'product': 0.4, 'educational': 0.3, 'community': 0.2, 'entertainment': 0.1},
    15: {'product': 0.4, 'educational': 0.3, 'community': 0.2, 'entertainment': 0.1},
    16: {'product': 0.3, 'educational': 0.3, 'community': 0.2, 'entertainment': 0.2},
    17: {'product': 0.3, 'educational': 0.2, 'community': 0.3, 'entertainment': 0.2},
    
    # Evening (18-22): Entertainment focus
    18: {'entertainment': 0.4, 'community': 0.3, 'educational': 0.2, 'product': 0.1},
    19: {'entertainment': 0.4, 'community': 0.3, 'educational': 0.2, 'product': 0.1},
    20: {'entertainment': 0.5, 'community': 0.2, 'educational': 0.2, 'product': 0.1},
    21: {'entertainment': 0.5, 'community': 0.2, 'educational': 0.2, 'product': 0.1},
    
    # Night (23-7): Minimal, mostly entertainment
    22: {'entertainment': 0.5, 'community': 0.3, 'educational': 0.1, 'product': 0.1},
    23: {'entertainment': 0.6, 'community': 0.2, 'educational': 0.1, 'product': 0.1},
    0: {'entertainment': 0.6, 'community': 0.2, 'educational': 0.1, 'product': 0.1},
    1: {'entertainment': 0.6, 'community': 0.2, 'educational': 0.1, 'product': 0.1},
    2: {'entertainment': 0.6, 'community': 0.2, 'educational': 0.1, 'product': 0.1},
    3: {'entertainment': 0.6, 'community': 0.2, 'educational': 0.1, 'product': 0.1},
    4: {'entertainment': 0.6, 'community': 0.2, 'educational': 0.1, 'product': 0.1},
    5: {'entertainment': 0.5, 'community': 0.2, 'educational': 0.2, 'product': 0.1},
    6: {'entertainment': 0.4, 'community': 0.2, 'educational': 0.3, 'product': 0.1},
    7: {'educational': 0.4, 'community': 0.3, 'product': 0.2, 'entertainment': 0.1},
}

# Minimum hours between posts of the same category (anti-repetition)
MIN_CATEGORY_GAP_HOURS = {
    'educational': 4,
    'product': 3,
    'entertainment': 6,
    'community': 4,
}


def get_current_hour() -> int:
    """Get current hour in local time."""
    return datetime.now().hour


def get_category_weights(hour: Optional[int] = None) -> dict:
    """Get category weights for a given hour."""
    if hour is None:
        hour = get_current_hour()
    return TIME_WEIGHTS.get(hour, TIME_WEIGHTS[12])  # Default to afternoon


def category_due(state: State, category: str) -> bool:
    """Check if a category is due based on minimum gap and last post time."""
    min_gap_hours = MIN_CATEGORY_GAP_HOURS.get(category, 4)
    min_gap_seconds = min_gap_hours * 3600
    
    # Get the most recent post time for any source in this category
    latest_time = 0
    for source in CATEGORIES.get(category, []):
        src_data = state.src(source)
        if src_data.get('last_run', 0) > latest_time:
            latest_time = src_data['last_run']
    
    # If no posts yet, category is due
    if latest_time == 0:
        return True
    
    return (time.time() - latest_time) >= min_gap_seconds


def select_category(state: State, hour: Optional[int] = None) -> Optional[str]:
    """Select a category based on time-of-day weights and anti-repetition constraints.
    
    Returns None if no category is available (all on cooldown).
    """
    weights = get_category_weights(hour)
    
    # Filter to categories that are due (not on cooldown)
    available = []
    for category, weight in weights.items():
        if category_due(state, category):
            available.append((category, weight))
    
    if not available:
        return None
    
    # Weighted random selection
    import random
    total_weight = sum(w for _, w in available)
    if total_weight == 0:
        return available[0][0]
    
    r = random.random() * total_weight
    cumulative = 0
    for category, weight in available:
        cumulative += weight
        if r <= cumulative:
            return category
    
    return available[-1][0]


def select_source_from_category(state: State, category: str, topic_tracker: TopicTracker = None, llm = None) -> Optional[str]:
    """Select a source from a category, preferring least-recently-posted that is due.
    
    Only returns sources that are due by their own interval and don't have
    recently posted topics.
    """
    sources = CATEGORIES.get(category, [])
    if not sources:
        return None
    
    # Find the source with the oldest last_run time that is also due
    # and doesn't have a recent topic
    candidates = []
    
    for source in sources:
        if source not in config.SCHEDULE:
            continue
        
        # Skip if source is not due by its own interval
        if not state.due(source, config.SCHEDULE[source]):
            continue
        
        src_data = state.src(source)
        last_run = src_data.get('last_run', 0)
        candidates.append((source, last_run))
    
    if not candidates:
        return None
    
    # Sort by last_run (oldest first)
    candidates.sort(key=lambda x: x[1])
    
    # Check topic tracking for each candidate
    for source, _ in candidates:
        # Get the latest item to check its topic
        if SOURCES is None or source not in SOURCES:
            continue
        
        try:
            src = SOURCES[source]
            # FeaturesSource needs llm for clustering - use latest() for topic check
            # to avoid side effects during selection
            items = src.latest()
            
            if items:
                item_text = items[0].get('text', '')
                topic = extract_topic(item_text, source)
                
                # Check if this topic was recently posted
                if topic_tracker and topic_tracker.is_topic_recent(source, topic):
                    continue  # Skip this source, topic is too recent
                
                # Good candidate
                return source
        except Exception:
            # If we can't check topic, use the source anyway
            return source
    
    # If all topics are recent, return the oldest anyway
    return candidates[0][0]


def should_run_source(state: State, source: str) -> bool:
    """Determine if a source should run based on smart scheduling.
    
    This replaces the simple interval check with category-aware scheduling.
    """
    if source not in config.SCHEDULE:
        return False
    
    # Check if source is in our smart scheduling system
    if source not in SOURCE_TO_CATEGORY:
        # Legacy sources not in categories - use old interval logic
        return state.due(source, config.SCHEDULE[source])
    
    category = SOURCE_TO_CATEGORY[source]
    
    # Check if category is due
    if not category_due(state, category):
        return False
    
    # Check if this specific source is due by its interval
    # (category being due doesn't mean every source is ready)
    return state.due(source, config.SCHEDULE[source])


def get_scheduled_sources(state: State, topic_tracker: TopicTracker = None, llm = None) -> list:
    """Get list of sources that should run in this tick.
    
    Returns sources in priority order based on category weights and recency.
    Uses topic_tracker to avoid repeating similar topics.
    """
    hour = get_current_hour()
    weights = get_category_weights(hour)
    
    scheduled = []
    
    # For each category, check if a source should run
    for category, weight in sorted(weights.items(), key=lambda x: -x[1]):
        if not category_due(state, category):
            continue
        
        source = select_source_from_category(state, category, topic_tracker, llm)
        if source and should_run_source(state, source):
            scheduled.append(source)
    
    return scheduled


def log_post(state: State, source: str, category: str, performance: dict = None):
    """Log a post for performance tracking.
    
    Args:
        state: State object
        source: Source name that was posted
        category: Category of the post
        performance: Optional dict with engagement metrics (likes, reblogs, etc.)
    """
    src = state.src(source)
    
    # Track category history
    if 'category_history' not in src:
        src['category_history'] = []
    
    src['category_history'].append({
        'category': category,
        'timestamp': time.time(),
        'performance': performance or {},
    })
    
    # Keep last 100 posts per source
    src['category_history'] = src['category_history'][-100:]
    
    # Update category-level stats
    cat_key = f'{category}_stats'
    if cat_key not in state.data:
        state.data[cat_key] = {
            'total_posts': 0,
            'total_engagement': 0,
        }
    
    state.data[cat_key]['total_posts'] += 1
    if performance:
        engagement = performance.get('likes', 0) + performance.get('reblogs', 0)
        state.data[cat_key]['total_engagement'] += engagement


def get_category_stats(state: State, category: str) -> dict:
    """Get performance statistics for a category."""
    cat_key = f'{category}_stats'
    stats = state.data.get(cat_key, {'total_posts': 0, 'total_engagement': 0})
    
    if stats['total_posts'] > 0:
        stats['avg_engagement'] = stats['total_engagement'] / stats['total_posts']
    else:
        stats['avg_engagement'] = 0
    
    return stats


def adjust_weights_for_performance(state: State, category: str, performance: dict):
    """Adjust category weights based on performance.
    
    This is a simple feedback mechanism - high-performing categories get
    slightly higher weights over time.
    """
    engagement = performance.get('likes', 0) + performance.get('reblogs', 0)
    
    # Get baseline weight for current hour
    hour = get_current_hour()
    base_weights = get_category_weights(hour)
    base_weight = base_weights.get(category, 0.2)
    
    # Calculate performance multiplier (1.0 = average, >1.0 = good, <1.0 = poor)
    stats = get_category_stats(state, category)
    if stats['avg_engagement'] > 0:
        multiplier = min(2.0, max(0.5, engagement / stats['avg_engagement']))
    else:
        multiplier = 1.0
    
    # Adjust weight (small step to avoid wild swings)
    adjustment = (multiplier - 1.0) * 0.1  # 10% of the deviation
    new_weight = max(0.05, min(0.8, base_weight + adjustment))
    
    # Store adjusted weight for this hour
    if 'adjusted_weights' not in state.data:
        state.data['adjusted_weights'] = {}
    
    state.data['adjusted_weights'][f'{category}_{hour}'] = new_weight


def get_effective_weights(state: State, hour: Optional[int] = None) -> dict:
    """Get effective weights including performance adjustments."""
    if hour is None:
        hour = get_current_hour()
    
    base_weights = get_category_weights(hour)
    adjusted = state.data.get('adjusted_weights', {})
    
    result = {}
    for category, base_weight in base_weights.items():
        adj_key = f'{category}_{hour}'
        if adj_key in adjusted:
            # Blend base and adjusted (70% base, 30% adjusted for stability)
            result[category] = 0.7 * base_weight + 0.3 * adjusted[adj_key]
        else:
            result[category] = base_weight
    
    return result
