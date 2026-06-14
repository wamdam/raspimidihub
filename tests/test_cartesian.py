"""Tests for the Cartesian play-surface plugin."""

from cartesian import Cartesian
from helpers import make_plugin


def _offsets(plugin):
    return [c["offset"] for c in plugin.get_param("grid")]


def test_default_live_fill_stamps_climbing_triad():
    """A fresh Live instance stamps the grid with the scale-aware
    voicing, climbing as inversions across the cells (offset =
    chord_tone(x+y))."""
    p, _ = make_plugin(Cartesian)
    offs = _offsets(p)
    assert offs[0:4] == [0, 4, 7, 12]   # row 0: C E G C  (major triad)
    assert offs[4:8] == [4, 7, 12, 16]  # row 1: 1st inversion
    assert offs[8:12] == [7, 12, 16, 19]
    assert offs[12:16] == [12, 16, 19, 24]


def test_minor_scale_flattens_the_third():
    p, _ = make_plugin(Cartesian)
    scale_idx = ["major", "minor"].index("minor")
    p.set_param("scale", scale_idx)
    p.on_param_change("scale", scale_idx)
    assert _offsets(p)[0:4] == [0, 3, 7, 12]  # minor third


def test_voicing_unison_climbs_in_octaves():
    p, _ = make_plugin(Cartesian)
    p.set_param("fill_voicing", 0)  # Unison
    p.on_param_change("fill_voicing", 0)
    assert _offsets(p)[0:4] == [0, 12, 24, 36]


def test_play_voices_held_root_along_rows_path():
    """X clock steps along the Rows path; each cell plays root +
    offset, transposing with the held note."""
    p, h = make_plugin(Cartesian)
    p.set_param("sync_mode", "tempo")
    p.on_note_on(0, 60, 100)
    fired = []
    for _ in range(5):
        h.clear()
        p.on_tick("1/16")  # default x_rate
        fired.append(h.note_ons[-1] if h.note_ons else None)
    assert fired == [(0, 60, 100), (0, 64, 100), (0, 67, 100),
                     (0, 72, 100), (0, 64, 100)]


def test_inversion_y_clock_windows_the_voicing_per_lap():
    p, _ = make_plugin(Cartesian)
    p.set_param("inversion", 2)
    p.on_param_change("inversion", 2)
    assert _offsets(p)[0:4] == [0, 4, 7, 12]
    p._advance_y()
    assert _offsets(p)[0:4] == [4, 7, 12, 16]   # 1st inversion
    p._advance_y()
    assert _offsets(p)[0:4] == [7, 12, 16, 19]  # 2nd inversion
    p._advance_y()
    assert _offsets(p)[0:4] == [0, 4, 7, 12]    # wraps (|inv|+1 laps)


def test_inversion_negative_descends():
    p, _ = make_plugin(Cartesian)
    p.set_param("inversion", -1)
    p.on_param_change("inversion", -1)
    p._advance_y()
    # one chord-tone down: chord_tone(-1) = 7 - 12 = -5 for cell(0,0)
    assert _offsets(p)[0] == -5


def test_latch_mode_freezes_grid_against_y_clock():
    p, _ = make_plugin(Cartesian)
    p.set_param("fill_mode", "Latch")
    p.on_param_change("fill_mode", "Latch")
    p.set_param("inversion", 2)
    p.on_param_change("inversion", 2)
    before = _offsets(p)
    p._advance_y()  # Latch → no re-stamp
    assert _offsets(p) == before


def test_apply_button_stamps_once_in_latch():
    p, _ = make_plugin(Cartesian)
    p.set_param("fill_mode", "Latch")
    p.on_param_change("fill_mode", "Latch")
    # Hand-edit a cell, then Apply restores the voicing.
    grid = p.get_param("grid")
    grid[0] = {"on": True, "offset": 5}
    p.set_param("grid", grid)
    p.on_param_change("fill_apply", True)
    assert _offsets(p)[0] == 0


