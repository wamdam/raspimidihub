"""Discord posting via a channel webhook — the simplest "post to a given
channel": create a webhook in the target channel's settings and put its URL in
DISCORD_WEBHOOK_URL. No bot, no token, no gateway.

Discord auto-embeds YouTube/GitHub links, so link posts get rich previews for
free; feature posts upload their screenshot as an attachment.
"""
import json
import urllib.request

from . import config

_BOUNDARY = '----raspimidihubBoundaryZ9x'
# Discord (behind Cloudflare) 403s the default Python-urllib User-Agent.
_USER_AGENT = 'raspimidihub-social/1.0 (+https://raspimidihub.com)'


class DiscordPoster:
    name = 'discord'

    def __init__(self):
        self.webhook = config.DISCORD_WEBHOOK_URL

    def configured(self) -> bool:
        return bool(self.webhook)

    def post(self, post) -> bool:
        if not self.configured():
            print("⚠️  Discord not configured (set DISCORD_WEBHOOK_URL).")
            return False
        try:
            if post.media_bytes:
                body, content_type = self._multipart(post)
                headers = {'Content-Type': content_type}
            else:
                body = json.dumps({'content': post.text}).encode()
                headers = {'Content-Type': 'application/json'}
            headers['User-Agent'] = _USER_AGENT
            req = urllib.request.Request(self.webhook, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                r.read()  # 204 No Content on success
            return True
        except Exception as e:  # noqa: BLE001
            print(f"❌ Discord post failed: {e}")
            return False

    def _multipart(self, post):
        payload = json.dumps({'content': post.text})
        mime = post.media_mime or 'image/png'
        head = (
            f'--{_BOUNDARY}\r\n'
            'Content-Disposition: form-data; name="payload_json"\r\n'
            'Content-Type: application/json\r\n\r\n'
            f'{payload}\r\n'
            f'--{_BOUNDARY}\r\n'
            'Content-Disposition: form-data; name="files[0]"; '
            'filename="screenshot.png"\r\n'
            f'Content-Type: {mime}\r\n\r\n'
        ).encode()
        body = head + post.media_bytes + f'\r\n--{_BOUNDARY}--\r\n'.encode()
        return body, f'multipart/form-data; boundary={_BOUNDARY}'
