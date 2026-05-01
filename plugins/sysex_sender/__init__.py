"""SysEx Sender — upload a .syx file and stream it to the connected
destination.

This plugin has no parameters. The user picks a file in the device-
detail panel; the browser POSTs the raw bytes to
`/api/plugins/instances/<id>/sysex` and the API hands them to
`send_sysex`, which chunks + paces them out the OUT port (256-byte
chunks, ~5 ms gap — safe for DX7-class input buffers).

Bytes never touch the disk and aren't part of the saved config —
upload, send, forget. To resend, pick the file again.
"""

from raspimidihub.plugin_api import PluginBase


class SysExSender(PluginBase):
    NAME = "SysEx Sender"
    DESCRIPTION = "Upload a .syx file and ship it to the connected destination"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Pick a .syx file in this panel; bytes are streamed out the OUT port
to whatever device you've wired in the matrix. The file is held only
in memory for the duration of the send, then discarded — there's no
library, no recall, no save.

For a DX7-style patch dump, route this plugin's OUT to the synth's
MIDI IN, pick the .syx, watch the toast confirm bytes sent.

Large dumps are paced (256-byte chunks, ~5 ms gap) so old synths'
input buffers stay happy. A 16 KB voice bank takes about 0.3 s."""

    params: list = []

    inputs: list[str] = []
    outputs = ["SysEx (uploaded file, streamed once on demand)"]
