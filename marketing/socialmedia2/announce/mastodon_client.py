"""Mastodon posting — one place for credentials and the posting API.

Accepts a Post; uploads its inline image bytes (if any) before posting.
Mastodon.py wants a file path for media_post, so image bytes are spilled to a
short-lived temp file.
"""
import tempfile
from pathlib import Path

from . import config

try:
    from mastodon import Mastodon
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class MastodonPoster:
    name = 'mastodon'

    def __init__(self):
        self.instance = config.MASTODON_INSTANCE
        self.token = config.MASTODON_ACCESS_TOKEN
        self._client = None

    def configured(self) -> bool:
        return _AVAILABLE and bool(self.token)

    def _client_or_none(self):
        if not self.configured():
            return None
        if self._client is None:
            self._client = Mastodon(
                access_token=self.token, api_base_url=self.instance)
        return self._client

    def post(self, post) -> bool:
        client = self._client_or_none()
        if client is None:
            print("⚠️  Mastodon not configured "
                  "(need Mastodon.py installed + MASTODON_ACCESS_TOKEN).")
            return False
        tmp_path = None
        try:
            media_ids = None
            if post.media_bytes:
                suffix = '.png' if (post.media_mime or '').endswith('png') else ''
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(post.media_bytes)
                    tmp_path = tmp.name
                media = client.media_post(
                    tmp_path,
                    mime_type=post.media_mime or 'image/png',
                    description=post.media_desc or None)
                media_ids = [media['id']]
            client.status_post(post.text, media_ids=media_ids)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"❌ Mastodon post failed: {e}")
            return False
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink()
                except OSError:
                    pass
