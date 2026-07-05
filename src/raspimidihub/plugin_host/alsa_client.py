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

# Sentinel returned by read_event for packets that were consumed or
# deliberately ignored (utility, partial SysEx, stream metadata) —
# distinct from None, which means "queue drained, stop the loop".
SKIP_EVENT = object()
_SKIP = SKIP_EVENT

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
            probe_ump_support,
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

        # MIDI 2.0 inbound (FSD-08): on capable systems the client runs
        # at midi_version=2 so bound CC automation receives the full
        # controller resolution. read_event() shims UMP packets back to
        # legacy-shaped events, so plugins keep their 0-127 API (D3).
        self._midi_version = 0
        if (probe_ump_support().capable
                and self._alsa.snd_seq_set_client_midi_version is not None
                and self._alsa.snd_seq_set_client_midi_version(self._handle, 2) >= 0):
            self._midi_version = 2
        self._sysex_asm = None  # lazy ump.Sysex7Assembler

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
        """Read one inbound event (non-blocking).

        Legacy clients return the raw snd_seq_event. MIDI 2.0 clients
        read UMP and return a legacy-shaped shim (ump.to_monitor_shim)
        with byte-identical 7-bit fields plus a `hires` dict carrying
        the 32-bit values — plugins and the dispatch code are agnostic.
        Returns None when the queue is drained; unmapped UMP packets
        return the sentinel None too, so callers just skip them.
        """
        if self._midi_version != 2:
            ev = self._alsa.SndSeqEventPtr()
            ret = self._alsa.snd_seq_event_input(self._handle, ctypes.byref(ev))
            if ret < 0:
                return None
            return ev.contents
        from .. import ump as _ump
        uev_p = self._alsa.SndSeqUmpEventPtr()
        ret = self._alsa.snd_seq_ump_event_input(self._handle, ctypes.byref(uev_p))
        if ret < 0:
            return None
        uev = uev_p.contents
        if not uev.is_ump:
            return uev  # classic event (queue control etc.) — legacy view
        words = uev.ump_words
        if ((words[0] >> 28) & 0xF) == _ump.MT_DATA64:
            if self._sysex_asm is None:
                self._sysex_asm = _ump.Sysex7Assembler()
            m = self._sysex_asm.feed(words)
        else:
            m = _ump.decode(words)
        if m is None:
            return _SKIP
        shim = _ump.to_monitor_shim(m, uev.source.client, uev.source.port,
                                    uev.dest.client, uev.dest.port, hires=True)
        return shim if shim is not None else _SKIP

    def send_event(self, ev_type: int, **kwargs) -> None:
        """Build and send an ALSA event on the OUT port. Rate-limited."""
        # Drop events if rate exceeds DIN MIDI limit (1000/sec)
        now = time.monotonic()
        self._rate_window = [t for t in self._rate_window if now - t < 1.0]
        if len(self._rate_window) >= 1000:
            return
        self._rate_window.append(now)

        MidiEventType = self._alsa.MidiEventType

        # Float values are fractional MIDI units (FSD-09): on a MIDI 2.0
        # client they go out as UMP at full resolution, interpolated so
        # 1.0 receivers see exactly int(value) — byte-identical to the
        # legacy generators' int() casts. On legacy clients the float
        # simply floors.
        if self._midi_version == 2 and self._try_send_hires(ev_type, kwargs):
            return
        for k in ("value", "velocity"):
            v = kwargs.get(k)
            if isinstance(v, float):
                kwargs[k] = int(v)

        ev = self._alsa.SndSeqEvent()
        ev.type = ev_type
        ev.source.client = self._client_id
        ev.source.port = self._out_port
        ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
        ev.dest.port = 0
        ev.queue = SND_SEQ_QUEUE_DIRECT
        ev.flags = 0

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

    def _try_send_hires(self, ev_type: int, kwargs: dict) -> bool:
        """Emit float-valued CC / note events as full-resolution UMP.
        Returns False for everything else (caller sends classic)."""
        from .. import midi_scale as _ms
        from .. import ump as _ump
        MidiEventType = self._alsa.MidiEventType
        if ev_type == MidiEventType.CONTROLLER \
                and isinstance(kwargs.get("value"), float):
            words = _ump.cc(0, kwargs.get("channel", 0) & 0xF,
                            kwargs.get("cc", 0),
                            _ms.lattice_interp(kwargs["value"]))
        elif ev_type == MidiEventType.NOTEON \
                and isinstance(kwargs.get("velocity"), float):
            words = _ump.note_on(0, kwargs.get("channel", 0) & 0xF,
                                 kwargs.get("note", 0),
                                 _ms.lattice_interp(kwargs["velocity"], 7, 16))
        else:
            return False
        self._send_ump_words(words)
        return True

    def _send_ump_words(self, words) -> None:
        ev = self._alsa.SndSeqUmpEvent()
        ev.flags = self._alsa.SND_SEQ_EVENT_UMP
        ev.queue = SND_SEQ_QUEUE_DIRECT
        ev.source.client = self._client_id
        ev.source.port = self._out_port
        ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
        ev.dest.port = 0
        for i, w in enumerate(words):
            ev.u.ump[i] = w
        if self._alsa.snd_seq_ump_event_output(self._handle, ctypes.pointer(ev)) >= 0:
            self._alsa.snd_seq_drain_output(self._handle)

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

    def send_sysex(self, payload: bytes,
                   chunk_size: int = 256, gap_s: float = 0.005) -> int:
        """Stream a complete SysEx dump out the OUT port. Splits into
        `chunk_size`-byte SYSEX events with `gap_s` seconds between
        them so old synths' input buffers (DX7-class hardware) don't
        overrun. ALSA bundles each chunk's bytes via the variable-
        length payload pointer in `data.ext`. The userspace buffer
        only needs to live until snd_seq_event_output_direct returns
        — the kernel copies on output.

        Returns the number of bytes actually fed to ALSA. The rate
        limiter that protects the matrix from runaway plugins is
        bypassed: a SysEx dump is one user-initiated action, not a
        loop in a tight callback."""
        if not payload:
            return 0
        from ..alsa_seq import SND_SEQ_EVENT_LENGTH_VARIABLE
        MidiEventType = self._alsa.MidiEventType

        sent = 0
        n = len(payload)
        i = 0
        while i < n:
            chunk = payload[i:i + chunk_size]
            buf = (ctypes.c_uint8 * len(chunk)).from_buffer_copy(chunk)
            ev = self._alsa.SndSeqEvent()
            ev.type = MidiEventType.SYSEX
            ev.flags = SND_SEQ_EVENT_LENGTH_VARIABLE
            ev.source.client = self._client_id
            ev.source.port = self._out_port
            ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
            ev.dest.port = 0
            ev.queue = SND_SEQ_QUEUE_DIRECT
            ev.data.ext.len = len(chunk)
            ev.data.ext.ptr = ctypes.cast(buf, ctypes.c_void_p)
            self._alsa.snd_seq_event_output_direct(
                self._handle, ctypes.pointer(ev))
            sent += len(chunk)
            i += chunk_size
            if i < n:
                time.sleep(gap_s)
        return sent

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
