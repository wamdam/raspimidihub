"""Read repo content (CHANGELOG, README, manual, screenshots) from the local
working copy when present, else from GitHub raw.

This is what lets the announcer run on the website server with no checkout: it
re-reads GitHub on every run, so a ``git push`` updates its knowledge with no
redeploy. Locally it just reads the working copy (freshest, no network).
"""
import json
import re
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


def _list_dir(subdir: str, suffix: str) -> list:
    """Relative paths of files under docs/<subdir>. Local: glob. Remote: API."""
    if _LOCAL_ROOT:
        d = _LOCAL_ROOT / 'docs' / subdir
        if d.exists():
            return sorted(f"docs/{subdir}/{p.name}" for p in d.glob(f'*{suffix}'))
        return []
    url = (f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/"
           f"docs/{subdir}?ref={config.GITHUB_BRANCH}")
    req = urllib.request.Request(
        url, headers={'Accept': 'application/vnd.github+json',
                      'User-Agent': 'raspimidihub-social/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            entries = json.load(r)
        return sorted(f"docs/{subdir}/{e['name']}"
                      for e in entries if e['name'].endswith(suffix))
    except Exception:  # noqa: BLE001
        return []


def list_screenshots() -> list:
    """Relative paths of screenshot PNGs. Local: glob. Remote: GitHub contents API."""
    return _list_dir('screenshots', '.png')


def list_manual_files() -> list:
    """Relative paths of the manual chapter markdown files."""
    return _list_dir('manual', '.md')


def manual_chapters() -> dict:
    """relpath -> full markdown text for every readable manual chapter."""
    out = {}
    for rel in list_manual_files():
        txt = read_text(rel)
        if txt:
            out[rel] = txt
    return out


def _strip_md(text: str) -> str:
    text = re.sub(r'[*`]', '', text)            # bold/italic/code markers
    return ' '.join(text.split())


def _humanise(filename: str) -> str:
    stem = re.sub(r'\.png$', '', filename)
    stem = re.sub(r'^\d+-', '', stem)           # drop the leading scene number
    return stem.replace('-', ' ').strip()


# `![caption](../screenshots/foo.png)` as embedded in the manual chapters.
_SHOT_RE = re.compile(r'!\[(.*?)\]\(\.\./screenshots/([A-Za-z0-9_-]+\.png)\)', re.S)


def screenshot_catalog() -> list:
    """Describe every selectable screenshot, harvested from the manual.

    The manual embeds each screenshot with a written caption -- that is the
    authoritative description, far better than guessing from the filename. We
    scan every chapter, keep the richest caption per file and the chapter it
    lives in (for grounding the post copy), and fall back to the screenshots
    README table, then a humanised filename, so every shot stays selectable.

    Returns ``[{file, name, caption, chapter}]`` for the light-theme variants
    only -- the dark variants are the same screens and marketing posts use the
    light theme.
    """
    available = {p.rsplit('/', 1)[-1] for p in list_screenshots()}
    cap, chap = {}, {}
    for rel, txt in manual_chapters().items():
        for m in _SHOT_RE.finditer(txt):
            fname = m.group(2)
            caption = _strip_md(m.group(1))
            if fname not in cap or len(caption) > len(cap[fname]):
                cap[fname] = caption
                chap[fname] = rel
    readme = read_text('docs/screenshots/README.md') or ''
    for m in re.finditer(r'\|\s*`([^`]+\.png)`\s*\|\s*([^|]+?)\s*\|', readme):
        cap.setdefault(m.group(1), _strip_md(m.group(2)))
    catalog = []
    for fname in sorted(available):
        if fname.endswith('-dark.png'):
            continue
        catalog.append({
            'file': f"docs/screenshots/{fname}",
            'name': fname,
            'caption': cap.get(fname) or _humanise(fname),
            'chapter': chap.get(fname),
        })
    return catalog