def test_fill_channel_records_intervals_and_flips_to_latch():
    p, _ = make_plugin(Cartesian)
    p.set_param("fill_channel", 2)  # channel index 1
    p.on_note_on(1, 60, 100)  # reference
    p.on_note_on(1, 67, 100)  # +7
    p.on_note_on(1, 55, 100)  # -5
    g = p.get_param("grid")
    assert p.get_param("fill_mode") == "Latch"
    assert (g[0]["offset"], g[1]["offset"], g[2]["offset"]) == (0, 7, -5)


def test_grid_size_limits_active_path():
    """At 2×2 only the top-left four cells (idx 0,1,4,5) are stepped."""
    p, h = make_plugin(Cartesian)
    p.set_param("sync_mode", "tempo")
    p.set_param("grid_size", 0)  # 2×2
    p.on_param_change("grid_size", 0)
    p.on_note_on(0, 60, 100)
    seen = []
    for _ in range(4):
        h.clear()
        p.on_tick("1/16")
        seen.append(p.get_param("playhead"))
    assert set(seen) == {0, 1, 4, 5}


def test_held_note_release_silences():
    p, h = make_plugin(Cartesian)
    p.set_param("sync_mode", "tempo")
    p.on_note_on(0, 60, 100)
    p.on_tick("1/16")
    h.clear()
    p.on_note_off(0, 60)
    p.on_tick("1/16")
    assert h.note_ons == []  # nothing fires without a held root


def _scale_idx(name):
    from cartesian import _SCALE_OPTIONS
    return _SCALE_OPTIONS.index(name)


def _play_triad(p, h, note):
    """Play one note and fire the first three cells (row 0 = the triad
    stacked); return the MIDI notes that fired."""
    p._held = []
    p.on_note_on(0, note, 100)
    p._step = 0
    out = []
    for _ in range(3):
        h.clear()
        p._advance_x()
        out.append(h.note_ons[-1][1] if h.note_ons else None)
    p.on_note_off(0, note)
    return out


def test_diatonic_harmonizes_the_played_degree_in_key():
    p, h = make_plugin(Cartesian)
    p.set_param("sync_mode", "tempo")
    p.set_param("harmony", "Diatonic")
    p.on_param_change("harmony", "Diatonic")
    p.set_param("scale", _scale_idx("major"))
    p.on_param_change("scale", _scale_idx("major"))
    p.set_param("root", 0)  # C major
    p.on_param_change("root", 0)
    assert _play_triad(p, h, 60) == [60, 64, 67]  # C  → C E G  (I)
    assert _play_triad(p, h, 64) == [64, 67, 71]  # E  → E G B  (iii, minor)
    assert _play_triad(p, h, 67) == [67, 71, 74]  # G  → G B D  (V)
    assert _play_triad(p, h, 62) == [62, 65, 69]  # D  → D F A  (ii, minor)


def test_chordal_keeps_a_fixed_quality_on_every_root():
    p, h = make_plugin(Cartesian)
    p.set_param("sync_mode", "tempo")
    p.set_param("scale", _scale_idx("major"))
    p.on_param_change("scale", _scale_idx("major"))
    # Chordal (default): the played note is always the tonic → major.
    assert _play_triad(p, h, 60) == [60, 64, 67]  # C major
    assert _play_triad(p, h, 64) == [64, 68, 71]  # E major (not E minor)


def test_diatonic_root_moves_the_key():
    p, h = make_plugin(Cartesian)
    p.set_param("sync_mode", "tempo")
    p.set_param("harmony", "Diatonic")
    p.on_param_change("harmony", "Diatonic")
    p.set_param("scale", _scale_idx("major"))
    p.on_param_change("scale", _scale_idx("major"))
    p.set_param("root", 2)  # D major
    p.on_param_change("root", 2)
    # In D major, playing F# (66, the third) gives the iii chord F#m: F# A C#
    assert _play_triad(p, h, 66) == [66, 69, 73]
