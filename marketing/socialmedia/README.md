# RaspiMIDIHub Social Media Post Generator

Automated social media post generator for RaspiMIDIHub. Creates engaging posts about features, improvements, and tips, with optional screenshot attachments.

This is a workstation-side marketing tool — it is **not** part of the appliance image and does not ship to the Pi. It lives under `marketing/socialmedia/`; all commands below are run from the repository root.

## Features

- **Content Sources**: Automatically extracts content from CHANGELOG.txt, README.md, and docs/screenshots/
- **Smart Deduplication**: Maintains state of last 50 posts to avoid repetition
- **Screenshot Matching**: Automatically finds relevant screenshots based on post content
- **Multiple Post Strategies**: Prioritizes new features, then improvements, then general tips
- **Mastodon Integration**: Ready to post to Mastodon when credentials are configured
- **Scheduled Execution**: Systemd timer for automatic posting every 6 hours

## Installation

1. Create a dedicated virtualenv and install dependencies (kept separate
   from the appliance dev `.venv` at the repo root — these deps don't ship
   to the Pi):
```bash
python3 -m venv marketing/socialmedia/.venv
marketing/socialmedia/.venv/bin/pip install -r marketing/socialmedia/requirements.txt
```

2. Copy and configure environment file:
```bash
cp marketing/socialmedia/.env.example marketing/socialmedia/.env
# Edit marketing/socialmedia/.env with your Mastodon credentials
```

3. Make the script executable:
```bash
chmod +x marketing/socialmedia/social-media-post.py
```

## Usage

Run the script with the venv interpreter so `Mastodon.py` is on the path
(`--next` previews work without it; `--post` needs it):

### Preview Next Post
```bash
marketing/socialmedia/.venv/bin/python marketing/socialmedia/social-media-post.py --next
```

### Generate and Post to Mastodon
```bash
marketing/socialmedia/.venv/bin/python marketing/socialmedia/social-media-post.py --post
```

### Skip Screenshot
```bash
marketing/socialmedia/.venv/bin/python marketing/socialmedia/social-media-post.py --next --skip-screenshot
```

## Configuration

### Mastodon Setup

1. Register an application at your Mastodon instance:
   - Visit: `https://your-instance/settings/applications`
   - Create a new application with "write" scope
   - Copy the Client ID and Client Secret

2. Get an access token:
   - Use OAuth flow or generate token manually
   - Add to `.env` file

3. Edit `.env`:
```env
MASTODON_INSTANCE=https://fosstodon.org
MASTODON_ACCESS_TOKEN=your_token_here
MASTODON_CLIENT_ID=your_client_id
MASTODON_CLIENT_SECRET=your_client_secret
```

### Scheduled Posting

To enable automatic posting every 6 hours:

1. Copy systemd files:
```bash
sudo cp marketing/socialmedia/raspimidihub-social-media.service /etc/systemd/system/
sudo cp marketing/socialmedia/raspimidihub-social-media.timer /etc/systemd/system/
```

2. Enable and start the timer:
```bash
sudo systemctl daemon-reload
sudo systemctl enable raspimidihub-social-media.timer
sudo systemctl start raspimidihub-social-media.timer
```

3. Check timer status:
```bash
sudo systemctl status raspimidihub-social-media.timer
sudo systemctl list-timers
```

## State Management

The script maintains state in `~/.raspimidihub/social-state.json`:

- `last_posts`: List of last 50 posted texts
- `used_screenshots`: Recent screenshot usage history
- Prevents duplicate or too-similar posts

To reset state:
```bash
rm ~/.raspimidihub/social-state.json
```

## Post Generation Strategy

The generator tries these strategies in order:

1. **Latest Features**: New features from recent changelog entries (high priority)
2. **README Features**: General feature descriptions from README
3. **Improvements**: Notable improvements from recent releases
4. **General Tips**: Evergreen tips about RaspiMIDIHub functionality

Each strategy generates multiple variations until a non-duplicate post is found.

## Tone Patterns

Posts use engaging tones like:
- "Did you know: ..."
- "There's this great thing I want to note: ..."
- "Quick tip for music makers: ..."
- "Fun fact: ..."
- "Pro tip: ..."

## Screenshots

The script automatically matches screenshots to post content:
- Routing matrix posts → routing screenshots
- Plugin posts → corresponding plugin screenshots
- Controller posts → controller screenshots
- Settings posts → settings screenshots

Screenshots are rotated to avoid overuse.

## Example Output

```
============================================================
NEXT SOCIAL MEDIA POST
============================================================

Did you know: New feature in v5.1.1: Factory Reset button (Settings → Sys Info). Erases routing, plugins, filters and settings and reboots clean. Your WiFi/AP settings and your rolling backups are kept. https://raspimidihub.com

Suggested screenshot: docs/screenshots/04-settings.png
============================================================
```

## Troubleshooting

### No new posts generated
- Check if CHANGELOG.txt has new entries
- Reset state file to try all strategies again

### Mastodon posting fails
- Verify credentials in `.env`
- Check that `Mastodon.py` is installed in the venv (`marketing/socialmedia/.venv/bin/pip show Mastodon.py`)
- Ensure access token has "write" scope

### Screenshot not found
- Script will post without screenshot if no match found
- Add more screenshots to `docs/screenshots/`

## License

LGPL - same as RaspiMIDIHub
