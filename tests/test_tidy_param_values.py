"""Tests for the schema-driven tidy-tool that strips stranded
_param_values keys (e.g. when a plugin's schema is updated and old
saved configs still carry the previous version's keys)."""

from raspimidihub.plugin_api import (
    Button,
    DropButtonRow,
    Group,
    Knob,
    LayoutCell,
    LayoutGrid,
    PluginBase,
    Wheel,
    schema_param_keys,
)


class _MiniPlugin(PluginBase):
    """A schema covering the patterns we care about: top-level Param,
    Group of Params, LayoutGrid with auxiliary param pointers, plus a
    DropButtonRow with its own auxiliary pointers."""
    NAME = "Mini"
    params = [
        Wheel("speed", "Speed", min=0, max=10, default=4),
        Group("Config", children=[
            Knob("gain", "Gain", min=0, max=127, default=64),
        ]),
        LayoutGrid(
            "grid", "",
            cols=2, rows=1,
            labels_param="cell_labels",
            bindings_param="cell_bindings",
            cells=[
                LayoutCell(Knob("k0", "K0"), col=1, row=1),
                LayoutCell(Button("b0", "B0"), col=2, row=1),
            ],
        ),
        DropButtonRow(
            "drops", "DROPS",
            count=2,
            states_param="drop_states",
            snapshots_param="drop_snapshots",
            modes_param="drop_modes",
            labels_param="drop_labels",
            schedule_param="drop_schedule",
            sync_param="drop_sync",
            fade_param="drop_fade",
            notes_param="drop_notes",
        ),
    ]


class TestSchemaParamKeys:
    def test_collects_top_level_names(self):
        keys = schema_param_keys(_MiniPlugin.params)
        assert "speed" in keys
        assert "drops" in keys

    def test_collects_group_children(self):
        keys = schema_param_keys(_MiniPlugin.params)
        assert "gain" in keys

    def test_collects_layout_grid_cells(self):
        keys = schema_param_keys(_MiniPlugin.params)
        assert "k0" in keys
        assert "b0" in keys

    def test_collects_layout_grid_aux_pointers(self):
        keys = schema_param_keys(_MiniPlugin.params)
        assert "cell_labels" in keys
        assert "cell_bindings" in keys

    def test_collects_drop_button_row_aux_pointers(self):
        keys = schema_param_keys(_MiniPlugin.params)
        assert "drop_states" in keys
        assert "drop_snapshots" in keys
        assert "drop_modes" in keys
        assert "drop_labels" in keys
        assert "drop_schedule" in keys
        # Phase 5 polish: per-button sync / fade / note refs
        assert "drop_sync" in keys
        assert "drop_fade" in keys
        assert "drop_notes" in keys

    def test_does_not_collect_dunder_or_private_attrs(self):
        """The auxiliary-pointer walk looks for attrs ending in `_param`
        but skipping private/dunder. Make sure things like __class__ or
        Param's internal state don't pollute the result."""
        keys = schema_param_keys(_MiniPlugin.params)
        # No internal Python attrs.
        assert not any(k.startswith("_") for k in keys)


class TestTidyParamValues:
    def test_drops_stranded_keys(self):
        p = _MiniPlugin()
        p._param_values = {
            "speed": 5,
            "gain": 100,
            "k0": 42,
            "drops": {"action": "idle"},
            # Stranded — schema doesn't declare these.
            "pad": "captured",
            "pad_snapshot": {"k1": 99},
            "old_legacy_thing": True,
        }
        dropped = p.tidy_param_values()

        assert sorted(dropped) == ["old_legacy_thing", "pad", "pad_snapshot"]
        assert "pad" not in p._param_values
        assert "pad_snapshot" not in p._param_values
        assert "old_legacy_thing" not in p._param_values
        # Valid keys are preserved.
        assert p._param_values["speed"] == 5
        assert p._param_values["gain"] == 100
        assert p._param_values["k0"] == 42
        assert p._param_values["drops"] == {"action": "idle"}

    def test_preserves_aux_pointers(self):
        """Keys named by *_param attributes (e.g. cell_labels,
        drop_states) are valid even though they're auxiliary, not
        top-level."""
        p = _MiniPlugin()
        p._param_values = {
            "speed": 5,
            "cell_labels": {"k0": "Cutoff"},
            "drop_states": {"0": "captured", "1": "idle"},
            "drop_snapshots": {"0": {"k0": 80}},
            "stale_key": "should disappear",
        }
        dropped = p.tidy_param_values()

        assert dropped == ["stale_key"]
        assert "cell_labels" in p._param_values
        assert "drop_states" in p._param_values
        assert "drop_snapshots" in p._param_values

    def test_empty_param_values_no_op(self):
        p = _MiniPlugin()
        p._param_values = {}
        assert p.tidy_param_values() == []
        assert p._param_values == {}

    def test_all_valid_no_drops(self):
        p = _MiniPlugin()
        p._param_values = {"speed": 5, "k0": 10}
        assert p.tidy_param_values() == []
