"""Tracker MVP — data model, plugin registration, playback engine,
and auto-learn recording. The frontend's covered by manual /
Playwright checks; this file pins the Python-side behaviours so the
ALSA-scheduling refactor can land later without breaking semantics."""

import pytest

from raspimidihub.plugin_api import TrackerGrid, schema_param_keys
from raspimidihub.tracker_base import (
    CC_HOLD,
    CC_NONE,
    NOTE_END,
    NOTE_HOLD,
    NOTE_OFF,
    TrackerBase,
    empty_page,
    empty_row,
    empty_voice,
    midi_to_note_str,
    note_str_to_midi,
)


def test_empty_voice_uses_hold_sentinels():
    v = empty_voice()
    assert v == {"note": NOTE_HOLD, "vel": CC_HOLD, "cc_num": CC_NONE, "cc_val": CC_HOLD}


def test_empty_row_has_track_count_voices():
    row = empty_row(8)
    assert len(row["voices"]) == 8
    assert all(v == empty_voice() for v in row["voices"])


def test_empty_page_has_max_rows_rows():
    page = empty_page(track_count=8, max_rows=16)
    assert len(page["rows"]) == 16
    assert all(len(r["voices"]) == 8 for r in page["rows"])


def test_sentinels_are_three_chars_or_two():
    # 3-char strict for the Note column …
    assert len(NOTE_HOLD) == 3
    assert len(NOTE_OFF) == 3
    assert len(NOTE_END) == 3
    # … 2-char for the velocity / CC-Val columns; "." is the special
    # CC# sentinel and renders right-padded in the cell.
    assert len(CC_HOLD) == 2
    assert CC_NONE == "."


class _DemoTracker(TrackerBase):
    NAME = "Demo Tracker"
    DESCRIPTION = "test fixture"
    TRACK_COUNT = 4


def test_subclass_surface_kind_is_play():
    assert _DemoTracker.SURFACE_KIND == "play"


def test_subclass_params_carry_tracker_grid():
    grids = [p for p in _DemoTracker.params if isinstance(p, TrackerGrid)]
    assert len(grids) == 1
    g = grids[0]
    assert g.track_count == 4
    assert g.pages_param == "pages"
    assert g.current_page_param == "current_page"
    assert g.cursor_row_param == "cursor_row"
    assert g.cursor_track_param == "cursor_track"
    assert g.cursor_half_param == "cursor_half"
    assert g.octave_param == "octave"
    assert g.rate_param == "rate"
    assert g.playhead_param == "playhead"


def test_top_level_param_shape():
    # The TrackerGrid is the play-surface entry (play_only). The
    # config-only entries below it are the per-track channel group +
    # the send-clock toggle. Rate is reached through TrackerGrid's
    # rate_param pointer, not as a standalone Radio.
    from raspimidihub.plugin_api import Group as _Group
    params = _DemoTracker.params
    assert isinstance(params[0], TrackerGrid)
    titles = [p.title for p in params if isinstance(p, _Group)]
    assert "Track Channels" in titles
    # No standalone Radio for `rate` (still reached via rate_param).
    from raspimidihub.plugin_api import Radio as _Radio
    assert not any(isinstance(p, _Radio) for p in params)


def test_schema_param_keys_collects_tracker_aux():
    keys = schema_param_keys(_DemoTracker.params)
    for name in ("pages", "current_page", "cursor_row", "cursor_track",
                 "cursor_half", "octave", "rate", "playhead",
                 "cmd_play", "cmd_stop", "send_clock", "note_preview"):
        assert name in keys, f"missing aux key {name!r}"
    # Per-track channels (one per voice). _DemoTracker has TRACK_COUNT=4.
    for i in range(4):
        assert f"track_ch_{i}" in keys
    # Single global `channel` etc were removed once tracks went per-channel.
    for removed in ("channel", "sync_mode", "bpm", "show_tracks"):
        assert removed not in keys, f"stale key {removed!r} still present"


def test_on_start_seeds_one_blank_page():
    t = _DemoTracker()
    t.on_start()
    pages = t._param_values["pages"]
    assert len(pages) == 1
    assert pages[0] == empty_page(4, 16)
    assert t._param_values["current_page"] == 0
    assert t._param_values["cursor_row"] == 0
    assert t._param_values["cursor_track"] == 0
    assert t._param_values["octave"] == 3
    assert t._param_values["rate"] == "1/16"
    assert t._param_values["cursor_half"] == "note"
    assert t._param_values["playhead"] == {"page": 0, "row": 0, "playing": False}
    assert t._param_values["cmd_play"] is False
    assert t._param_values["cmd_stop"] is False
    assert t._param_values["send_clock"] is False
    assert t._param_values["note_preview"] == -1
    # All eight track channels default to MIDI ch 1.
    for i in range(4):
        assert t._param_values[f"track_ch_{i}"] == 1
    assert t.transient_params == {
        "cursor_row", "cursor_track", "cursor_half", "octave",
        "playhead", "cmd_play", "cmd_stop", "note_preview",
        "queued_pattern", "pattern_status", "cmd_pattern_select",
    }


