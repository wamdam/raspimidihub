"""Tracker MVP — data model, plugin registration, playback engine,
and auto-learn recording. The frontend's covered by manual /
Playwright checks; this file pins the Python-side behaviours so the
ALSA-scheduling refactor can land later without breaking semantics."""

import pytest
from tracker.tracker_base import (
    CC_HOLD,
    CC_NONE,
    NOTE_END,
    NOTE_HOLD,
    NOTE_OFF,
    TrackerBase,
    TrackerGrid,
    empty_page,
    empty_row,
    empty_voice,
    midi_to_note_str,
    note_str_to_midi,
)

from raspimidihub.plugin_api import schema_param_keys


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
                 "cmd_play", "cmd_stop", "send_clock", "send_transport",
                 "bpm", "note_preview", "auto_ch"):
        assert name in keys, f"missing aux key {name!r}"
    # Per-track channels (one per voice). _DemoTracker has TRACK_COUNT=4.
    for i in range(4):
        assert f"track_ch_{i}" in keys
    # Pre-split-toggle params that no longer exist.
    for removed in ("channel", "sync_mode", "show_tracks"):
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
        "playhead", "cmd_play", "cmd_play_page", "cmd_stop", "note_preview",
        "queued_pattern", "pattern_status", "cmd_pattern_select",
    }
    assert t._param_values["cmd_play_page"] is False


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


def _started(track_count=4, auto_ch=3):
    """Tracker subclass instance with the engine wired up.

    Default `auto_ch=3` matches the channel=2 (0-based MIDI ch 3)
    that the recording tests below use — keeps them on the
    historic cursor-relative recording path. Pass `auto_ch=0`
    (Off) to exercise the new channel-driven routing where notes
    land on whichever track is configured for the incoming
    channel.
    """

    class _T(TrackerBase):
        NAME = "T"
        TRACK_COUNT = track_count

    t = _T()
    t.on_start()
    t._param_values["auto_ch"] = auto_ch
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
    # After on_start completes, the same call works — but cmd_play
    # schedules a pre-roll timer, so we wait for it to fire.
    t.on_start()
    t._param_values["pages"] = [{"rows": [empty_row(4) for _ in range(16)]}]
    s.events.clear()
    t.on_param_change("cmd_play", True)
    if t._preroll_timer is not None:
        t._preroll_timer.join()
    assert t._playing is True


def test_all_pages_end_keep_playing_silently():
    """Every page with End on row 0 is a 'fully muted' pattern. Playback
    must keep ticking silently rather than stopping — otherwise a user
    can't add content live without re-pressing Play, and a queued
    pattern switch (which lives on _just_wrapped) couldn't fire."""
    t = _started()
    end_row = [{"note": "End", "vel": "--", "cc_num": ".", "cc_val": "--"},
               empty_voice(), empty_voice(), empty_voice()]
    t._param_values["pages"] = [
        {"rows": [{"voices": end_row}] + [empty_row(4) for _ in range(15)]}
        for _ in range(3)
    ]
    t._param_values["rate"] = "1/16"
    s = _Sender()
    s.attach(t)
    t.on_transport_start()
    assert t._playing is True
    assert t._param_values["playhead"]["playing"] is True
    assert s.events == []  # silent
    t.on_tick("1/16")
    assert t._playing is True
    assert s.events == []  # still silent
    # Now drop content into page 1 row 0; the next tick must fire it
    # without the user re-pressing Play.
    t._param_values["pages"][1]["rows"][0]["voices"][0] = {
        "note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--",
    }
    t.on_tick("1/16")
    assert ("on", 0, 60, 90) in s.events


def test_single_page_end_on_row_0_keeps_playing():
    """The minimal regression: one page, End on row 0, Play. Playback
    must stay alive (silent) instead of immediately stopping."""
    t = _started()
    end_row = [{"note": "End", "vel": "--", "cc_num": ".", "cc_val": "--"},
               empty_voice(), empty_voice(), empty_voice()]
    t._param_values["pages"] = [
        {"rows": [{"voices": end_row}] + [empty_row(4) for _ in range(15)]},
    ]
    t._param_values["rate"] = "1/16"
    s = _Sender()
    s.attach(t)
    t.on_transport_start()
    assert t._playing is True
    assert s.events == []
    # Tick a few more times — still alive, still silent.
    for _ in range(4):
        t.on_tick("1/16")
    assert t._playing is True
    assert s.events == []


