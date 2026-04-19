"""Userspace MIDI passthrough with channel/message filtering and mapping.

For connections that have filters or mappings applied, MIDI events are routed
through userspace instead of direct ALSA kernel subscriptions. This adds ~1-3ms
latency but enables per-channel filtering and MIDI mapping.
"""

import asyncio
import ctypes
import logging
from dataclasses import dataclass, field
from enum import Enum

from .alsa_seq import (
    AlsaSeq, MidiEventType, MSG_FILTER_GROUPS, SndSeqEvent, SndSeqEventData,
    SeqEventType,
)

log = logging.getLogger(__name__)

# Default: all channels, all message types pass through
ALL_CHANNELS = 0xFFFF  # bits 0-15 = channels 1-16
ALL_MSG_TYPES = {"note", "cc", "pc", "pitchbend", "aftertouch", "sysex", "clock"}


# --- Mapping types ---

class MappingType(str, Enum):
    NOTE_TO_CC = "note_to_cc"            # Note on/off → CC value A / B
    NOTE_TO_CC_TOGGLE = "note_to_cc_toggle"  # Note on toggles CC between A / B
    CC_TO_CC = "cc_to_cc"                # Remap CC number, optional range transform
    CHANNEL_MAP = "channel_map"          # Route events from one channel to another


@dataclass
class MidiMapping:
    """A single MIDI mapping rule applied to a connection."""
    type: MappingType
    # Source matching
    src_channel: int | None = None   # None = any channel
    # Note→CC fields
    src_note: int | None = None      # Note number to match
    dst_cc: int | None = None        # CC number to output
    cc_on_value: int = 127           # CC value when note on
    cc_off_value: int = 0            # CC value when note off
    # CC→CC fields
    src_cc: int | None = None        # CC number to match
    dst_cc_num: int | None = None    # Output CC number (None = same as src)
    in_range_min: int = 0            # Input range min
    in_range_max: int = 127          # Input range max
    out_range_min: int = 0           # Output range min
    out_range_max: int = 127         # Output range max
    # Channel remap fields
    dst_channel: int | None = None   # Target channel (0-15)
    # Behavior
    pass_through: bool = False       # Also forward the original event

    def to_dict(self) -> dict:
        d = {"type": self.type.value}
        if self.src_channel is not None:
            d["src_channel"] = self.src_channel
        if self.dst_channel is not None:
            d["dst_channel"] = self.dst_channel
        if self.pass_through:
            d["pass_through"] = True
        if self.type in (MappingType.NOTE_TO_CC, MappingType.NOTE_TO_CC_TOGGLE):
            d["src_note"] = self.src_note
            d["dst_cc"] = self.dst_cc
            d["cc_on_value"] = self.cc_on_value
            d["cc_off_value"] = self.cc_off_value
        elif self.type == MappingType.CC_TO_CC:
            d["src_cc"] = self.src_cc
            d["dst_cc_num"] = self.dst_cc_num
            d["in_range_min"] = self.in_range_min
            d["in_range_max"] = self.in_range_max
            d["out_range_min"] = self.out_range_min
            d["out_range_max"] = self.out_range_max
        return d

    @staticmethod
    def from_dict(data: dict) -> "MidiMapping":
        mtype = MappingType(data["type"])
        m = MidiMapping(type=mtype)
        m.src_channel = data.get("src_channel")
        m.dst_channel = data.get("dst_channel")
        m.pass_through = data.get("pass_through", False)
        if mtype in (MappingType.NOTE_TO_CC, MappingType.NOTE_TO_CC_TOGGLE):
            m.src_note = data.get("src_note")
            m.dst_cc = data.get("dst_cc")
            m.cc_on_value = data.get("cc_on_value", 127)
            m.cc_off_value = data.get("cc_off_value", 0)
        elif mtype == MappingType.CC_TO_CC:
            m.src_cc = data.get("src_cc")
            m.dst_cc_num = data.get("dst_cc_num")
            m.in_range_min = data.get("in_range_min", 0)
            m.in_range_max = data.get("in_range_max", 127)
            m.out_range_min = data.get("out_range_min", 0)
            m.out_range_max = data.get("out_range_max", 127)
        return m

    def _scale_value(self, val: int) -> int:
        """Scale input value from in_range to out_range."""
        in_span = self.in_range_max - self.in_range_min
        out_span = self.out_range_max - self.out_range_min
        if in_span == 0:
            return self.out_range_min
        scaled = (val - self.in_range_min) / in_span * out_span + self.out_range_min
        return max(0, min(127, int(round(scaled))))


