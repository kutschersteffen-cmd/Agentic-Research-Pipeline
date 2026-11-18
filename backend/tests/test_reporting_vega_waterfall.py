"""Waterfall component chart kind, HTML and native PowerPoint (spec 2026-11-18-house-deck-vega-lite-charts, slice 3)."""

import re

import pytest
from pptx import Presentation
from pydantic import ValidationError

from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.house_style import load_tokens
from arp.reporting.html_render import render_deck_html
from arp.reporting.lint import lint_deck
from arp.reporting.render_model import VisualDataError, column_plot_y, palette, render_slide, value_range
from arp.reporting.slide_fill import fill_slide
from arp.reporting.storyline import draft_storyline
from arp.schemas.chart_specs import ChartSpec
from arp.schemas.reporting import (
    DatasetColumn,
    Deck,
    LayoutInstructions,
    OutputFormat,
    QuantitativeDataset,
    ReportRequest,
    SlideContent,
    Storyline,
    StorylineSlide,
)
from arp.schemas.visuals import Chart

T = load_tokens()
P = palette(T, "light")
ROWS = [("Start", 100), ("Funding cost", -14), ("Fees", -6), ("Volume", 4), ("FX", -2), ("End", 82)]
W = Chart(kind="waterfall", data=ChartSpec(dataset_id="w", category_column="step", value_columns=["v"]), highlight="Funding cost")


def _ds(rows):
    return QuantitativeDataset(dataset_id="w", name="Bridge", columns=[DatasetColumn(name="step"), DatasetColumn(name="v")],
                               rows=[{"step": s, "v": v} for s, v in rows])


def _deck(visual=W):
    return Deck(title="D", slides=[SlideContent(headline="H", kicker="K", visual=visual)])


def _svg(rows=ROWS):
    html = render_deck_html(_deck(), [_ds(rows)])
    start = html.index("<svg", html.index('data-name="chart"') - 200)
    return html[start:html.index("</svg>", start)]


def _marks(svg):
    return re.findall(r'<path[^>]*aria-label="([^"]*\| [^"]*)"[^>]*>', svg)


def test_ac30_waterfall_plots_one_value_column():
    with pytest.raises(ValidationError, match="a waterfall plots 1 value column"):
        Chart(kind="waterfall", data=ChartSpec(dataset_id="w", category_column="step", value_columns=["v", "u"]))


def test_ac31_ac32_marks_and_texts():
    svg = _svg()
    assert _marks(svg) == ["Start | v | 100", "Funding cost | v | −14", "Fees | v | −6", "Volume | v | +4", "FX | v | −2", "End | v | 82"]
    assert sorted(re.findall(r"<text[^>]*>([^<]*)</text>", svg)) == sorted(
        ["Start", "Funding cost", "Fees", "Volume", "FX", "End", "100", "−14", "−6", "+4", "−2", "82"])


def test_ac33_fills():
    tags = re.findall(r'<path[^>]*aria-label="[^"]*\| [^"]*"[^>]*>', _svg())
    fills = [re.search(r'fill="([^"]*)"', t).group(1).lower() for t in tags]
    assert fills == [P["ink"], P["highlight"], P["series_2"], P["series_2"], P["series_2"], P["ink"]]


def test_ac34_bars_span_the_running_totals():
    prims = {p.name: p for p in render_slide(_deck().slides[0], 0, _deck(), T, {"w": _ds(ROWS)})}
    chart = prims["chart"]
    lo, hi = value_range(chart)
    y0, y1 = column_plot_y(chart)
    sy = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)  # noqa: E731
    rects = [tuple(map(float, m)) for m in re.findall(r'aria-label="[^"]*"[^>]* d="M([-\d.]+),([-\d.]+)h([-\d.]+)v([-\d.]+)', _svg())]
    spans = [(0, 100), (100, 86), (86, 80), (80, 84), (84, 82), (0, 82)]
    assert len(rects) == 6
    for (_, y, _, h), (a, b) in zip(rects, spans, strict=True):
        top, bottom = min(y, y + h), max(y, y + h)
        assert abs(top - sy(max(a, b))) <= 2 and abs(bottom - sy(min(a, b))) <= 2


def test_ac35_native_stacked_column(tmp_path):
    out = build_house_pptx(_deck(), [_ds(ROWS)], tmp_path / "w.pptx")
    chart = {s.name: s for s in Presentation(str(out)).slides[0].shapes}["chart"].chart
    assert chart.chart_type == 52
    base, shown = chart.plots[0].series
    assert list(shown.values) == [100, 14, 6, 4, 2, 82] and list(base.values) == [0, 86, 80, 80, 82, 0]
    assert base.format.fill.type == 5  # MSO_FILL.BACKGROUND: invisible
    assert [str(shown.points[i].format.fill.fore_color.rgb).lower() for i in range(6)] == [
        "121722", "2a78d6", "c4ccd7", "c4ccd7", "c4ccd7", "121722"]
    assert [shown.points[i].data_label.text_frame.text for i in range(6)] == ["100", "−14", "−6", "+4", "−2", "82"]


def test_ac36_no_chart_picture_finding():
    assert not [f for f in lint_deck(_deck(), ReportRequest(title="T", qualitative_notes="n", datasets=[_ds(ROWS)]))
                if f.rule == "chart_picture"]


@pytest.mark.parametrize("rows, message", [
    ([("Start", 100), *[(f"S{k}", 1) for k in range(9)], ("End", 109)], "a waterfall has 3 to 10 rows (got 11)"),
    ([("Start", 100), ("End", 100)], "a waterfall has 3 to 10 rows (got 2)"),
    ([*ROWS[:-1], ("End", 80)], "waterfall end total 80 is not the start plus the changes (82)"),
    ([("Start", 10), ("Loss", -30), ("End", -20)], "a waterfall's running total must stay at or above 0 (Loss: −20)"),
])
def test_ac37_ac37b_ac38_ac39_rejected(rows, message):
    visual = W.model_copy(update={"highlight": None})
    with pytest.raises(VisualDataError, match=re.escape(message)):
        render_slide(_deck(visual).slides[0], 0, _deck(visual), T, {"w": _ds(rows)})


async def test_ac40_prompt_names_the_chart_kinds(fake_llm):
    llm = fake_llm({"Storyline": [Storyline(title="T", slides=[StorylineSlide(headline="h", purpose="p")])]})
    request = ReportRequest(title="T", qualitative_notes="n", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK))
    await draft_storyline(request, llm)
    assert "bar, column, stacked_column, line, waterfall or heatmap" in llm.prompts[0]


async def test_ac41_waterfall_slide_fills(fake_llm):
    story = StorylineSlide(headline="Funding cost took most of the gap.", purpose="p", visual="chart", chart_kind="waterfall",
                           source_refs=["w"])
    llm = fake_llm({"SlideContent": [SlideContent(headline="h", visual=W)]})
    slide, findings, _ = await fill_slide(story, 1, ReportRequest(title="T", qualitative_notes="n", datasets=[_ds(ROWS)]), llm)
    assert slide.visual.type == "chart" and slide.visual.kind == "waterfall"
    assert findings == []
