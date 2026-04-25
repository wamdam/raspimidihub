"""Tests for MidiEngine.apply_edge_diff (Phase 2: smooth preset switching).

The diff computes added / removed / changed / untouched edges from the
current routing vs a target list, and applies the minimum set of
ALSA + FilterEngine operations to reconcile. Removed edges release
tracked notes and emit CC 123 on used channels so destinations don't
end up stuck.
"""

from unittest.mock import MagicMock, patch

from raspimidihub.midi_engine import Connection, MidiEngine

# Stable IDs used across tests. Keep the mapping small and explicit.
_STABLE = {32: "dev-A", 33: "dev-B", 34: "dev-C", 35: "dev-D"}
_STABLE_REV = {v: k for k, v in _STABLE.items()}


def _make_engine():
    engine = MidiEngine()
    engine._seq = MagicMock()
    engine._seq.client_id = 128
    engine._seq.handle = MagicMock()
    engine._monitor_port = 0

    fe = MagicMock()
    fe.has_filter.return_value = False
    fe.get_filter.return_value = None
    fe.get_mappings.return_value = []
    engine._filter_engine = fe

    reg = MagicMock()
    reg.get_by_client.side_effect = lambda cid: (
        MagicMock(stable_id=_STABLE[cid]) if cid in _STABLE else None
    )
    reg.client_for_stable_id.side_effect = lambda sid: _STABLE_REV.get(sid)
    engine._device_registry = reg

    return engine


def _edge(src_sid="dev-A", src_port=0, dst_sid="dev-B", dst_port=0,
          filter_dict=None, mappings=None):
    e = {"src_stable_id": src_sid, "src_port": src_port,
         "dst_stable_id": dst_sid, "dst_port": dst_port}
    if filter_dict is not None:
        e["filter"] = filter_dict
    if mappings is not None:
        e["mappings"] = mappings
    return e


def _capture_alsa_events():
    """Patch snd_seq_event_output_direct, return the patcher + capture list.

    Caller is responsible for entering/exiting the patcher.
    """
    captured: list[tuple] = []

    def cap(_handle, ev_ptr):
        ev = ev_ptr.contents
        captured.append((int(ev.type), ev.data.control.channel,
                         ev.data.control.param, ev.dest.client, ev.dest.port))
        return 0

    patcher = patch("raspimidihub.alsa_seq.snd_seq_event_output_direct", cap)
    return patcher, captured


class TestDiffSummary:
    def test_added_only(self):
        engine = _make_engine()
        stats = engine.apply_edge_diff([_edge()])
        assert stats == {"removed": 0, "added": 1, "changed": 0,
                         "untouched": 0, "skipped": 0}
        engine._seq.subscribe.assert_called_once_with(32, 0, 33, 0)
        assert Connection(32, 0, 33, 0) in engine._connections

    def test_untouched(self):
        engine = _make_engine()
        conn = Connection(32, 0, 33, 0)
        engine._connections.add(conn)
        # not userspace, no filter, no mappings — passthrough direct edge
        stats = engine.apply_edge_diff([_edge()])
        assert stats == {"removed": 0, "added": 0, "changed": 0,
                         "untouched": 1, "skipped": 0}
        engine._seq.subscribe.assert_not_called()
        engine._seq.unsubscribe.assert_not_called()

    def test_removed_only(self):
        engine = _make_engine()
        engine._connections.add(Connection(32, 0, 33, 0))
        patcher, _ = _capture_alsa_events()
        with patcher:
            stats = engine.apply_edge_diff([])
        assert stats == {"removed": 1, "added": 0, "changed": 0,
                         "untouched": 0, "skipped": 0}
        engine._seq.unsubscribe.assert_called_once_with(32, 0, 33, 0)
        assert Connection(32, 0, 33, 0) not in engine._connections

    def test_added_and_removed(self):
        engine = _make_engine()
        engine._connections.add(Connection(32, 0, 33, 0))  # to remove
        patcher, _ = _capture_alsa_events()
        with patcher:
            stats = engine.apply_edge_diff([
                _edge("dev-C", 0, "dev-D", 0),
            ])
        assert stats["removed"] == 1
        assert stats["added"] == 1
        assert stats["untouched"] == 0
        engine._seq.subscribe.assert_called_once_with(34, 0, 35, 0)
        engine._seq.unsubscribe.assert_called_once_with(32, 0, 33, 0)


