"""Shared text helpers: markdown stripping, length trimming, LLM-or-template."""
import re

MASTODON_LIMIT = 500


def clean(text: str, max_len: int = 400) -> str:
    """Strip markdown, collapse whitespace, trim to a sentence/word boundary."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # bold
    text = re.sub(r'\*(.+?)\*', r'\1', text)      # italic
    text = re.sub(r'`(.+?)`', r'\1', text)        # code
    text = ' '.join(text.split())
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    for punct in ('. ', '! ', '? '):
        idx = cut.rfind(punct)
        if idx > 60:
            return cut[:idx + 1]
    return cut.rsplit(' ', 1)[0]


def append_link(text: str, url: str) -> str:
    return f"{text}\n\n{url}"


def llm_or_template(llm, system: str, user: str, *, fallback: str,
                    max_len: int = 400, temperature: float = 0.7) -> str:
    """Generate via the LLM; fall back to a deterministic template on failure."""
    out = llm.generate(system, user, temperature=temperature)
    return clean(out if out else fallback, max_len)
