"""Jokes source — posts from a curated list of 100 MIDI-themed jokes.

This bot uses a pre-generated list of 100 original MIDI/hardware-themed jokes
for Mastodon. Each joke is posted once per cycle, then the cycle restarts.
The LLM can optionally polish each joke before posting.

Target audience: Hardware enthusiasts, synth owners, electronics hobbyists.
Avoids DAW/software references; focuses on physical connections, cables,
Raspberry Pi, patch bays, THRU boxes, and hardware tinkerers.
"""
import hashlib

from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = (
    "You are a witty music technology comedian. Polish this MIDI/hardware-themed "
    "joke for social media. Keep it under 280 characters. No hashtags, no URLs. "
    "At most one emoji if it fits naturally. Audience: hardware enthusiasts, "
    "not DAW users."
)

# A curated list of 100 original MIDI/hardware-themed jokes
# Focused on physical connections, cables, Raspberry Pi, patch bays, THRU boxes
# Avoids DAW/software references
_JOKES = [
    "Why don't MIDI cables ever get lost? They always know their channel.",
    "What's a MIDI cable's favorite type of music? Anything with good connections.",
    "Why did the synthesizer bring a ladder to the concert? To reach the high notes.",
    "What do you call a MIDI hub that tells jokes? A stand-hub comedian.",
    "Why was the MIDI note so good at math? It could count to 127.",
    "Why did the MIDI controller go to therapy? It had too many knobs to turn.",
    "What do you call a MIDI message that's always late? A delayed packet.",
    "Why was the MIDI hub so good at parties? It knew how to route the fun.",
    "What's a synthesizer's favorite type of weather? Thunder and lightning effects.",
    "Why did the MIDI cable become a therapist? It helped people work through their issues.",
    "What do you call a MIDI channel that's always positive? An upbeat channel.",
    "Why was the MIDI note so good at sports? It had great pitch control.",
    "Why did the MIDI controller become a chef? It knew how to mix the right ingredients.",
    "What do you call a MIDI message that's always calm? A steady byte.",
    "Why was the MIDI hub so good at meditation? It found its inner frequency.",
    "Why did the MIDI cable become a detective? It could trace any connection.",
    "What do you call a MIDI controller that's always honest? A true knob.",
    "Why was the MIDI note so good at school? It always hit the right notes.",
    "Why did the MIDI controller become a therapist? It helped people find their rhythm.",
    "What do you call a MIDI message that's always ready? A prepared packet.",
    "Why was the MIDI hub so good at teamwork? It connected everyone.",
    "Why did the MIDI cable become a philosopher? It questioned the nature of sound.",
    "What do you call a MIDI channel that's always curious? An inquisitive channel.",
    "Why was the MIDI note so good at dancing? It had perfect timing.",
    "Why did the MIDI controller become a writer? It had a lot to express.",
    "What do you call a MIDI message that's always kind? A gentle byte.",
    "Why was the MIDI hub so good at problem-solving? It found the right path.",
    "Why did the MIDI cable become a musician? It knew how to connect the dots.",
    "What do you call a MIDI controller that's always brave? A fearless knob.",
    "Why was the MIDI note so good at leadership? It knew how to guide the melody.",
    "Why did the MIDI controller become a teacher? It knew how to tune students in.",
    "What do you call a MIDI message that's always creative? An imaginative byte.",
    "Why was the MIDI hub so good at friendship? It brought people together.",
    "What's a synthesizer's favorite type of vacation? A frequency retreat.",
    "Why did the MIDI cable become a counselor? It helped resolve conflicts.",
    "What do you call a MIDI channel that's always reliable? A steady channel.",
    "Why was the MIDI note so good at motivation? It inspired others to perform.",
    "Why did the MIDI controller become a guide? It showed the way to great sound.",
    "What do you call a MIDI message that's always wise? A knowledgeable byte.",
    "Why was the MIDI hub so good at wisdom? It understood every connection.",
    "What's a synthesizer's favorite type of wisdom? Sound philosophy.",
    "I asked my Raspberry Pi if it believed in ghosts. It said, 'Only in my MIDI cables.'",
    "Why did the hardware synth go to art school? It wanted to learn about patching colors.",
    "I asked my MIDI hub how it stays so cool. It said, 'I have excellent ventilation.'",
    "What do you call a MIDI cable that's been on vacation? A relaxed connector.",
    "My patch bay has commitment issues. It can't decide which signal to route.",
    "Why don't hardware synths ever get stressed? They know how to handle their voltage.",
    "I tried to tell my opto-isolator a joke. It said it needed to process it first.",
    "What's a hardware tinkerer's favorite weather? A good thunderstorm for grounding practice.",
    "My MIDI interface told me it's feeling a bit disconnected. I plugged it back in.",
    "Why did the Raspberry Pi start a band? It wanted to be the main controller.",
    "I asked my THRU box if it has any siblings. It said, 'I'm one of many.'",
    "What do you call a hardware synth that loves to dance? A rhythm machine.",
    "My patch cables are great listeners. They never interrupt the signal.",
    "Why don't MIDI enthusiasts ever get bored? There's always something to patch.",
    "I tried to explain Bluetooth MIDI to my cat. She just walked away.",
    "What's a hardware enthusiast's favorite movie genre? Cable westerns.",
    "My hardware synth has excellent manners. It always completes its handshake.",
    "Why did the MIDI cable go to therapy? It had too many connection issues.",
    "I asked my Raspberry Pi if it dreams of electric sheep. It said, 'Only MIDI ones.'",
    "What do you call a THRU box that tells stories? A pass-through narrative.",
    "My opto-isolator is great at boundaries. It knows when to let things through.",
    "Why don't hardware synths ever get lost in the studio? They always follow their cables.",
    "I tried to count all my patch cables. I lost count at 'plenty.'",
    "What's a hardware tinkerer's favorite board game? Circuit-opoly.",
    "My MIDI hub told me it's feeling a bit overworked. I said, 'You're just wired that way.'",
    "Why did the patch cable win the award? It was outstanding in its field.",
    "I asked my hardware synth if it believes in fate. It said, 'I believe in patch notes.'",
    "What do you call a MIDI cable that's always positive? An optimistic connector.",
    "My Raspberry Pi has great networking skills. It connects everything beautifully.",
    "Why don't opto-isolators ever get into arguments? They keep their circuits separate.",
    "I tried to tell my THRU box a secret. It just passed it right along.",
    "What's a hardware enthusiast's favorite drink? Soldering flux, but only as a metaphor.",
    "My MIDI interface told me it's feeling a bit buffered. I said, 'That's normal.'",
    "Why did the hardware synth become a teacher? It wanted to help others find their signal.",
    "I asked my patch bay if it ever gets confused. It said, 'I route, therefore I am.'",
    "What do you call a Raspberry Pi that tells jokes? A comedi-an Pi.",
    "My hardware cables have great loyalty. They stick with me through thick and thin insulation.",
    "Why don't MIDI enthusiasts ever get stuck? They always have a THRU box to help out.",
    "I tried to explain network MIDI to my neighbor. He thought I was talking about WiFi.",
    "What's a hardware tinkerer's favorite philosophy? Everything should be patchable.",
    "My opto-isolator has excellent judgment. It knows when to conduct and when to isolate.",
    "Why did the MIDI cable become a therapist? It's great at helping connections work through issues.",
    "I asked my Raspberry Pi if it's ever lonely. It said, 'I have 40 GPIO friends.'",
    "What do you call a hardware synth that loves mysteries? A patch detective.",
    "My patch bay is the ultimate host. Every signal gets a place to go.",
    "Why did the hardware enthusiast bring a ladder to the concert? To reach the top of the rack.",
    "What's a hardware synth's favorite type of exercise? Cable stretching.",
    "Why don't hardware enthusiasts ever argue about tone? They just adjust their potentiometers.",
    "My MIDI interface has a great sense of direction. It always knows which pin is pin 1.",
    "What do you call a Raspberry Pi that loves to jam? A hardware tinkerer.",
    "What do you call a 5-pin DIN connector that tells tall tales? A stretch cable.",
    "My THRU box never keeps secrets. It shares everything with all its friends.",
    "Why did the opto-isolator become a philosopher? It understood the light between worlds.",
    "What's a hardware synth's favorite social media? Patch-ter.",
    "I asked my MIDI cable about its relationship status. It said, 'It's complicated - I'm connected to everything.'",
    "Why don't patch bays ever play hide and seek? They're always found in the rack.",
    "What do you call a Raspberry Pi that loves to tell stories? A tale-bearer.",
    "My hardware synth has great boundaries. It knows where its signal ends and yours begins.",
    "Why did the MIDI enthusiast bring a map to the studio? To find the best signal path.",
    "What's a THRU box's favorite type of story? A pass-through tale.",
]


def _key(text: str) -> str:
    """Generate a deduplication key from the source joke text."""
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class JokesSource(Source):
    name = 'jokes'

    def find_new(self, state) -> list:
        """Return the next unposted joke from the curated list."""
        for joke in _JOKES:
            if not state.is_announced(self.name, _key(joke)):
                return [{'text': joke}]
        # Cycle exhausted, reset and start over
        state.reset(self.name)
        return [{'text': _JOKES[0]}]

    def latest(self) -> list:
        """Return the first joke for --force testing."""
        return [{'text': _JOKES[0]}]

    def render(self, item, llm) -> Post:
        """Polish the joke using the LLM."""
        user = f"Polish this MIDI joke for a social media post:\n{item['text']}"
        text = llm_or_template(
            llm, _SYSTEM, user,
            fallback=item['text'],
            max_len=280,
            temperature=0.7
        )
        # Dedupe key is based on the SOURCE joke, not the LLM output
        dedupe_key = _key(item['text'])
        return Post(
            text=append_link(text, "https://raspimidihub.com"),
            source=self.name,
            dedupe_key=dedupe_key
        )
