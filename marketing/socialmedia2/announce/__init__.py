"""RaspiMIDIHub social announcer.

A small framework of autonomous content *sources* (YouTube uploads, GitHub
releases, feature/improvement spotlights) that each detect what's new, write a
post via a local LLM, and publish to Mastodon. A tick dispatcher
(``python -m announce.dispatch``) runs whichever sources are due on their own
cadence; each source is also runnable by hand (``python -m announce <source>``).

This is a workstation/server-side marketing tool — it is not part of the Pi
appliance image.
"""
