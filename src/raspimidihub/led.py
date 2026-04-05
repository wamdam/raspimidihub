"""LED status indication via the Pi's activity LED.

FR-4A: Green steady = running, fast blink = hotplug, off = stopped.
"""

import asyncio
import logging
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)

LED_PATH = Path("/sys/class/leds/ACT")
# Some Pi models use 'led0' instead
LED_PATH_ALT = Path("/sys/class/leds/led0")


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
        self._state = LedState.OFF

        for path in (LED_PATH, LED_PATH_ALT):
            if path.exists():
                self._led_path = path
                break

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

    def _stop_blink(self) -> None:
        if self._blink_task and not self._blink_task.done():
            self._blink_task.cancel()
            self._blink_task = None

    def set_steady(self) -> None:
        """FR-4A.1: Green steady = service running."""
        self._stop_blink()
        self._state = LedState.STEADY
        self._write("none", "1")

    def set_off(self) -> None:
        """FR-4A.5: Off = service not running."""
        self._stop_blink()
        self._state = LedState.OFF
        self._write("none", "0")

    def set_fast_blink(self) -> None:
        """FR-4A.2: Fast blink = config fallback."""
        self._stop_blink()
        self._state = LedState.FAST_BLINK
        self._write("timer")
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

    def restore_default_trigger(self) -> None:
        """Restore LED to default kernel trigger on shutdown."""
        if self._led_path:
            try:
                (self._led_path / "trigger").write_text("mmc0")
            except OSError:
                pass
