"""Plugin host package — discovery, instance lifecycle, threads,
ALSA ports, clock bus.

Public surface lives here so existing imports `from .plugin_host import
PluginHost` (etc.) keep working unchanged after the split into a
package.
"""

from .alsa_client import PluginAlsaClient
from .clock_bus import ClockBus, DIVISION_TICKS
from .host import PluginHost
from .instance import PluginInstance

__all__ = [
    "PluginAlsaClient",
    "ClockBus",
    "DIVISION_TICKS",
    "PluginHost",
    "PluginInstance",
]
