"""Tests for the SysEx Sender plugin."""

from helpers import make_plugin

from sysex_sender import SysExSender


class TestSysExSender:
    def test_metadata(self):
        p, _ = make_plugin(SysExSender)
        assert p.NAME == "SysEx Sender"
        assert p.params == []
        # No event handlers should produce output.
        assert p.on_note_on(0, 60, 100) is None
        assert p.on_cc(0, 7, 64) is None

    def test_send_sysex_routes_to_host_hook(self):
        p, h = make_plugin(SysExSender)
        # 12-byte fake DX7 patch dump.
        payload = b"\xf0\x43\x00" + b"\x00" * 8 + b"\xf7"
        sent = p.send_sysex(payload)
        assert sent == len(payload)
        assert h.sent == [("sysex", payload)]

    def test_send_sysex_no_hook_returns_zero(self):
        p, _ = make_plugin(SysExSender)
        # Strip the harness hook to mimic the case where the host
        # never wired _send_sysex (e.g. plugin used in standalone
        # tests). Should be silent, not raise.
        p._send_sysex = None
        assert p.send_sysex(b"\xf0\x01\xf7") == 0
