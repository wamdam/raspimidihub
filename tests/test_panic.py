"""Tests for MidiEngine soft/hard panic split."""

from unittest.mock import MagicMock, patch

from raspimidihub.alsa_seq import MidiEventType
from raspimidihub.midi_engine import Connection, MidiEngine


def _make_engine():
    engine = MidiEngine()
    mock_seq = MagicMock()
    mock_seq.client_id = 128
    mock_seq.handle = MagicMock()
    engine._seq = mock_seq
    engine._monitor_port = 0
    return engine


def _captured_events(engine, fn):
    """Run `fn(engine)` while patching snd_seq_event_output_direct, return
    list of (type, channel, param, value, dst_client, dst_port) tuples."""
    captured: list[tuple] = []

    def _capture(_handle, ev_ptr):
        ev = ev_ptr.contents
        # Note events use ev.data.note.*; CC uses ev.data.control.*
        if ev.type == int(MidiEventType.NOTEOFF):
            captured.append(("noteoff", ev.data.note.channel, ev.data.note.note,
                             ev.data.note.velocity, ev.dest.client, ev.dest.port))
        elif ev.type == int(MidiEventType.CONTROLLER):
            captured.append(("cc", ev.data.control.channel, ev.data.control.param,
                             ev.data.control.value, ev.dest.client, ev.dest.port))
        return 0

    with patch("raspimidihub.alsa_seq.snd_seq_event_output_direct", _capture):
        fn(engine)

    return captured


class TestSoftPanic:
    def test_emits_cc123_only(self):
        engine = _make_engine()
        engine._connections.add(Connection(1, 0, 2, 0))

        captured = _captured_events(engine, lambda e: e.panic(hard=False))

        cc_events = [c for c in captured if c[0] == "cc"]
        assert all(c[2] == 123 for c in cc_events), "soft panic must not send CC 120"
        # 16 channels × 1 destination
        assert len(cc_events) == 16

    def test_emits_per_edge_noteoffs_for_tracked_notes(self):
        engine = _make_engine()
        conn = Connection(1, 0, 2, 0)
        engine._connections.add(conn)
        engine._active_notes[conn] = {(0, 60): 1, (1, 64): 2}

        captured = _captured_events(engine, lambda e: e.panic(hard=False))

        noteoffs = [c for c in captured if c[0] == "noteoff"]
        # One NoteOff per held (ch, note), regardless of refcount value
        notes = {(n[1], n[2]) for n in noteoffs}
        assert notes == {(0, 60), (1, 64)}
        # All routed to the tracked edge's destination
        assert all((n[4], n[5]) == (2, 0) for n in noteoffs)

    def test_calls_plugin_panic_all(self):
        engine = _make_engine()
        engine._plugin_host = MagicMock()

        _captured_events(engine, lambda e: e.panic(hard=False))

        engine._plugin_host.panic_all.assert_called_once()

    def test_no_destinations_no_cc(self):
        engine = _make_engine()
        captured = _captured_events(engine, lambda e: e.panic(hard=False))
        assert [c for c in captured if c[0] == "cc"] == []


class TestHardPanic:
    def test_emits_cc123_and_cc120(self):
        engine = _make_engine()
        engine._connections.add(Connection(1, 0, 2, 0))

        captured = _captured_events(engine, lambda e: e.panic(hard=True))

        cc_events = [c for c in captured if c[0] == "cc"]
        cc_nums = {c[2] for c in cc_events}
        assert cc_nums == {123, 120}
        # 16 channels × 2 ccs × 1 destination
        assert len(cc_events) == 32

    def test_default_is_soft(self):
        """Calling panic() with no flag is soft (no CC 120)."""
        engine = _make_engine()
        engine._connections.add(Connection(1, 0, 2, 0))

        captured = _captured_events(engine, lambda e: e.panic())

        cc_nums = {c[2] for c in captured if c[0] == "cc"}
        assert cc_nums == {123}


class TestPanicMultipleDestinations:
    def test_cc_emitted_per_destination(self):
        engine = _make_engine()
        engine._connections.add(Connection(1, 0, 2, 0))
        engine._connections.add(Connection(1, 0, 3, 0))

        captured = _captured_events(engine, lambda e: e.panic(hard=True))

        # 2 dests × 16 channels × 2 ccs = 64
        cc_events = [c for c in captured if c[0] == "cc"]
        assert len(cc_events) == 64
        dests = {(c[4], c[5]) for c in cc_events}
        assert dests == {(2, 0), (3, 0)}
