"""Quick Tips source — short, actionable MIDI tips for hardware enthusiasts.

Each post is a concise tip about MIDI setup, troubleshooting, or best practices.
Focused on practical knowledge that helps users get more from their gear.
"""
import hashlib

from .. import config
from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = (
    "You write concise, practical MIDI tips for hardware enthusiasts and musicians. "
    "One short sentence, actionable advice. Conversational tone. "
    "No hashtags, no URLs, no emoji. Stay under 280 characters."
)

# Curated list of 50 quick MIDI tips
_QUICK_TIPS = [
    {
        "id": 1,
        "text": "Always use high-quality MIDI cables. Cheap cables can cause intermittent connections that result in dropped notes or erratic behavior.",
        "category": "cables",
    },
    {
        "id": 2,
        "text": "Keep MIDI cable runs under 50 feet. Longer runs can cause signal degradation and data errors.",
        "category": "cables",
    },
    {
        "id": 3,
        "text": "When daisy-chaining MIDI devices, use the THRU output, not the OUT. The OUT sends your device's data, THRU passes through the incoming data.",
        "category": "routing",
    },
    {
        "id": 4,
        "text": "If you're experiencing MIDI clock drift, try setting one device as the master clock and have all others sync to it.",
        "category": "timing",
    },
    {
        "id": 5,
        "text": "MIDI channels 1-16 are your friend. Assign different instruments to different channels to control them independently from one controller.",
        "category": "channels",
    },
    {
        "id": 6,
        "text": "When troubleshooting MIDI issues, start simple. Test with just two devices before adding more to the chain.",
        "category": "troubleshooting",
    },
    {
        "id": 7,
        "text": "MIDI doesn't carry audio. It only transmits performance data. You still need audio cables for sound.",
        "category": "basics",
    },
    {
        "id": 8,
        "text": "Program Change messages can instantly switch patches on your synths. Map them to your controller for quick sound changes during performance.",
        "category": "performance",
    },
    {
        "id": 9,
        "text": "CC 1 is Modulation Wheel, CC 7 is Volume, CC 11 is Expression. These standard assignments work across most MIDI devices.",
        "category": "cc",
    },
    {
        "id": 10,
        "text": "If your MIDI device isn't responding, check the channel first. The most common problem is mismatched channels.",
        "category": "troubleshooting",
    },
    {
        "id": 11,
        "text": "MIDI Time Code (MTC) is better than MIDI Clock for syncing with video. It's frame-accurate and works over longer distances.",
        "category": "sync",
    },
    {
        "id": 12,
        "text": "Use a MIDI merger if you have multiple controllers. It combines multiple MIDI inputs into one output without conflicts.",
        "category": "routing",
    },
    {
        "id": 13,
        "text": "MIDI Thru boxes are better than daisy-chaining for large setups. Each device gets a clean signal from the source.",
        "category": "routing",
    },
    {
        "id": 14,
        "text": "Save your MIDI setups! Most modern controllers let you store multiple configurations for different songs or contexts.",
        "category": "workflow",
    },
    {
        "id": 15,
        "text": "MIDI 2.0's Per-Note Pitch Bend lets you bend individual notes in a chord. It's a game-changer for expressive playing.",
        "category": "midi_2",
    },
    {
        "id": 16,
        "text": "When using Network MIDI, keep your network cables short and use a dedicated switch for best timing performance.",
        "category": "network",
    },
    {
        "id": 17,
        "text": "MIDI CC messages can control more than just synths. Try mapping them to lighting, effects pedals, or even smart home devices.",
        "category": "creative",
    },
    {
        "id": 18,
        "text": "If you're getting stuck notes, check for MIDI messages that aren't being properly terminated. A note-on without note-off causes this.",
        "category": "troubleshooting",
    },
    {
        "id": 19,
        "text": "MIDI Over USB is more reliable than traditional MIDI cables for computer connections. Use it when available.",
        "category": "connections",
    },
    {
        "id": 20,
        "text": "Transpose on your controller, not your synth. It keeps your original patch intact and lets you switch back instantly.",
        "category": "performance",
    },
    {
        "id": 21,
        "text": "MIDI Clock sends 24 pulses per quarter note. If your sequencer seems fast or slow, check the clock division settings.",
        "category": "timing",
    },
    {
        "id": 22,
        "text": "Use MIDI filters to clean up your signal. Block unnecessary messages like Aftertouch if your receiver doesn't need them.",
        "category": "routing",
    },
    {
        "id": 23,
        "text": "MIDI Machine Control (MMC) can start, stop, and transport your recorder remotely. Great for hands-free recording.",
        "category": "recording",
    },
    {
        "id": 24,
        "text": "When recording MIDI, record at the lowest latency your system can handle. It makes timing feel more natural.",
        "category": "recording",
    },
    {
        "id": 25,
        "text": "MIDI's 127 velocity levels give you expression. Practice controlling your touch for more dynamic performances.",
        "category": "performance",
    },
    {
        "id": 26,
        "text": "System Exclusive (SysEx) messages can dump synth patches. Use them to backup your custom sounds.",
        "category": "backup",
    },
    {
        "id": 27,
        "text": "MIDI Merge requires careful timing. If you're merging two controllers, make sure they're not sending the same messages simultaneously.",
        "category": "routing",
    },
    {
        "id": 28,
        "text": "Use MIDI Learn to map controller knobs to software parameters. It's faster than manually setting each one.",
        "category": "workflow",
    },
    {
        "id": 29,
        "text": "MIDI Over Bluetooth has improved significantly. For casual use, it's now reliable enough for most applications.",
        "category": "wireless",
    },
    {
        "id": 30,
        "text": "If you're using multiple synths, consider a MIDI sequencer that can send different patterns to different channels.",
        "category": "sequencing",
    },
    {
        "id": 31,
        "text": "MIDI CC 64 is the Sustain Pedal. Make sure your pedal polarity matches what your synth expects, or it will work backwards.",
        "category": "pedals",
    },
    {
        "id": 32,
        "text": "When setting up a live rig, label your MIDI cables. You'll thank yourself during soundcheck.",
        "category": "workflow",
    },
    {
        "id": 33,
        "text": "MIDI's 31.25 kbps speed is slow by modern standards. That's why it doesn't carry audio or high-resolution data.",
        "category": "technical",
    },
    {
        "id": 34,
        "text": "Use MIDI Thru for monitoring while recording. It lets you hear your performance with minimal latency.",
        "category": "recording",
    },
    {
        "id": 35,
        "text": "MIDI Program Changes can trigger entire setups. Map them to switch between different song configurations instantly.",
        "category": "performance",
    },
    {
        "id": 36,
        "text": "If your MIDI clock is unstable, try a dedicated clock source. Some devices have better clock circuits than others.",
        "category": "timing",
    },
    {
        "id": 37,
        "text": "MIDI's 5-pin DIN connector is polarized. You can't plug it in backwards, which prevents damage.",
        "category": "hardware",
    },
    {
        "id": 38,
        "text": "Use MIDI CC to automate parameters in real-time. Record the movements for a more human performance.",
        "category": "recording",
    },
    {
        "id": 39,
        "text": "MIDI Over TRS cables (like audio cables) is becoming popular. It's cheaper and more convenient than DIN for short runs.",
        "category": "connections",
    },
    {
        "id": 40,
        "text": "When using a loopback for monitoring, make sure to disable monitoring in your DAW to avoid double audio.",
        "category": "recording",
    },
    {
        "id": 41,
        "text": "MIDI's note range is 0-127, but most instruments only use 21-108. The extremes are often unused.",
        "category": "technical",
    },
    {
        "id": 42,
        "text": "Use MIDI filters to remove duplicate note-ons. Some controllers send them by accident, causing stuck notes.",
        "category": "troubleshooting",
    },
    {
        "id": 43,
        "text": "MIDI Clock can drift over long sessions. For precise timing, use MTC or Word Clock instead.",
        "category": "timing",
    },
    {
        "id": 44,
        "text": "When routing MIDI through a computer, use a virtual MIDI port. It gives you more flexibility than hardware routing.",
        "category": "routing",
    },
    {
        "id": 45,
        "text": "MIDI's Aftertouch can add expression to sustained notes. Try it on pads and strings for more life.",
        "category": "expression",
    },
    {
        "id": 46,
        "text": "If you're getting MIDI errors, try lowering the cable quality. Sometimes better cables cause more issues due to shielding.",
        "category": "troubleshooting",
    },
    {
        "id": 47,
        "text": "MIDI's 16 channels can be expanded with multiple cables. Use a multi-port interface for large setups.",
        "category": "scaling",
    },
    {
        "id": 48,
        "text": "Use MIDI CC to control your effects units. Reverb, delay, and modulation can all be automated via MIDI.",
        "category": "effects",
    },
    {
        "id": 49,
        "text": "MIDI's timing resolution is 24 PPQN (pulses per quarter note). For most music, this is more than adequate.",
        "category": "technical",
    },
    {
        "id": 50,
        "text": "When setting up a MIDI network, document your routing. It saves hours of troubleshooting later.",
        "category": "workflow",
    },
]


def _key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class QuickTipsSource(Source):
    name = 'quick_tips'

    def find_new(self, state) -> list:
        """Find the oldest unposted tip."""
        unposted = [
            tip for tip in _QUICK_TIPS
            if not state.is_announced(self.name, _key(tip['text']))
        ]
        
        if not unposted:
            state.reset(self.name)
            unposted = _QUICK_TIPS
        
        # Return oldest by ID for variety
        unposted.sort(key=lambda x: x['id'])
        return [unposted[0]]

    def latest(self) -> list:
        """Return the first tip for --force testing."""
        return [_QUICK_TIPS[0]]

    def render(self, item, llm) -> Post:
        """Transform the tip into a concise post."""
        user = (
            f"Write a concise MIDI tip (category: {item['category']}):\n"
            f"{item['text']}\n\n"
            "Make it actionable and clear. One sentence. "
            "No hashtags, no URLs, no emoji."
        )
        text = llm_or_template(
            llm, _SYSTEM, user,
            fallback=item['text'],
            max_len=280,
            temperature=0.5
        )
        return Post(
            text=append_link(text, "https://raspimidihub.com"),
            source=self.name,
            dedupe_key=_key(item['text'])
        )
