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

        # Per-client ALSA queue for scheduled-event delivery. The queue
        # runs in real-time (CLOCK_MONOTONIC under the hood) and lets
        # plugins emit events at exact future moments — used by the
        # drop-button fire path to land snapshot CCs ahead of the bar
        # boundary, ahead of the audible kick. _queue_start_monotonic
        # is captured right after start so we can convert
        # `target_monotonic` → `queue_real_time = target - start`.
        self._queue_id = self._alsa.snd_seq_alloc_named_queue(
            self._handle, f"plugin-{client_name}".encode())
        if self._queue_id < 0:
            log.warning("plugin %s: alloc_named_queue failed (%d) — "
                        "scheduled events disabled", client_name, self._queue_id)
            self._queue_id = -1
            self._queue_start_monotonic = None
        else:
            self._alsa.snd_seq_start_queue(
                self._handle, self._queue_id, None)
            self._alsa.snd_seq_drain_output(self._handle)
            self._queue_start_monotonic = time.monotonic()

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

    def send_event_at(self, when_monotonic: float, ev_type: int,
                      tag: int = 0, **kwargs) -> None:
        """Schedule a MIDI event for ALSA-queue delivery at the given
        monotonic time. Drop-in replacement for send_event() except
        the event lands in the future; the kernel-side queue dispatches
        it at the requested moment regardless of Python latency.

        `tag` (1..255; 0 = no tag) lets the caller cancel pending events
        en masse via cancel_tag() — drop-button cancel uses this.

        Falls back to immediate send_event() if the queue couldn't be
        allocated at startup."""
        if self._queue_id < 0 or self._queue_start_monotonic is None:
            return self.send_event(ev_type, **kwargs)

        # Drop into the past = fire immediately. Avoid the kernel
        # silently discarding it.
        delta = when_monotonic - self._queue_start_monotonic
        if delta <= 0:
            return self.send_event(ev_type, **kwargs)

        # Rate limiter still applies — scheduled events count too.
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
        ev.queue = self._queue_id
        ev.tag = tag & 0xFF
        # set_event_time_real handles flags + the time-stamp union slot.
        sec = int(delta)
        nsec = int((delta - sec) * 1_000_000_000)
        self._alsa.set_event_time_real(ev, sec, nsec)

        MidiEventType = self._alsa.MidiEventType
        if ev_type in (MidiEventType.NOTEON, MidiEventType.NOTEOFF, MidiEventType.KEYPRESS):
            ev.data.note.channel = kwargs.get("channel", 0)
            ev.data.note.note = kwargs.get("note", 0)
            ev.data.note.velocity = kwargs.get("velocity", 0)
        elif ev_type == MidiEventType.CONTROLLER:
            ev.data.control.channel = kwargs.get("channel", 0)
            ev.data.control.param = kwargs.get("cc", 0)
            ev.data.control.value = kwargs.get("value", 0)
        elif ev_type in (MidiEventType.PITCHBEND, MidiEventType.CHANPRESS, MidiEventType.PGMCHANGE):
            ev.data.control.channel = kwargs.get("channel", 0)
            ev.data.control.value = kwargs.get("value", 0)

        # output (queued) + drain to flush to kernel.
        self._alsa.snd_seq_event_output(self._handle, ctypes.pointer(ev))
        self._alsa.snd_seq_drain_output(self._handle)

    def cancel_tag(self, tag: int) -> None:
        """Remove all pending queued events from this client tagged `tag`.
        Used to undo a scheduled drop fire when the user cancels before
        the bar boundary."""
        if self._queue_id < 0 or tag <= 0:
            return
        from ..alsa_seq import (
            SND_SEQ_REMOVE_OUTPUT,
            SND_SEQ_REMOVE_TAG_MATCH,
        )
        rm = self._alsa.SndSeqRemoveEventsPtr()
        if self._alsa.snd_seq_remove_events_malloc(ctypes.byref(rm)) < 0:
            return
        try:
            self._alsa.snd_seq_remove_events_set_condition(
                rm, SND_SEQ_REMOVE_OUTPUT | SND_SEQ_REMOVE_TAG_MATCH)
            self._alsa.snd_seq_remove_events_set_tag(rm, tag & 0xFF)
            self._alsa.snd_seq_remove_events_set_queue(rm, self._queue_id)
            self._alsa.snd_seq_remove_events(self._handle, rm)
        finally:
            self._alsa.snd_seq_remove_events_free(rm)

    def close(self) -> None:
        if self._handle:
            if self._queue_id >= 0:
                try:
                    self._alsa.snd_seq_stop_queue(
                        self._handle, self._queue_id, None)
                    self._alsa.snd_seq_free_queue(
                        self._handle, self._queue_id)
                except Exception:
                    pass
                self._queue_id = -1
            self._alsa.snd_seq_close(self._handle)
            self._handle = self._alsa.SndSeqPtr()
