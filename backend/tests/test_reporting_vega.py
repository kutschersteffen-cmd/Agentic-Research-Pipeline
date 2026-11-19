"""Component charts drawn by Vega-Lite in the HTML (spec 2026-11-18-house-deck-vega-lite-charts, slice 1)."""

import json
import re
import tomllib
from pathlib import Path

import pytest

from arp.reporting import vega
from arp.reporting.house_style import load_tokens
from arp.reporting.html_writer import html_slide
from arp.reporting.render_model import ChartPrim, Series, bar_plot_x, column_plot_y, line_point, palette, value_range

T = load_tokens()
P = palette(T, "light")
BAR = ChartPrim("chart", 96, 300, 1200, 500, "bar", ["Tech", "Utilities", "Energy"],
                [Series("growth", [18, 4, -2.5], [P["well"], P["highlight"], P["well"]])], "%", True)
TWO_MARKS = ["Q1 | a | 1.50", "Q2 | a | 2.00", "Q3 | a | 3.00", "Q1 | b | 4.00", "Q2 | b | −1.00", "Q3 | b | 0.25"]


def two(kind):
    return ChartPrim("chart", 96, 300, 1200, 500, kind, ["Q1", "Q2", "Q3"],
                     [Series("a", [1.5, 2, 3], [P["highlight"]] * 3), Series("b", [4, -1, 0.25], [P["series_2"]] * 3)], "", True)


def marks(svg):
    return re.findall(r'aria-label="([^"]*\| [^"]*)"', svg)


def texts(svg):
    return sorted(re.findall(r"<text[^>]*>([^<]*)</text>", svg))


def text_fills(svg):
    return {t: f for f, t in re.findall(r'<text[^>]* fill="([^"]*)"[^>]*>([^<]*)</text>', svg)}


def bars(svg):
    """(x, y, w, h) of each data mark rect, box-relative, in document order."""
    return [tuple(map(float, m)) for m in
            re.findall(r'aria-label="[^"]*"[^>]* d="M([-\d.]+),([-\d.]+)h([-\d.]+)v([-\d.]+)', svg)]


def test_ac1_chart_svg_box():
    svg = html_slide([BAR], T, "light")
    assert svg.count('data-name="chart"') == 1
    root = svg[:svg.index(">")]
    assert 'class="marks"' in root and 'width="1200"' in root and 'height="500"' in root
    assert all(d in root for d in ("left:96px", "top:300px", "width:1200px", "height:500px"))


def test_ac2_ac3_bar_marks_and_texts():
    svg = html_slide([BAR], T, "light")
    assert marks(svg) == ["Tech | growth | 18.0%", "Utilities | growth | 4.0%", "Energy | growth | −2.5%"]
    assert texts(svg) == sorted(["Tech", "Utilities", "Energy", "18.0%", "4.0%", "−2.5%"])


@pytest.mark.parametrize("kind", ["bar", "column", "stacked_column", "line"])
def test_ac4_two_series_marks(kind):
    assert marks(html_slide([two(kind)], T, "light")) == TWO_MARKS


def test_ac5_ac6_texts():
    assert texts(html_slide([two("line")], T, "light")) == sorted(["Q1", "Q2", "Q3", "a 3.00", "b 0.25"])
    for kind in ("bar", "column", "stacked_column"):
        assert texts(html_slide([two(kind)], T, "light")) == sorted(
            ["Q1", "Q2", "Q3", "1.50", "2.00", "3.00", "4.00", "−1.00", "0.25"])


def test_ac7_ac7b_ac8_text_look():
    for prim in (BAR, two("line")):
        tags = re.findall(r"<text[^>]*>", html_slide([prim], T, "light"))
        assert tags and all('font-size="24px"' in t and 'font-family="Geist' in t for t in tags)
    light, dark = text_fills(html_slide([BAR], T, "light")), text_fills(html_slide([BAR], T, "dark"))
    for cat, val in (("Tech", "18.0%"), ("Energy", "−2.5%")):
        assert (light[cat], light[val]) == (P["muted"], P["ink"])
        assert (dark[cat], dark[val]) == ("#a3acbb", "#e8ebf0")


