"""The Source contract.

A source knows how to (a) find items that haven't been announced yet, (b)
return the latest item regardless of state (for --force / manual testing), and
(c) render an item into a Post. State management (seeding, dedup) lives in
find_new so each source can express its own policy — "new uploads" for YouTube,
"rotate through the catalog" for features.
"""
from abc import ABC, abstractmethod

from ..post import Post


class Source(ABC):
    name: str = ''

    @abstractmethod
    def find_new(self, state) -> list:
        """Return items to announce now (may mutate/seed state). [] if nothing."""

    @abstractmethod
    def latest(self) -> list:
        """Return the most recent item(s) ignoring state (for --force)."""

    @abstractmethod
    def render(self, item, llm) -> Post:
        """Turn one item into a publishable Post."""
