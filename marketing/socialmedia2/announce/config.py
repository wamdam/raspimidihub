"""Central configuration: .env loading, paths, schedule, source constants.

Everything tunable lives here and is overridable via environment / .env, so the
same code runs unchanged locally (LLM on `spark`, content from the working
copy) and on the website server later (LLM endpoint swapped, content from
GitHub raw).
"""
import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
ROOT_DIR = PKG_DIR.parent  # marketing/socialmedia2/


def _load_dotenv(path: Path):
    """Minimal .env loader (no external dependency). First definition wins."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# Load .env from the package root first, then the working directory.
_load_dotenv(ROOT_DIR / '.env')
_load_dotenv(Path.cwd() / '.env')


def _env(key, default=None):
    return os.environ.get(key, default)


# --- Content sources ------------------------------------------------------
GITHUB_REPO = _env('SOCIAL_GITHUB_REPO', 'wamdam/raspimidihub')
GITHUB_BRANCH = _env('SOCIAL_GITHUB_BRANCH', 'main')
YOUTUBE_PLAYLIST_ID = _env(
    'SOCIAL_YOUTUBE_PLAYLIST_ID', 'PLtvjGBXW1XVlCX-6kVOwsjVSW12kIFKJ7'
)

# Where CHANGELOG/README/manual/screenshots are read from. Unset auto-detects
# the local repo (walk up for CHANGELOG.txt) and falls back to GitHub raw, so
# the same code works on a server with no checkout. Set to a path to force a
# local copy, or to a raw base URL to force remote.
CONTENT_BASE = _env('SOCIAL_CONTENT_BASE')
GITHUB_RAW = f'https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}'

# --- LLM (OpenAI-compatible; local vLLM on `spark` by default) ------------
LLM_ENABLED = _env('SOCIAL_LLM_ENABLED', '1') not in ('0', 'false', 'no', '')
LLM_BASE_URL = _env('SOCIAL_LLM_BASE_URL', 'http://spark:8000/v1').rstrip('/')
LLM_MODEL = _env('SOCIAL_LLM_MODEL', 'qwen/qwen3.5-122b')
LLM_API_KEY = _env('SOCIAL_LLM_API_KEY', '')

# --- Publishers -----------------------------------------------------------
MASTODON_INSTANCE = _env('MASTODON_INSTANCE', 'https://mastodon.social')
MASTODON_ACCESS_TOKEN = _env('MASTODON_ACCESS_TOKEN')
# Discord channel webhook (Channel Settings -> Integrations -> Webhooks):
DISCORD_WEBHOOK_URL = _env('DISCORD_WEBHOOK_URL')

# --- State ----------------------------------------------------------------
STATE_DIR = Path(
    _env('SOCIAL_STATE_DIR', str(Path.home() / '.raspimidihub' / 'socialmedia2'))
)
STATE_FILE = STATE_DIR / 'state.json'

# --- Per-source publisher routing -----------------------------------------
# Which publishers each source posts to. A source NOT listed here goes to every
# configured publisher. 'features' (the public feature/improvement ads) is
# Mastodon-only — those would be noise in the Discord community channel.
# 'jokes', 'midi_facts', 'midi_history', 'quick_tips', 'behind_the_code' are
# also Mastodon-only for the same reason.
SOURCE_TARGETS = {
    'features': ['mastodon'],
    'jokes': ['mastodon'],
    'midi_facts': ['mastodon'],
    'creative_uses': ['mastodon'],  # Educational content, Mastodon only
    'midi_history': ['mastodon'],   # Educational content, Mastodon only
    'quick_tips': ['mastodon'],     # Educational content, Mastodon only
    'behind_the_code': ['mastodon'],  # Developer stories, Mastodon only
    # 'youtube' / 'github' omitted -> all configured publishers
}

# --- Schedule (seconds) for the dispatch tick -----------------------------
SCHEDULE = {
    'youtube': int(_env('SOCIAL_INTERVAL_YOUTUBE', 3600)),     # 1h
    'github': int(_env('SOCIAL_INTERVAL_GITHUB', 3600)),       # 1h
    'features': int(_env('SOCIAL_INTERVAL_FEATURES', 21600)),  # 6h (reduced frequency)
    'jokes': int(_env('SOCIAL_INTERVAL_JOKES', 43200)),        # 12h (reduced frequency)
    'midi_facts': int(_env('SOCIAL_INTERVAL_MIDI_FACTS', 43200)),  # 12h
    'creative_uses': int(_env('SOCIAL_INTERVAL_CREATIVE_USES', 86400)),  # 24h
    'midi_history': int(_env('SOCIAL_INTERVAL_MIDI_HISTORY', 86400)),  # 24h
    'quick_tips': int(_env('SOCIAL_INTERVAL_QUICK_TIPS', 43200)),  # 12h
    'behind_the_code': int(_env('SOCIAL_INTERVAL_BEHIND_CODE', 172800)),  # 48h
}

SITE_URL = _env('SOCIAL_SITE_URL', 'https://raspimidihub.com')
