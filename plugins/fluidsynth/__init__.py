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

from raspimidihub.plugin_api import Group, PluginBase, Radio, Wheel

log = logging.getLogger(__name__)

_SOUNDFONT_CANDIDATES = [
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/sounds/sf2/TimGM6mb.sf2",
    "/usr/share/soundfonts/default.sf2",
    "/usr/share/sounds/sf2/default.sf2",
]


def _find_soundfont() -> str | None:
    for p in _SOUNDFONT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def _detect_alsa_card(keyword: str) -> str | None:
    """Return 'plughw:N,0' for the first /proc/asound/cards line matching keyword."""
    try:
        with open("/proc/asound/cards") as f:
            for line in f:
                m = re.match(r"\s*(\d+)\s+\[", line)
                if m and keyword.lower() in line.lower():
                    return f"plughw:{m.group(1)},0"
    except OSError:
        pass
    return None


class FluidSynthGm(PluginBase):
    """Software GM synthesizer — render MIDI to HDMI or headphone audio."""

    NAME = "FluidSynth GM"
    DESCRIPTION = "Software GM synthesizer — render MIDI to HDMI or headphone audio"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Renders incoming MIDI as audio through the Raspberry Pi audio output.
No external synthesizer hardware needed.

Requirements (install once):
  sudo apt install fluidsynth fluid-soundfont-gm

Wire any MIDI source to this plugin's IN port in the routing matrix.
Choose the Audio Output that matches your speakers or headphones.
Gain controls the master volume (0 = silent, 100 = maximum).

The FluidR3_GM General MIDI soundfont is loaded automatically from
/usr/share/sounds/sf2/ when the packages above are installed."""

    params = [
        Group("Audio", [
            Radio("output", "Audio Output",
                  options=["Default", "HDMI", "Headphone Jack"],
                  default="Default"),
            Wheel("gain", "Gain", min=0, max=100, default=50, unit="%", default_cc=7),
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
            # FluidSynth gain range: 0.0–5.0
            fs_gain = value / 100.0 * 5.0
            self._cmd(f"gain {fs_gain:.3f}")
        elif name == "output":
            # Audio device change — restart the subprocess
            self._cmd("__restart__")

    # --- Internal helpers ---

    def _cmd(self, s: str) -> None:
        try:
            self._queue.put_nowait(s)
        except queue.Full:
            pass

    def _alsa_device(self) -> str:
        output = self.get_param("output") or "Default"
        if output == "HDMI":
            return _detect_alsa_card("hdmi") or _detect_alsa_card("vc4") or "plughw:0,0"
        if output == "Headphone Jack":
            return (_detect_alsa_card("Headphones")
                    or _detect_alsa_card("bcm2835")
                    or "plughw:1,0")
        return "default"

    def _start_proc(self) -> bool:
        soundfont = _find_soundfont()
        if not soundfont:
            log.warning(
                "FluidSynth: soundfont not found — "
                "run: sudo apt install fluid-soundfont-gm"
            )
            return False

        device = self._alsa_device()
        gain = (self.get_param("gain") or 50) / 100.0 * 5.0
        argv = [
            "fluidsynth",
            "-a", "alsa",
            "-o", f"audio.alsa.device={device}",
            "-g", f"{gain:.3f}",
            soundfont,
        ]
        log.info("FluidSynth: starting (device=%s, soundfont=%s)", device, soundfont)
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
                "FluidSynth: 'fluidsynth' not found — "
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
                # Binary or soundfont missing — wait before retrying
                end = time.monotonic() + 30
                while self._running and time.monotonic() < end:
                    try:
                        self._queue.get(timeout=1)
                    except queue.Empty:
                        pass
                continue

            # FluidSynth needs a moment to initialise ALSA before it
            # starts processing stdin commands.
            time.sleep(0.5)

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
                    # Drain stale MIDI before restarting with new device
                    while True:
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            break
                    restart = True
                    break

                if self._proc and self._proc.stdin:
                    try:
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