def test_on_start_preserves_existing_state():
    t = _DemoTracker()
    custom_page = {"rows": [{"voices": [{"note": "C-4", "vel": 90,
                                          "cc_num": 1, "cc_val": 64}]}]}
    t._param_values["pages"] = [custom_page]
    t._param_values["octave"] = 5
    t.on_start()
    assert t._param_values["pages"] == [custom_page]
    assert t._param_values["octave"] == 5


def test_panic_calls_send_note_off_for_every_pitch():
    t = _DemoTracker()
    t.on_start()
    sent: list[tuple[int, int]] = []
    t._send_note_off = lambda ch, note: sent.append((ch, note))
    t.panic()
    assert len(sent) == 128
    # Output is always channel 1 (0-based 0).
    assert all(ch == 0 for ch, _ in sent)
    assert sorted(n for _, n in sent) == list(range(128))


@pytest.mark.parametrize("rate", ["1/4", "1/8", "1/16", "1/16T"])
def test_clock_divisions_include_standard_rates(rate):
    assert rate in TrackerBase.clock_divisions


# ---------------------------------------------------------------------------
# Note-string ↔ MIDI conversion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("midi,expected", [
    (12, "C-0"),
    (13, "C#0"),
    (60, "C-4"),         # Middle C in our 0-based-octave convention
    (61, "C#4"),
    (119, "B-8"),        # B-9 = MIDI 131 → unreachable
    (127, "G-9"),        # top of MIDI range, last representable note
])
def test_midi_to_note_str_in_range(midi, expected):
    assert midi_to_note_str(midi) == expected


@pytest.mark.parametrize("midi", [-1, 0, 11, 128, 200])
def test_midi_to_note_str_out_of_range(midi):
    assert midi_to_note_str(midi) is None


def test_note_str_to_midi_roundtrip_full_range():
    for midi in range(12, 128):
        s = midi_to_note_str(midi)
        assert s is not None
        assert note_str_to_midi(s) == midi


@pytest.mark.parametrize("s", ["---", "Off", "End", "", "X-3", "C#A", "C+3"])
def test_note_str_to_midi_rejects_sentinels_and_garbage(s):
    assert note_str_to_midi(s) is None


# ---------------------------------------------------------------------------
# Playback engine
# ---------------------------------------------------------------------------

class _Sender:
    """Captures every send_* call as a tagged tuple in the order
    fired so tests can assert sequence + payload."""

    def __init__(self):
        self.events: list[tuple] = []

    def attach(self, plugin):
        plugin._send_note_on = lambda ch, note, vel: self.events.append(("on", ch, note, vel))
        plugin._send_note_off = lambda ch, note: self.events.append(("off", ch, note))
        plugin._send_cc = lambda ch, cc, val: self.events.append(("cc", ch, cc, val))


def _started(track_count=4):
    """Tracker subclass instance with the engine wired up."""

    class _T(TrackerBase):
        NAME = "T"
        TRACK_COUNT = track_count

    t = _T()
    t.on_start()
    return t


def test_on_tick_ignores_non_matching_division():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    t.on_tick("1/4")
    assert s.events == []


def test_on_tick_does_nothing_without_transport_start():
    # Strictly transport-driven: clock alone shouldn't move the
    # playhead. The user has to send MIDI Start first.
    t = _started()
    s = _Sender()
    s.attach(t)
    pages = [{"rows": [
        {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"}] +
                   [empty_voice() for _ in range(3)]},
    ]}]
    t._param_values["pages"] = pages
    t._param_values["rate"] = "1/16"
    t.on_tick("1/16")
    assert s.events == []
    assert t._playing is False
    # Start fires row 0 immediately (no 1/16 lag).
    t.on_transport_start()
    assert ("on", 0, 60, 90) in s.events


