"""LayoutCell spring-config schema tests.

Locks in: defaults are off (force=0, home=bottom_left), and the
`to_dict` projection only emits fields when they diverge from the
default (so existing on-the-wire schemas don't get noisier).
"""

from __future__ import annotations

from raspimidihub.plugin_api import LayoutCell, LayoutGrid, XYPad


def _grid(cell: LayoutCell) -> dict:
    g = LayoutGrid(name="g", label="G", cols=2, rows=1, cells=[cell])
    return g.to_dict()["cells"][0]


class TestSpringDefaults:
    def test_layoutcell_defaults_off(self):
        c = LayoutCell(XYPad("xy", "XY"), col=1, row=1)
        assert c.spring_force == 0
        assert c.spring_home == "bottom_left"

    def test_to_dict_omits_defaults(self):
        c = LayoutCell(XYPad("xy", "XY"), col=1, row=1)
        out = _grid(c)
        assert "spring_force" not in out
        assert "spring_home" not in out

    def test_to_dict_emits_force_when_set(self):
        c = LayoutCell(XYPad("xy", "XY"), col=1, row=1, spring_force=64)
        out = _grid(c)
        assert out["spring_force"] == 64
        # home still default → omitted
        assert "spring_home" not in out

    def test_to_dict_emits_home_when_non_default(self):
        c = LayoutCell(XYPad("xy", "XY"), col=1, row=1, spring_home="center")
        out = _grid(c)
        assert out["spring_home"] == "center"
        # force still 0 → omitted
        assert "spring_force" not in out

    def test_to_dict_emits_both_when_set(self):
        c = LayoutCell(XYPad("xy", "XY"), col=1, row=1,
                       spring_force=127, spring_home="center")
        out = _grid(c)
        assert out["spring_force"] == 127
        assert out["spring_home"] == "center"
