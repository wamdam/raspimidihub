"""FluidSynth GM — software synthesizer plugin.

Spawns a `fluidsynth` subprocess with ALSA audio output and forwards
incoming MIDI events to it via stdin.  The plugin acts as a pure MIDI
sink: MIDI flows IN → audio comes out of HDMI or the headphone jack.
No MIDI is emitted on the OUT port.

Requirements (install once on the Pi):
    sudo apt install fluidsynth fluid-soundfont-gm
"""

import logging
import os
import queue
import re
import subprocess
import threading
import time

from raspimidihub.plugin_api import Button, ChannelSelect, Group, PluginBase, Radio, Wheel

log = logging.getLogger(__name__)

_SOUNDFONT_SEARCH_DIRS = [
    "/usr/share/sounds/sf2",
    "/usr/share/soundfonts",
]

# General MIDI program names (program 0–127)
_GM_PROGRAMS = [
    # Pianos
    "Acoustic Grand Piano", "Bright Acoustic Piano", "Electric Grand Piano",
    "Honky-tonk Piano", "Electric Piano 1", "Electric Piano 2",
    "Harpsichord", "Clavinet",
    # Chromatic Percussion
    "Celesta", "Glockenspiel", "Music Box", "Vibraphone",
    "Marimba", "Xylophone", "Tubular Bells", "Dulcimer",
    # Organs
    "Drawbar Organ", "Percussive Organ", "Rock Organ", "Church Organ",
    "Reed Organ", "Accordion", "Harmonica", "Tango Accordion",
    # Guitars
    "Acoustic Guitar (nylon)", "Acoustic Guitar (steel)",
    "Electric Guitar (jazz)", "Electric Guitar (clean)",
    "Electric Guitar (muted)", "Overdriven Guitar",
    "Distortion Guitar", "Guitar Harmonics",
    # Bass
    "Acoustic Bass", "Electric Bass (finger)", "Electric Bass (pick)",
    "Fretless Bass", "Slap Bass 1", "Slap Bass 2",
    "Synth Bass 1", "Synth Bass 2",
    # Strings
    "Violin", "Viola", "Cello", "Contrabass",
    "Tremolo Strings", "Pizzicato Strings",
    "Orchestral Harp", "Timpani",
    # Ensemble
    "String Ensemble 1", "String Ensemble 2",
    "Synth Strings 1", "Synth Strings 2",
    "Choir Aahs", "Voice Oohs", "Synth Voice", "Orchestra Hit",
    # Brass
    "Trumpet", "Trombone", "Tuba", "Muted Trumpet",
    "French Horn", "Brass Section", "Synth Brass 1", "Synth Brass 2",
    # Reed
    "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax",
    "Oboe", "English Horn", "Bassoon", "Clarinet",
    # Pipe
    "Piccolo", "Flute", "Recorder", "Pan Flute",
    "Blown Bottle", "Shakuhachi", "Whistle", "Ocarina",
    # Synth Lead
    "Lead 1 (square)", "Lead 2 (sawtooth)", "Lead 3 (calliope)",
    "Lead 4 (chiff)", "Lead 5 (charang)", "Lead 6 (voice)",
    "Lead 7 (fifths)", "Lead 8 (bass+lead)",
    # Synth Pad
    "Pad 1 (new age)", "Pad 2 (warm)", "Pad 3 (polysynth)",
    "Pad 4 (choir)", "Pad 5 (bowed)", "Pad 6 (metallic)",
    "Pad 7 (halo)", "Pad 8 (sweep)",
    # Synth Effects
    "FX 1 (rain)", "FX 2 (soundtrack)", "FX 3 (crystal)",
    "FX 4 (atmosphere)", "FX 5 (brightness)", "FX 6 (goblins)",
    "FX 7 (echoes)", "FX 8 (sci-fi)",
    # Ethnic
    "Sitar", "Banjo", "Shamisen", "Koto",
    "Kalimba", "Bagpipe", "Fiddle", "Shanai",
    # Percussive
    "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock",
    "Taiko Drum", "Melodic Tom", "Synth Drum", "Reverse Cymbal",
    # Sound Effects
    "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet",
    "Telephone Ring", "Helicopter", "Applause", "Gunshot",
]


# ---------------------------------------------------------------------------
# Scanned once at plugin-discovery time (module import)
# ---------------------------------------------------------------------------

def _scan_soundfonts() -> dict[str, str]:
    """Return {display_name: path} for every .sf2 found on the system."""
    found: dict[str, str] = {}
    for d in _SOUNDFONT_SEARCH_DIRS:
        try:
            for fname in sorted(os.listdir(d)):
                if fname.lower().endswith(".sf2"):
                    path = os.path.join(d, fname)
                    if os.path.isfile(path):
                        found.setdefault(fname[:-4], path)
        except OSError:
            pass
    return found