def test_advance_step_fires_note_on_and_tracks_sounding():
    t = _started()
    s = _Sender()
    s.attach(t)
    page = {"rows": [
        {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
        {"voices": [{"note": "D-4", "vel": 100, "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
    ]}
    t._param_values["pages"] = [page]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()    # fires row 0 (C-4) immediately
    t.on_tick("1/16")         # fires row 1 (D-4): off C-4, on D-4
    assert ("on", 0, 60, 90) in s.events
    assert ("off", 0, 60) in s.events
    assert ("on", 0, 62, 100) in s.events
    assert s.events.index(("off", 0, 60)) < s.events.index(("on", 0, 62, 100))
    assert t._sounding[0] == (62, 0)    # (midi, channel) — default ch 1 = 0-based 0


def test_off_cell_silences_voice():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [
        {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
        {"voices": [{"note": "Off", "vel": "--", "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
    ]}]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()    # row 0 fires C-4
    t.on_tick("1/16")         # row 1 fires Off → cuts C-4
    assert ("off", 0, 60) in s.events
    assert t._sounding[0] is None


def test_hold_sentinel_does_not_retrigger():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [
        {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
        {"voices": [{"note": "---", "vel": "--", "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
    ]}]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()  # row 0 fires C-4
    s.events.clear()        # discard the row-0 events
    t.on_tick("1/16")       # row 1 is `---` → no MIDI
    assert s.events == []
    assert t._sounding[0] == (60, 0)


def test_cc_fires_independent_of_note():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [
        {"voices": [{"note": "---", "vel": "--", "cc_num": 1, "cc_val": 64},
                    empty_voice(), empty_voice(), empty_voice()]},
    ]}]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()    # row 0 fires immediately — CC and all
    assert ("cc", 0, 1, 64) in s.events


def test_cc_collision_rightmost_voice_wins_same_channel():
    # Same CC# AND same channel on multiple voices → only the
    # rightmost (highest track index) value is sent.
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [
        {"voices": [
            {"note": "---", "vel": "--", "cc_num": 7, "cc_val": 50},
            {"note": "---", "vel": "--", "cc_num": 7, "cc_val": 80},
            {"note": "---", "vel": "--", "cc_num": 11, "cc_val": 99},
            {"note": "---", "vel": "--", "cc_num": 7, "cc_val": 100},
        ]},
    ]}]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    cc_events = [e for e in s.events if e[0] == "cc"]
    assert ("cc", 0, 7, 100) in cc_events
    assert ("cc", 0, 11, 99) in cc_events
    assert not any(e == ("cc", 0, 7, 50) or e == ("cc", 0, 7, 80)
                   for e in cc_events)
    cc7 = [e for e in cc_events if e[2] == 7]
    assert len(cc7) == 1


def test_cc_same_number_different_channels_both_fire():
    # T1 sets CC 7 = 50 on channel 1, T3 sets CC 7 = 80 on channel 5.
    # Different channels → independent events; both fire.
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["track_ch_0"] = 1     # T1 = ch 1 (0-based 0)
    t._param_values["track_ch_2"] = 5     # T3 = ch 5 (0-based 4)
    t._param_values["pages"] = [{"rows": [
        {"voices": [
            {"note": "---", "vel": "--", "cc_num": 7, "cc_val": 50},
            empty_voice(),
            {"note": "---", "vel": "--", "cc_num": 7, "cc_val": 80},
            empty_voice(),
        ]},
    ]}]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    cc_events = [e for e in s.events if e[0] == "cc"]
    # Both fire on their respective channels.
    assert ("cc", 0, 7, 50) in cc_events
    assert ("cc", 4, 7, 80) in cc_events


def test_different_cc_numbers_coexist_on_same_step():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [
        {"voices": [
            {"note": "---", "vel": "--", "cc_num": 1,  "cc_val": 10},
            {"note": "---", "vel": "--", "cc_num": 7,  "cc_val": 20},
            {"note": "---", "vel": "--", "cc_num": 11, "cc_val": 30},
            {"note": "---", "vel": "--", "cc_num": 74, "cc_val": 40},
        ]},
    ]}]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    cc_events = [e for e in s.events if e[0] == "cc"]
    assert ("cc", 0, 1, 10) in cc_events
    assert ("cc", 0, 7, 20) in cc_events
    assert ("cc", 0, 11, 30) in cc_events
    assert ("cc", 0, 74, 40) in cc_events


def test_end_marker_jumps_to_next_page_same_tick():
    # End on page 0 row 0 means: skip this row entirely and play
    # page 1 row 0 NOW (same tick). The End row never plays.
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [
        {"rows": [
            {"voices": [{"note": "End", "vel": "--", "cc_num": ".", "cc_val": "--"},
                        empty_voice(), empty_voice(), empty_voice()]},
        ] + [empty_row(4) for _ in range(15)]},
        {"rows": [
            {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                        empty_voice(), empty_voice(), empty_voice()]},
        ] + [empty_row(4) for _ in range(15)]},
    ]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    # The very first tick (transport_start fires row 0 immediately)
    # should already have fired page 1 row 0 — no gap.
    assert ("on", 0, 60, 90) in s.events
    assert t._play_page == 1
    assert t._play_row == 1


def test_end_row_does_not_play_other_voices():
    # The End row is structural — even if voice 2..N have notes set,
    # they don't play. End-rows are silent.
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [
        {"rows": [
            {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                        empty_voice(), empty_voice(), empty_voice()]},
            {"voices": [{"note": "End", "vel": "--", "cc_num": ".", "cc_val": "--"},
                        # G-4 on voice 2 of the End row — must NOT play.
                        {"note": "G-4", "vel": 80, "cc_num": ".", "cc_val": "--"},
                        empty_voice(), empty_voice()]},
        ] + [empty_row(4) for _ in range(14)]},
        {"rows": [
            {"voices": [{"note": "D-4", "vel": 100, "cc_num": ".", "cc_val": "--"},
                        empty_voice(), empty_voice(), empty_voice()]},
        ] + [empty_row(4) for _ in range(15)]},
    ]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()  # fires C-4 at page 0 row 0
    t.on_tick("1/16")       # row 1 = End → skip + fire D-4 same tick
    assert ("on", 0, 67, 80) not in s.events    # G-4 was on the End row
    assert ("on", 0, 62, 100) in s.events       # D-4 fired


