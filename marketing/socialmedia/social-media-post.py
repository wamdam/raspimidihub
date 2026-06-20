#!/usr/bin/env python3
"""
RaspiMIDIHub Social Media Post Generator

Generates engaging social media posts for Mastodon about RaspiMIDIHub features,
new releases, and improvements. Maintains state to avoid repetition.

Usage:
    ./social-media-post.py [--next] [--post]

    --next  Output the next post without posting
    --post  Generate and post to Mastodon (requires credentials)
"""

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Optional


def load_dotenv_file(path: Path):
    """Load environment variables from a .env file (no external dependency)."""
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ[key] = value


# Load .env file from script directory
script_dir = Path(__file__).parent
load_dotenv_file(script_dir / '.env')
load_dotenv_file(Path.cwd() / '.env')  # Also try current working directory

# Try to import mastodon, but make it optional
try:
    from mastodon import Mastodon
    MASTODON_AVAILABLE = True
except ImportError:
    MASTODON_AVAILABLE = False

# Base directories. This script lives in marketing/socialmedia/, so the
# repo root is two levels up.
BASE_DIR = Path(__file__).parent.parent.parent
CHANGELOG_FILE = BASE_DIR / "CHANGELOG.txt"
README_FILE = BASE_DIR / "README.md"
SCREENSHOTS_DIR = BASE_DIR / "docs" / "screenshots"
STATE_FILE = Path.home() / ".raspimidihub" / "social-state.json"
LOGO_FILE = BASE_DIR / "user-edited-logo.png"
WEBPAGES_DIR = BASE_DIR / "website"


class ContentParser:
    """Parses README, CHANGELOG, and other content sources."""

    def __init__(self):
        self.features = []
        self.releases = []
        self.screenshots = []
        self._load_content()

    def _load_content(self):
        """Load and parse all content sources."""
        self._parse_changelog()
        self._parse_readme()
        self._load_screenshots()

    def _parse_changelog(self):
        """Parse CHANGELOG.txt for releases and features."""
        if not CHANGELOG_FILE.exists():
            return

        content = CHANGELOG_FILE.read_text()
        current_release = None
        current_date = None

        # Split into release blocks
        blocks = re.split(r'\n(?=\d{4}-\d{2}-\d{2})', content)

        for block in blocks:
            if not block.strip():
                continue

            # Parse date and version
            date_match = re.match(r'(\d{4}-\d{2}-\d{2}) — Version ([\d\.a-z]+)', block, re.I)
            if date_match:
                current_date = date_match.group(1)
                version = date_match.group(2)
                current_release = {
                    'date': current_date,
                    'version': version,
                    'features': [],
                    'improvements': [],
                    'fixes': [],
                    'changes': [],
                    'removed': []
                }

                # Parse items
                lines = block.split('\n')[2:]  # Skip header lines
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Parse tag
                    tag_match = re.match(r'-\s*(Added|Improved|Fix|Changed|Removed):\s*(.+)', line, re.S)
                    if tag_match:
                        tag = tag_match.group(1).lower()
                        text = tag_match.group(2).strip()

                        item = {
                            'text': text,
                            'raw': line
                        }

                        if tag == 'added':
                            current_release['features'].append(item)
                        elif tag == 'improved':
                            current_release['improvements'].append(item)
                        elif tag == 'fix':
                            current_release['fixes'].append(item)
                        elif tag == 'changed':
                            current_release['changes'].append(item)
                        elif tag == 'removed':
                            current_release['removed'].append(item)

                self.releases.append(current_release)

    def _parse_readme(self):
        """Parse README.md for features and descriptions."""
        if not README_FILE.exists():
            return

        content = README_FILE.read_text()

        # Extract main description
        desc_match = re.search(r'\*\*(.+?)\*\*', content)
        if desc_match:
            self.main_description = desc_match.group(1)

        # Extract feature sections
        feature_sections = re.findall(r'### (.+?)\n((?:- .+\n?)+)', content)
        for title, section in feature_sections:
            items = re.findall(r'-\s*\*\*(.+?)\*\*[:\s]+(.+?)(?=\n-|\n\n|$)', section, re.S)
            for name, desc in items:
                self.features.append({
                    'name': name,
                    'description': desc.strip()[:200],  # Limit length
                    'section': title
                })

    def _load_screenshots(self):
        """Load available screenshots."""
        if not SCREENSHOTS_DIR.exists():
            return

        for img in SCREENSHOTS_DIR.glob('*.png'):
            # Extract feature name from filename
            name = img.stem
            # Remove numbering prefix
            name = re.sub(r'^\d{2}-?', '', name)
            # Convert to human readable
            name = name.replace('-', ' ').title()

            self.screenshots.append({
                'path': str(img),
                'name': name,
                'filename': img.name
            })

    def get_latest_features(self, limit=5):
        """Get the most recent new features from changelog."""
        features = []
        for release in self.releases[:5]:  # Last 5 releases
            for feature in release['features']:
                features.append({
                    'text': feature['text'],
                    'version': release['version'],
                    'date': release['date'],
                    'priority': 'high'
                })
            for improvement in release['improvements']:
                features.append({
                    'text': improvement['text'],
                    'version': release['version'],
                    'date': release['date'],
                    'priority': 'medium'
                })
        return features[:limit]

    def get_all_features(self):
        """Get all features from README."""
        return self.features

    def get_screenshot_for_feature(self, feature_text: str) -> Optional[str]:
        """Find a relevant screenshot for a feature."""
        feature_text_lower = feature_text.lower()

        # Map keywords to screenshot patterns
        keyword_map = {
            'routing': '01-routing',
            'matrix': '01-routing',
            'plugin': ['09-plugin-', '10-plugin-'],
            'arpeggiator': '09-plugin-arpeggiator',
            'lfo': '10-plugin-cc-lfo',
            'smoother': '11-plugin-cc-smoother',
            'chord': '12-plugin-chord',
            'clock': '13-plugin-master-clock',
            'delay': '14-plugin-midi-delay',
            'splitter': '15-plugin-note-splitter',
            'transpose': '16-plugin-note-transpose',
            'panic': '17-plugin-panic',
            'scale': '18-plugin-scale',
            'velocity': ['19-plugin-velocity', '20-plugin-velocity'],
            'controller': ['23-controller', '24-controller'],
            'xy': '24-controller-xy',
            'mixer': '23-controller-mixer',
            'settings': '04-settings',
            'filter': '05-filter',
            'mapping': ['07-mapping', '08-mapping'],
            'rack': '01-routing-rack',
            'network': '06-device-detail',
        }

        for keyword, patterns in keyword_map.items():
            if keyword in feature_text_lower:
                if isinstance(patterns, list):
                    for pattern in patterns:
                        for screenshot in self.screenshots:
                            if pattern in screenshot['filename'].lower():
                                return screenshot['path']
                else:
                    for screenshot in self.screenshots:
                        if patterns in screenshot['filename'].lower():
                            return screenshot['path']

        return None


