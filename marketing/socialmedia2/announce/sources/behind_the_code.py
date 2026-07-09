"""Behind the Code source — developer stories and technical deep-dives.

Posts about the development process, technical challenges, and design decisions
behind RaspiMIDIHub. Humanizes the project and educates users about the tech.
"""
import hashlib

from .. import config
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = (
    "You write engaging behind-the-scenes stories about software development. "
    "Conversational, human tone. Share the 'why' behind technical decisions. "
    "One or two short sentences. No hashtags, no URLs, no emoji. "
    "Stay under 280 characters."
)

# Curated behind-the-code stories
_BEHIND_CODE = [
    {
        "id": 1,
        "text": "The routing matrix started as a simple 8x8 grid. But users wanted more flexibility, so we rebuilt it as a dynamic graph that can handle any input-to-output mapping.",
        "topic": "architecture",
        "year": 2024,
    },
    {
        "id": 2,
        "text": "We spent three weeks debugging a MIDI timing issue. Turns out it was a race condition in the USB stack. The fix was three lines of code, but finding it took forever.",
        "topic": "debugging",
        "year": 2024,
    },
    {
        "id": 3,
        "text": "The dual-hub mirroring feature was inspired by a user's request. They wanted redundancy for live performances. Now it's one of our most popular features.",
        "topic": "user_feedback",
        "year": 2025,
    },
    {
        "id": 4,
        "text": "Network MIDI seemed impossible on a Raspberry Pi at first. The latency was too high. We optimized the packet handling and got it down to acceptable levels.",
        "topic": "optimization",
        "year": 2024,
    },
    {
        "id": 5,
        "text": "The plugin system was the hardest part to design. We wanted it to be extensible but not overwhelming. After many iterations, we settled on the current architecture.",
        "topic": "design",
        "year": 2023,
    },
    {
        "id": 6,
        "text": "We almost used a different OS, but Linux's MIDI support was too good to pass up. The ALSA subsystem made our lives so much easier.",
        "topic": "technology",
        "year": 2023,
    },
    {
        "id": 7,
        "text": "The UI went through five major redesigns. Each one taught us something about what users actually need versus what they say they want.",
        "topic": "ux",
        "year": 2024,
    },
    {
        "id": 8,
        "text": "Bluetooth MIDI was a nightmare to implement. The spec is vague, and every device handles it differently. But it's worth it for the cable-free convenience.",
        "topic": "challenges",
        "year": 2025,
    },
    {
        "id": 9,
        "text": "The tracker feature was inspired by tracker music software from the 90s. We wanted that precision but with a modern interface.",
        "topic": "inspiration",
        "year": 2023,
    },
    {
        "id": 10,
        "text": "We added the read-only filesystem after a user fried their SD card during a power cut. Now it's one of our most reliable features.",
        "topic": "reliability",
        "year": 2024,
    },
    {
        "id": 11,
        "text": "The Euclidean rhythm generator was a learning experience. We had to study music theory to understand how to implement it correctly.",
        "topic": "learning",
        "year": 2023,
    },
    {
        "id": 12,
        "text": "MIDI clock sync seemed simple until we tested it with 20 devices. The jitter was unacceptable. We had to implement a dedicated timing thread.",
        "topic": "timing",
        "year": 2024,
    },
    {
        "id": 13,
        "text": "The controller surface was designed for tactile feedback. Every button press should feel deliberate. We tested dozens of switches before finding the right ones.",
        "topic": "hardware",
        "year": 2023,
    },
    {
        "id": 14,
        "text": "We debated whether to include virtual instruments. Some said it was out of scope. But users wanted an all-in-one solution, so we added them.",
        "topic": "decisions",
        "year": 2024,
    },
    {
        "id": 15,
        "text": "The channel selector was added after a user pointed out that switching channels was too many taps. Now it's one tap instead of five.",
        "topic": "usability",
        "year": 2024,
    },
    {
        "id": 16,
        "text": "We almost skipped the mobile app, but the web interface wasn't working well on phones. The app solved so many usability issues.",
        "topic": "mobile",
        "year": 2025,
    },
    {
        "id": 17,
        "text": "The autosave feature was a response to a user losing hours of work. We now save every change automatically, with version history.",
        "topic": "safety",
        "year": 2024,
    },
    {
        "id": 18,
        "text": "Implementing MIDI 2.0 was a challenge. The spec is huge, and hardware support is still limited. But we wanted to be ready when it arrives.",
        "topic": "future",
        "year": 2025,
    },
    {
        "id": 19,
        "text": "The open-source license was a deliberate choice. We wanted the community to be able to learn from and improve the code.",
        "topic": "philosophy",
        "year": 2023,
    },
    {
        "id": 20,
        "text": "We tested the opto-isolators with 100 different cables. Some cheap ones caused issues. Now we recommend specific cable types.",
        "topic": "testing",
        "year": 2023,
    },
    {
        "id": 21,
        "text": "The arpeggiator had to support multiple modes. Simple up/down wasn't enough. We added random, order, and custom patterns.",
        "topic": "features",
        "year": 2024,
    },
    {
        "id": 22,
        "text": "We considered using a different microcontroller, but the Pi's processing power was necessary for the features we wanted.",
        "topic": "hardware",
        "year": 2023,
    },
    {
        "id": 23,
        "text": "The logging system was overengineered at first. We had too much detail. Now it's focused on what's actually useful for debugging.",
        "topic": "debugging",
        "year": 2024,
    },
    {
        "id": 24,
        "text": "We added the backup feature after a user bricked their device. Now you can restore from a backup in minutes, not hours.",
        "topic": "recovery",
        "year": 2024,
    },
    {
        "id": 25,
        "text": "The documentation was an afterthought at first. But users kept asking the same questions. Now we document everything.",
        "topic": "documentation",
        "year": 2024,
    },
]


def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class BehindTheCodeSource(Source):
    name = 'behind_the_code'

    def find_new(self, state) -> list:
        """Find the oldest unposted story."""
        unposted = [
            story for story in _BEHIND_CODE
            if not state.is_announced(self.name, _key(story['text']))
        ]
        
        if not unposted:
            state.reset(self.name)
            unposted = _BEHIND_CODE
        
        # Return oldest by ID
        unposted.sort(key=lambda x: x['id'])
        return [unposted[0]]

    def latest(self) -> list:
        """Return the first story for --force testing."""
        return [_BEHIND_CODE[0]]

    def render(self, item, llm) -> Post:
        """Transform the story into an engaging post."""
        user = (
            f"Write a behind-the-scenes story about software development (topic: {item['topic']}):\n"
            f"{item['text']}\n\n"
            "Make it conversational and human. One or two sentences. "
            "No hashtags, no URLs, no emoji."
        )
        text = llm_or_template(
            llm, _SYSTEM, user,
            fallback=item['text'],
            max_len=280,
            temperature=0.7
        )
        return Post(
            text=append_link(text, "https://raspimidihub.com"),
            source=self.name,
            dedupe_key=_key(item['text'])
        )