def validate_new_mapping(existing: list["MidiMapping"],
                         new: "MidiMapping") -> str | None:
    """Return an error string if `new` shouldn't be added, else None.

    Two rejection categories:
      1. Pointless — the new mapping on its own has no audible effect.
      2. Exact duplicate — every behavior-affecting field matches an existing
         mapping of the same type on the same connection. (Different scaling,
         different dst channel, different pass-through, etc. are all allowed
         and represent legitimate fan-out / re-shape use cases.)

    Anything else is allowed. Callers are expected to have pre-validated the
    shape of `new` (e.g. via MidiMapping.from_dict).
    """
    # --- Pointless check (type-specific) ---
    if new.type == MappingType.CC_TO_CC:
        eff_dst_ch = new.dst_channel if new.dst_channel is not None else new.src_channel
        eff_dst_cc = new.dst_cc_num if new.dst_cc_num is not None else new.src_cc
        identity_scaling = (
            new.in_range_min == 0 and new.in_range_max == 127
            and new.out_range_min == 0 and new.out_range_max == 127
        )
        if (new.src_channel == eff_dst_ch and new.src_cc == eff_dst_cc
                and identity_scaling):
            return "Same channel, same CC, identity scaling — mapping has no effect"

    if new.type == MappingType.CHANNEL_MAP:
        if new.src_channel is not None and new.src_channel == new.dst_channel:
            return "Channel remap to the same channel — mapping has no effect"

    # --- Duplicate check against each existing mapping ---
    for exist in existing:
        if exist.type != new.type:
            continue
        if _mappings_equivalent(exist, new):
            return _duplicate_error_message(new)

    return None


def _mappings_equivalent(a: "MidiMapping", b: "MidiMapping") -> bool:
    """Two mappings are equivalent iff every behavior-affecting field matches.

    Uses `effective` values so that `dst_channel=None` (fall back to event's
    channel, i.e. src_channel) is treated the same as explicitly setting
    dst_channel to src_channel.
    """
    if a.type != b.type:
        return False
    if a.src_channel != b.src_channel:
        return False
    if a.pass_through != b.pass_through:
        return False

    def eff_dst_ch(m):
        return m.dst_channel if m.dst_channel is not None else m.src_channel

    if eff_dst_ch(a) != eff_dst_ch(b):
        return False

    if a.type in (MappingType.NOTE_TO_CC, MappingType.NOTE_TO_CC_TOGGLE):
        return (a.src_note == b.src_note
                and a.dst_cc == b.dst_cc
                and a.cc_on_value == b.cc_on_value
                and a.cc_off_value == b.cc_off_value)

    if a.type == MappingType.CC_TO_CC:
        def eff_dst_cc(m):
            return m.dst_cc_num if m.dst_cc_num is not None else m.src_cc
        return (a.src_cc == b.src_cc
                and eff_dst_cc(a) == eff_dst_cc(b)
                and a.in_range_min == b.in_range_min
                and a.in_range_max == b.in_range_max
                and a.out_range_min == b.out_range_min
                and a.out_range_max == b.out_range_max)

    if a.type == MappingType.CHANNEL_MAP:
        return True  # src_channel + dst_channel already compared above

    return False


