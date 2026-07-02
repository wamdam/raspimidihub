"""Jokes source — posts from a curated list of 100 MIDI-themed jokes.

This bot uses a pre-generated list of 100 original MIDI/music-themed jokes
for Mastodon. Each joke is posted once per cycle, then the cycle restarts.
The LLM can optionally polish each joke before posting.
"""
import hashlib

from ..post import Post
from ..text import append_link, llm_or_template
from .base import Source

_SYSTEM = (
    "You are a witty music technology comedian. Polish this MIDI/music-themed "
    "joke for social media. Keep it under 280 characters. No hashtags, no URLs. "
    "At most one emoji if it fits naturally."
)

# A curated list of 100 original MIDI-themed jokes
_JOKES = [
    "Why did the MIDI cable cross the road? To get to the other side! 🎹",
    "What's a synthesizer's favorite type of vacation? A filter sweep to the beach.",
    "Why did the MIDI message become a writer? It had a lot to say.",
    "What do you call a MIDI controller that's always curious? An inquisitive knob.",
    "Why was the MIDI channel so adventurous? It explored new frequencies.",
    "What's a music producer's favorite type of cooking? Sampling.",
    "Why did the MIDI hub become a detective? It solved connection mysteries.",
    "What do you call a MIDI cable that's always brave? A fearless wire.",
    "Why was the MIDI note so creative? It thought outside the staff.",
    "What's a synthesizer's favorite type of game? Patch and seek.",
    "Why did the MIDI controller become a philosopher? It pondered the nature of sound.",
    "What do you call a MIDI message that's always friendly? A welcome packet.",
    "Why was the MIDI hub so patient? It knew good things take time.",
    "What's a music producer's favorite type of exercise? Beat boxing.",
    "Why did the MIDI cable become a poet? It expressed itself beautifully.",
    "What do you call a MIDI controller that's always generous? A sharing knob.",
    "Why was the MIDI channel so mysterious? It had hidden messages.",
    "What's a synthesizer's favorite type of literature? Sound bytes.",
    "Why did the MIDI note become an athlete? It had great endurance.",
    "What do you call a MIDI cable that's always reliable? A trusty wire.",
    "Why was the MIDI hub so humble? It let others shine through.",
    "What's a music producer's favorite type of movie? A blockbuster hit.",
    "Why did the MIDI controller become a gardener? It loved growing sounds.",
    "What do you call a MIDI message that's always optimistic? A positive byte.",
    "Why was the MIDI channel so wise? It had seen many signals.",
    "What's a synthesizer's favorite type of sport? Wave racing.",
    "Why did the MIDI hub become a librarian? It organized sounds perfectly.",
    "What do you call a MIDI cable that's always energetic? A lively wire.",
    "Why was the MIDI note so determined? It never gave up its pitch.",
    "What's a music producer's favorite type of weather? A storm of inspiration.",
    "Why did the MIDI controller become a magician? It made sounds appear.",
    "What do you call a MIDI message that's always helpful? A service packet.",
    "Why was the MIDI hub so creative? It found new paths for signals.",
    "What's a synthesizer's favorite type of music? Electronic soul.",
    "Why did the MIDI cable become an artist? It painted with sound.",
    "What do you call a MIDI controller that's always thoughtful? A considerate knob.",
    "Why was the MIDI channel so inspiring? It sparked creativity.",
    "What's a music producer's favorite type of food? Audio bites.",
    "Why did the MIDI note become a historian? It remembered every performance.",
    "What do you call a MIDI cable that's always peaceful? A zen wire.",
    "Why was the MIDI hub so adaptable? It worked with everything.",
    "What's a synthesizer's favorite type of art? Digital impressionism.",
    "Why did the MIDI controller become a scientist? It experimented with sound.",
    "What do you call a MIDI message that's always confident? A bold byte.",
    "Why was the MIDI channel so generous? It shared its bandwidth.",
    "What's a music producer's favorite type of drink? A remix cocktail.",
    "Why did the MIDI cable become a teacher? It educated about connections.",
    "What do you call a MIDI controller that's always playful? A fun knob.",
    "Why was the MIDI note so resilient? It bounced back from silence.",
    "What's a synthesizer's favorite type of hobby? Sound design.",
    "Why did the MIDI hub become a coach? It motivated signals to perform.",
    "What do you call a MIDI message that's always gentle? A soft byte.",
    "Why was the MIDI channel so memorable? It left an impression.",
    "What's a music producer's favorite type of hobby? Vinyl collecting.",
    "Why did the MIDI cable become a storyteller? It connected narratives.",
    "What do you call a MIDI controller that's always precise? An accurate knob.",
    "Why was the MIDI note so passionate? It poured its heart into every performance.",
    "What's a synthesizer's favorite type of vacation? A sound retreat.",
    "Why did the MIDI hub become a mentor? It guided new signals.",
    "What do you call a MIDI message that's always warm? A friendly byte.",
    "Why was the MIDI channel so enduring? It stood the test of time.",
    "What's a music producer's favorite type of music? Everything with a good groove.",
    "Why don't MIDI messages ever get lost? They always know their channel.",
    "What's a MIDI cable's favorite type of music? Anything with good connections.",
    "Why did the synthesizer bring a ladder to the concert? To reach the high notes.",
    "What do you call a MIDI hub that tells jokes? A stand-up hub-comedian.",
    "Why was the MIDI note so good at math? It could count to 127.",
    "What's a music producer's favorite type of tree? A sampling oak.",
    "Why did the MIDI controller go to therapy? It had too many knobs to turn.",
    "What do you call a MIDI message that's always late? A delayed packet.",
    "Why was the MIDI hub so good at parties? It knew how to route the fun.",
    "What's a synthesizer's favorite type of weather? Thunder and lightning effects.",
    "Why did the MIDI cable become a therapist? It helped people work through their issues.",
    "What do you call a MIDI channel that's always positive? An upbeat channel.",
    "Why was the MIDI note so good at sports? It had great pitch control.",
    "What's a music producer's favorite type of car? A sound system with good bass.",
    "Why did the MIDI controller become a chef? It knew how to mix the right ingredients.",
    "What do you call a MIDI message that's always calm? A steady byte.",
    "Why was the MIDI hub so good at meditation? It found its inner frequency.",
    "What's a synthesizer's favorite type of book? A sound byte novel.",
    "Why did the MIDI cable become a detective? It could trace any connection.",
    "What do you call a MIDI controller that's always honest? A true knob.",
    "Why was the MIDI note so good at school? It always hit the right notes.",
    "What's a music producer's favorite type of phone? A ringtone maker.",
    "Why did the MIDI controller become a therapist? It helped people find their rhythm.",
    "What do you call a MIDI message that's always ready? A prepared packet.",
    "Why was the MIDI hub so good at teamwork? It connected everyone.",
    "What's a synthesizer's favorite type of movie? A sound track thriller.",
    "Why did the MIDI cable become a philosopher? It questioned the nature of sound.",
    "What do you call a MIDI channel that's always curious? An inquisitive channel.",
    "Why was the MIDI note so good at dancing? It had perfect timing.",
    "What's a music producer's favorite type of art? Sound sculpture.",
    "Why did the MIDI controller become a writer? It had a lot to express.",
    "What do you call a MIDI message that's always kind? A gentle byte.",
    "Why was the MIDI hub so good at problem-solving? It found the right path.",
    "What's a synthesizer's favorite type of game? Frequency matching.",
    "Why did the MIDI cable become a musician? It knew how to connect the dots.",
    "What do you call a MIDI controller that's always brave? A fearless knob.",
    "Why was the MIDI note so good at leadership? It knew how to guide the melody.",
    "What's a music producer's favorite type of sport? Beat boxing championships.",
    "Why did the MIDI controller become a teacher? It knew how to tune students in.",
    "What do you call a MIDI message that's always creative? An imaginative byte.",
    "Why was the MIDI hub so good at friendship? It brought people together.",
    "What's a synthesizer's favorite type of vacation? A frequency retreat.",
    "Why did the MIDI cable become a counselor? It helped resolve conflicts.",
    "What do you call a MIDI channel that's always reliable? A steady channel.",
    "Why was the MIDI note so good at motivation? It inspired others to perform.",
    "What's a music producer's favorite type of vacation? A sound sanctuary.",
    "Why did the MIDI controller become a guide? It showed the way to great sound.",
    "What do you call a MIDI message that's always wise? A knowledgeable byte.",
    "Why was the MIDI hub so good at wisdom? It understood every connection.",
    "What's a synthesizer's favorite type of wisdom? Sound philosophy.",
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
