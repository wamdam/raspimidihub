"""Userspace MIDI passthrough with channel and message type filtering.

For connections that have filters applied, MIDI events are routed through
userspace instead of direct ALSA kernel subscriptions. This adds ~1-3ms
latency but enables per-channel and per-message-type filtering.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from .alsa_seq import (
    AlsaSeq, MidiEventType, MSG_FILTER_GROUPS, SndSeqEvent, SeqEventType,
)

log = logging.getLogger(__name__)

# Default: all channels, all message types pass through
ALL_CHANNELS = 0xFFFF  # bits 0-15 = channels 1-16
ALL_MSG_TYPES = {"note", "cc", "pc", "pitchbend", "aftertouch", "sysex", "clock"}


@dataclass
class MidiFilter:
    """Filter configuration for a single connection."""
    channel_mask: int = ALL_CHANNELS       # bitmask: bit N = channel N+1
    msg_types: set[str] = field(default_factory=lambda: ALL_MSG_TYPES.copy())

    @property
    def is_passthrough(self) -> bool:
        """Returns True if this filter allows everything (no filtering needed)."""
        return self.channel_mask == ALL_CHANNELS and self.msg_types == ALL_MSG_TYPES

    def allows_event(self, ev: SndSeqEvent) -> bool:
        """Check if a MIDI event passes through this filter."""
        try:
            ev_type = MidiEventType(ev.type)
        except ValueError:
            return True  # Unknown event types pass through

        # Check message type filter
        type_allowed = False
        for group_name, group_types in MSG_FILTER_GROUPS.items():
            if ev_type in group_types:
                if group_name in self.msg_types:
                    type_allowed = True
                break
        else:
            # Event type not in any group — let it through
            return True

        if not type_allowed:
            return False

        # Check channel filter (only for channel messages)
        if ev_type in (MidiEventType.NOTEON, MidiEventType.NOTEOFF,
                       MidiEventType.KEYPRESS, MidiEventType.CONTROLLER,
                       MidiEventType.PGMCHANGE, MidiEventType.CHANPRESS,
                       MidiEventType.PITCHBEND):
            channel = ev.channel
            if not (self.channel_mask & (1 << channel)):
                return False

        return True

    def to_dict(self) -> dict:
        return {
            "channel_mask": self.channel_mask,
            "msg_types": sorted(self.msg_types),
        }

    @staticmethod
    def from_dict(data: dict) -> "MidiFilter":
        return MidiFilter(
            channel_mask=data.get("channel_mask", ALL_CHANNELS),
            msg_types=set(data.get("msg_types", ALL_MSG_TYPES)),
        )


@dataclass
class FilteredConnection:
    """A connection that routes MIDI through userspace with filtering."""
    src_client: int
    src_port: int
    dst_client: int
    dst_port: int
    filter: MidiFilter
    # Our internal port IDs for this connection
    _read_port: int = -1

    @property
    def conn_id(self) -> str:
        return f"{self.src_client}:{self.src_port}-{self.dst_client}:{self.dst_port}"


class FilterEngine:
    """Manages filtered MIDI connections with userspace passthrough.

    Unfiltered connections remain as direct ALSA subscriptions (handled by MidiEngine).
    Filtered connections are managed here: we subscribe our own port to the source,
    read events, filter them, and forward to the destination.
    """

    def __init__(self, seq: AlsaSeq):
        self._seq = seq
        self._filtered: dict[str, FilteredConnection] = {}
        self._running = False
        self._port_counter = 0

    @property
    def filtered_connections(self) -> dict[str, FilteredConnection]:
        return self._filtered

    def add_filter(self, src_client: int, src_port: int,
                   dst_client: int, dst_port: int,
                   midi_filter: MidiFilter) -> FilteredConnection:
        """Add or update a filtered connection.

        If the connection was a direct ALSA subscription, the caller must
        remove that subscription first.
        """
        conn_id = f"{src_client}:{src_port}-{dst_client}:{dst_port}"

        # Remove existing filtered connection if present
        if conn_id in self._filtered:
            self.remove_filter(conn_id)

        # Create a read port and subscribe to the source
        self._port_counter += 1
        port_name = f"filter:{self._port_counter}"
        read_port = self._seq.create_port(port_name, writable=True)

        # Subscribe: source -> our read port
        self._seq.subscribe(src_client, src_port,
                            self._seq.client_id, read_port)

        fc = FilteredConnection(
            src_client=src_client,
            src_port=src_port,
            dst_client=dst_client,
            dst_port=dst_port,
            filter=midi_filter,
            _read_port=read_port,
        )
        self._filtered[conn_id] = fc
        log.info("Added filter on %s: channels=0x%04x types=%s",
                 conn_id, midi_filter.channel_mask, midi_filter.msg_types)
        return fc

    def remove_filter(self, conn_id: str) -> bool:
        """Remove a filtered connection. Returns True if found."""
        fc = self._filtered.pop(conn_id, None)
        if fc is None:
            return False

        # Unsubscribe source from our port
        try:
            self._seq.unsubscribe(fc.src_client, fc.src_port,
                                  self._seq.client_id, fc._read_port)
        except OSError:
            pass

        log.info("Removed filter on %s", conn_id)
        return True

    def has_filter(self, conn_id: str) -> bool:
        return conn_id in self._filtered

    def get_filter(self, conn_id: str) -> MidiFilter | None:
        fc = self._filtered.get(conn_id)
        return fc.filter if fc else None

    def update_filter(self, conn_id: str, midi_filter: MidiFilter) -> bool:
        """Update the filter on an existing filtered connection."""
        fc = self._filtered.get(conn_id)
        if fc is None:
            return False
        fc.filter = midi_filter
        log.info("Updated filter on %s: channels=0x%04x types=%s",
                 conn_id, midi_filter.channel_mask, midi_filter.msg_types)
        return True

    def clear_all(self):
        """Remove all filtered connections."""
        for conn_id in list(self._filtered.keys()):
            self.remove_filter(conn_id)

    def process_event(self, ev: SndSeqEvent) -> None:
        """Process a single event — check all filtered connections and forward if allowed."""
        src_client = ev.source.client
        src_port = ev.source.port

        for fc in self._filtered.values():
            if fc.src_client != src_client or fc.src_port != src_port:
                continue

            # Check if our read port received this
            if ev.dest.client != self._seq.client_id:
                continue

            if fc.filter.allows_event(ev):
                self._seq.send_event(ev, fc.dst_client, fc.dst_port)