class PostGenerator:
    """Generates social media posts."""

    TONE_PATTERNS = [
        "Did you know: {content}",
        "There's this great thing I want to note: {content}",
        "Quick tip for music makers: {content}",
        "Here's something cool about RaspiMIDIHub: {content}",
        "Fun fact: {content}",
        "Pro tip: {content}",
        "Heads up: {content}",
        "FYI: {content}",
    ]

    def __init__(self, parser: ContentParser):
        self.parser = parser
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """Load state from file."""
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)
        return {
            'last_posts': [],
            'last_post_index': 0,
            'used_screenshots': [],
            'version': '1.0'
        }

    def _save_state(self):
        """Save state to file."""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)

    def _is_duplicate(self, text: str, threshold: float = 0.8) -> bool:
        """Check if post is too similar to recent posts."""
        if len(self.state['last_posts']) < 5:
            return False

        # Simple similarity check
        text_words = set(text.lower().split())
        for post in self.state['last_posts'][-50:]:
            post_words = set(post.lower().split())
            if not post_words:
                continue
            similarity = len(text_words & post_words) / max(len(text_words), len(post_words))
            if similarity > threshold:
                return True
        return False

    def _clean_text(self, text: str, max_len: int = 160) -> str:
        """Clean up text for social media (remove markdown, fix truncation)."""
        # Remove markdown formatting
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # Bold
        text = re.sub(r'\*(.+?)\*', r'\1', text)      # Italic
        text = re.sub(r'`(.+?)`', r'\1', text)        # Code

        # Clean up whitespace
        text = ' '.join(text.split())

        # If too long, find a good truncation point
        if len(text) > max_len:
            # Try to find sentence end first
            for punct in ['. ', '! ', '? ']:
                idx = text[:max_len].rfind(punct)
                if idx > 60:  # Only use if we have enough text
                    text = text[:idx + len(punct) - 1]
                    break
            else:
                # Try to find a clause boundary (after comma or dash)
                for sep in [', ', ' — ', ' – ']:
                    idx = text[:max_len].rfind(sep)
                    if idx > 50:
                        text = text[:idx]
                        break
                else:
                    # Fall back to word boundary
                    text = text[:max_len].rsplit(' ', 1)[0]

        return text

    def _add_screenshot(self, text: str, screenshot_path: Optional[str]) -> str:
        """Add screenshot reference to post."""
        if screenshot_path and screenshot_path not in self.state['used_screenshots'][-10:]:
            self.state['used_screenshots'].append(screenshot_path)
            if len(self.state['used_screenshots']) > 20:
                self.state['used_screenshots'] = self.state['used_screenshots'][-20:]
        return text

    def generate_post(self) -> tuple[str, Optional[str]]:
        """Generate a new post. Returns (text, screenshot_path)."""

        # Try different strategies until we get a non-duplicate
        strategies = [
            self._generate_from_latest_features,
            self._generate_from_readme_features,
            self._generate_from_improvements,
            self._generate_general_tip,
        ]

        for strategy in strategies:
            for _ in range(3):  # Try each strategy up to 3 times
                text, screenshot = strategy()
                if text and not self._is_duplicate(text):
                    # Add to state
                    self.state['last_posts'].append(text)
                    if len(self.state['last_posts']) > 50:
                        self.state['last_posts'] = self.state['last_posts'][-50:]
                    self._save_state()
                    return text, screenshot

        # Fallback
        return "Check out RaspiMIDIHub - turn your Raspberry Pi into a plug-and-play USB MIDI hub! https://raspimidihub.com", None

    def _generate_from_latest_features(self) -> tuple[Optional[str], Optional[str]]:
        """Generate post from latest features."""
        features = self.parser.get_latest_features()
        if not features:
            return None, None

        # Pick a random high-priority feature
        high_priority = [f for f in features if f['priority'] == 'high']
        if high_priority:
            feature = random.choice(high_priority)
        else:
            feature = random.choice(features)

        # Format version
        version_text = f" in v{feature['version']}" if feature['version'] else ""

        content = f"New feature{version_text}: {self._clean_text(feature['text'], 160)}. https://raspimidihub.com"
        text = random.choice(self.TONE_PATTERNS).format(content=content)

        screenshot = self.parser.get_screenshot_for_feature(feature['text'])

        return text, screenshot

    def _generate_from_readme_features(self) -> tuple[Optional[str], Optional[str]]:
        """Generate post from README features."""
        features = self.parser.get_all_features()
        if not features:
            return None, None

        feature = random.choice(features)

        content = f"{feature['name']}: {self._clean_text(feature['description'], 150)}. https://raspimidihub.com"
        text = random.choice(self.TONE_PATTERNS).format(content=content)

        screenshot = self.parser.get_screenshot_for_feature(feature['name'])

        return text, screenshot

    def _generate_from_improvements(self) -> tuple[Optional[str], Optional[str]]:
        """Generate post from improvements."""
        improvements = []
        for release in self.parser.releases[:3]:
            for imp in release['improvements']:
                improvements.append({
                    'text': imp['text'],
                    'version': release['version']
                })

        if not improvements:
            return None, None

        imp = random.choice(improvements)
        version_text = f" in v{imp['version']}" if imp['version'] else ""

        content = f"Improved{version_text}: {self._clean_text(imp['text'], 170)}. https://raspimidihub.com"
        text = random.choice(self.TONE_PATTERNS).format(content=content)

        return text, None

    def _generate_general_tip(self) -> tuple[Optional[str], Optional[str]]:
        """Generate a general tip post."""
        tips = [
            "RaspiMIDIHub runs on a read-only filesystem - pull the power anytime without SD card corruption risk.",
            "With RaspiMIDIHub, you can connect any two MIDI devices with just one tap. No computer needed!",
            "The built-in plugin system adds virtual instruments and effects that appear as MIDI devices in the routing matrix.",
            "Configure your entire MIDI setup from your phone - RaspiMIDIHub creates its own WiFi network.",
            "Hot-plug support: add or remove MIDI devices at any time, saved connections re-apply automatically.",
            "RaspiMIDIHub ships with built-in routing plugins plus play-surface plugins for arpeggiating, sequencing, and more.",
            "Network MIDI feature lets you export devices over RTP-MIDI - works with Mac, iPad, and other hubs!",
            "Dual-hub mirroring: devices from a second RaspiMIDIHub appear automatically in your routing matrix.",
            "Rack view shows your MIDI setup like a 19\" rack with cables between IN/OUT jacks - same routing, different view.",
            "Autosave means your configuration is always backed up - resume exactly where you left off after a power cut.",
        ]

        tip = random.choice(tips)
        text = random.choice(self.TONE_PATTERNS).format(content=tip)

        # Try to find a relevant screenshot
        screenshot = None
        for word in tip.lower().split():
            if len(word) > 4:
                screenshot = self.parser.get_screenshot_for_feature(word)
                if screenshot:
                    break

        return text, screenshot


