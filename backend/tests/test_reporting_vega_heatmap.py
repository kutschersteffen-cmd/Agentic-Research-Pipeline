"""Heatmap component chart kind: HTML, PowerPoint picture, lint (spec 2026-11-18-house-deck-vega-lite-charts, slice 4)."""

import io
import re

import pytest
from PIL import Image
from pptx import Presentation
from pydantic import ValidationError

from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.house_style import load_tokens
from arp.reporting.html_render import render_deck_html
from arp.reporting.lint import lint_deck
from arp.reporting.render_model import VisualDataError, palette, render_slide
from arp.schemas.chart_specs import ChartSpec
from arp.schemas.reporting import DatasetColumn, Deck, QuantitativeDataset, ReportRequest, SlideContent
from arp.schemas.visuals import Callout, Chart

T = load_tokens()
P = palette(T, "light")
ROWS = [("api", "Mon", 3), ("api", "Tue", 5), ("cli", "Mon", 1), ("cli", "Tue", 0)]
H = Chart(kind="heatmap", data=ChartSpec(dataset_id="h", category_column="day", y_column="pkg", value_columns=["commits"]))


def _ds(rows):
    return QuantitativeDataset(dataset_id="h", name="Commits",
                               columns=[DatasetColumn(name="pkg"), DatasetColumn(name="day"), DatasetColumn(name="commits")],
                               rows=[{"pkg": p, "day": d, "commits": v} for p, d, v in rows])


def _deck(visual=H):
    return Deck(title="D", slides=[SlideContent(headline="H", kicker="K", visual=visual)])


def _svg(rows=ROWS, visual=H):
    html = render_deck_html(_deck(visual), [_ds(rows)])
    start = html.index("<svg", html.index('data-name="chart"') - 200)
    return html[start:html.index("</svg>", start)]


def _marks(svg):
    return re.findall(r'<path[^>]*aria-label="([^"]*\| [^"]*)"[^>]*>', svg)


def _fill(tag):
    return re.search(r'fill="([^"]*)"', tag).group(1).lower()


def _texts(svg):
    return {t: _fill(tag) for tag, t in re.findall(r"(<text[^>]*>)([^<]*)</text>", svg)}


def test_ac42_heatmap_needs_y_column():
    with pytest.raises(ValidationError, match="a heatmap needs y_column"):
        Chart(kind="heatmap", data=ChartSpec(dataset_id="h", category_column="day", value_columns=["commits"]))


def test_ac43_heatmap_plots_one_value_column():
    with pytest.raises(ValidationError, match="a heatmap plots 1 value column"):
        Chart(kind="heatmap", data=ChartSpec(dataset_id="h", category_column="day", y_column="pkg", value_columns=["commits", "x"]))


def test_ac44_ac45_marks_and_texts():
    svg = _svg()
    assert _marks(svg) == ["api | Mon | 3", "api | Tue | 5", "cli | Mon | 1", "cli | Tue | 0"]
    assert sorted(re.findall(r"<text[^>]*>([^<]*)</text>", svg)) == sorted(["api", "cli", "Mon", "Tue", "3", "5", "1", "0"])


def test_ac46_ac47_cell_and_label_colours():
    svg = _svg()
    fills = {m: _fill(t) for t, m in re.findall(r'(<path[^>]*aria-label="([^"]*\| [^"]*)"[^>]*>)', svg)}
    assert fills["cli | Tue | 0"] == P["ground"].lower() and fills["api | Tue | 5"] == P["highlight"].lower()
    texts = _texts(svg)
    assert [texts[t] for t in ("3", "5", "1", "0")] == [P["panel"].lower()] * 2 + [P["ink"].lower()] * 2


def test_ac47b_all_equal_values():
    svg = _svg([(p, d, 2) for p, d, _ in ROWS])
    tags = re.findall(r'<path[^>]*aria-label="[^"]*\| [^"]*"[^>]*>', svg)
    assert len(tags) == 4 and {_fill(t) for t in tags} == {P["highlight"].lower()}
    assert _texts(svg)["2"] == P["panel"].lower()


def test_ac48_missing_cell_has_no_mark():
    marks = _marks(_svg(ROWS[:3]))
    assert len(marks) == 3 and not any(m.startswith("cli | Tue |") for m in marks)


def test_ac49_at_most_8_rows_and_10_columns():
    rows = [(f"p{i}", d, 1) for i in range(9) for d in ("Mon", "Tue")]
    with pytest.raises(VisualDataError, match=re.escape("a heatmap shows at most 8 rows and 10 columns (got 9 × 2)")):
        render_slide(_deck().slides[0], 0, _deck(), T, {"h": _ds(rows)})


def test_ac50_duplicate_cell():
    with pytest.raises(VisualDataError, match=re.escape("duplicate heatmap cell (api, Mon)")):
        render_slide(_deck().slides[0], 0, _deck(), T, {"h": _ds([*ROWS, ("api", "Mon", 4)])})


def test_ac51_powerpoint_picture(tmp_path):
    path = tmp_path / "d.pptx"
    build_house_pptx(_deck(), [_ds(ROWS)], path)
    shapes = [s for s in Presentation(str(path)).slides[0].shapes if s.name == "chart"]
    assert len(shapes) == 1 and shapes[0].shape_type == 13 and not shapes[0].has_chart  # 13: picture
    w, h = Image.open(io.BytesIO(shapes[0].image.blob)).size
    assert abs(w - 2 * shapes[0].width / T.emu_per_px) <= 1 and abs(h - 2 * shapes[0].height / T.emu_per_px) <= 1


def test_ac52_chart_picture_finding():
    found = [f for f in lint_deck(_deck(), ReportRequest(title="t", qualitative_notes="n", datasets=[_ds(ROWS)])) if f.rule == "chart_picture"]
    assert [(f.slide, f.slot, f.stage, f.message) for f in found] == [
        (0, "chart", "lint", "heatmap chart is a picture in the PowerPoint: change its data in ARP and build again")]


def test_heatmap_has_no_callout():
    visual = H.model_copy(update={"callout": Callout(category="Mon", text="busy")})
    names = [p.name for p in render_slide(_deck(visual).slides[0], 0, _deck(visual), T, {"h": _ds(ROWS)})]
    assert "chart" in names and not any(n.startswith("callout") for n in names)
