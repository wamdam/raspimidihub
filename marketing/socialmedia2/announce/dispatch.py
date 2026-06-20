"""The scheduling service — a stateless "tick".

Run on a short, fixed cadence by a single systemd timer (e.g. every 10 min).
Each tick runs whichever sources are due per the per-source interval in
config.SCHEDULE, comparing against each source's last_run in state. Because the
schedule lives in state (not in a long-running process), it is crash-safe and
catches up after the machine was asleep/off (systemd Persistent=true).

    python -m announce.dispatch
"""
from . import config, content
from .__main__ import SOURCES, build_publishers, run_source
from .llm import LLMClient
from .state import State


def main():
    state = State()
    llm = LLMClient()
    publishers = build_publishers()
    print(f"dispatch tick | content: {content.source_label()} | "
          f"publishers: {', '.join(p.name for p in publishers) or 'NONE'}")
    ran = []
    for name, interval in config.SCHEDULE.items():
        if name not in SOURCES:
            continue
        if not state.due(name, interval):
            print(f"   {name}: not due")
            continue
        print(f"-> {name}: due (every {interval}s)")
        run_source(name, do_post=True, force=False,
                   state=state, llm=llm, publishers=publishers)
        state.touch(name)
        ran.append(name)
    state.save()
    print(f"ran: {', '.join(ran) if ran else 'none'}")


if __name__ == '__main__':
    main()