def test_ac9_no_rect_no_white():
    svg = html_slide([BAR], T, "light").lower()
    assert "<rect" not in svg and "#ffffff" not in svg and '"white"' not in svg


def test_ac11_ac11b_line_points_and_widths():
    p = two("line")
    svg = html_slide([p], T, "light")
    pts = [tuple(map(float, m)) for m in re.findall(r'aria-label="[^"]*\|[^"]*"[^>]* transform="translate\(([-\d.]+),([-\d.]+)\)"', svg)]
    want = [line_point(p, i, v) for s in p.series for i, v in enumerate(s.values)]
    assert len(pts) == 6
    for (x, y), (wx, wy) in zip(pts, want, strict=True):  # the frame groups translate by (0, 0)
        assert abs(x + 96 - wx) <= 2 and abs(y + 300 - wy) <= 2
    assert f'stroke="{P["highlight"]}" stroke-width="6"' in svg and f'stroke="{P["series_2"]}" stroke-width="4"' in svg


def test_ac12_bar_geometry():
    col = two("column")
    lo, hi = value_range(col)
    y0, y1 = column_plot_y(col)
    sy = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)  # noqa: E731
    rects = bars(html_slide([col], T, "light"))
    for i in range(3):
        mine = [rects[i], rects[3 + i]]  # series a, then b
        centre = (min(x for x, _, _, _ in mine) + max(x + w for x, _, w, _ in mine)) / 2
        assert abs(centre - (i + 0.5) * col.w / 3) <= 2
        for (_, y, _, h), v in zip(mine, (col.series[0].values[i], col.series[1].values[i]), strict=True):
            assert abs((y if v >= 0 else y + h) - sy(v)) <= 2
    lo, hi = value_range(BAR)
    x0, x1 = bar_plot_x(BAR)
    sx = lambda v: x0 + (v - lo) / (hi - lo) * (x1 - x0)  # noqa: E731
    rects = bars(html_slide([BAR], T, "light"))
    for i, (x, y, w, h) in enumerate(rects):
        v = BAR.series[0].values[i]
        assert abs(y + h / 2 - (i + 0.5) * BAR.h / 3) <= 2
        assert abs((x + w if v >= 0 else x) - sx(v)) <= 2
    tech, energy = rects[0], rects[2]
    assert abs(energy[0] + energy[2] - tech[0]) <= 0.01 and abs(tech[0] - sx(0)) <= 2  # Energy ends where Tech starts


def test_ac13_template_values_are_escaped():
    bad = ChartPrim("chart", 96, 300, 1200, 500, "bar", ["Tech"], [Series("g", [1], ['#000"><script>x()</script>'])], '"<b>', True)
    out = html_slide([bad], T, "light")
    assert "<script" not in out and "<b>" not in out


def test_ac18_theme_file_sets_label_size(tmp_path, monkeypatch):
    def cat_sizes():
        svg = html_slide([BAR], T, "light")
        return {s for s, t in re.findall(r'<text[^>]* font-size="([^"]*)"[^>]*>([^<]*)</text>', svg) if t in BAR.categories}

    assert cat_sizes() == {"24px"}
    theme = json.loads(vega.THEME_PATH.read_text())
    theme["text"]["fontSize"] = 30
    (tmp_path / "chart_theme.json").write_text(json.dumps(theme))
    monkeypatch.setattr(vega, "THEME_PATH", tmp_path / "chart_theme.json")
    assert cat_sizes() == {"30px"}


def test_ac19_vl_convert_dependency():
    deps = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]["dependencies"]
    assert "vl-convert-python>=1.9,<2" in [d.replace(" ", "") for d in deps]
