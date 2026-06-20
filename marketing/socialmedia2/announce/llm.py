"""LLM client — one place that talks to the OpenAI-compatible endpoint.

Defaults to the local vLLM server on `spark`. The model there is a Qwen3
reasoning model: without ``enable_thinking=false`` it spends the entire token
budget "thinking" and returns empty content, so we disable it. Any failure
returns None so callers fall back to a template.
"""
import json
import urllib.request
from typing import Optional

from . import config


class LLMClient:
    def __init__(self):
        self.enabled = config.LLM_ENABLED
        self.base = config.LLM_BASE_URL
        self.model = config.LLM_MODEL
        self.api_key = config.LLM_API_KEY

    def generate(self, system: str, user: str, *,
                 max_tokens: int = 600, temperature: float = 0.7) -> Optional[str]:
        if not self.enabled:
            return None
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
            'max_tokens': max_tokens,
            'temperature': temperature,
            'chat_template_kwargs': {'enable_thinking': False},
        }
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        req = urllib.request.Request(
            f'{self.base}/chat/completions',
            data=json.dumps(payload).encode(),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.load(resp)
            content = body['choices'][0]['message'].get('content')
            return content.strip() if content else None
        except Exception as e:  # noqa: BLE001 — network/parse, fall back to template
            print(f"⚠️  LLM unavailable ({e}); using template fallback.")
            return None
