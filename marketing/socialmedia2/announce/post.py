"""The Post value object passed from a source's render() to the poster."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Post:
    text: str
    source: str
    dedupe_key: str
    media_bytes: Optional[bytes] = None
    media_mime: Optional[str] = None
    media_desc: Optional[str] = None  # alt text for accessibility
