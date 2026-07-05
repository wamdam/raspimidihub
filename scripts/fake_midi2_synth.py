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
import math
import sys
import time

sys.path.insert(0, "/usr/lib/python3/dist-packages")

from raspimidihub import midi_scale, ump  # noqa: E402
from raspimidihub.alsa_seq import (  # noqa: E402
    SND_SEQ_ADDRESS_SUBSCRIBERS,
    SNDRV_UMP_DIR_BIDIRECTION,
    SNDRV_UMP_EP_INFO_PROTO_MIDI1,
    SNDRV_UMP_EP_INFO_PROTO_MIDI2,
    AlsaSeq,
    SndUmpBlockInfo,
    SndUmpEndpointInfo,
)


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
    print(f"Fake MIDI2 Synth up: client {seq.client_id}, "
          f"sweeping CC {args.cc} every {args.period}s")

    t0 = time.monotonic()
    try:
        while True:
            t = time.monotonic() - t0
            units = 63.5 + 63.5 * math.sin(2 * math.pi * t / args.period)
            value32 = midi_scale.from_midi_units(units)
            seq.send_ump(ump.cc(0, 0, args.cc, value32),
                         SND_SEQ_ADDRESS_SUBSCRIBERS, 0, source_port=keys)
            time.sleep(1.0 / args.rate)
    except KeyboardInterrupt:
        pass
    finally:
        seq.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