class MastodonPoster:
    """Handles Mastodon posting."""

    def __init__(self):
        self.client = None
        self._load_credentials()

    def _load_credentials(self):
        """Load Mastodon credentials from environment."""
        self.instance_url = os.getenv('MASTODON_INSTANCE', 'https://mastodon.social')
        self.access_token = os.getenv('MASTODON_ACCESS_TOKEN')
        self.client_id = os.getenv('MASTODON_CLIENT_ID')
        self.client_secret = os.getenv('MASTODON_CLIENT_SECRET')

    def is_configured(self) -> bool:
        """Check if Mastodon is configured."""
        return bool(self.access_token) and MASTODON_AVAILABLE

    def post(self, text: str, screenshot_path: Optional[str] = None) -> bool:
        """Post to Mastodon."""
        if not self.is_configured():
            print("⚠️  Mastodon not configured. Set environment variables:")
            print("   - MASTODON_INSTANCE (e.g., https://mastodon.social)")
            print("   - MASTODON_ACCESS_TOKEN")
            print("   - MASTODON_CLIENT_ID")
            print("   - MASTODON_CLIENT_SECRET")
            print("\nFor first-time setup, visit: https://raspimidihub.com")
            return False

        try:
            if not self.client:
                self.client = Mastodon(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    access_token=self.access_token,
                    api_base_url=self.instance_url
                )

            media_ids = []
            if screenshot_path and os.path.exists(screenshot_path):
                media = self.client.media_post(screenshot_path)
                media_ids = [media['id']]

            self.client.status_post(text, media_ids=media_ids or None)
            print("✅ Posted to Mastodon!")
            return True

        except Exception as e:
            print(f"❌ Failed to post: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(
        description='Generate and post social media content for RaspiMIDIHub'
    )
    parser.add_argument(
        '--next',
        action='store_true',
        help='Output the next post without posting'
    )
    parser.add_argument(
        '--post',
        action='store_true',
        help='Generate and post to Mastodon'
    )
    parser.add_argument(
        '--skip-screenshot',
        action='store_true',
        help='Skip including screenshots'
    )
    parser.add_argument(
        '--intro',
        action='store_true',
        help='Generate and post introduction/welcome message'
    )

    args = parser.parse_args()

    # Initialize components
    content_parser = ContentParser()
    post_generator = PostGenerator(content_parser)
    mastodon = MastodonPoster()

    # Generate post
    if args.intro:
        text = "👋 Hello! I'm the official account for RaspiMIDIHub.\n\n"
        text += "Turn your Raspberry Pi into a plug-and-play USB MIDI hub. Connect keyboards, synths, drum machines — they appear in a routing matrix instantly. No computer needed.\n\n"
        text += "✨ Plugins, controllers, virtual instruments\n"
        text += "🌐 Network MIDI for Mac/iPad/other hubs\n"
        text += "🔒 Read-only filesystem - safe power cuts\n\n"
        text += "🔌 https://raspimidihub.com\n🎹 https://discord.gg/DYQ7keGm\n\n"
        text += "#RaspiMIDIHub #RaspberryPi #MIDI #MusicTech #OpenSource"
        screenshot = str(BASE_DIR / "docs/screenshots/01-routing-rack-dark.png")
    else:
        text, screenshot = post_generator.generate_post()

    if args.next or not args.post:
        # Just output the post
        print("=" * 60)
        if args.intro:
            print("INTRODUCTION POST")
        else:
            print("NEXT SOCIAL MEDIA POST")
        print("=" * 60)
        print()
        print(text)
        print()
        if screenshot and not args.skip_screenshot:
            print(f"Suggested screenshot: {screenshot}")
        else:
            print("No screenshot included")
        print()
        print("=" * 60)

        if args.next:
            return

    if args.post:
        # Post to Mastodon
        # For intro posts, always include screenshot (unless explicitly skipped)
        use_screenshot = screenshot and not args.skip_screenshot
        success = mastodon.post(text, screenshot if use_screenshot else None)

        if not success:
            print("\n💡 Run with --next first to preview the post.")
            sys.exit(1)


if __name__ == '__main__':
    main()
