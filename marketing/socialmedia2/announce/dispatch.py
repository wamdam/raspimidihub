"""The scheduling service — smart tick with category-based routing.

Run on a short, fixed cadence by a single systemd timer (e.g. every 10 min).
Uses smart scheduling to select content based on time-of-day, category weights,
and anti-repetition constraints.

    python -m announce.dispatch
"""
from . import config, content
from .__main__ import SOURCES, build_publishers, run_source
from .llm import LLMClient
from .scheduler import get_scheduled_sources, SOURCE_TO_CATEGORY
from .state import State
from .topic_tracker import TopicTracker


def main():
    state = State()
    topic_tracker = TopicTracker()
    llm = LLMClient()
    publishers = build_publishers()
    print(f"dispatch tick | content: {content.source_label()} | "
          f"publishers: {', '.join(p.name for p in publishers) or 'NONE'}")
    
    # Get sources scheduled for this tick using smart scheduling
    scheduled = get_scheduled_sources(state, topic_tracker)
    
    ran = []
    for name in scheduled:
        if name not in SOURCES:
            continue
        
        interval = config.SCHEDULE.get(name, 3600)
        if not state.due(name, interval):
            print(f"   {name}: not due (interval)")
            continue
        
        category = SOURCE_TO_CATEGORY.get(name, 'unknown')
        print(f"-> {name}: due (category: {category}, interval: {interval}s)")
        
        run_source(name, do_post=True, force=False,
                   state=state, llm=llm, publishers=publishers)
        state.touch(name)
        ran.append(name)
    
    topic_tracker.save()
    state.save()
    print(f"ran: {', '.join(ran) if ran else 'none'}")


if __name__ == '__main__':
    main()
