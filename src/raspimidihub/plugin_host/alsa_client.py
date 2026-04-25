"""Minimal ALSA seq client for a plugin instance.

Each plugin runs its own ALSA seq client so its IN/OUT ports show up in
the matrix exactly like a hardware device. This module is the
lightweight wrapper around `snd_seq_*` calls used by plugin threads.
"""

import ctypes
import logging
import sys
import time

log = logging.getLogger(__name__)

# ALSA constants (duplicated here to avoid circular imports through alsa_seq)
SND_SEQ_OPEN_DUPLEX = 3
SND_SEQ_NONBLOCK = 1
SND_SEQ_PORT_CAP_READ = 1 << 0
SND_SEQ_PORT_CAP_SUBS_READ = 1 << 5
SND_SEQ_PORT_CAP_WRITE = 1 << 1
SND_SEQ_PORT_CAP_SUBS_WRITE = 1 << 6
SND_SEQ_PORT_TYPE_MIDI_GENERIC = 1 << 1
SND_SEQ_PORT_TYPE_APPLICATION = 1 << 20
SND_SEQ_QUEUE_DIRECT = 253
SND_SEQ_ADDRESS_SUBSCRIBERS = 254


class PluginAlsaClient:
    """Minimal ALSA seq client for a plugin instance.

    Creates its own handle with an IN port (writable) and OUT port (readable).
    """

    def __init__(self, client_name: str):
        from ..alsa_seq import (
            SndSeqPtr,
            check,
            snd_seq_client_id,
            snd_seq_create_simple_port,
            snd_seq_open,
            snd_seq_set_client_name,
        )
        self._alsa = sys.modules["raspimidihub.alsa_seq"]

        self._handle = SndSeqPtr()
        check(snd_seq_open(
            ctypes.byref(self._handle), b"default",
            SND_SEQ_OPEN_DUPLEX, SND_SEQ_NONBLOCK,
        ), "plugin: open seq")
        snd_seq_set_client_name(self._handle, client_name.encode())
        self._client_id = snd_seq_client_id(self._handle)

        # IN port — receives MIDI (writable by subscribers)
        self._in_port = snd_seq_create_simple_port(
            self._handle, b"IN",
            SND_SEQ_PORT_CAP_WRITE | SND_SEQ_PORT_CAP_SUBS_WRITE,
            SND_SEQ_PORT_TYPE_MIDI_GENERIC | SND_SEQ_PORT_TYPE_APPLICATION,
        )
        check(self._in_port, "plugin: create IN port")

        # OUT port — sends MIDI (readable by subscribers)
        self._out_port = snd_seq_create_simple_port(
            self._handle, b"OUT",
            SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ,
            SND_SEQ_PORT_TYPE_MIDI_GENERIC | SND_SEQ_PORT_TYPE_APPLICATION,
        )
        check(self._out_port, "plugin: create OUT port")

        # Rate limiter
        self._rate_window = []

    @property
    def client_id(self) -> int:
        return self._client_id

    @property
    def in_port(self) -> int:
        return self._in_port

    @property
    def out_port(self) -> int:
        return self._out_port

    def fileno(self) -> int:
        import struct
        count = self._alsa.snd_seq_poll_descriptors_count(self._handle, 1)
        buf = ctypes.create_string_buffer(8 * count)
        self._alsa.snd_seq_poll_descriptors(self._handle, buf, count, 1)
        return struct.unpack_from("i", buf, 0)[0]

    def read_event(self):
        ev = self._alsa.SndSeqEventPtr()
        ret = self._alsa.snd_seq_event_input(self._handle, ctypes.byref(ev))
        if ret < 0:
            return None
        return ev.contents

    def send_event(self, ev_type: int, **kwargs) -> None:
        """Build and send an ALSA event on the OUT port. Rate-limited."""
        # Drop events if rate exceeds DIN MIDI limit (1000/sec)
        now = time.monotonic()
        self._rate_window = [t for t in self._rate_window if now - t < 1.0]
        if len(self._rate_window) >= 1000:
            return
        self._rate_window.append(now)

        ev = self._alsa.SndSeqEvent()
        ev.type = ev_type
        ev.source.client = self._client_id
        ev.source.port = self._out_port
        ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
        ev.dest.port = 0
        ev.queue = SND_SEQ_QUEUE_DIRECT
        ev.flags = 0

        MidiEventType = self._alsa.MidiEventType

        if ev_type in (MidiEventType.NOTEON, MidiEventType.NOTEOFF, MidiEventType.KEYPRESS):
            ev.data.note.channel = kwargs.get("channel", 0)
            ev.data.note.note = kwargs.get("note", 0)
            ev.data.note.velocity = kwargs.get("velocity", 0)
        elif ev_type == MidiEventType.CONTROLLER:
            ev.data.control.channel = kwargs.get("channel", 0)
            ev.data.control.param = kwargs.get("cc", 0)
            ev.data.control.value = kwargs.get("value", 0)
        elif ev_type == MidiEventType.PITCHBEND or ev_type == MidiEventType.CHANPRESS or ev_type == MidiEventType.PGMCHANGE:
            ev.data.control.channel = kwargs.get("channel", 0)
            ev.data.control.value = kwargs.get("value", 0)

        self._alsa.snd_seq_event_output_direct(self._handle, ctypes.pointer(ev))

    def close(self) -> None:
        if self._handle:
            self._alsa.snd_seq_close(self._handle)
            self._handle = self._alsa.SndSeqPtr()