def test_end_on_any_voice_triggers_page_skip():
    # End placed on T3 (voice index 2) — not just T1 — should still
    # trigger the page jump on its row.
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [
        {"rows": [
            {"voices": [empty_voice(), empty_voice(),
                        {"note": "End", "vel": "--", "cc_num": ".", "cc_val": "--"},
                        empty_voice()]},
        ] + [empty_row(4) for _ in range(15)]},
        {"rows": [
            {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                        empty_voice(), empty_voice(), empty_voice()]},
        ] + [empty_row(4) for _ in range(15)]},
    ]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    # End at page 0 row 0 on T3 → skip to page 1 row 0, fire C-4.
    assert ("on", 0, 60, 90) in s.events
    assert t._play_page == 1


def test_on_param_change_ignored_before_initialization():
    # Simulates restore_instances replaying a saved cmd_play=True
    # before on_start has run on the plugin thread. The trigger
    # must NOT fire on_transport_start — otherwise every restart
    # with a mid-play save would re-start the engine.
    class _T(TrackerBase):
        NAME = "T"
        TRACK_COUNT = 4
    t = _T()
    # No on_start() yet → _initialized is missing / falsy.
    s = _Sender()
    s.attach(t)
    t.on_param_change("cmd_play", True)
    assert s.events == []                  # nothing fired
    # After on_start completes, the same call works.
    t.on_start()
    t._param_values["pages"] = [{"rows": [empty_row(4) for _ in range(16)]}]
    s.events.clear()
    t.on_param_change("cmd_play", True)
    assert t._playing is True


def test_all_pages_end_stops_playback():
    t = _started()
    end_row = [{"note": "End", "vel": "--", "cc_num": ".", "cc_val": "--"},
               empty_voice(), empty_voice(), empty_voice()]
    t._param_values["pages"] = [
        {"rows": [{"voices": end_row}] + [empty_row(4) for _ in range(15)]}
        for _ in range(3)
    ]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    # Cycled every page without finding a fireable row → stop.
    assert t._playing is False
    assert t._param_values["playhead"]["playing"] is False


def test_last_page_loops_back_to_zero():
    t = _started()
    s = _Sender()
    s.attach(t)
    page = {"rows": [empty_row(4) for _ in range(16)]}
    t._param_values["pages"] = [page]   # single page → row F should wrap
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    t._play_row = 15
    t.on_tick("1/16")
    assert t._play_page == 0
    assert t._play_row == 0


def test_playhead_broadcasts_just_played_position():
    # Visual ▶ should land on the row whose notes are sounding right
    # now — i.e. the row that just fired, not the next-to-fire one.
    t = _started()
    s = _Sender()
    s.attach(t)
    page = {"rows": [empty_row(4) for _ in range(16)]}
    t._param_values["pages"] = [page]
    t._param_values["rate"] = "1/16"
    t.on_transport_start()    # fires row 0 immediately
    assert t._param_values["playhead"] == {"page": 0, "row": 0, "playing": True}
    t.on_tick("1/16")         # fires row 1
    assert t._param_values["playhead"] == {"page": 0, "row": 1, "playing": True}
    t.on_tick("1/16")         # fires row 2
    assert t._param_values["playhead"] == {"page": 0, "row": 2, "playing": True}


def test_playhead_clears_on_transport_stop():
    t = _started()
    t._param_values["pages"] = [{"rows": [empty_row(4) for _ in range(16)]}]
    t.on_transport_start()
    assert t._param_values["playhead"]["playing"] is True
    t.on_transport_stop()
    assert t._param_values["playhead"]["playing"] is False


def test_transport_stop_silences_sounding():
    t = _started()
    s = _Sender()
    s.attach(t)
    # _sounding now carries (midi_note, channel) tuples — different
    # tracks may be on different channels, and the note-off must go
    # back to the channel the note was started on.
    t._sounding[0] = (60, 0)
    t._sounding[2] = (64, 5)
    t.on_transport_stop()
    assert ("off", 0, 60) in s.events
    assert ("off", 5, 64) in s.events
    assert all(n is None for n in t._sounding)
    assert t._playing is False


# ---------------------------------------------------------------------------
# Recording / auto-learn
# ---------------------------------------------------------------------------

def test_on_note_on_passes_through_and_records():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["cursor_row"] = 4
    t._param_values["cursor_track"] = 1
    t.on_note_on(channel=2, note=60, velocity=100)
    assert ("on", 0, 60, 100) in s.events       # pass-through to ch 1
    cell = t._param_values["pages"][0]["rows"][4]["voices"][1]
    assert cell["note"] == "C-4"
    assert cell["vel"] == 100


