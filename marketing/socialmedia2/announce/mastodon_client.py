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

    def get_account_id(self) -> str | None:
        """Get the account ID (numeric) for the authenticated user."""
        client = self._client_or_none()
        if client is None:
            return None
        try:
            # Verify the token works and get account info
            account = client.account_verify_credentials()
            return str(account['id'])
        except Exception as e:
            print(f"❌ Failed to get account info: {e}")
            return None

    def fetch_statuses(self, count: int = 50, exclude_replies: bool = True) -> list:
        """Fetch the last N statuses from the authenticated account.

        Args:
            count: Number of statuses to fetch (default 50)
            exclude_replies: If True, exclude replies from the results

        Returns:
            List of status dicts with keys: id, created_at, content, visibility,
            reblogs_count, favorites_count, replies_count, media_attachments
        """
        client = self._client_or_none()
        if client is None:
            print("⚠️  Mastodon not configured "
                  "(need Mastodon.py installed + MASTODON_ACCESS_TOKEN).")
            return []

        try:
            account_id = self.get_account_id()
            if account_id is None:
                return []

            statuses = client.account_statuses(
                account_id,
                limit=count,
                exclude_replies=exclude_replies,
                only_media=False
            )

            # Return simplified status dicts
            result = []
            for status in statuses:
                result.append({
                    'id': status['id'],
                    'created_at': status['created_at'],
                    'content': status['content'],
                    'visibility': status['visibility'],
                    'reblogs_count': status.get('reblogs_count', 0),
                    'favourites_count': status.get('favourites_count', 0),  # Mastodon uses British spelling
                    'replies_count': status.get('replies_count', 0),
                    'media_attachments': status.get('media_attachments', []),
                })
            return result

        except Exception as e:
            print(f"❌ Failed to fetch statuses: {e}")
            return []

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
