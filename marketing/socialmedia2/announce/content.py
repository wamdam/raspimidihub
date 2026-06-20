"""Read repo content (CHANGELOG, README, manual, screenshots) from the local
working copy when present, else from GitHub raw.

This is what lets the announcer run on the website server with no checkout: it
re-reads GitHub on every run, so a ``git push`` updates its knowledge with no
redeploy. Locally it just reads the working copy (freshest, no network).
"""
import json
import urllib.request
from pathlib import Path
from typing import Optional

from . import config


def _detect_local_root() -> Optional[Path]:
    if config.CONTENT_BASE and not config.CONTENT_BASE.startswith('http'):
        return Path(config.CONTENT_BASE)
    for start in (Path.cwd(), config.PKG_DIR):
        p = start
        for _ in range(8):
            if (p / 'CHANGELOG.txt').exists():
                return p
            if p.parent == p:
                break
            p = p.parent
    return None


_LOCAL_ROOT = _detect_local_root()
_REMOTE_BASE = (
    config.CONTENT_BASE
    if (config.CONTENT_BASE and config.CONTENT_BASE.startswith('http'))
    else config.GITHUB_RAW
)


def source_label() -> str:
    return f"local:{_LOCAL_ROOT}" if _LOCAL_ROOT else f"remote:{_REMOTE_BASE}"


def is_local() -> bool:
    return _LOCAL_ROOT is not None


def read_text(relpath: str) -> Optional[str]:
    if _LOCAL_ROOT:
        f = _LOCAL_ROOT / relpath
        return f.read_text() if f.exists() else None
    try:
        with urllib.request.urlopen(f"{_REMOTE_BASE}/{relpath}", timeout=30) as r:
            return r.read().decode('utf-8', 'replace')
    except Exception:  # noqa: BLE001
        return None


def read_bytes(relpath: str) -> Optional[bytes]:
    if _LOCAL_ROOT:
        f = _LOCAL_ROOT / relpath
        return f.read_bytes() if f.exists() else None
    try:
        with urllib.request.urlopen(f"{_REMOTE_BASE}/{relpath}", timeout=30) as r:
            return r.read()
    except Exception:  # noqa: BLE001
        return None


def list_screenshots() -> list:
    """Relative paths of screenshot PNGs. Local: glob. Remote: GitHub contents API."""
    if _LOCAL_ROOT:
        d = _LOCAL_ROOT / 'docs' / 'screenshots'
        if d.exists():
            return sorted(f"docs/screenshots/{p.name}" for p in d.glob('*.png'))
        return []
    url = (f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/"
           f"docs/screenshots?ref={config.GITHUB_BRANCH}")
    req = urllib.request.Request(
        url, headers={'Accept': 'application/vnd.github+json',
                      'User-Agent': 'raspimidihub-social/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            entries = json.load(r)
        return sorted(f"docs/screenshots/{e['name']}"
                      for e in entries if e['name'].endswith('.png'))
    except Exception:  # noqa: BLE001
        return []