def _scan_audio_outputs() -> dict[str, str]:
    """Return OrderedDict {display_name: alsa_device} for each playback card.

    Parses `aplay -l` for human-readable card names so the Radio shows
    e.g. 'bcm2835 Headphones' and 'vc4-hdmi-1' instead of fixed labels.
    Falls back to /proc/asound/cards if aplay is unavailable.
    Always prepends 'Default' → 'default'.
    """
    result: dict[str, str] = {"Default": "default"}
    seen_cards: set[str] = set()
    try:
        out = subprocess.run(
            ["aplay", "-l"], capture_output=True, text=True, timeout=5
        )
        for line in out.stdout.splitlines():
            # "card N: short_id [Long Name], device D: ..."
            m = re.match(r"card\s+(\d+):\s+\S+\s+\[([^\]]+)\]", line)
            if m:
                card_n, long_name = m.group(1), m.group(2).strip()
                if card_n not in seen_cards:
                    seen_cards.add(card_n)
                    result[long_name] = f"plughw:{card_n},0"
    except Exception:
        # aplay unavailable — fall back to /proc/asound/cards
        try:
            with open("/proc/asound/cards") as f:
                for line in f:
                    m = re.match(r"\s*(\d+)\s+\[(\S+)\s*\]", line)
                    if m:
                        result.setdefault(m.group(2), f"plughw:{m.group(1)},0")
        except OSError:
            pass
    return result


_SOUNDFONTS: dict[str, str] = _scan_soundfonts()
_SF_NAMES: list[str] = list(_SOUNDFONTS) or ["(none found)"]
_SF_DEFAULT: str = _SF_NAMES[0]

_AUDIO_OUTPUTS: dict[str, str] = _scan_audio_outputs()
_OUT_NAMES: list[str] = list(_AUDIO_OUTPUTS)  # always starts with "Default"