class TestRemovedFlushesNotes:
    def test_release_edge_notes_called_with_active_notes(self):
        engine = _make_engine()
        conn = Connection(32, 0, 33, 0)
        engine._connections.add(conn)
        engine._active_notes[conn] = {(0, 60): 1, (5, 64): 2}

        patcher, captured = _capture_alsa_events()
        with patcher:
            engine.apply_edge_diff([])

        # CC 123 (All Notes Off) should be emitted on each channel that had
        # tracked notes — channel 0 and channel 5.
        cc_events = [e for e in captured if e[2] == 123]
        cc_channels = {e[1] for e in cc_events}
        assert cc_channels == {0, 5}
        # And all of them target the destination of the removed edge.
        assert all((e[3], e[4]) == (33, 0) for e in cc_events)

    def test_no_cc_when_no_active_notes(self):
        engine = _make_engine()
        engine._connections.add(Connection(32, 0, 33, 0))
        # No entries in _active_notes.

        patcher, captured = _capture_alsa_events()
        with patcher:
            engine.apply_edge_diff([])

        # No tracked notes -> no CC 123 emitted.
        assert [e for e in captured if e[2] == 123] == []


class TestChangedEdges:
    def test_changed_mappings_in_place(self):
        engine = _make_engine()
        conn = Connection(32, 0, 33, 0)
        engine._connections.add(conn)
        # Mark this edge as userspace with one mapping; target is the same
        # endpoints with a different mapping list.
        engine._filter_engine.has_filter.return_value = True
        old_filter = MagicMock()
        old_filter.to_dict.return_value = {"channel_mask": 0xFFFF,
                                           "msg_types": ["cc", "note"]}
        engine._filter_engine.get_filter.return_value = old_filter
        old_mapping = MagicMock()
        old_mapping.to_dict.return_value = {"type": "channel_map",
                                            "src_channel": 0,
                                            "dst_channel": 1}
        engine._filter_engine.get_mappings.return_value = [old_mapping]

        new_mapping = {"type": "channel_map", "src_channel": 0,
                       "dst_channel": 5}
        target = [_edge(filter_dict={"channel_mask": 0xFFFF,
                                     "msg_types": ["cc", "note"]},
                        mappings=[new_mapping])]

        stats = engine.apply_edge_diff(target)
        assert stats["changed"] == 1
        # In-place: no remove_filter, no resubscribe.
        engine._filter_engine.remove_filter.assert_not_called()
        engine._seq.subscribe.assert_not_called()
        engine._seq.unsubscribe.assert_not_called()
        # update_filter + set_mappings both called on the same conn_id.
        engine._filter_engine.update_filter.assert_called_once()
        engine._filter_engine.set_mappings.assert_called_once()

    def test_mode_switch_direct_to_userspace_uses_full_swap(self):
        engine = _make_engine()
        conn = Connection(32, 0, 33, 0)
        engine._connections.add(conn)  # current is direct
        engine._filter_engine.has_filter.return_value = False

        target = [_edge(mappings=[{"type": "channel_map",
                                   "src_channel": 0,
                                   "dst_channel": 5}])]

        patcher, _ = _capture_alsa_events()
        with patcher:
            stats = engine.apply_edge_diff(target)

        assert stats["changed"] == 1
        # Old direct subscription torn down; new userspace edge installed.
        engine._seq.unsubscribe.assert_called_once_with(32, 0, 33, 0)
        engine._filter_engine.add_filter.assert_called_once()
        engine._filter_engine.add_mapping.assert_called_once()


class TestUnresolvedTargets:
    def test_skipped_when_stable_id_does_not_resolve(self):
        engine = _make_engine()
        target = [_edge(src_sid="ghost-device", dst_sid="dev-B")]
        stats = engine.apply_edge_diff(target)
        assert stats == {"removed": 0, "added": 0, "changed": 0,
                         "untouched": 0, "skipped": 1}
        engine._seq.subscribe.assert_not_called()