def test_single_note_on_advances_cursor_one_row():
    t = _started()
    t._param_values["cursor_row"] = 5
    t._param_values["cursor_track"] = 0
    t.on_note_on(2, 60, 100)
    assert t._param_values["pages"][0]["rows"][5]["voices"][0]["note"] == "C-4"
    assert t._param_values["cursor_row"] == 6


def test_cursor_wraps_at_row_F_to_next_page_on_recording():
    t = _started()
    t._param_values["pages"] = [
        {"rows": [empty_row(4) for _ in range(16)]},
        {"rows": [empty_row(4) for _ in range(16)]},
    ]
    t._param_values["current_page"] = 0
    t._param_values["cursor_row"] = 15      # row F
    t._param_values["cursor_track"] = 0
    t.on_note_on(2, 60, 100)
    # The note still wrote to row F of page 0 (the captured chord row).
    assert t._param_values["pages"][0]["rows"][15]["voices"][0]["note"] == "C-4"
    # Cursor advanced past F → next page row 0.
    assert t._param_values["cursor_row"] == 0
    assert t._param_values["current_page"] == 1


def test_cursor_wraps_from_last_page_back_to_zero_on_recording():
    t = _started()
    t._param_values["pages"] = [{"rows": [empty_row(4) for _ in range(16)]}]
    t._param_values["current_page"] = 0
    t._param_values["cursor_row"] = 15
    t._param_values["cursor_track"] = 0
    t.on_note_on(2, 60, 100)
    # Single page → row F wraps back to row 0 of the same (only) page.
    assert t._param_values["cursor_row"] == 0
    assert t._param_values["current_page"] == 0


def test_chord_spreads_across_consecutive_tracks():
    t = _started()
    t._param_values["cursor_row"] = 0
    t._param_values["cursor_track"] = 1
    # Three notes within the chord window → tracks 1, 2, 3 of the
    # captured chord row (row 0). Cursor itself advances one step at
    # chord-start so the next chord lands on row 1.
    t.on_note_on(2, 60, 100)
    t.on_note_on(2, 64, 100)
    t.on_note_on(2, 67, 100)
    voices = t._param_values["pages"][0]["rows"][0]["voices"]
    assert voices[1]["note"] == "C-4"
    assert voices[2]["note"] == "E-4"
    assert voices[3]["note"] == "G-4"
    assert t._param_values["cursor_row"] == 1


def test_chord_overflow_drops_silently():
    t = _started(track_count=4)
    t._param_values["cursor_row"] = 0
    t._param_values["cursor_track"] = 3   # only T4 left
    t.on_note_on(2, 60, 100)              # → T4
    t.on_note_on(2, 64, 100)              # off the end, dropped
    voices = t._param_values["pages"][0]["rows"][0]["voices"]
    assert voices[3]["note"] == "C-4"
    # The dropped note should not appear anywhere.
    assert all(v["note"] != "E-4" for v in voices)


def test_on_cc_passes_through_and_records():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["cursor_row"] = 2
    t._param_values["cursor_track"] = 0
    t.on_cc(channel=2, cc=7, value=100)
    assert ("cc", 0, 7, 100) in s.events
    cell = t._param_values["pages"][0]["rows"][2]["voices"][0]
    assert cell["cc_num"] == 7
    assert cell["cc_val"] == 100
    # CCs don't auto-advance — only notes do. (Twiddling a knob
    # would race the cursor down otherwise.)
    assert t._param_values["cursor_row"] == 2


def test_on_note_off_passes_through_only():
    t = _started()
    s = _Sender()
    s.attach(t)
    t.on_note_off(channel=2, note=60)
    assert s.events == [("off", 0, 60)]
    # No row was touched — the cells are still default sentinels.
    cell = t._param_values["pages"][0]["rows"][0]["voices"][0]
    assert cell["note"] == NOTE_HOLD


def test_panic_silences_all_voices_and_stops_playback():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._sounding[0] = (60, 0)
    t._playing = True
    t.panic()
    assert ("off", 0, 60) in s.events
    assert t._playing is False
    assert all(n is None for n in t._sounding)


# ---------------------------------------------------------------------------
# Per-track channel routing
# ---------------------------------------------------------------------------