def _duplicate_error_message(new: "MidiMapping") -> str:
    if new.type == MappingType.CC_TO_CC:
        dst_cc = new.dst_cc_num if new.dst_cc_num is not None else new.src_cc
        return f"A CC mapping for CC{new.src_cc} -> CC{dst_cc} already exists with the same settings"
    if new.type in (MappingType.NOTE_TO_CC, MappingType.NOTE_TO_CC_TOGGLE):
        return f"A note mapping for note {new.src_note} -> CC{new.dst_cc} already exists with the same settings"
    if new.type == MappingType.CHANNEL_MAP:
        return "A channel remap with the same settings already exists"
    return "Duplicate mapping"


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
    """A connection that routes MIDI through userspace with filtering/mapping."""
    src_client: int
    src_port: int
    dst_client: int
    dst_port: int
    filter: MidiFilter
    mappings: list[MidiMapping] = field(default_factory=list)
    _toggle_state: dict = field(default_factory=dict)  # mapping index -> bool
    # Our internal port IDs for this connection
    _read_port: int = -1
    _write_port: int = -1

    @property
    def conn_id(self) -> str:
        return f"{self.src_client}:{self.src_port}-{self.dst_client}:{self.dst_port}"

    @property
    def needs_userspace(self) -> bool:
        """Whether this connection needs userspace passthrough."""
        return not self.filter.is_passthrough or len(self.mappings) > 0


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
        read_name = f"filter:{self._port_counter}"
        read_port = self._seq.create_port(read_name, writable=True)

        # Create a write port dedicated to this connection's destination
        self._port_counter += 1
        write_name = f"fout:{self._port_counter}"
        write_port = self._seq.create_port(write_name, readable=True)

        # Subscribe: source -> our read port
        self._seq.subscribe(src_client, src_port,
                            self._seq.client_id, read_port)

        # Subscribe: our write port -> destination
        self._seq.subscribe(self._seq.client_id, write_port,
                            dst_client, dst_port)

        fc = FilteredConnection(
            src_client=src_client,
            src_port=src_port,
            dst_client=dst_client,
            dst_port=dst_port,
            filter=midi_filter,
            _read_port=read_port,
            _write_port=write_port,
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

        # Unsubscribe source from our read port
        try:
            self._seq.unsubscribe(fc.src_client, fc.src_port,
                                  self._seq.client_id, fc._read_port)
        except OSError:
            pass
        # Unsubscribe our write port from destination
        if fc._write_port >= 0:
            try:
                self._seq.unsubscribe(self._seq.client_id, fc._write_port,
                                      fc.dst_client, fc.dst_port)
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

    # --- Mapping management ---

    def add_mapping(self, conn_id: str, mapping: MidiMapping) -> int:
        """Add a mapping to a filtered connection. Returns mapping index."""
        fc = self._filtered.get(conn_id)
        if fc is None:
            return -1
        fc.mappings.append(mapping)
        log.info("Added %s mapping on %s", mapping.type.value, conn_id)
        return len(fc.mappings) - 1

    def remove_mapping(self, conn_id: str, index: int) -> bool:
        """Remove a mapping by index."""
        fc = self._filtered.get(conn_id)
        if fc is None or index < 0 or index >= len(fc.mappings):
            return False
        fc.mappings.pop(index)
        log.info("Removed mapping %d on %s", index, conn_id)
        return True

    def get_mappings(self, conn_id: str) -> list[MidiMapping]:
        fc = self._filtered.get(conn_id)
        return fc.mappings if fc else []

    def set_mappings(self, conn_id: str, mappings: list[MidiMapping]) -> bool:
        fc = self._filtered.get(conn_id)
        if fc is None:
            return False
        fc.mappings = mappings
        return True

    def clear_all(self):
        """Remove all filtered connections."""
        for conn_id in list(self._filtered.keys()):
            self.remove_filter(conn_id)

    def process_event(self, ev: SndSeqEvent) -> None:
        """Process a single event — check all filtered connections, apply filters + mappings."""
        src_client = ev.source.client
        src_port = ev.source.port

        for fc in self._filtered.values():
            if fc.src_client != src_client or fc.src_port != src_port:
                continue

            # Check if this event arrived on our specific read port
            if ev.dest.client != self._seq.client_id or ev.dest.port != fc._read_port:
                continue

            if not fc.filter.allows_event(ev):
                continue

            # Apply mappings — a mapping may consume the event and produce new ones
            if fc.mappings:
                consumed = self._apply_mappings(ev, fc)
                if consumed:
                    continue

            # Forward original event via dedicated write port
            self._forward_event(ev, fc)

    def _forward_event(self, ev: SndSeqEvent, fc: FilteredConnection) -> None:
        """Forward an event via the connection's dedicated write port."""
        from .alsa_seq import (
            snd_seq_event_output_direct, SndSeqAddr,
            SND_SEQ_ADDRESS_SUBSCRIBERS, SND_SEQ_QUEUE_DIRECT,
        )
        ev.source.client = self._seq.client_id
        ev.source.port = fc._write_port
        ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
        ev.dest.port = 0
        ev.queue = SND_SEQ_QUEUE_DIRECT
        ev.flags = 0
        snd_seq_event_output_direct(self._seq.handle, ctypes.pointer(ev))

    def _forward_cc(self, fc: FilteredConnection, channel: int, cc: int, value: int) -> None:
        """Send a CC event via the connection's dedicated write port."""
        from .alsa_seq import SndSeqEvent, MidiEventType
        ev = SndSeqEvent()
        ev.type = MidiEventType.CONTROLLER
        ev.data.control.channel = channel
        ev.data.control.param = cc
        ev.data.control.value = value
        self._forward_event(ev, fc)

    def _apply_mappings(self, ev: SndSeqEvent, fc: FilteredConnection) -> bool:
        """Apply mappings to an event. Returns True if the event was consumed."""
        try:
            ev_type = MidiEventType(ev.type)
        except ValueError:
            return False

        consumed = False
        for idx, mapping in enumerate(fc.mappings):
            # Check channel match
            if mapping.src_channel is not None and ev.channel != mapping.src_channel:
                continue

            if mapping.type == MappingType.NOTE_TO_CC:
                if ev_type in (MidiEventType.NOTEON, MidiEventType.NOTEOFF) and \
                   mapping.src_note is not None and ev.data.note.note == mapping.src_note and \
                   mapping.dst_cc is not None:
                    is_on = (ev_type == MidiEventType.NOTEON and ev.data.note.velocity > 0)
                    val = mapping.cc_on_value if is_on else mapping.cc_off_value
                    ch = mapping.dst_channel if mapping.dst_channel is not None else ev.channel
                    self._forward_cc(fc, ch, mapping.dst_cc, val)
                    if not mapping.pass_through:
                        consumed = True

            elif mapping.type == MappingType.NOTE_TO_CC_TOGGLE:
                if mapping.src_note is not None and ev.data.note.note == mapping.src_note and \
                   mapping.dst_cc is not None:
                    is_note_on = (ev_type == MidiEventType.NOTEON and ev.data.note.velocity > 0)
                    is_note_off = (ev_type == MidiEventType.NOTEOFF or
                                   (ev_type == MidiEventType.NOTEON and ev.data.note.velocity == 0))
                    if is_note_on:
                        toggled = not fc._toggle_state.get(idx, False)
                        fc._toggle_state[idx] = toggled
                        val = mapping.cc_on_value if toggled else mapping.cc_off_value
                        ch = mapping.dst_channel if mapping.dst_channel is not None else ev.channel
                        self._forward_cc(fc, ch, mapping.dst_cc, val)
                        if not mapping.pass_through:
                            consumed = True
                    elif is_note_off:
                        if not mapping.pass_through:
                            consumed = True

            elif mapping.type == MappingType.CC_TO_CC:
                if ev_type == MidiEventType.CONTROLLER and \
                   mapping.src_cc is not None and ev.data.control.param == mapping.src_cc:
                    out_cc = mapping.dst_cc_num if mapping.dst_cc_num is not None else mapping.src_cc
                    out_val = mapping._scale_value(ev.data.control.value)
                    ch = mapping.dst_channel if mapping.dst_channel is not None else ev.channel
                    self._forward_cc(fc, ch, out_cc, out_val)
                    if not mapping.pass_through:
                        consumed = True

            elif mapping.type == MappingType.CHANNEL_MAP:
                if mapping.dst_channel is not None:
                    # Fan-out: forward a copy with the remapped channel. Multiple
                    # channel maps produce multiple copies (e.g. layering a bass
                    # on ch 1 with strings on ch 6 from a single keyboard).
                    new_ev = SndSeqEvent.from_buffer_copy(ev)
                    new_ev.data.note.channel = mapping.dst_channel
                    self._forward_event(new_ev, fc)
                    consumed = True

        return consumed
