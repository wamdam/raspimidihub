"""PluginInstance dataclass — wraps a plugin object + its thread + ALSA client."""

import threading
from dataclasses import dataclass

from ..plugin_api import PluginBase
from .alsa_client import PluginAlsaClient


@dataclass
class PluginInstance:
    id: str
    plugin_type: str  # directory name, e.g. "arpeggiator"
    name: str         # user-facing name, e.g. "Arp 1"
    plugin: PluginBase
    alsa_client: PluginAlsaClient | None = None
    thread: threading.Thread | None = None
    running: bool = False
    crashed: bool = False
    crash_error: str = ""
    _tick_queue: object = None  # queue.Queue for clock ticks from bus
    _tick_pipe: tuple = None   # (read_fd, write_fd) for waking select on tick
