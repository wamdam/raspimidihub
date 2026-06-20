# RaspiMIDIHub social announcer

A small framework that autonomously announces RaspiMIDIHub news to Mastodon:

- **YouTube** — new uploads from the playlist (via the public RSS feed, no API key).
- **GitHub** — new releases of `wamdam/raspimidihub` (public REST API, no auth).
- **Features** — rotating spotlights of recent features & improvements from the
  `CHANGELOG`, with a matching screenshot.

Every post is written by a local LLM for quality, with a deterministic template
fallback if the LLM is unreachable. Posts go to the **publishers** each source is routed to —
**Mastodon** and/or a **Discord** channel webhook — with per-target delivery
tracking so a partial failure retries only the target that missed (no
double-posting). Discord auto-embeds YouTube/GitHub links; feature posts upload
their screenshot.

**Routing** (config `SOURCE_TARGETS`): YouTube and GitHub releases go to *all*
configured publishers (Mastodon + Discord); the `features` spotlights are the
public ads and go to **Mastodon only** — they'd be noise in the Discord
community channel. A source not listed in `SOURCE_TARGETS` posts everywhere.

This is a **workstation/server-side marketing tool** — it is *not* part of the
Pi appliance image and does not ship to the device. It supersedes the older
`../socialmedia/` generator.

## Architecture

```
announce/
  config.py          env/.env loading, paths, schedule, source constants
  llm.py             LLMClient — OpenAI-compatible (vLLM on `spark` by default)
  mastodon_client.py \
  discord_client.py  publishers — post(Post); each has .name/.configured()/.post()
  state.py           JSON store: announced keys, seed flag, last-run per source
  content.py         read CHANGELOG/README/manual/screenshots: local repo or GitHub raw
  text.py            markdown strip / length trim / llm-or-template
  post.py            Post dataclass (text, media, dedupe_key)
  sources/
    base.py          Source contract: find_new() / latest() / render()
    youtube.py  github.py  features.py
  __main__.py        CLI — run one source by hand
  dispatch.py        the "tick" — run whichever sources are due
systemd/             one timer -> dispatch.py
```

Three abstractions carry the design:

1. **`Source`** — `find_new(state)` detects un-announced items (and *seeds* state
   on first run so old items aren't backfired); `render(item, llm)` builds the
   post with a per-source prompt; `latest()` powers `--force` for testing.
2. **`LLMClient`** — the single place that talks to the model.
3. **State** — per-source `announced` keys + `last_run`, so scheduling is
   crash-safe and survives the machine being off.

**Scheduling is a stateless tick.** One systemd timer fires `dispatch.py` every
~10 min; it runs each source whose interval (config `SCHEDULE`: youtube 1h,
github 1h, features 4h) has elapsed since its `last_run`. Adding a source later
is one module + one schedule entry — no new unit files.

## Install

```bash
python3 -m venv marketing/socialmedia2/.venv
marketing/socialmedia2/.venv/bin/pip install -r marketing/socialmedia2/requirements.txt
cp marketing/socialmedia2/.env.example marketing/socialmedia2/.env
# edit .env: Mastodon token and/or Discord webhook URL; LLM endpoint if not `spark`
```

## Usage

Run from the `marketing/socialmedia2/` directory (so the `announce` package
resolves), using the venv interpreter:

```bash
cd marketing/socialmedia2
.venv/bin/python -m announce youtube              # preview (dry-run)
.venv/bin/python -m announce youtube --post       # publish
.venv/bin/python -m announce features --force      # render latest, no state change
.venv/bin/python -m announce all --post            # every source once
.venv/bin/python -m announce.dispatch              # run whatever's due (what the timer calls)
```

Dry-run never publishes and never marks items announced. On the **first** run a
source *seeds* its baseline (records what already exists, announces nothing), so
only items that appear afterwards get posted.

## Scheduling (systemd)

The committed `.service` ships with placeholders (no machine-specific paths in
git). Fill them in for this host, then install — e.g.:

```bash
USER_NAME=$(whoami)
INSTALL_DIR=$(pwd)/marketing/socialmedia2     # absolute path to this dir
sed -e "s|<USER>|$USER_NAME|" -e "s|<INSTALL_DIR>|$INSTALL_DIR|" \
    marketing/socialmedia2/systemd/socialmedia2.service \
    | sudo tee /etc/systemd/system/socialmedia2.service >/dev/null
sudo cp marketing/socialmedia2/systemd/socialmedia2.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now socialmedia2.timer
systemctl list-timers socialmedia2.timer
```

(The installed copy under `/etc/systemd/system/` is local-only and never
committed.)

## Deploying to the website server

The content layer reads from GitHub raw when there's no local checkout, so the
server stays current with every `git push` — no redeploy to update its
knowledge. Two things to set in the server's `.env`:

- **`SOCIAL_LLM_BASE_URL`** — the workstation default `http://spark:8000/v1` is
  LAN-only and **not reachable from the server**. Point it at an endpoint the
  server can reach (a tunnel/VPN to `spark`, or another OpenAI-compatible
  endpoint), or set `SOCIAL_LLM_ENABLED=0` to fall back to templates.
- **`MASTODON_ACCESS_TOKEN`** — the posting account.

`SOCIAL_CONTENT_BASE` can stay unset (auto GitHub raw) or be pinned explicitly.
