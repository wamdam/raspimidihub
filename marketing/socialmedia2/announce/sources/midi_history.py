"""MIDI History source — posts historical facts about MIDI development.

Curated facts about MIDI's history, from its creation in 1983 to modern developments.
Educational content that appeals to both veteran musicians and newcomers.
"""
import hashlib

from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = (
    "You write engaging historical facts about MIDI for musicians and tech enthusiasts. "
    "One or two short sentences, conversational tone. Focus on interesting historical "
    "details, not dry specifications. No emoji, no source attribution, no URLs, no hashtags. "
    "Stay under 280 characters."
)

# Curated historical MIDI facts
_MIDI_HISTORIES = [
    {
        "text": "MIDI was created in 1982 by Dave Smith of Sequential Circuits and Ikutaro Kakehashi of Roland. They presented the proposal to Yamaha, Korg, and Kawai, who all agreed to adopt it.",
        "year": 1982,
        "topic": "creation",
    },
    {
        "text": "The first MIDI-equipped synthesizers hit the market in 1983: the Prophet-600 from Sequential Circuits and the Jupiter-6 from Roland. They could communicate with each other immediately.",
        "year": 1983,
        "topic": "first_implementations",
    },
    {
        "text": "MIDI's 31,250 baud transfer rate was chosen because it was fast enough for real-time performance but slow enough to work reliably with inexpensive opto-isolators.",
        "year": 1983,
        "topic": "technical",
    },
    {
        "text": "The original MIDI specification was only 44 pages long. Today's MIDI 2.0 specification runs to thousands of pages across multiple profile documents.",
        "year": 1983,
        "topic": "specification",
    },
    {
        "text": "Before MIDI, each synthesizer manufacturer used their own proprietary control protocols. A Korg couldn't talk to a Roland, making live performance with multiple synths nearly impossible.",
        "year": 1983,
        "topic": "pre_midi",
    },
    {
        "text": "The MIDI 5-pin DIN connector was chosen because it was already widely available and inexpensive, having been used for audio connections in hi-fi equipment.",
        "year": 1983,
        "topic": "hardware",
    },
    {
        "text": "Dave Smith won the first Technical Grammy in 2013 for his invention of MIDI, recognizing its impact on the music industry over 30 years.",
        "year": 2013,
        "topic": "recognition",
    },
    {
        "text": "MIDI's note-on/note-off message structure was inspired by telegraph systems. The concept of 'events' rather than continuous data streams was revolutionary.",
        "year": 1983,
        "topic": "technical",
    },
    {
        "text": "The General MIDI standard, introduced in 1991, ensured that the same program number would produce the same instrument sound across all GM-compatible devices.",
        "year": 1991,
        "topic": "general_midi",
    },
    {
        "text": "MIDI Time Code (MTC), developed in the late 1980s, allowed MIDI devices to synchronize with video equipment, opening up new possibilities for film and television.",
        "year": 1988,
        "topic": "synchronization",
    },
    {
        "text": "The original MIDI 1.0 specification has remained backward compatible for nearly 40 years. No other music technology standard has achieved this level of longevity.",
        "year": 1983,
        "topic": "longevity",
    },
    {
        "text": "MIDI Show Control (MSC) extended MIDI beyond music to control lighting, stage effects, and theatrical productions. It's still used in Broadway shows today.",
        "year": 1991,
        "topic": "theater",
    },
    {
        "text": "The MIDI Manufacturers Association (MMA) was formed in 1985 to maintain and develop the MIDI standard. It's still the governing body for MIDI today.",
        "year": 1985,
        "topic": "organization",
    },
    {
        "text": "USB MIDI was introduced in 1999, allowing MIDI devices to connect directly to computers without needing a traditional MIDI interface.",
        "year": 1999,
        "topic": "usb",
    },
    {
        "text": "Wireless MIDI over Bluetooth was standardized in 2012, finally freeing musicians from cables while maintaining the MIDI protocol.",
        "year": 2012,
        "topic": "wireless",
    },
    {
        "text": "MIDI 2.0 was approved in 2020, introducing features like 14-bit resolution, per-note pitch bend, and profile-based implementations. It's the biggest update since 1983.",
        "year": 2020,
        "topic": "midi_2",
    },
    {
        "text": "The original MIDI specification was developed in just six months. Dave Smith and Ikutaro Kakehashi met at the Winter NAMM show in 1981 and began the collaboration.",
        "year": 1981,
        "topic": "development",
    },
    {
        "text": "MIDI's success was so unexpected that the initial specification didn't include a formal test suite. Compliance was based on manufacturer goodwill.",
        "year": 1983,
        "topic": "specification",
    },
    {
        "text": "The term 'MIDI' was originally going to be 'Musical Interface Digital Interface' (MIDI), but they shortened it to avoid the awkward acronym.",
        "year": 1982,
        "topic": "naming",
    },
    {
        "text": "MIDI's 16 channels were chosen as a compromise between the need for multiple instruments and the bandwidth limitations of the 1980s.",
        "year": 1983,
        "topic": "technical",
    },
    {
        "text": "The first MIDI sequencer software was created by Scott Russell in 1983. It ran on an Apple II and could record and play back MIDI data.",
        "year": 1983,
        "topic": "sequencing",
    },
    {
        "text": "MIDI's impact on popular music was immediate. By 1985, most new synthesizers included MIDI, and it became the standard for music production.",
        "year": 1985,
        "topic": "adoption",
    },
    {
        "text": "The MIDI 1.0 Detailed Specification was published in 1984 and has been updated regularly since. It's one of the most comprehensive technical documents in music technology.",
        "year": 1984,
        "topic": "specification",
    },
    {
        "text": "MIDI's opto-isolator design prevents ground loops and electrical noise between devices. This was crucial for reliable operation in noisy stage environments.",
        "year": 1983,
        "topic": "hardware",
    },
    {
        "text": "The concept of 'System Exclusive' messages (SysEx) allowed manufacturers to send proprietary data while maintaining MIDI compatibility for standard messages.",
        "year": 1983,
        "topic": "technical",
    },
    {
        "text": "MIDI's success led to the creation of the Digital Audio Workstation (DAW) industry. Today's music production would be impossible without MIDI.",
        "year": 1990,
        "topic": "impact",
    },
    {
        "text": "The original MIDI cable length limit of 15 meters (50 feet) was determined by signal integrity testing. Longer cables could cause data corruption.",
        "year": 1983,
        "topic": "hardware",
    },
    {
        "text": "MIDI's note number system (0-127) maps to musical pitches with MIDI note 69 being A440 (the standard tuning pitch). This mapping is still used today.",
        "year": 1983,
        "topic": "technical",
    },
    {
        "text": "The MIDI Association (TMA) was formed in 2016 to promote MIDI 2.0 and ensure its adoption across the industry. It includes members from all major music technology companies.",
        "year": 2016,
        "topic": "organization",
    },
    {
        "text": "MIDI's velocity sensitivity (how hard a key is pressed) was one of its most innovative features. It added expression to what had been binary on/off control.",
        "year": 1983,
        "topic": "expression",
    },
]


