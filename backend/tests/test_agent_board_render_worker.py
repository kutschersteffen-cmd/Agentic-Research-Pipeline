"""Agent board chart rendering on the Board (spec agent-board, slice 3): dark grid lines take the palette's `line`
colour, and the chart's own title is dropped because the block card shows the title."""
from __future__ import annotations

from arp.agent_board.render_worker import themed_svgs
from arp.reporting.house_style import load_tokens
from arp.reporting.render_model import palette

CHART = {"title": "Chart title text", "mark": "bar", "data": {"values": [{"s": "Energy", "w": 0.125}, {"s": "Utilities", "w": 0.31}]},
         "encoding": {"x": {"field": "s", "type": "nominal"}, "y": {"field": "w", "type": "quantitative"}}}


def test_grid_lines_take_the_palette_line_colour_in_both_schemes():
    out = themed_svgs(CHART)
    for mode in ("light", "dark"):
        assert palette(load_tokens(), mode)["line"] in out[mode]
    assert "#ddd" not in out["dark"]


def test_the_chart_title_is_not_drawn_twice():
    out = themed_svgs(CHART)
    assert "Chart title text" not in out["light"] and "Chart title text" not in out["dark"]
    assert "Utilities" in out["light"]