def test_queued_pattern_switch_fires_from_silent_pattern():
    """A pattern that is fully muted (End on row 0) must still let a
    queued pattern switch fire on the wrap — otherwise a user who
    queues a switch while listening to a silent pattern would be stuck
    until they reload."""
    t = _started()
    end_row = [{"note": "End", "vel": "--", "cc_num": ".", "cc_val": "--"},
               empty_voice(), empty_voice(), empty_voice()]
    # Slot 0 is fully muted; slot 1 has a C-4 on row 0.
    t._param_values["patterns"] = [
        [{"rows": [{"voices": end_row}] + [empty_row(4) for _ in range(15)]}],
        [{"rows": [{"voices": [
            {"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
            empty_voice(), empty_voice(), empty_voice(),
        ]}] + [empty_row(4) for _ in range(15)]}],
    ] + [[{"rows": [empty_row(4) for _ in range(16)]}]
         for _ in range(t.PATTERN_COUNT - 2)]
    t._param_values["selected_pattern"] = 0
    t._param_values["pages"] = list(t._param_values["patterns"][0])
    t._param_values["rate"] = "1/16"
    s = _Sender()
    s.attach(t)
    t.on_transport_start()
    assert s.events == []
    # Queue slot 1 while playing the silent slot 0.
    t._set_queued_pattern(1)
    t.on_tick("1/16")
    # The all-End scan triggers _just_wrapped on every iteration, so the
    # switch fires this tick. Next tick must play slot 1's C-4.
    t.on_tick("1/16")
    assert ("on", 0, 60, 90) in s.events


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
# Channel-driven recording (Auto Ch. + direct routing)
# ---------------------------------------------------------------------------

def test_resolve_targets_auto_ch_off_drops_unmatched():
    t = _started(auto_ch=0)
    # Defaults: all 4 tracks on MIDI ch 1 (0-based 0). Incoming on
    # channel 2 (0-based ch 3) matches no track → empty list.
    targets, is_auto = t._resolve_targets(channel=2)
    assert targets == []
    assert is_auto is False


def test_resolve_targets_auto_ch_match_returns_cursor_spread():
    t = _started(auto_ch=3)
    t._param_values["cursor_track"] = 1
    # channel=2 is 0-based MIDI ch 3 → matches auto_ch=3.
    targets, is_auto = t._resolve_targets(channel=2)
    assert is_auto is True
    # Cursor-spread starts at cursor_track and runs to TRACK_COUNT-1.
    assert targets == [1, 2, 3]


def test_resolve_targets_direct_first_match_only():
    t = _started(auto_ch=0)
    t._param_values["track_ch_2"] = 5      # T3 → MIDI ch 5 (0-based 4)
    targets, is_auto = t._resolve_targets(channel=4)
    assert is_auto is False
    assert targets == [2]


def test_resolve_targets_direct_multi_match_in_T_order():
    t = _started(auto_ch=0)
    t._param_values["track_ch_0"] = 5
    t._param_values["track_ch_2"] = 5
    t._param_values["track_ch_3"] = 5
    targets, _ = t._resolve_targets(channel=4)
    # T1, T3, T4 (indices 0, 2, 3) — ascending, not the order
    # they were assigned in.
    assert targets == [0, 2, 3]


def test_resolve_targets_auto_ch_wins_over_track_match():
    # Auto Ch.=3 and T1 is also configured to ch 3. Auto Ch. takes
    # priority — the chord-spread path is preferred when a single
    # channel double-matches.
    t = _started(auto_ch=3)
    t._param_values["cursor_track"] = 1
    t._param_values["track_ch_0"] = 3
    targets, is_auto = t._resolve_targets(channel=2)
    assert is_auto is True
    assert targets[0] == 1            # cursor_track, not T1


def test_unmatched_channel_drops_record_and_pass_through():
    t = _started(auto_ch=0)
    s = _Sender()
    s.attach(t)
    t._param_values["cursor_row"] = 3
    t._param_values["cursor_track"] = 0
    # No track is on incoming ch 3 (0-based 2) and Auto Ch. = Off.
    t.on_note_on(channel=2, note=60, velocity=100)
    assert s.events == []
    assert t._param_values["pages"][0]["rows"][3]["voices"][0]["note"] == NOTE_HOLD
    # Cursor didn't move either — nothing was recorded.
    assert t._param_values["cursor_row"] == 3


def test_direct_routing_single_match_records_to_matched_track():
    t = _started(auto_ch=0)
    s = _Sender()
    s.attach(t)
    t._param_values["track_ch_2"] = 5      # T3 → MIDI ch 5
    t._param_values["cursor_row"] = 4
    t._param_values["cursor_track"] = 0    # cursor is on T1 — irrelevant
    t.on_note_on(channel=4, note=60, velocity=100)
    # Pass-through goes out on the matched track's channel (= incoming).
    assert ("on", 4, 60, 100) in s.events
    # Note landed on T3 at the cursor row, not on T1 (where the cursor is).
    cell = t._param_values["pages"][0]["rows"][4]["voices"][2]
    assert cell["note"] == "C-4"
    assert cell["vel"] == 100
    # Cursor still auto-advances in stopped mode.
    assert t._param_values["cursor_row"] == 5


def test_direct_routing_multi_match_chord_spreads_across_matches():
    t = _started(auto_ch=0)
    t._param_values["track_ch_0"] = 5
    t._param_values["track_ch_2"] = 5      # gaps in the matching set
    t._param_values["track_ch_3"] = 5
    t._param_values["cursor_row"] = 0
    t.on_note_on(channel=4, note=60, velocity=100)
    t.on_note_on(channel=4, note=64, velocity=100)
    t.on_note_on(channel=4, note=67, velocity=100)
    voices = t._param_values["pages"][0]["rows"][0]["voices"]
    # Filled in T-ascending order: T1, T3, T4.
    assert voices[0]["note"] == "C-4"
    assert voices[1]["note"] == NOTE_HOLD   # T2 doesn't match — untouched
    assert voices[2]["note"] == "E-4"
    assert voices[3]["note"] == "G-4"


def test_direct_routing_excess_polyphony_drops():
    t = _started(auto_ch=0)
    t._param_values["track_ch_0"] = 5      # one matching track
    t._param_values["cursor_row"] = 0
    t.on_note_on(channel=4, note=60, velocity=100)
    t.on_note_on(channel=4, note=64, velocity=100)
    # Single matching track: first note lands on T1, subsequent
    # chord-window notes on the same channel are dropped (the
    # per-channel offset has run past `len(targets)`). This mirrors
    # the Auto-Ch chord-spread behaviour where the first note is
    # the anchor and excess notes silently drop.
    voices = t._param_values["pages"][0]["rows"][0]["voices"]
    assert voices[0]["note"] == "C-4"


def test_chord_across_two_channels_advances_cursor_only_once():
    t = _started(auto_ch=0)
    t._param_values["track_ch_0"] = 3      # T1 → ch 3
    t._param_values["track_ch_1"] = 5      # T2 → ch 5
    t._param_values["cursor_row"] = 0
    t.on_note_on(channel=2, note=60, velocity=100)   # → T1
    t.on_note_on(channel=4, note=64, velocity=100)   # → T2, same window
    voices = t._param_values["pages"][0]["rows"][0]["voices"]
    assert voices[0]["note"] == "C-4"
    assert voices[1]["note"] == "E-4"
    # Cursor advanced exactly once, even though two channels fired.
    assert t._param_values["cursor_row"] == 1


def test_direct_routing_note_off_pass_through_only_on_match():
    t = _started(auto_ch=0)
    s = _Sender()
    s.attach(t)
    t._param_values["track_ch_2"] = 5
    t.on_note_off(channel=4, note=60)
    assert s.events == [("off", 4, 60)]    # matched T3, out on ch 5
    # Unmatched channel: nothing emitted.
    s.events.clear()
    t.on_note_off(channel=7, note=60)
    assert s.events == []


def test_direct_routing_cc_records_to_first_match_no_spread():
    t = _started(auto_ch=0)
    s = _Sender()
    s.attach(t)
    t._param_values["track_ch_1"] = 5
    t._param_values["track_ch_3"] = 5      # two tracks share ch 5
    t._param_values["cursor_row"] = 2
    t._param_values["cursor_track"] = 0    # cursor on T1 — irrelevant
    t.on_cc(channel=4, cc=7, value=100)
    # CC went to the FIRST matching track (T2), not to all matches.
    cell_t2 = t._param_values["pages"][0]["rows"][2]["voices"][1]
    assert cell_t2["cc_num"] == 7
    assert cell_t2["cc_val"] == 100
    cell_t4 = t._param_values["pages"][0]["rows"][2]["voices"][3]
    assert cell_t4["cc_num"] == "."        # T4 untouched
    # CCs don't advance the cursor.
    assert t._param_values["cursor_row"] == 2
    assert ("cc", 4, 7, 100) in s.events


def test_direct_routing_cc_drops_when_unmatched():
    t = _started(auto_ch=0)
    s = _Sender()
    s.attach(t)
    t._param_values["cursor_row"] = 2
    # No track matches incoming ch 5 (0-based 4) and Auto Ch.=Off.
    t.on_cc(channel=4, cc=7, value=100)
    assert s.events == []
    cell = t._param_values["pages"][0]["rows"][2]["voices"][0]
    assert cell["cc_num"] == "."


def test_live_record_direct_routing_uses_playhead_row():
    t = _started(auto_ch=0)
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [empty_row(4) for _ in range(16)]}]
    t._param_values["track_ch_2"] = 5      # T3 → ch 5
    t._param_values["cursor_row"] = 7      # cursor far from playhead
    t._param_values["cursor_track"] = 0
    t._param_values["rate"] = "1/16"
    t.on_transport_start()                 # row 0
    t.on_tick("1/16")                      # row 1 → _record_row = 1
    t.on_note_on(channel=4, note=60, velocity=100)
    # Recorded on T3 (matched), at the now-playing row.
    voices = t._param_values["pages"][0]["rows"][1]["voices"]
    assert voices[2]["note"] == "C-4"
    # Cursor untouched while playing.
    assert t._param_values["cursor_row"] == 7