def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class MidiHistorySource(Source):
    name = 'midi_history'

    def find_new(self, state) -> list:
        """Find the oldest unposted history fact."""
        unposted = [
            item for item in _MIDI_HISTORIES
            if not state.is_announced(self.name, _key(item['text']))
        ]
        
        if not unposted:
            state.reset(self.name)
            unposted = _MIDI_HISTORIES
        
        # Return oldest (by year), then by topic variety
        unposted.sort(key=lambda x: (x['year'], x['topic']))
        return [unposted[0]]

    def latest(self) -> list:
        """Return the oldest fact for --force testing."""
        sorted_items = sorted(_MIDI_HISTORIES, key=lambda x: (x['year'], x['topic']))
        return [sorted_items[0]]

    def render(self, item, llm) -> Post:
        """Transform the history fact into an engaging post."""
        user = (
            f"Write an engaging historical fact about MIDI (year: {item['year']}):\n"
            f"{item['text']}\n\n"
            "Make it conversational and interesting. One or two sentences. "
            "No hashtags, no URLs, no emoji."
        )
        text = llm_or_template(
            llm, _SYSTEM, user,
            fallback=f"Did you know? {item['text']}",
            max_len=280,
            temperature=0.6
        )
        return Post(
            text=append_link(text, "https://raspimidihub.com"),
            source=self.name,
            dedupe_key=_key(item['text'])
        )
