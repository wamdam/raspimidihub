"""SndSeqEvent <-> raw MIDI bytes, including SysEx.

Shared by the network MIDI bridge (and eventually the BLE bridge,
which today carries its own copy of the channel-voice subset — see
ble_midi_bridge._event_to_midi). Pure translation, no I/O: callers
fill in source/dest/queue and perform the actual ALSA output.

SysEx rides in ALSA variable-length events (data.ext.{len, ptr},
flags |= SND_SEQ_EVENT_LENGTH_VARIABLE). A device may deliver one
SysEx message as several SYSEX events (chunked); event_to_midi
returns each chunk's raw bytes as-is and leaves reassembly /
re-framing to the transport layer.
"""

import ctypes

from .alsa_seq import (
    SND_SEQ_EVENT_LENGTH_VARIABLE,
    MidiEventType,
    SndSeqEvent,
)

_STATUS_NOTE_OFF = 0x80
_STATUS_NOTE_ON = 0x90
_STATUS_POLY_PRESSURE = 0xA0
_STATUS_CC = 0xB0
_STATUS_PROGRAM = 0xC0
_STATUS_CHAN_PRESSURE = 0xD0
_STATUS_PITCH_BEND = 0xE0


def event_to_midi(ev) -> bytes | None:
    """Convert an ALSA SndSeqEvent to raw MIDI bytes. Returns None for
    event types that have no wire representation (port management,
    TICK, ...). SYSEX events return the chunk's payload verbatim."""
    try:
        ev_type = MidiEventType(ev.type)
    except ValueError:
        return None

    if ev_type == MidiEventType.SYSEX:
        if not ev.data.ext.ptr or not ev.data.ext.len:
            return None
        return ctypes.string_at(ev.data.ext.ptr, ev.data.ext.len)

    ch = ev.data.note.channel & 0x0F

    if ev_type == MidiEventType.NOTEON:
        return bytes([_STATUS_NOTE_ON | ch, ev.data.note.note & 0x7F,
                      ev.data.note.velocity & 0x7F])
    if ev_type == MidiEventType.NOTEOFF:
        return bytes([_STATUS_NOTE_OFF | ch, ev.data.note.note & 0x7F,
                      ev.data.note.velocity & 0x7F])
    if ev_type == MidiEventType.KEYPRESS:
        return bytes([_STATUS_POLY_PRESSURE | ch, ev.data.note.note & 0x7F,
                      ev.data.note.velocity & 0x7F])
    if ev_type == MidiEventType.CONTROLLER:
        return bytes([_STATUS_CC | ch, ev.data.control.param & 0x7F,
                      ev.data.control.value & 0x7F])
    if ev_type == MidiEventType.PGMCHANGE:
        return bytes([_STATUS_PROGRAM | ch, ev.data.control.value & 0x7F])
    if ev_type == MidiEventType.CHANPRESS:
        return bytes([_STATUS_CHAN_PRESSURE | ch,
                      ev.data.control.value & 0x7F])
    if ev_type == MidiEventType.PITCHBEND:
        val = ev.data.control.value
        return bytes([_STATUS_PITCH_BEND | ch, val & 0x7F, (val >> 7) & 0x7F])
    if ev_type == MidiEventType.CLOCK:
        return b"\xf8"
    if ev_type == MidiEventType.START:
        return b"\xfa"
    if ev_type == MidiEventType.CONTINUE:
        return b"\xfb"
    if ev_type == MidiEventType.STOP:
        return b"\xfc"
    if ev_type == MidiEventType.SENSING:
        return b"\xfe"
    if ev_type == MidiEventType.SONGPOS:
        val = ev.data.control.value & 0x3FFF
        return bytes([0xF2, val & 0x7F, (val >> 7) & 0x7F])
    return None


def midi_to_event(msg: bytes) -> SndSeqEvent | None:
    """Convert one complete MIDI message to an SndSeqEvent with type
    and data filled in; the caller sets source/dest/queue/flags-extras.
    For SysEx the payload buffer is parked on the event as
    `_sysex_buf` — keep the event referenced until the ALSA output
    call returns (the kernel copies on output)."""
    if not msg:
        return None
    status = msg[0]
    if not status & 0x80:
        return None
    ev = SndSeqEvent()

    if status == 0xF0:
        if msg[-1] != 0xF7:
            return None  # transport must hand us complete messages
        buf = (ctypes.c_uint8 * len(msg)).from_buffer_copy(msg)
        ev.type = MidiEventType.SYSEX
        ev.flags = SND_SEQ_EVENT_LENGTH_VARIABLE
        ev.data.ext.len = len(msg)
        ev.data.ext.ptr = ctypes.cast(buf, ctypes.c_void_p)
        ev._sysex_buf = buf  # keepalive until the kernel copies
        return ev

    status_type = status & 0xF0
    channel = status & 0x0F

    if status_type == _STATUS_NOTE_ON and len(msg) >= 3:
        ev.type = MidiEventType.NOTEON
        ev.data.note.channel = channel
        ev.data.note.note = msg[1]
        ev.data.note.velocity = msg[2]
    elif status_type == _STATUS_NOTE_OFF and len(msg) >= 3:
        ev.type = MidiEventType.NOTEOFF
        ev.data.note.channel = channel
        ev.data.note.note = msg[1]
        ev.data.note.velocity = msg[2]
    elif status_type == _STATUS_POLY_PRESSURE and len(msg) >= 3:
        ev.type = MidiEventType.KEYPRESS
        ev.data.note.channel = channel
        ev.data.note.note = msg[1]
        ev.data.note.velocity = msg[2]
    elif status_type == _STATUS_CC and len(msg) >= 3:
        ev.type = MidiEventType.CONTROLLER
        ev.data.control.channel = channel
        ev.data.control.param = msg[1]
        ev.data.control.value = msg[2]
    elif status_type == _STATUS_PROGRAM and len(msg) >= 2:
        ev.type = MidiEventType.PGMCHANGE
        ev.data.control.channel = channel
        ev.data.control.value = msg[1]
    elif status_type == _STATUS_CHAN_PRESSURE and len(msg) >= 2:
        ev.type = MidiEventType.CHANPRESS
        ev.data.control.channel = channel
        ev.data.control.value = msg[1]
    elif status_type == _STATUS_PITCH_BEND and len(msg) >= 3:
        ev.type = MidiEventType.PITCHBEND
        ev.data.control.channel = channel
        ev.data.control.value = (msg[2] << 7) | msg[1]
    elif status == 0xF8:
        ev.type = MidiEventType.CLOCK
    elif status == 0xFA:
        ev.type = MidiEventType.START
    elif status == 0xFB:
        ev.type = MidiEventType.CONTINUE
    elif status == 0xFC:
        ev.type = MidiEventType.STOP
    elif status == 0xFE:
        ev.type = MidiEventType.SENSING
    elif status == 0xF2 and len(msg) >= 3:
        ev.type = MidiEventType.SONGPOS
        ev.data.control.value = msg[1] | (msg[2] << 7)
    else:
        return None
    return ev