def test_each_voice_fires_on_its_own_channel():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["track_ch_0"] = 3      # T1 → ch 3 (0-based 2)
    t._param_values["track_ch_1"] = 7      # T2 → ch 7 (0-based 6)
    t._param_values["pages"] = [{"rows": [
        {"voices": [
            {"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
            {"note": "E-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
            empty_voice(), empty_voice(),
        ]},
    ]}]
    t.on_transport_start()
    note_ons = [e for e in s.events if e[0] == "on"]
    assert ("on", 2, 60, 90) in note_ons   # C-4 on ch 3
    assert ("on", 6, 64, 90) in note_ons   # E-4 on ch 7
    assert t._sounding[0] == (60, 2)
    assert t._sounding[1] == (64, 6)


def test_note_off_uses_original_channel_after_track_remap():
    # User starts a note on ch 3, then changes the track's channel
    # to ch 5 mid-pattern, then the next non-`---` cell fires.
    # The note-off must go to ch 3 (where the note was started),
    # otherwise the synth on ch 3 keeps ringing.
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["track_ch_0"] = 3
    t._param_values["pages"] = [{"rows": [
        {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
        {"voices": [{"note": "D-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
    ]}]
    t.on_transport_start()              # fires C-4 on ch 3
    t._param_values["track_ch_0"] = 5   # user retargets the track
    t.on_tick("1/16")                   # fires D-4: off C-4 on ch 3, on D-4 on ch 5
    assert ("on", 2, 60, 90) in s.events
    assert ("off", 2, 60) in s.events    # off on ch 3 (0-based 2)
    assert ("on", 4, 62, 90) in s.events  # on on ch 5 (0-based 4)


# ---------------------------------------------------------------------------
# Manual transport — cmd_play / cmd_stop signals
# ---------------------------------------------------------------------------

def test_cmd_play_starts_transport_and_resets_signal():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [
        {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
    ] + [empty_row(4) for _ in range(15)]}]
    # Frontend writes cmd_play=True; on_param_change fires
    # on_transport_start (which fires row 0 immediately) and resets
    # the signal back to False.
    t.on_param_change("cmd_play", True)
    assert t._playing is True
    assert ("on", 0, 60, 90) in s.events
    assert t._param_values["cmd_play"] is False


def test_cmd_stop_halts_transport_and_resets_signal():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._sounding[0] = (60, 0)
    t._playing = True
    t.on_param_change("cmd_stop", True)
    assert t._playing is False
    assert ("off", 0, 60) in s.events
    assert t._param_values["cmd_stop"] is False


def test_live_record_note_lands_on_playhead_row_when_playing():
    # While the tracker is playing, a note-on records into the row
    # whose events just fired (the row currently sounding), NOT
    # whatever row the edit cursor sits on. The cursor doesn't
    # auto-advance — playback owns the position.
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [empty_row(4) for _ in range(16)]}]
    t._param_values["cursor_row"] = 7         # cursor far from the playhead
    t._param_values["cursor_track"] = 1
    t._param_values["rate"] = "1/16"
    t.on_transport_start()                     # fires row 0; record_row = 0
    t.on_tick("1/16")                          # fires row 1; record_row = 1
    t.on_note_on(2, 60, 100)
    voices = t._param_values["pages"][0]["rows"][1]["voices"]
    assert voices[1]["note"] == "C-4"          # landed on row 1, T2
    assert voices[1]["vel"] == 100
    # Cursor was NOT advanced — playback owns row position.
    assert t._param_values["cursor_row"] == 7
    # Row 7 (cursor's row) stays untouched.
    cursor_row_voices = t._param_values["pages"][0]["rows"][7]["voices"]
    assert cursor_row_voices[1]["note"] == NOTE_HOLD


def test_live_record_cc_lands_on_playhead_row_when_playing():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [empty_row(4) for _ in range(16)]}]
    t._param_values["cursor_row"] = 12
    t._param_values["cursor_track"] = 0
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    t.on_tick("1/16")
    t.on_tick("1/16")                          # record_row = 2
    t.on_cc(2, 7, 100)
    cell_at_play = t._param_values["pages"][0]["rows"][2]["voices"][0]
    assert cell_at_play["cc_num"] == 7
    assert cell_at_play["cc_val"] == 100


def test_step_record_when_stopped_still_uses_cursor_and_advances():
    # The original behaviour stays for the not-playing case.
    t = _started()
    t._param_values["cursor_row"] = 5
    t._param_values["cursor_track"] = 0
    t.on_note_on(2, 60, 100)
    assert t._param_values["pages"][0]["rows"][5]["voices"][0]["note"] == "C-4"
    assert t._param_values["cursor_row"] == 6


def test_note_preview_fires_note_on_and_resets_signal():
    # Frontend writes note_preview=<midi> when a wheel/keyboard tick
    # picks a real pitch. Plugin fires note-on on the focused track's
    # channel and schedules a release; the signal resets to -1.
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["track_ch_2"] = 5    # T3 → ch 5 (0-based 4)
    t._param_values["cursor_track"] = 2
    t.on_param_change("note_preview", 60)
    assert ("on", 4, 60, 90) in s.events
    assert t._param_values["note_preview"] == -1
    # Cancel the release timer so it doesn't tick during teardown.
    if t._preview_timer is not None:
        t._preview_timer.cancel()


# ---------------------------------------------------------------------------
# Clock + transport forwarding (send_clock toggle)
# ---------------------------------------------------------------------------

class _ForwardSender(_Sender):
    """Adds the clock + transport sends that _Sender doesn't capture."""

    def attach(self, plugin):
        super().attach(plugin)
        plugin._send_clock = lambda: self.events.append(("clk",))
        plugin._send_start = lambda: self.events.append(("start",))
        plugin._send_stop = lambda: self.events.append(("stop",))
        plugin._send_continue = lambda: self.events.append(("cont",))


def test_send_clock_off_swallows_clock_messages():
    t = _started()
    s = _ForwardSender()
    s.attach(t)
    t._param_values["send_clock"] = False
    t.on_clock()
    t.on_clock_start()
    t.on_clock_stop()
    t.on_clock_continue()
    # No clock-family events forwarded — send_clock is off.
    assert not any(e[0] in ("clk", "start", "stop", "cont") for e in s.events)


def test_send_clock_on_forwards_clock_and_transport():
    t = _started()
    s = _ForwardSender()
    s.attach(t)
    t._param_values["send_clock"] = True
    t.on_clock()
    t.on_clock_start()
    t.on_clock_continue()
    t.on_clock_stop()
    forwarded = [e[0] for e in s.events if e[0] in ("clk", "start", "stop", "cont")]
    assert forwarded == ["clk", "start", "cont", "stop"]


# =========================================================================
# Pattern bank — 8 stored grids per Tracker, switch on tap (queued at
# the next page-0 row-0 boundary while playing) or Shift+Tap (immediate
# with a play-row preserving fallback).
# =========================================================================


def _filled_voice(note="C-4", vel=90):
    return {"note": note, "vel": vel, "cc_num": ".", "cc_val": "--"}


def _filled_page(track_count=4):
    rows = []
    for i in range(16):
        rows.append({"voices": [_filled_voice() if i == 0 else empty_voice()
                                for _ in range(track_count)]})
    return {"rows": rows}


def test_on_start_seeds_eight_empty_patterns():
    t = _started()
    pats = t._param_values["patterns"]
    assert len(pats) == 8
    # Slot 0 is empty (matches a single fresh page). Slots 1..7 same.
    for p in pats:
        assert t._is_empty_pattern(p)
    assert t._param_values["selected_pattern"] == 0
    assert t._param_values["queued_pattern"] == -1
    assert t._param_values["pattern_status"] == [False] * 8


def test_on_start_migrates_legacy_pages_into_pattern_0():
    """A config saved before patterns existed has only `pages`.
    Migration lifts that into slot 0 and seeds slots 1..7 empty."""
    class _T(TrackerBase):
        NAME = "T"
        TRACK_COUNT = 4

    t = _T()
    # Pre-set legacy state as if config-restore had just run.
    legacy = [_filled_page(track_count=4)]
    t._param_values["pages"] = legacy
    t.on_start()
    # patterns[0] is the legacy grid; slots 1..7 are empty.
    assert t._param_values["patterns"][0] is legacy or \
        t._param_values["patterns"][0] == legacy
    for i in range(1, 8):
        assert t._is_empty_pattern(t._param_values["patterns"][i])
    # Selection lands on slot 0 (the migrated content).
    assert t._param_values["selected_pattern"] == 0
    # Pattern status reflects: slot 0 has content, rest are empty.
    assert t._param_values["pattern_status"] == [True] + [False] * 7


def test_pages_edit_mirrors_into_selected_pattern():
    """Editing the live grid (set_param 'pages') must write through
    to patterns[selected_pattern] so the slot keeps its content."""
    t = _started()
    new_pages = [_filled_page(track_count=4)]
    t.on_param_change("pages", new_pages)
    assert t._param_values["patterns"][0] == new_pages
    # Status flips empty → non-empty for slot 0 only.
    assert t._param_values["pattern_status"][0] is True
    assert all(s is False for s in t._param_values["pattern_status"][1:])


def test_tap_while_stopped_switches_immediately_and_resets_cursor():
    t = _started()
    # Seed two distinct patterns to make the switch observable.
    t._param_values["patterns"][1] = [_filled_page(track_count=4)]
    t._refresh_pattern_status_slot(1)
    # User moved the cursor before tapping.
    t._param_values["current_page"] = 3
    t._param_values["cursor_row"] = 7
    t.on_param_change("cmd_pattern_select", {"pattern": 1, "mode": "tap"})
    assert t._param_values["selected_pattern"] == 1
    assert t._param_values["pages"] == t._param_values["patterns"][1]
    assert t._param_values["current_page"] == 0
    assert t._param_values["cursor_row"] == 0


def test_tap_while_playing_queues_until_next_boundary():
    t = _started()
    # Two patterns: A (selected, currently playing) has 2 pages so
    # the wrap is reachable in one row's worth of ticks. B is the
    # target.
    page_a0 = empty_page(t.TRACK_COUNT, t.MAX_ROWS_PER_PAGE)
    # Put a fireable note on page 1 row 0 so we exit the End-loop.
    page_a1 = empty_page(t.TRACK_COUNT, t.MAX_ROWS_PER_PAGE)
    page_a1["rows"][0]["voices"][0] = _filled_voice("D-4")
    t._param_values["patterns"][0] = [page_a0, page_a1]
    t._param_values["pages"] = t._param_values["patterns"][0]
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(0)
    t._refresh_pattern_status_slot(1)
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    # Queue pattern 1.
    t.on_param_change("cmd_pattern_select", {"pattern": 1, "mode": "tap"})
    assert t._param_values["queued_pattern"] == 1
    # Still selected 0 -- switch only fires on the next wrap.
    assert t._param_values["selected_pattern"] == 0
    # Drive ticks until the wrap consumes the queue. 2 pages × 16
    # rows = 32 steps; on_transport_start already fired row 0, so
    # 31 more ticks lands on the wrap.
    for _ in range(31):
        t.on_tick("1/16")
    # The wrap consumed the queue: selected swapped to 1, queue
    # cleared, pages mirrors the new pattern.
    assert t._param_values["selected_pattern"] == 1
    assert t._param_values["queued_pattern"] == -1
    assert t._param_values["pages"] == t._param_values["patterns"][1]


def test_tap_playing_slot_while_playing_cancels_queue():
    t = _started()
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    t.on_transport_start()
    # Queue something, then tap the currently-playing slot -> cancel.
    t.on_param_change("cmd_pattern_select", {"pattern": 1, "mode": "tap"})
    assert t._param_values["queued_pattern"] == 1
    t.on_param_change("cmd_pattern_select", {"pattern": 0, "mode": "tap"})
    assert t._param_values["queued_pattern"] == -1
    assert t._param_values["selected_pattern"] == 0


def test_shift_tap_while_playing_switches_immediately_same_page_row():
    t = _started()
    # Both patterns have ≥ 4 pages so the page index stays valid.
    multi_page = [empty_page(t.TRACK_COUNT, t.MAX_ROWS_PER_PAGE)
                  for _ in range(4)]
    t._param_values["patterns"][0] = multi_page
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)
                                       for _ in range(4)]
    t._param_values["pages"] = t._param_values["patterns"][0]
    t._refresh_pattern_status_slot(1)
    # Position the playhead mid-pattern.
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    t._play_page = 2
    t._play_row = 7
    t.on_param_change("cmd_pattern_select", {"pattern": 1, "mode": "shift"})
    # Immediate switch -- view followed, playhead preserved.
    assert t._param_values["selected_pattern"] == 1
    assert t._play_page == 2
    assert t._play_row == 7