class FluidSynthGm(PluginBase):
    """Software GM synthesizer — render MIDI to HDMI or headphone audio."""

    NAME = "FluidSynth GM"
    DESCRIPTION = "Software GM synthesizer — render MIDI to HDMI or headphone audio"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.1"
    HELP = """\
Renders incoming MIDI as audio through the Raspberry Pi audio output.
No external synthesizer hardware needed.

Requirements (install once):
  sudo apt install fluidsynth fluid-soundfont-gm

Wire any MIDI source to this plugin's IN port in the routing matrix.
Audio Output lists every playback card found at startup — pick the one
that matches your speakers or headphones.
Gain controls the master volume (0 = silent, 100 = maximum).
Soundfont selects the GM instrument bank loaded by FluidSynth."""

    params = [
        Group("Audio", [
            Radio("output", "Audio Output", options=_OUT_NAMES, default=_OUT_NAMES[0]),
            Wheel("gain", "Gain", min=0, max=100, default=50, unit="%", default_cc=7),
            Button("reverb", "Reverb", default=False, color="blue"),
        ]),
        Group("Instrument", [
            ChannelSelect("channel", "Channel", default=0, allow_any=True),
            Wheel("program", "GM Program", min=0, max=127, default=0,
                  labels=_GM_PROGRAMS, span=2),
        ]),
        Group("Soundfont", [
            Radio("soundfont", "Soundfont", options=_SF_NAMES, default=_SF_DEFAULT),
        ]),
    ]

    inputs = ["Note On/Off", "CC", "Pitch Bend", "Program Change", "Aftertouch"]
    outputs = []  # pure audio sink — no MIDI output

    def on_start(self):
        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue = queue.Queue(maxsize=512)
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def on_stop(self):
        self._running = False
        self._queue.put(None)  # wake the loop
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass

    # --- MIDI event handlers ---

    def on_note_on(self, channel, note, velocity):
        self._cmd(f"noteon {channel} {note} {velocity}")

    def on_note_off(self, channel, note):
        self._cmd(f"noteoff {channel} {note}")

    def on_cc(self, channel, cc, value):
        self._cmd(f"cc {channel} {cc} {value}")

    def on_pitchbend(self, channel, value):
        # Plugin API delivers -8192..8191; FluidSynth wants 0..16383
        self._cmd(f"pitch_bend {channel} {value + 8192}")

    def on_program_change(self, channel, program):
        self._cmd(f"prog {channel} {program}")

    def on_aftertouch(self, channel, value):
        self._cmd(f"channel_pressure {channel} {value}")

    def on_param_change(self, name, value):
        if name == "gain":
            fs_gain = value / 100.0 * 5.0  # FluidSynth range: 0.0–5.0
            self._cmd(f"gain {fs_gain:.3f}")
        elif name in ("program", "channel"):
            self._apply_program()
        elif name == "reverb":
            self._cmd(f"reverb {'on' if value else 'off'}")
        elif name in ("output", "soundfont"):
            self._cmd("__restart__")

    # --- Internal ---

    def _apply_program(self) -> None:
        """Send prog command to fluidsynth for the current channel+program.

        Channel 0 (Any) broadcasts to all 16 channels except ch 9 (GM drums).
        """
        ch = self.get_param("channel") or 0
        prog = self.get_param("program") or 0
        if ch == 0:
            # Broadcast to every melodic channel (skip 9 = GM percussion)
            for c in range(16):
                if c != 9:
                    self._cmd(f"prog {c} {prog}")
        else:
            self._cmd(f"prog {ch - 1} {prog}")  # ChannelSelect is 1-based

    def _cmd(self, s: str) -> None:
        try:
            self._queue.put_nowait(s)
        except queue.Full:
            pass

    def _current_soundfont(self) -> str | None:
        name = self.get_param("soundfont") or _SF_DEFAULT
        path = _SOUNDFONTS.get(name)
        if path and os.path.isfile(path):
            return path
        for p in _SOUNDFONTS.values():
            if os.path.isfile(p):
                return p
        return None

    def _current_device(self) -> str:
        output = self.get_param("output") or _OUT_NAMES[0]
        # Gracefully handle stale saved values from an older config
        return _AUDIO_OUTPUTS.get(output, "default")

    def _start_proc(self) -> bool:
        soundfont = self._current_soundfont()
        if not soundfont:
            log.warning(
                "FluidSynth: no soundfont found — "
                "run: sudo apt install fluid-soundfont-gm"
            )
            return False

        device = self._current_device()
        gain = (self.get_param("gain") or 50) / 100.0 * 5.0
        reverb = self.get_param("reverb") or False
        argv = [
            "fluidsynth",
            "-a", "alsa",
            "-o", f"audio.alsa.device={device}",
            "-g", f"{gain:.3f}",
            "-R", "1" if reverb else "0",
            soundfont,
        ]
        output_name = self.get_param("output") or _OUT_NAMES[0]
        log.info("FluidSynth: starting (output=%r device=%s sf=%s)",
                 output_name, device, os.path.basename(soundfont))
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except FileNotFoundError:
            log.warning(
                "FluidSynth: 'fluidsynth' binary not found — "
                "run: sudo apt install fluidsynth"
            )
            return False
        except Exception as e:
            log.warning("FluidSynth: failed to start: %s", e)
            return False

    def _loop(self):
        """Lifecycle: start fluidsynth, forward commands, restart on exit."""
        while self._running:
            if not self._start_proc():
                # Binary or soundfont missing — long wait before retry
                end = time.monotonic() + 30
                while self._running and time.monotonic() < end:
                    try:
                        self._queue.get(timeout=1)
                    except queue.Empty:
                        pass
                continue

            start_time = time.monotonic()
            # Give fluidsynth time to open ALSA before we write commands
            time.sleep(0.8)

            # Apply the saved program selection now that fluidsynth is ready
            self._apply_program()

            # If the process died during startup the audio device is bad
            if self._proc and self._proc.poll() is not None:
                elapsed = time.monotonic() - start_time
                log.warning(
                    "FluidSynth: process exited within %.1f s — "
                    "check Audio Output selection", elapsed
                )
                self._proc = None
                # Back off to avoid a tight crash-loop; still drain the
                # queue so a __restart__ from a new selection gets through
                end = time.monotonic() + 10
                while self._running and time.monotonic() < end:
                    try:
                        item = self._queue.get(timeout=1)
                        if item in ("__restart__", None):
                            break
                    except queue.Empty:
                        pass
                continue

            restart = False
            while self._running and not restart:
                try:
                    item = self._queue.get(timeout=0.2)
                except queue.Empty:
                    if self._proc and self._proc.poll() is not None:
                        log.warning("FluidSynth: process exited unexpectedly, restarting")
                        restart = True
                    continue

                if item is None or not self._running:
                    break

                if item == "__restart__":
                    # Drain stale MIDI before restarting with new settings
                    while True:
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            break
                    restart = True
                    break

                if self._proc and self._proc.stdin:
                    try:
                        log.debug("FluidSynth stdin: %s", item)
                        self._proc.stdin.write(f"{item}\n".encode())
                        self._proc.stdin.flush()
                    except Exception:
                        restart = True

            if self._proc:
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=3)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                self._proc = None

            if self._running and restart:
                time.sleep(0.3)