# ---------------------------------------------------------------------------
# Chord-gate (held-note window for record-as-you-play)
# ---------------------------------------------------------------------------

def test_chord_stays_open_while_any_note_held_across_channels():
    # Press C on ch1, then E on ch2 (held), then release C, then
    # press G on ch1 (E still held). All three notes belong to ONE
    # chord — same target row, cursor advances exactly once.
    t = _started(auto_ch=0)
    t._param_values["track_ch_0"] = 1      # T1 → ch 1
    t._param_values["track_ch_1"] = 2      # T2 → ch 2
    t._param_values["cursor_row"] = 0
    t.on_note_on(channel=0, note=60, velocity=100)   # C on ch 1
    t.on_note_on(channel=1, note=64, velocity=100)   # E on ch 2 (held)
    t.on_note_off(channel=0, note=60)                # release C
    t.on_note_on(channel=0, note=67, velocity=100)   # G on ch 1 — still in chord
    voices = t._param_values["pages"][0]["rows"][0]["voices"]
    assert voices[0]["note"] == "C-4"      # G was offset=1 on ch1 → dropped (only T1 matches)
    assert voices[1]["note"] == "E-4"
    # Cursor only advanced ONCE (chord opened on the first note-on).
    assert t._param_values["cursor_row"] == 1


def test_new_chord_starts_after_all_notes_released():
    # Press C, release C, press E → two chords. Cursor advances twice.
    t = _started(auto_ch=0)
    t._param_values["track_ch_0"] = 1
    t._param_values["cursor_row"] = 0
    t.on_note_on(channel=0, note=60, velocity=100)
    t.on_note_off(channel=0, note=60)
    t.on_note_on(channel=0, note=64, velocity=100)
    # Both notes land on row 0 and row 1 — two chord-starts.
    voices_r0 = t._param_values["pages"][0]["rows"][0]["voices"]
    voices_r1 = t._param_values["pages"][0]["rows"][1]["voices"]
    assert voices_r0[0]["note"] == "C-4"
    assert voices_r1[0]["note"] == "E-4"
    assert t._param_values["cursor_row"] == 2


def test_velocity_zero_note_on_closes_chord():
    # Some keyboards send note-on with velocity=0 instead of an
    # explicit note-off. The chord must still close so the next
    # note-on opens a fresh chord (and advances the cursor).
    t = _started(auto_ch=0)
    t._param_values["track_ch_0"] = 1
    t._param_values["cursor_row"] = 0
    t.on_note_on(channel=0, note=60, velocity=100)
    t.on_note_on(channel=0, note=60, velocity=0)     # = note-off in MIDI
    t.on_note_on(channel=0, note=64, velocity=100)
    voices_r0 = t._param_values["pages"][0]["rows"][0]["voices"]
    voices_r1 = t._param_values["pages"][0]["rows"][1]["voices"]
    assert voices_r0[0]["note"] == "C-4"
    assert voices_r1[0]["note"] == "E-4"


def test_stale_chord_resets_after_timeout():
    # If a note-off goes missing the held set never empties, which
    # would silently freeze the chord on one row forever. After
    # _CHORD_STALE_TIMEOUT_S of inactivity the next note-on must
    # force-clear the set and start a fresh chord.
    from tracker.tracker_base import _CHORD_STALE_TIMEOUT_S
    t = _started(auto_ch=0)
    t._param_values["track_ch_0"] = 1
    t._param_values["cursor_row"] = 0
    t.on_note_on(channel=0, note=60, velocity=100)
    # Simulate a lost note-off by NOT calling on_note_off, then
    # backdate the last-event clock past the stale threshold.
    t._chord_last_event_t -= _CHORD_STALE_TIMEOUT_S + 0.1
    t.on_note_on(channel=0, note=64, velocity=100)
    voices_r0 = t._param_values["pages"][0]["rows"][0]["voices"]
    voices_r1 = t._param_values["pages"][0]["rows"][1]["voices"]
    assert voices_r0[0]["note"] == "C-4"
    assert voices_r1[0]["note"] == "E-4"       # treated as new chord


def test_transport_stop_clears_held_chord():
    # Pressing Play / Stop after a stuck chord must always recover —
    # transport-cycle is the universal "I know it's broken, reset" gesture.
    t = _started(auto_ch=0)
    t._param_values["track_ch_0"] = 1
    t.on_note_on(channel=0, note=60, velocity=100)
    assert t._held_recording_keys
    t.on_transport_stop()
    assert not t._held_recording_keys
    assert t._chord_offset_by_ch == {}


# ---------------------------------------------------------------------------
# Play pre-roll (manual cmd_play vs external Start)
# ---------------------------------------------------------------------------

def test_cmd_play_schedules_preroll_does_not_fire_synchronously():
    # cmd_play returns immediately and queues a Timer that will fire
    # on_transport_start. The synth doesn't see anything until the
    # pre-roll elapses.
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [
        {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
    ] + [empty_row(4) for _ in range(15)]}]
    t.on_param_change("cmd_play", True)
    assert t._preroll_timer is not None
    assert t._playing is False              # not yet
    assert s.events == []                    # no notes leaked
    t._preroll_timer.join()
    assert t._playing is True
    assert ("on", 0, 60, 90) in s.events


def test_cmd_stop_during_preroll_cancels_start():
    # User taps Play then immediately Stop. The pre-roll timer must
    # be cancelled so no delayed start fires after the user gave up.
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [
        {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
    ] + [empty_row(4) for _ in range(15)]}]
    t.on_param_change("cmd_play", True)
    pre = t._preroll_timer
    assert pre is not None
    t.on_param_change("cmd_stop", True)
    assert t._preroll_timer is None
    # Wait past where the pre-roll would have fired; _playing must
    # stay False because the timer was cancelled before firing.
    pre.join()
    assert t._playing is False
    assert not any(e[0] == "on" for e in s.events)


