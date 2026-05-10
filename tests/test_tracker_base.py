"""Tracker MVP — covers the data model + plugin registration shape.

Playback / auto-learn behaviour is exercised in later tests once the
engine is wired."""

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


def test_only_tracker_grid_in_params():
    # No standalone Radio / Group / etc — the TrackerGrid is the
    # sole top-level entry; rate is reached through `rate_param`
    # so there's no separate buttons-style render anywhere.
    assert all(isinstance(p, TrackerGrid) for p in _DemoTracker.params)
    assert len(_DemoTracker.params) == 1


def test_schema_param_keys_collects_tracker_aux():
    keys = schema_param_keys(_DemoTracker.params)
    # Sibling auxiliary params declared on the TrackerGrid — including
    # `rate` which is now reached through `rate_param` instead of a
    # standalone Radio, and `cursor_half` which controls keypad split.
    for name in ("pages", "current_page", "cursor_row", "cursor_track",
                 "cursor_half", "octave", "rate"):
        assert name in keys, f"missing aux key {name!r}"
    # Channel / sync / show-tracks were trimmed: output is always ch 1
    # and transport is always external. Make sure the schema doesn't
    # carry stale keys that would re-appear in saved configs.
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
    assert t.transient_params == {
        "cursor_row", "cursor_track", "cursor_half", "octave",
    }


def test_on_start_preserves_existing_state():
    t = _DemoTracker()
    custom_page = {"rows": [{"voices": [{"note": "C-3", "vel": 90,
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
