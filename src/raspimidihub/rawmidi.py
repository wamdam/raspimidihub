"""Rawmidi helper — send raw MIDI bytes to hardware outputs.

Workaround for ALSA seq not converting user-space Start/Stop/Continue
events to raw MIDI bytes (0xFA/0xFC/0xFB) on some USB MIDI drivers.
"""

import ctypes
import ctypes.util
import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

_lib_path = ctypes.util.find_library("asound")
_lib = ctypes.CDLL(_lib_path) if _lib_path else None

# Raw MIDI bytes for transport
MIDI_START = b"\xfa"
MIDI_STOP = b"\xfc"
MIDI_CONTINUE = b"\xfb"


def _seq_port_to_rawmidi(client_id: int, port_id: int) -> str | None:
    """Map an ALSA seq client:port to a rawmidi device name (e.g. 'hw:1,0,2').

    Walks /proc/asound to find the card number for a seq client,
    then uses the port_id as the rawmidi subdevice.
    """
    # Find card number for this ALSA seq client
    try:
        seq_clients = Path("/proc/asound/seq/clients").read_text()
    except OSError:
        return None

    # Parse: "Client  20 : "LCXL3 1" [type=kernel,card=1]"
    for line in seq_clients.splitlines():
        m = re.match(r'^Client\s+(\d+)\s*:\s*".*"\s+\[.*card\s*=\s*(\d+)', line)
        if m and int(m.group(1)) == client_id:
            card = int(m.group(2))
            device = f"hw:{card},0,{port_id}"
            # Verify it exists
            midi_path = Path(f"/proc/asound/card{card}/midi0")
            if midi_path.exists():
                return device
            return None

    return None


def send_raw_transport(dest_client: int, dest_port: int, raw_byte: bytes) -> bool:
    """Send a raw MIDI byte to a hardware rawmidi output device.

    Returns True if sent, False if the device couldn't be opened.
    """
    if not _lib:
        return False

    device = _seq_port_to_rawmidi(dest_client, dest_port)
    if not device:
        return False

    handle = ctypes.c_void_p()
    ret = _lib.snd_rawmidi_open(None, ctypes.byref(handle), device.encode(), 2)  # SND_RAWMIDI_NONBLOCK
    if ret < 0:
        return False

    try:
        buf = ctypes.create_string_buffer(raw_byte)
        ret = _lib.snd_rawmidi_write(handle, buf, len(raw_byte))
        return ret > 0
    finally:
        _lib.snd_rawmidi_close(handle)


def get_subscribed_destinations(alsa_seq_handle, client_id: int, port_id: int) -> list[tuple[int, int]]:
    """Get all destination (client, port) pairs subscribed to a source port."""
    from .alsa_seq import (
        SndSeqQuerySubscribePtr, SndSeqAddr,
        snd_seq_query_subscribe_malloc, snd_seq_query_subscribe_free,
        snd_seq_query_subscribe_set_root, snd_seq_query_subscribe_set_type,
        snd_seq_query_subscribe_set_index, snd_seq_query_subscribe_get_addr,
        snd_seq_query_port_subscribers,
    )

    subs = []
    qsub = SndSeqQuerySubscribePtr()
    snd_seq_query_subscribe_malloc(ctypes.byref(qsub))
    try:
        root = SndSeqAddr(client=client_id, port=port_id)
        snd_seq_query_subscribe_set_root(qsub, ctypes.pointer(root))
        snd_seq_query_subscribe_set_type(qsub, 0)  # 0 = READ subscribers (destinations)

        idx = 0
        while True:
            snd_seq_query_subscribe_set_index(qsub, idx)
            ret = snd_seq_query_port_subscribers(alsa_seq_handle, qsub)
            if ret < 0:
                break
            addr = snd_seq_query_subscribe_get_addr(qsub)
            if addr:
                subs.append((addr.contents.client, addr.contents.port))
            idx += 1
    finally:
        snd_seq_query_subscribe_free(qsub)

    return subs