def test_external_start_bypasses_preroll():
    # An upstream MIDI Start arrives directly at on_transport_start
    # (not via cmd_play). Engine must respond immediately — adding a
    # pre-roll would desync from the upstream clock.
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [{"rows": [
        {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
    ] + [empty_row(4) for _ in range(15)]}]
    t.on_transport_start()
    assert t._playing is True
    assert ("on", 0, 60, 90) in s.events
    assert t._preroll_timer is None


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
    # Frontend writes cmd_play=True; on_param_change schedules a
    # pre-roll timer that fires on_transport_start ~50 ms later.
    # The cmd_play signal resets to False immediately so a re-tap
    # always queues a fresh start.
    t.on_param_change("cmd_play", True)
    assert t._param_values["cmd_play"] is False
    assert t._preroll_timer is not None
    t._preroll_timer.join()
    assert t._playing is True
    assert ("on", 0, 60, 90) in s.events


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


# ---------------------------------------------------------------------------
# Live record (playing): notes land where the playhead is, simultaneous
# notes spread across tracks, and releases are recorded as `Off` on the
# corresponding track. Step record (stopped) is unchanged and covered above.
# ---------------------------------------------------------------------------

def _blank_pages(rows=16, tracks=4):
    return [{"rows": [empty_row(tracks) for _ in range(rows)]}]


def test_live_record_held_note_then_later_note_land_on_their_own_rows():
    """The old chord-collapse model is gone for live record: a note held
    across steps does not pull a later note onto its row -- each lands
    where the playhead was when it was played."""
    t = _started(auto_ch=0)
    t._param_values["pages"] = _blank_pages()
    t._param_values["track_ch_0"] = 1   # T1 ← ch 1 (0-based 0)
    t._param_values["rate"] = "1/16"
    t.on_transport_start()              # record_row = 0
    t.on_note_on(0, 60, 100)            # C-4 at row 0 (held)
    t.on_tick("1/16")                   # record_row = 1
    t.on_tick("1/16")                   # record_row = 2
    t.on_note_on(0, 62, 100)            # D-4 while C still held
    rows = t._param_values["pages"][0]["rows"]
    assert rows[0]["voices"][0]["note"] == "C-4"
    assert rows[2]["voices"][0]["note"] == "D-4"
    # Row 0's C is untouched; row 1 stays a hold (the note rings through).
    assert rows[1]["voices"][0]["note"] == NOTE_HOLD


def test_live_record_simultaneous_notes_spread_across_tracks():
    """Notes arriving within the same step still spread across
    consecutive tracks (a live-strummed chord on one row)."""
    t = _started(auto_ch=2)             # MIDI ch 2 = 0-based ch 1 = Auto Ch.
    t._param_values["pages"] = _blank_pages()
    t._param_values["cursor_track"] = 0
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    t.on_tick("1/16")                   # record_row = 1
    t.on_note_on(channel=1, note=60, velocity=100)  # → T1
    t.on_note_on(channel=1, note=64, velocity=100)  # same step → T2
    t.on_note_on(channel=1, note=67, velocity=100)  # same step → T3
    voices = t._param_values["pages"][0]["rows"][1]["voices"]
    assert voices[0]["note"] == "C-4"
    assert voices[1]["note"] == "E-4"
    assert voices[2]["note"] == "G-4"


def test_live_record_spread_resets_each_step():
    """The per-step spread resets when the playhead advances, so a note
    on the next step starts back at the first target track."""
    t = _started(auto_ch=2)
    t._param_values["pages"] = _blank_pages()
    t._param_values["cursor_track"] = 0
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    t.on_tick("1/16")                   # row 1
    t.on_note_on(channel=1, note=60, velocity=100)  # row 1 → T1
    t.on_tick("1/16")                   # row 2 (spread resets)
    t.on_note_on(channel=1, note=64, velocity=100)  # row 2 → T1 again
    rows = t._param_values["pages"][0]["rows"]
    assert rows[1]["voices"][0]["note"] == "C-4"
    assert rows[2]["voices"][0]["note"] == "E-4"


def test_live_record_note_off_records_off_on_same_track():
    t = _started(auto_ch=0)
    t._param_values["pages"] = _blank_pages()
    t._param_values["track_ch_0"] = 1
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    t.on_note_on(0, 60, 100)            # C-4 at row 0, T1
    t.on_tick("1/16")                   # row 1
    t.on_tick("1/16")                   # row 2
    t.on_note_off(0, 60)                # release → Off on T1 at row 2
    rows = t._param_values["pages"][0]["rows"]
    assert rows[0]["voices"][0]["note"] == "C-4"
    assert rows[1]["voices"][0]["note"] == NOTE_HOLD   # rings through
    assert rows[2]["voices"][0]["note"] == NOTE_OFF


def test_live_record_off_lands_on_chord_member_track():
    """With a spread chord, each release records its Off on the track its
    own note-on used -- not all on the first track."""
    t = _started(auto_ch=2)
    t._param_values["pages"] = _blank_pages()
    t._param_values["cursor_track"] = 0
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    t.on_note_on(channel=1, note=60, velocity=100)  # row 0 → T1
    t.on_note_on(channel=1, note=64, velocity=100)  # row 0 → T2
    t.on_tick("1/16")                   # row 1
    t.on_note_off(channel=1, note=64)   # release the 2nd note → Off on T2
    rows = t._param_values["pages"][0]["rows"]
    assert rows[1]["voices"][1]["note"] == NOTE_OFF     # T2 got the Off
    assert rows[1]["voices"][0]["note"] == NOTE_HOLD    # T1 still ringing


def test_live_record_velocity_zero_records_off_and_passes_note_off():
    t = _started(auto_ch=0)
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = _blank_pages()
    t._param_values["track_ch_0"] = 1
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    t.on_note_on(0, 60, 100)            # C-4 row 0
    t.on_tick("1/16")                   # row 1
    s.events.clear()
    t.on_note_on(0, 60, 0)              # velocity-0 = note-off at row 1
    assert t._param_values["pages"][0]["rows"][1]["voices"][0]["note"] == NOTE_OFF
    # Passed through as a real note-off, NOT a velocity-1 note-on.
    assert ("off", 0, 60) in s.events
    assert not any(e[0] == "on" for e in s.events)


def test_live_record_off_does_not_clobber_note_on_same_cell():
    """Releasing an old note must not overwrite a new note recorded on
    the same track/row in the same step."""
    t = _started(auto_ch=0)
    t._param_values["pages"] = _blank_pages()
    t._param_values["track_ch_0"] = 1   # only T1 matches ch 1
    t._param_values["rate"] = "1/16"
    t.on_transport_start()
    t.on_note_on(0, 60, 100)            # C-4 row 0, T1 (held)
    t.on_tick("1/16")                   # row 1
    t.on_note_on(0, 62, 100)            # D-4 row 1, T1
    t.on_note_off(0, 60)                # release C → target T1 row 1, occupied
    assert t._param_values["pages"][0]["rows"][1]["voices"][0]["note"] == "D-4"


def test_note_off_when_stopped_records_no_off():
    t = _started(auto_ch=0)
    t._param_values["track_ch_0"] = 1
    t._param_values["cursor_row"] = 0
    t.on_note_on(0, 60, 100)            # step record: C-4 row 0
    t.on_note_off(0, 60)
    notes = [v["note"]
             for row in t._param_values["pages"][0]["rows"]
             for v in row["voices"]]
    assert NOTE_OFF not in notes


def test_live_record_sub_step_note_off_lands_on_next_step():
    """A note played and released within the same step still gets a
    clean ending: the Off lands on the next step."""
    t = _started(auto_ch=0)
    t._param_values["pages"] = _blank_pages()
    t._param_values["track_ch_0"] = 1
    t._param_values["rate"] = "1/16"
    t.on_transport_start()              # record_row = 0
    t.on_note_on(0, 60, 100)            # C-4 at row 0
    t.on_note_off(0, 60)                # released same step → Off on row 1
    rows = t._param_values["pages"][0]["rows"]
    assert rows[0]["voices"][0]["note"] == "C-4"
    assert rows[1]["voices"][0]["note"] == NOTE_OFF


def test_live_record_sub_step_off_skipped_when_next_step_occupied():
    """The pushed-to-next-step Off never clobbers a note already
    recorded on that next step."""
    t = _started(auto_ch=0)
    t._param_values["pages"] = _blank_pages()
    t._param_values["track_ch_0"] = 1
    t._param_values["rate"] = "1/16"
    # Next step already holds a note on the same track.
    t._param_values["pages"][0]["rows"][1]["voices"][0] = {
        "note": "E-4", "vel": 90, "cc_num": ".", "cc_val": "--"}
    t.on_transport_start()
    t.on_note_on(0, 60, 100)            # C-4 row 0
    t.on_note_off(0, 60)                # same step → would push to row 1, occupied
    assert t._param_values["pages"][0]["rows"][1]["voices"][0]["note"] == "E-4"


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


def test_clock_in_never_forwarded_after_split():
    """on_clock is a pure consumer now -- clock to OUT is the
    generator thread's job, gated by send_clock. Forwarding raw
    incoming clock through would double-emit when both toggles
    are on, so it's always dropped."""
    t = _started()
    s = _ForwardSender()
    s.attach(t)
    for flag in (False, True):
        t._param_values["send_clock"] = flag
        s.events.clear()
        t.on_clock()
        assert not any(e[0] == "clk" for e in s.events)


def test_send_transport_off_swallows_incoming_transport():
    t = _started()
    s = _ForwardSender()
    s.attach(t)
    t._param_values["send_transport"] = False
    t.on_clock_start()
    t.on_clock_continue()
    t.on_clock_stop()
    assert not any(e[0] in ("start", "cont", "stop") for e in s.events)


def test_send_transport_on_forwards_incoming_transport():
    t = _started()
    s = _ForwardSender()
    s.attach(t)
    t._param_values["send_transport"] = True
    t.on_clock_start()
    t.on_clock_continue()
    t.on_clock_stop()
    forwarded = [e[0] for e in s.events if e[0] in ("start", "cont", "stop")]
    assert forwarded == ["start", "cont", "stop"]


def test_send_transport_on_emits_for_play_button():
    """The on-screen Play / Stop buttons emit START / STOP to OUT
    when send_transport is on, so downstream slaves bar-align with
    the Tracker even when the Tracker is clock-master."""
    t = _started()
    s = _ForwardSender()
    s.attach(t)
    t._param_values["send_transport"] = True
    t.on_transport_start()   # = on-screen Play
    t.on_transport_stop()    # = on-screen Stop
    forwarded = [e[0] for e in s.events if e[0] in ("start", "stop")]
    assert forwarded == ["start", "stop"]


def test_send_transport_off_does_not_emit_for_play_button():
    t = _started()
    s = _ForwardSender()
    s.attach(t)
    t._param_values["send_transport"] = False
    t.on_transport_start()
    t.on_transport_stop()
    assert not any(e[0] in ("start", "stop") for e in s.events)


def _row0_c4_page():
    """A page whose row 0 fires C-4 on T1 (channel 1 → 0-based 0)."""
    return {"rows": [
        {"voices": [{"note": "C-4", "vel": 90, "cc_num": ".", "cc_val": "--"},
                    empty_voice(), empty_voice(), empty_voice()]},
    ] + [empty_row(4) for _ in range(15)]}


def test_recv_transport_defaults_on():
    t = _started()
    assert t._param_values["recv_transport"] is True


def test_recv_transport_on_external_start_drives_playhead():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [_row0_c4_page()]
    t._param_values["recv_transport"] = True
    t.on_transport_start()  # foreign START off the ClockBus
    assert t._playing is True
    assert ("on", 0, 60, 90) in s.events


def test_recv_transport_off_ignores_external_start():
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [_row0_c4_page()]
    t._param_values["recv_transport"] = False
    t.on_transport_start()
    assert t._playing is False
    assert s.events == []  # nothing fired — foreign transport ignored


def test_recv_transport_off_ignores_external_stop_and_continue():
    t = _started()
    t._param_values["recv_transport"] = False
    # The Tracker is running on its own (e.g. its Play button).
    t._playing = True
    t.on_transport_stop()       # foreign STOP must not halt it
    assert t._playing is True
    t.on_transport_continue()   # foreign CONTINUE is a no-op too
    assert t._playing is True


def test_play_button_works_with_recv_transport_off():
    """Rcv Trnsp. only gates *external* transport — the on-screen Play
    button must still start the playhead."""
    t = _started()
    s = _Sender()
    s.attach(t)
    t._param_values["pages"] = [_row0_c4_page()]
    t._param_values["recv_transport"] = False
    t.on_param_change("cmd_play", True)
    assert t._preroll_timer is not None
    t._preroll_timer.join()
    assert t._playing is True
    assert ("on", 0, 60, 90) in s.events


def test_stop_button_works_with_recv_transport_off():
    t = _started()
    t._param_values["recv_transport"] = False
    t._playing = True
    t.on_param_change("cmd_stop", True)
    assert t._playing is False


def _page_with_note(track_count, note="C-4"):
    page = empty_page(track_count, 16)
    page["rows"][0]["voices"][0] = _filled_voice(note)
    return page


def test_loop_page_repeats_current_page_without_advancing():
    """Shift+Play (loop_page) loops the displayed page instead of
    walking through the pages."""
    t = _started(auto_ch=0)
    t._param_values["pages"] = [
        _page_with_note(t.TRACK_COUNT, "E-4"),
        _page_with_note(t.TRACK_COUNT, "C-4"),
    ]
    t._param_values["current_page"] = 1
    t._param_values["rate"] = "1/16"
    s = _Sender()
    s.attach(t)
    t._begin_playback(loop_page=True)   # starts on the displayed page (1)
    assert t._loop_page is True
    assert t._play_page == 1
    for _ in range(17):                 # > one page; would cross pages if advancing
        t.on_tick("1/16")
    assert t._play_page == 1            # never left page 1
    assert any(e == ("on", 0, 60, 90) for e in s.events)          # C-4 fired
    assert not any(e[0] == "on" and e[2] == 64 for e in s.events)  # page 0's E-4 never


def test_loop_page_follows_navigation_at_wrap():
    """Navigating to another page while looping moves the loop there at
    the next wrap (follow-current-page)."""
    t = _started(auto_ch=0)
    t._param_values["pages"] = [
        _page_with_note(t.TRACK_COUNT, "E-4"),   # page 0 → E-4 (64)
        _page_with_note(t.TRACK_COUNT, "C-4"),   # page 1 → C-4 (60)
    ]
    t._param_values["current_page"] = 0
    t._param_values["rate"] = "1/16"
    s = _Sender()
    s.attach(t)
    t._begin_playback(loop_page=True)            # looping page 0
    assert t._play_page == 0
    t._param_values["current_page"] = 1          # navigate mid-loop
    for _ in range(20):                          # let page 0's loop finish and wrap
        if t._play_page == 1:
            break
        t.on_tick("1/16")
    assert t._play_page == 1                     # loop followed to page 1 at the wrap
    assert t._play_row == 0
    s.events.clear()
    t.on_tick("1/16")                            # fires page 1 row 0 → C-4
    assert any(e == ("on", 0, 60, 90) for e in s.events)


def test_loop_page_cleared_on_stop_and_normal_play():
    t = _started(auto_ch=0)
    t._param_values["pages"] = [_page_with_note(t.TRACK_COUNT)]
    t._begin_playback(loop_page=True)
    assert t._loop_page is True
    t._end_playback()
    assert t._loop_page is False
    t._begin_playback()                          # normal play does not loop a page
    assert t._loop_page is False


def test_cmd_play_page_triggers_loop_via_preroll():
    t = _started(auto_ch=0)
    t._param_values["pages"] = [_page_with_note(t.TRACK_COUNT)]
    t.on_param_change("cmd_play_page", True)
    assert t._preroll_timer is not None
    t._preroll_timer.join()
    assert t._playing is True
    assert t._loop_page is True
    assert t._param_values["cmd_play_page"] is False


def test_legacy_send_clock_migrates_to_both_flags():
    """A config saved with the old combined `send_clock=True` toggle
    used to mean 'forward clock + start/stop/continue.' After the
    split, that intent migrates to send_clock=True (generate own
    clock) AND send_transport=True (forward transport)."""
    class _T(TrackerBase):
        NAME = "T"
        TRACK_COUNT = 4

    t = _T()
    # Pre-seed legacy field as if config-restore had just run.
    t._param_values["send_clock"] = True
    t.on_start()
    assert t._param_values["send_clock"] is True
    assert t._param_values["send_transport"] is True
    # New install (neither key present) defaults both off.
    u = _T()
    u.on_start()
    assert u._param_values["send_clock"] is False
    assert u._param_values["send_transport"] is False
    # Stop the generator threads on_start may have started.
    t._clock_gen.stop()


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


def test_patterns_replace_refreshes_full_status():
    """Restored configs land in on_param_change("patterns", saved_array)
    AFTER on_start has already seeded pattern_status against empty
    defaults. Without a "patterns" handler, only the currently-
    selected slot ever got refreshed (via the pages mirror), so a
    saved config with content in slot 1+ rendered dashed-empty
    until the user touched it. The handler must recompute the
    whole status array."""
    t = _started()
    filled = [_filled_page(track_count=4)]
    new_patterns = (
        [filled, filled, filled]
        + [[empty_page(t.TRACK_COUNT, t.MAX_ROWS_PER_PAGE)]] * 5
    )
    t.on_param_change("patterns", new_patterns)
    # Slots 0..2 carry data → True; slots 3..7 stay empty → False.
    assert t._param_values["pattern_status"] == (
        [True, True, True] + [False] * 5
    )


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


def test_live_record_mirrors_into_selected_pattern():
    """Live-recorded edits go through _record_voice_field_at which
    uses set_param internally -- that bypasses on_param_change.
    Without explicit mirroring, the patterns[] storage drifts out of
    sync with `pages` and a pattern switch + back loses the edit."""
    t = _started()
    # Live-record into voice 0 at row 0 of page 0 of the current
    # (selected) pattern.
    t._record_voice_field_at(0, 0, 0, {"note": "G-4", "vel": 100})
    # Pages reflects the edit.
    assert t._param_values["pages"][0]["rows"][0]["voices"][0]["note"] == "G-4"
    # patterns[selected] should mirror.
    sel = t._param_values["selected_pattern"]
    assert t._param_values["patterns"][sel][0]["rows"][0]["voices"][0]["note"] == "G-4"
    # Switch + switch-back round-trip preserves the recorded note.
    t.on_param_change("cmd_pattern_select", {"pattern": 1, "mode": "tap"})
    t.on_param_change("cmd_pattern_select", {"pattern": sel, "mode": "tap"})
    assert t._param_values["pages"][0]["rows"][0]["voices"][0]["note"] == "G-4"


# ---------------------------------------------------------------------------
# Pattern-control channel: incoming notes on pattern_ctrl_ch trigger pattern
# switches (queued while playing, immediate while stopped). Recording and
# pass-through are suppressed on the reserved channel.
# ---------------------------------------------------------------------------

def _started_with_ctrl(ctrl_ch=10, notes=None):
    """Tracker with pattern_ctrl_ch on ch 10 (0-based ch 9) and the 8 trigger
    notes set to 36..43 (the in-code default)."""
    t = _started(track_count=4, auto_ch=0)
    t._param_values["pattern_ctrl_ch"] = ctrl_ch
    notes = notes if notes is not None else list(range(36, 44))
    for i, n in enumerate(notes):
        t._param_values[f"pattern_note_{i}"] = n
    return t


def test_control_note_when_stopped_switches_immediately():
    t = _started_with_ctrl()
    s = _Sender()
    s.attach(t)
    assert t._param_values["selected_pattern"] == 0
    # Press the note assigned to pattern slot 3 on the control channel.
    t.on_note_on(channel=9, note=39, velocity=100)
    assert t._param_values["selected_pattern"] == 3
    # Switched immediately because the engine is stopped — no queue lingers.
    assert t._param_values["queued_pattern"] == -1
    # The event did not leak to OUT.
    assert s.events == []


def test_control_note_when_playing_queues_switch():
    t = _started_with_ctrl()
    s = _Sender()
    s.attach(t)
    t._playing = True  # pretend transport is running
    t.on_note_on(channel=9, note=41, velocity=100)
    # Selection unchanged until the next page-0 boundary consumes the queue.
    assert t._param_values["selected_pattern"] == 0
    assert t._param_values["queued_pattern"] == 5
    assert s.events == []


def test_control_note_unmapped_is_swallowed():
    """A control-channel note that doesn't match any slot still gets dropped —
    the channel is reserved end-to-end."""
    t = _started_with_ctrl()
    s = _Sender()
    s.attach(t)
    t.on_note_on(channel=9, note=99, velocity=100)
    assert t._param_values["selected_pattern"] == 0
    assert t._param_values["queued_pattern"] == -1
    assert s.events == []


def test_control_note_off_is_swallowed():
    t = _started_with_ctrl()
    s = _Sender()
    s.attach(t)
    t.on_note_off(channel=9, note=36)
    assert s.events == []


def test_control_channel_cc_is_swallowed():
    """CCs on the control channel are dropped — no record, no pass-through."""
    t = _started_with_ctrl()
    s = _Sender()
    s.attach(t)
    t.on_cc(channel=9, cc=74, value=100)
    assert s.events == []


def test_control_channel_off_disables_intercept():
    """With pattern_ctrl_ch=0 (Off, the default), the intercept is bypassed
    and notes route normally."""
    t = _started(track_count=4, auto_ch=0)
    # auto_ch=0, track_ch_i defaults to 1 → notes on channel 0 record into T1+
    t._param_values["pattern_ctrl_ch"] = 0
    t._param_values["pattern_note_0"] = 60
    s = _Sender()
    s.attach(t)
    # Even though note 60 is configured as pattern_note_0, ctrl_ch=Off means
    # no intercept — the note records / passes through as normal.
    t.on_note_on(channel=0, note=60, velocity=100)
    assert t._param_values["selected_pattern"] == 0
    # OUT got a pass-through note-on.
    assert any(e[0] == "on" for e in s.events)


def test_control_velocity_zero_does_not_trigger_switch():
    """A note-on with velocity 0 (running-status note-off) on the control
    channel must NOT flip patterns — that would double-fire on every press."""
    t = _started_with_ctrl()
    s = _Sender()
    s.attach(t)
    t.on_note_on(channel=9, note=36, velocity=0)
    assert t._param_values["selected_pattern"] == 0
    assert s.events == []


def test_control_note_overlap_with_auto_ch_wins():
    """If pattern_ctrl_ch shares a channel number with auto_ch, control wins —
    pattern switching takes priority over recording on the same channel."""
    t = _started_with_ctrl(ctrl_ch=3)  # same as default auto_ch in helpers
    t._param_values["auto_ch"] = 3
    s = _Sender()
    s.attach(t)
    t.on_note_on(channel=2, note=37, velocity=100)  # channel 2 = MIDI ch 3
    assert t._param_values["selected_pattern"] == 1
    assert s.events == []


# ---------------------------------------------------------------------------
# Trigger modes: One-shot / Hold / Toggle launch the pattern off incoming
# clock without a transport Start. Mode 0 (Switch) is the historic
# queue/immediate select and is covered by the tests above (which never set
# trigger_mode, so it defaults to 0).
# ---------------------------------------------------------------------------

_END_VOICE = {"note": NOTE_END, "vel": CC_HOLD, "cc_num": CC_NONE, "cc_val": CC_HOLD}


def _started_launch(mode, ctrl_ch=10, notes=None):
    """Tracker on control channel 10 (0-based ch 9), trigger notes 36..43,
    with `trigger_mode` set to one of the launch modes (1/2/3)."""
    t = _started(track_count=4, auto_ch=0)
    t._param_values["pattern_ctrl_ch"] = ctrl_ch
    t._param_values["trigger_mode"] = mode
    notes = notes if notes is not None else list(range(36, 44))
    for i, n in enumerate(notes):
        t._param_values[f"pattern_note_{i}"] = n
    return t


def _one_row_pattern(track_count, with_end=True):
    """A page whose row 0 fires C-4 on T1; row 1 is an End marker so the
    pattern is effectively one fireable step long."""
    page = empty_page(track_count, 16)
    page["rows"][0]["voices"][0] = _filled_voice("C-4")
    if with_end:
        page["rows"][1]["voices"][0] = dict(_END_VOICE)
    return page


def test_trigger_mode_defaults_to_switch():
    t = _started()
    assert t._param_values["trigger_mode"] == 0


def test_switch_mode_does_not_launch():
    """Mode 0 keeps the historic select path — no launch state is set."""
    t = _started_with_ctrl()  # trigger_mode unset -> defaults to 0
    t.on_note_on(channel=9, note=37, velocity=100)
    assert t._launch_active is False
    assert t._param_values["selected_pattern"] == 1


def test_launch_starts_without_transport_and_waits_for_next_step():
    """A One-shot trigger arms the launch but fires nothing until the next
    clock tick — that one-step wait is the quantize-to-the-next-step start."""
    t = _started_launch(mode=1)
    t._param_values["patterns"][1] = [_one_row_pattern(t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    s = _Sender()
    s.attach(t)
    assert t._playing is False
    t.on_note_on(channel=9, note=37, velocity=100)  # slot 1
    assert t._launch_active is True
    assert t._param_values["selected_pattern"] == 1
    assert s.events == []  # nothing fired yet — waiting for the clock
    t.on_tick("1/16")      # next step fires row 0
    assert ("on", 0, 60, 90) in s.events


def test_launch_advances_on_clock_without_playing_flag():
    """on_tick advances a launch even though transport (_playing) is off."""
    t = _started_launch(mode=2)  # Hold loops, easy to observe
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    s = _Sender()
    s.attach(t)
    t.on_note_on(channel=9, note=37, velocity=100)
    assert t._playing is False
    t.on_tick("1/16")
    assert any(e[0] == "on" for e in s.events)


def test_launch_oneshot_stops_at_end_marker():
    t = _started_launch(mode=1)
    t._param_values["patterns"][1] = [_one_row_pattern(t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    s = _Sender()
    s.attach(t)
    t.on_note_on(channel=9, note=37, velocity=100)
    t.on_tick("1/16")  # fires row 0 (C-4 on)
    assert t._launch_active is True
    t.on_tick("1/16")  # lands on End -> release + stop
    assert t._launch_active is False
    assert ("off", 0, 60) in s.events


def test_launch_oneshot_plays_full_page_then_stops_at_wrap():
    """No End marker: the pattern plays its 16 rows, the last row keeps a
    full step of ring, then the launch stops on the following tick."""
    t = _started_launch(mode=1)
    page = empty_page(t.TRACK_COUNT, t.MAX_ROWS_PER_PAGE)
    page["rows"][0]["voices"][0] = _filled_voice("C-4")
    t._param_values["patterns"][1] = [page]
    t._refresh_pattern_status_slot(1)
    s = _Sender()
    s.attach(t)
    t.on_note_on(channel=9, note=37, velocity=100)
    for _ in range(t.MAX_ROWS_PER_PAGE):  # fire rows 0..15
        t.on_tick("1/16")
    # Last row fired; the stop is deferred one tick so it rings a full step.
    assert t._launch_active is True
    assert t._launch_oneshot_ending is True
    t.on_tick("1/16")
    assert t._launch_active is False
    assert ("off", 0, 60) in s.events


def test_launch_hold_loops_while_held_and_stops_on_release():
    t = _started_launch(mode=2)
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    s = _Sender()
    s.attach(t)
    t.on_note_on(channel=9, note=37, velocity=100)
    assert t._launch_active is True
    for _ in range(40):  # well past one page — Hold keeps looping
        t.on_tick("1/16")
    assert t._launch_active is True
    # A release of a different control note doesn't stop our launch.
    t.on_note_off(channel=9, note=99)
    assert t._launch_active is True
    # Releasing the launch note stops it.
    t.on_note_off(channel=9, note=37)
    assert t._launch_active is False


def test_hold_launch_supersedes_transport_play_and_stops_on_release():
    """A Hold launch while the tracker is already running from transport
    takes over and fully stops on release. Regression: the release only
    cleared _launch_active, so transport-driven _playing kept the
    playhead advancing and Hold never actually stopped."""
    t = _started_launch(mode=2)
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    t._playing = True                  # already running from external transport
    t.on_note_on(channel=9, note=37, velocity=100)   # Hold press
    assert t._launch_active is True
    assert t._playing is False         # launch superseded the normal play
    t.on_note_off(channel=9, note=37)  # Hold release
    assert t._launch_active is False
    assert t._playing is False         # fully stopped — on_tick won't advance


def test_launch_toggle_press_starts_then_second_press_stops():
    t = _started_launch(mode=3)
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    t.on_note_on(channel=9, note=37, velocity=100)
    assert t._launch_active is True
    assert t._param_values["selected_pattern"] == 1
    t.on_note_on(channel=9, note=37, velocity=100)  # same slot again
    assert t._launch_active is False


def test_launch_toggle_other_slot_replaces():
    t = _started_launch(mode=3)
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._param_values["patterns"][2] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    t._refresh_pattern_status_slot(2)
    t.on_note_on(channel=9, note=37, velocity=100)  # slot 1
    assert t._param_values["selected_pattern"] == 1
    t.on_note_on(channel=9, note=38, velocity=100)  # slot 2 replaces
    assert t._launch_active is True
    assert t._param_values["selected_pattern"] == 2


def test_transport_stop_clears_active_launch():
    t = _started_launch(mode=2)
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    t.on_note_on(channel=9, note=37, velocity=100)
    assert t._launch_active is True
    t.on_transport_stop()
    assert t._launch_active is False


def test_panic_clears_active_launch():
    t = _started_launch(mode=2)
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    t.on_note_on(channel=9, note=37, velocity=100)
    assert t._launch_active is True
    t.panic()
    assert t._launch_active is False


# ---------------------------------------------------------------------------
# Pattern selection is "quiet" (persist=False): launching stems / tapping
# pattern slots moves the live pointer (selected_pattern) + mirror (pages)
# but changes no saveable content, so it must NOT mark the config dirty nor
# invalidate the autosave encode cache. Recording goes through the normal
# (persisting) path and DOES both. The fake _notify_param_change below
# mirrors the host's PluginHost._on_param_change gating so we test the
# end-to-end consequence (dirty + encode_seq), not just the persist flag.
# ---------------------------------------------------------------------------

def _wire_dirty_tracker(t):
    """Attach a _notify_param_change mirroring the host gating: a
    persisted, non-transient change bumps encode_seq + marks dirty;
    transient or quiet (persist=False) writes do neither. Returns a
    state dict {dirty, encode_seq, calls}."""
    state = {"dirty": False, "encode_seq": 0, "calls": []}

    def notify(name, value, persist=True):
        state["calls"].append((name, value, persist))
        if persist and name not in t.transient_params:
            state["encode_seq"] += 1
            state["dirty"] = True

    t._notify_param_change = notify
    return state


def _persist_calls(state, name):
    return [c[2] for c in state["calls"] if c[0] == name]


@pytest.mark.parametrize("mode", [1, 2, 3])  # One-shot / Hold / Toggle
def test_launch_is_quiet_no_dirty_no_encode_bump(mode):
    t = _started_launch(mode=mode)
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    state = _wire_dirty_tracker(t)  # wire AFTER on_start so seeding doesn't count
    t.on_note_on(channel=9, note=37, velocity=100)  # launch slot 1
    assert t._launch_active is True
    assert t._param_values["selected_pattern"] == 1
    # The launch selected a pattern but dirtied nothing and forced no
    # re-encode — a live set stays asterisk-free and autosave-quiet.
    assert state["dirty"] is False
    assert state["encode_seq"] == 0
    # Both pointer + mirror were written quietly.
    assert _persist_calls(state, "selected_pattern") == [False]
    assert _persist_calls(state, "pages") == [False]


def test_switch_mode_tap_is_quiet():
    t = _started_with_ctrl()  # trigger_mode 0 = Switch
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    state = _wire_dirty_tracker(t)
    # Stopped + tap = immediate switch (the Switch-mode selection path).
    t.on_param_change("cmd_pattern_select", {"pattern": 1, "mode": "tap"})
    assert t._param_values["selected_pattern"] == 1
    assert state["dirty"] is False
    assert state["encode_seq"] == 0
    assert _persist_calls(state, "selected_pattern") == [False]
    assert _persist_calls(state, "pages") == [False]


def test_recording_dirties_and_bumps_encode_seq():
    t = _started()
    state = _wire_dirty_tracker(t)
    t._record_voice_field_at(0, 0, 0, {"note": "G-4", "vel": 100})
    # Recording wrote real, saveable content → dirty + cache invalidated.
    assert state["dirty"] is True
    assert state["encode_seq"] >= 1
    assert _persist_calls(state, "pages") == [True]


def test_selected_pattern_stays_serialized_after_launch():
    """Even though launches are quiet, selected_pattern must remain a
    NON-transient (serialized) param so a deliberate Save still records
    the active pattern."""
    t = _started_launch(mode=1)
    t._param_values["patterns"][1] = [_filled_page(track_count=t.TRACK_COUNT)]
    t._refresh_pattern_status_slot(1)
    t.on_note_on(channel=9, note=37, velocity=100)
    assert "selected_pattern" not in t.transient_params
    assert "pages" not in t.transient_params
    assert t._param_values["selected_pattern"] == 1
