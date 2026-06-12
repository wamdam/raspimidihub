"""E2E loopback: exporter + mirror manager in one process.

Real ALSA seq, real UDP sockets, real zeroconf — verifies the whole
network MIDI chain on a dev machine: advertise → mDNS discover →
AppleMIDI handshake → mirror ALSA client appears → MIDI crosses the
wire in both directions.

NOT collected by pytest (no test_ prefix, and it must run without
RASPIMIDIHUB_TEST_MODE — it needs the real libasound + zeroconf).
Run directly from the repo root:

    .venv/bin/python tests/e2e/network_midi_loopback.py

Expected output ends with "E2E PASS".
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ctypes import pointer

from raspimidihub.alsa_seq import (
    SND_SEQ_ADDRESS_SUBSCRIBERS,
    SND_SEQ_QUEUE_DIRECT,
    AlsaSeq,
    MidiDevice,
    MidiEventType,
    MidiPort,
    SndSeqEvent,
    snd_seq_event_output_direct,
)
from raspimidihub.device_id import DeviceRegistry
from raspimidihub.network_midi import NetworkMidiManager


class FakeServer:
    def record_latency(self, name, ms):
        pass

    async def send_sse(self, event, data):
        pass


class ExporterEngine:
    def __init__(self, synth, out_port, in_port):
        self._synth = synth
        self.devices = [MidiDevice(
            client_id=synth.client_id, name="FakeSynth",
            ports=[MidiPort(out_port, "out", True, False),
                   MidiPort(in_port, "in", False, True)])]
        self.device_registry = self

    # registry duck-typing
    def client_for_stable_id(self, sid):
        return self._synth.client_id if sid == "usb-test-synth" else None

    def get_by_stable_id(self, sid):
        return None

    def on_change(self, cb):
        pass


class MirrorEngine:
    def __init__(self):
        self.devices = []
        self.device_registry = DeviceRegistry()

    def on_change(self, cb):
        pass


class Cfg:
    def __init__(self, data):
        self.data = data


async def main():
    # The "hardware": a real ALSA client with one readable (produces
    # MIDI) and one writable (consumes MIDI) port.
    synth = AlsaSeq("FakeSynth", default_ports=False)
    synth_out = synth.create_port("out", readable=True)
    synth_in = synth.create_port("in", writable=True)

    exporter = NetworkMidiManager(
        ExporterEngine(synth, synth_out, synth_in),
        Cfg({"network_midi": {"enabled": True, "exported": ["usb-test-synth"]}}),
        FakeServer())
    mirror_mgr = NetworkMidiManager(
        MirrorEngine(),
        Cfg({"network_midi": {"enabled": True, "exported": []}}),
        FakeServer())
    mirror_mgr.hub_id = "bbbbbbbbbbbb"  # same machine-id → fake a 2nd hub

    await exporter.start()
    assert exporter._exports, "export session did not come up"
    print("EXPORT OK:", list(exporter._exports.values())[0].service_name)
    await mirror_mgr.start()

    # Wait for discovery + auto-mirror + handshake.
    for _ in range(100):
        await asyncio.sleep(0.1)
        if mirror_mgr._mirrors and \
                list(mirror_mgr._mirrors.values())[0].state == "connected":
            break
    else:
        raise AssertionError(f"mirror never connected: "
                             f"{ {k: m.state for k, m in mirror_mgr._mirrors.items()} } "
                             f"discovered={list(mirror_mgr._discovered)}")
    mirror = list(mirror_mgr._mirrors.values())[0]
    print("MIRROR OK:", mirror.device_name, "state:", mirror.state,
          "stable_id:", mirror.stable_id)

    # Listener client plays the role of the rest of hub B's matrix.
    listener = AlsaSeq("Listener", default_ports=False)
    l_recv = listener.create_port("recv", writable=True)
    l_send = listener.create_port("send", readable=True)
    listener.subscribe(mirror._alsa.client_id, mirror._out_port,
                       listener.client_id, l_recv)
    listener.subscribe(listener.client_id, l_send,
                       mirror._alsa.client_id, mirror._in_port)

    # Direction 1: FakeSynth (hub A) plays a note → must arrive at the
    # listener on hub B via export tx → RTP → mirror inject.
    ev = SndSeqEvent()
    ev.type = MidiEventType.NOTEON
    ev.data.note.channel = 0
    ev.data.note.note = 60
    ev.data.note.velocity = 100
    ev.source.client = synth.client_id
    ev.source.port = synth_out
    ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
    ev.dest.port = 0
    ev.queue = SND_SEQ_QUEUE_DIRECT
    snd_seq_event_output_direct(synth.handle, pointer(ev))

    got = None
    for _ in range(50):
        await asyncio.sleep(0.05)
        e = listener.read_event()
        if e is not None and e.type == MidiEventType.NOTEON:
            got = e
            break
    assert got is not None, "note A→B never arrived"
    assert got.data.note.note == 60 and got.data.note.velocity == 100
    print("A->B OK: NoteOn 60/100 crossed the wire")

    # Direction 2: hub B routes a CC into the mirror → must arrive at
    # FakeSynth's writable port on hub A.
    ev2 = SndSeqEvent()
    ev2.type = MidiEventType.CONTROLLER
    ev2.data.control.channel = 1
    ev2.data.control.param = 7
    ev2.data.control.value = 99
    ev2.source.client = listener.client_id
    ev2.source.port = l_send
    ev2.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
    ev2.dest.port = 0
    ev2.queue = SND_SEQ_QUEUE_DIRECT
    snd_seq_event_output_direct(listener.handle, pointer(ev2))

    got2 = None
    for _ in range(50):
        await asyncio.sleep(0.05)
        e = synth.read_event()
        if e is not None and e.type == MidiEventType.CONTROLLER:
            got2 = e
            break
    assert got2 is not None, "CC B→A never arrived"
    assert got2.data.control.param == 7 and got2.data.control.value == 99
    print("B->A OK: CC7=99 crossed the wire")

    # Latency check via the mirror's CK round (already measured).
    print("latency_ms:", mirror.latency_ms)

    # Teardown: exporter stop must send BY; give the mirror a moment.
    await mirror_mgr.stop()
    await exporter.stop()
    listener.close()
    synth.close()
    print("E2E PASS")


asyncio.run(main())
