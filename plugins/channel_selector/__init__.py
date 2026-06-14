"""Channel Selector — momentary CC buttons pick the output MIDI channel.

Built for controllers without a display: a handful of buttons that each
fire a short CC 127 select which channel everything plays out on. The
input channel is ignored entirely — whatever the keyboard sends gets
re-stamped onto the currently-selected channel, so a downstream channel
filter in the routing matrix decides where it actually goes (plain, an
arpeggiator, a Euclidean voice, ...). The "Active Channel" wheel mirrors
the live selection, giving the visual feedback the controller lacks.
"""

from raspimidihub.plugin_api import CCSelect, Group, PluginBase, Wheel


class ChannelSelector(PluginBase):
    """Select the output channel from distinct momentary CC buttons."""

    NAME = "Channel Selector"
    DESCRIPTION = "Momentary CC buttons pick the output MIDI channel; input channel ignored"
    AUTHOR = "RaspiMIDIHub"
    VERSION = "1.0"
    HELP = """\
Turns a set of CC buttons into a channel picker. Assign one CC per
channel; pressing that button (a momentary CC at or above the trigger
threshold) makes that channel the active one. Everything coming in —
notes, CCs, pitch bend, aftertouch, program change — is then re-stamped
onto the active channel, no matter which channel the controller actually
sent on. Wire your routing matrix's channel filters downstream as usual
and the buttons now choose the destination.

The "Active Channel" wheel always shows the current selection (and can
be scrolled by hand as an override). To bind a button: tap "Learn" under
the channel's slot, then press the button on the controller — its CC is
captured into that slot. Each slot has its own Learn.

Selector CCs are swallowed (never forwarded); any other CC passes through
on the active channel."""

    inputs = ["Notes / CC / Pitchbend / Aftertouch / Program Change (input channel ignored)"]
    outputs = ["Everything re-stamped onto the Active Channel"]

    params = [
        Wheel("active_ch", "Active Channel", min=1, max=16, default=1,
              wide=True, span=2),
        Wheel("threshold", "Trigger ≥", min=1, max=127, default=64),
        Group("CC → Channel", [
            CCSelect(f"cc_ch{n}", f"Ch {n}", default=-1)
            for n in range(1, 17)
        ], config_only=True),
    ]

    def __init__(self):
        super().__init__()
        # note number -> channel it was started on, so a note held across
        # a channel switch still gets its Note Off on the original channel
        # (no stuck notes on the channel we just left).
        self._held: dict[int, int] = {}

    # --- helpers ---

    def _out_ch(self) -> int:
        """0-based ALSA channel index for the active selection."""
        return int(self.get_param("active_ch") or 1) - 1

    def _channel_for_cc(self, cc: int) -> int | None:
        """1-based channel whose slot is bound to this CC, or None.
        Slot value -1 = unbound; 0..127 = the bound CC number."""
        for n in range(1, 17):
            v = self.get_param(f"cc_ch{n}")
            if v is not None and v >= 0 and v == cc:
                return n
        return None

    # --- handlers ---

    def on_cc(self, channel, cc, value):
        slot_ch = self._channel_for_cc(cc)
        if slot_ch is not None:
            # A bound selector button: switch on a real press, but always
            # swallow it (both the 127 press and the 0 release) so the
            # destination never sees a stray CC.
            if value >= int(self.get_param("threshold") or 64):
                # Live performance move, not a config edit — quiet write
                # so it broadcasts to the UI without dirtying / autosaving.
                self.set_param("active_ch", slot_ch, persist=False)
            return
        self.send_cc(self._out_ch(), cc, value)

    def on_note_on(self, channel, note, velocity):
        if velocity == 0:
            self.on_note_off(channel, note)
            return
        out = self._out_ch()
        self._held[note] = out
        self.send_note_on(out, note, velocity)

    def on_note_off(self, channel, note):
        out = self._held.pop(note, self._out_ch())
        self.send_note_off(out, note)

    def on_pitchbend(self, channel, value):
        self.send_pitchbend(self._out_ch(), value)

    def on_aftertouch(self, channel, value):
        self.send_aftertouch(self._out_ch(), value)

    def on_program_change(self, channel, program):
        self.send_program_change(self._out_ch(), program)

    def panic(self):
        self._held.clear()
