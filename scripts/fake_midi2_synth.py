#!/usr/bin/env python3
"""Virtual MIDI 2.0 synth — a UMP user client the hub treats as a real
MIDI 2.0 device, so the whole 2.0 feature set (badge, function-block
rows, hi-res monitor, hi-res filters/mappings, plugin automation) can
be exercised without buying MIDI 2.0 hardware.

Declares endpoint "Fake MIDI2 Synth" (MIDI 2.0 protocol, two function
blocks: Keys / Pads, one port each) and emits a stepless 32-bit CC 74
sine sweep on the Keys port — permanently off the 7-bit lattice, so
everything downstream sees genuine high-resolution traffic.

Run ON the hub (needs the installed raspimidihub package + UMP kernel):

    python3 fake_midi2_synth.py [--cc 74] [--period 10] [--rate 20]

Stop with Ctrl+C. The hub picks the device up via the normal hotplug
rescan and forgets it again when the script exits.
"""

import argparse
import json
import math
import select
import sys
import time

sys.path.insert(0, "/usr/lib/python3/dist-packages")

from raspimidihub import midi_ci, midi_scale, ump  # noqa: E402
from raspimidihub.alsa_seq import (  # noqa: E402
    SND_SEQ_ADDRESS_SUBSCRIBERS,
    SNDRV_UMP_DIR_BIDIRECTION,
    SNDRV_UMP_EP_INFO_PROTO_MIDI1,
    SNDRV_UMP_EP_INFO_PROTO_MIDI2,
    AlsaSeq,
    SndUmpBlockInfo,
    SndUmpEndpointInfo,
)

DEVICE_INFO = {
    "manufacturer": "FakeCo Instruments",
    "model": "Fake MIDI2 Synth",
    "version": "1.0.0",
    "serialNumber": "FAKE-2000",
}


class CiResponder:
    """Answers MIDI-CI Discovery + Property Exchange (DeviceInfo).

    The synth is a midi_version=2 client, so inbound SysEx arrives as
    SysEx7 UMP packets; replies go back the same way on the source
    port that received the inquiry.
    """

    def __init__(self, seq, port):
        self.seq = seq
        self.port = port
        self.muid = midi_ci.new_muid()
        self.asm = ump.Sysex7Assembler()

    def handle_words(self, words) -> None:
        if ((words[0] >> 28) & 0xF) != ump.MT_DATA64:
            return
        msg = self.asm.feed(words)
        if msg is None:
            return
        m = midi_ci.parse(msg.payload)
        if m is None:
            return
        reply = None
        if m.sub2 == midi_ci.MSG_DISCOVERY:
            reply = midi_ci.build_discovery_reply(
                self.muid, m.src_muid,
                manufacturer=(0x7D, 0x01, 0x02), family=0x0001, model=0x0002,
                version=b"\x01\x00\x00\x00",
                categories=midi_ci.CAT_PROPERTY_EXCHANGE, max_sysex=512)
        elif m.sub2 == midi_ci.MSG_PE_CAPS:
            reply = midi_ci.build_pe_caps_reply(self.muid, m.src_muid)
        elif m.sub2 == midi_ci.MSG_PE_GET \
                and m.header.get("resource") == "DeviceInfo":
            body = json.dumps(DEVICE_INFO, separators=(",", ":")).encode("ascii")
            reply = midi_ci.build_pe_get_reply(self.muid, m.src_muid,
                                               m.request_id, body)
        if reply is not None:
            # strip F0/F7 — SysEx7 packets carry the bare payload
            for pkt in ump.sysex7_encode(0, reply[1:-1]):
                self.seq.send_ump(pkt, SND_SEQ_ADDRESS_SUBSCRIBERS, 0,
                                  source_port=self.port)
            print(f"CI: answered 0x{m.sub2:02X}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", type=int, default=74)
    ap.add_argument("--period", type=float, default=10.0,
                    help="sine period in seconds")
    ap.add_argument("--rate", type=float, default=20.0,
                    help="CC updates per second")
    args = ap.parse_args()

    seq = AlsaSeq("Fake MIDI2 Synth", default_ports=False, midi_version=2)
    if seq.midi_version != 2:
        print("No UMP support on this system (kernel/alsa-lib)")
        return 1

    ep = SndUmpEndpointInfo()
    ep.name = b"Fake MIDI2 Synth"
    ep.product_id = b"FAKE-2000"
    ep.protocol_caps = (SNDRV_UMP_EP_INFO_PROTO_MIDI1
                        | SNDRV_UMP_EP_INFO_PROTO_MIDI2)
    ep.protocol = SNDRV_UMP_EP_INFO_PROTO_MIDI2
    ep.num_blocks = 2
    if not seq.set_ump_endpoint_info(ep):
        print("Failed to declare UMP endpoint")
        return 1
    for i, (name, group) in enumerate(((b"Keys", 0), (b"Pads", 1))):
        blk = SndUmpBlockInfo()
        blk.block_id = i
        blk.direction = SNDRV_UMP_DIR_BIDIRECTION
        blk.active = 1
        blk.first_group = group
        blk.num_groups = 1
        blk.name = name
        seq.set_ump_block_info(i, blk)

    keys = seq.create_port("Keys", readable=True, writable=True)
    seq.create_port("Pads", readable=True, writable=True)
    responder = CiResponder(seq, keys)
    print(f"Fake MIDI2 Synth up: client {seq.client_id}, "
          f"sweeping CC {args.cc} every {args.period}s, MIDI-CI responder on")

    fd = seq.fileno()
    t0 = time.monotonic()
    try:
        while True:
            t = time.monotonic() - t0
            units = 63.5 + 63.5 * math.sin(2 * math.pi * t / args.period)
            value32 = midi_scale.from_midi_units(units)
            seq.send_ump(ump.cc(0, 0, args.cc, value32),
                         SND_SEQ_ADDRESS_SUBSCRIBERS, 0, source_port=keys)
            # Poll for inbound MIDI-CI between sweep updates
            deadline = time.monotonic() + 1.0 / args.rate
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                readable, _, _ = select.select([fd], [], [], remaining)
                if not readable:
                    break
                for _ in range(64):
                    uev = seq.read_ump_event()
                    if uev is None:
                        break
                    if uev.is_ump:
                        responder.handle_words(uev.ump_words)
    except KeyboardInterrupt:
        pass
    finally:
        seq.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