def test_shift_tap_falls_back_to_page_0_when_target_shorter():
    t = _started()
    # A: 4 pages, B: 1 page. Playhead on page 2 row 7 of A.
    t._param_values["patterns"][0] = [
        empty_page(t.TRACK_COUNT, t.MAX_ROWS_PER_PAGE) for _ in range(4)
    ]
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._param_values["pages"] = t._param_values["patterns"][0]
    t._refresh_pattern_status_slot(1)
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    t._play_page = 2
    t._play_row = 7
    t.on_param_change("cmd_pattern_select", {"pattern": 1, "mode": "shift"})
    # Fallback: page 0, row preserved.
    assert t._param_values["selected_pattern"] == 1
    assert t._play_page == 0
    assert t._play_row == 7


def test_clone_copies_selected_pattern_into_target():
    t = _started()
    # Edit slot 0, then clone into slot 3.
    pages_a = [_filled_page(track_count=t.TRACK_COUNT)]
    t.on_param_change("pages", pages_a)
    t.on_param_change("cmd_pattern_select", {"pattern": 3, "mode": "clone"})
    assert t._param_values["patterns"][3] == pages_a
    # Slot 0 (source) still has content; slot 3 (dest) too.
    assert t._param_values["pattern_status"][0] is True
    assert t._param_values["pattern_status"][3] is True
    # Mutating one slot's content shouldn't bleed into the other
    # (deepcopy guarantee).
    t._param_values["patterns"][3][0]["rows"][1]["voices"][0]["note"] = "E-4"
    assert t._param_values["patterns"][0][0]["rows"][1]["voices"][0]["note"] \
        != "E-4"
    # Selection / view unchanged by clone.
    assert t._param_values["selected_pattern"] == 0


def test_clear_empties_target_pattern():
    t = _started()
    # Fill slots 0 and 2.
    t.on_param_change("pages", [_filled_page(track_count=t.TRACK_COUNT)])
    t.on_param_change("cmd_pattern_select", {"pattern": 2, "mode": "clone"})
    assert t._param_values["pattern_status"][2] is True
    t.on_param_change("cmd_pattern_select", {"pattern": 2, "mode": "clear"})
    assert t._is_empty_pattern(t._param_values["patterns"][2])
    assert t._param_values["pattern_status"][2] is False
    # Slot 0 untouched.
    assert t._param_values["pattern_status"][0] is True
