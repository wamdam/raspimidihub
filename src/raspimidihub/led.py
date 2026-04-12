"""LED status indication via the Pi's activity LED.

FR-4A: Green steady = running, fast blink = hotplug, off = stopped.
"""

import asyncio
import logging
import time
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)

LED_PATH = Path("/sys/class/leds/ACT")
# Some Pi models use 'led0' instead
LED_PATH_ALT = Path("/sys/class/leds/led0")
PWR_LED_PATH = Path("/sys/class/leds/PWR")


class LedState(Enum):
    OFF = "off"
    STEADY = "steady"
    FAST_BLINK = "fast_blink"
    HOTPLUG_BLINK = "hotplug_blink"


class LedController:
    """Controls the Pi activity LED for status indication."""

    def __init__(self):
        self._led_path: Path | None = None
        self._blink_task: asyncio.Task | None = None
        self._midi_task: asyncio.Task | None = None
        self._last_midi_blink: float = 0
        self._state = LedState.OFF

        for path in (LED_PATH, LED_PATH_ALT):
            if path.exists():
                self._led_path = path
                break

        self._pwr_path = PWR_LED_PATH if PWR_LED_PATH.exists() else None

        if self._led_path is None:
            log.warning("No activity LED found, LED status disabled")

    @property
    def available(self) -> bool:
        return self._led_path is not None

    def _write(self, trigger: str = "", brightness: str = "0") -> None:
        if not self._led_path:
            return
        try:
            (self._led_path / "trigger").write_text(trigger)
            if trigger == "none":
                (self._led_path / "brightness").write_text(brightness)
        except OSError as e:
            log.debug("LED write failed: %s", e)

    def _write_pwr(self, on: bool) -> None:
        if not self._pwr_path:
            return
        try:
            (self._pwr_path / "trigger").write_text("none")
            (self._pwr_path / "brightness").write_text("1" if on else "0")
        except OSError as e:
            log.debug("PWR LED write failed: %s", e)

    def _stop_blink(self) -> None:
        if self._blink_task and not self._blink_task.done():
            self._blink_task.cancel()
            self._blink_task = None

    def set_steady(self) -> None:
        """FR-4A.1: Green steady = service running. Red off."""
        self._stop_blink()
        self._state = LedState.STEADY
        self._write("none", "1")
        self._write_pwr(False)

    def set_off(self) -> None:
        """FR-4A.5: Off = service not running."""
        self._stop_blink()
        self._state = LedState.OFF
        self._write("none", "0")

    def set_fast_blink(self) -> None:
        """FR-4A.2: Fast blink = config fallback. Red on."""
        self._stop_blink()
        self._state = LedState.FAST_BLINK
        self._write("timer")
        self._write_pwr(True)
        # timer trigger defaults to 500ms on/off; write faster values
        if self._led_path:
            try:
                (self._led_path / "delay_on").write_text("100")
                (self._led_path / "delay_off").write_text("100")
            except OSError:
                pass

    def set_hotplug_blink(self, duration: float = 2.0) -> None:
        """FR-4A.4: Brief fast green blink during hotplug re-establishment."""
        self._stop_blink()
        self._state = LedState.HOTPLUG_BLINK
        self._write("timer")
        if self._led_path:
            try:
                (self._led_path / "delay_on").write_text("200")
                (self._led_path / "delay_off").write_text("200")
            except OSError:
                pass
        self._blink_task = asyncio.ensure_future(self._restore_after(duration))

    async def _restore_after(self, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
            self.set_steady()
        except asyncio.CancelledError:
            pass

    def midi_blink(self) -> None:
        """Brief green LED flicker on note/CC activity. Throttled to max ~20/sec."""
        if self._state != LedState.STEADY:
            return
        now = time.monotonic()
        if now - self._last_midi_blink < 0.05:
            return
        self._last_midi_blink = now
        if self._midi_task and not self._midi_task.done():
            return
        self._midi_task = asyncio.ensure_future(self._midi_blink_cycle())

    def clock_pulse(self) -> None:
        """Gentle heartbeat on MIDI clock — one pulse per beat (every 24 ticks)."""
        if self._state != LedState.STEADY:
            return
        self._clock_tick_count = getattr(self, '_clock_tick_count', 0) + 1
        if self._clock_tick_count < 24:
            return
        self._clock_tick_count = 0
        # Dim briefly on the beat (softer than midi_blink)
        if self._midi_task and not self._midi_task.done():
            return
        self._midi_task = asyncio.ensure_future(self._clock_pulse_cycle())

    async def _midi_blink_cycle(self) -> None:
        try:
            self._write("none", "0")
            await asyncio.sleep(0.03)
            if self._state == LedState.STEADY:
                self._write("none", "1")
        except asyncio.CancelledError:
            pass

    async def _clock_pulse_cycle(self) -> None:
        """Longer, gentler off-on for clock beat — looks like breathing."""
        try:
            self._write("none", "0")
            await asyncio.sleep(0.08)
            if self._state == LedState.STEADY:
                self._write("none", "1")
        except asyncio.CancelledError:
            pass

    def restore_default_trigger(self) -> None:
        """Restore LEDs to default kernel triggers on shutdown."""
        if self._led_path:
            try:
                (self._led_path / "trigger").write_text("mmc0")
            except OSError:
                pass
        if self._pwr_path:
            try:
                (self._pwr_path / "trigger").write_text("default-on")
            except OSError:
                pass
