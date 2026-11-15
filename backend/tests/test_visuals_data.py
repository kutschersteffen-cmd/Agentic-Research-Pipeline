"""Data visuals: chart (+ insight) and comparison table (spec 2026-11-15-slide-components)."""

import re

import pytest
from pptx import Presentation

from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.house_style import load_tokens
from arp.reporting.html_render import render_deck_html
from arp.reporting.render_model import VISUALS, ChartPrim, RenderCtx, VisualDataError, body_box, line_point, render_slide
from arp.schemas.chart_specs import ChartSpec, TableSpec
from arp.schemas.reporting import DatasetColumn, Deck, QuantitativeDataset, SlideContent
from arp.schemas.visuals import Callout, Chart, ComparisonTable, Insight


def _ds(ds_id, name, cols, rows):
    return QuantitativeDataset(dataset_id=ds_id, name=name, columns=[DatasetColumn(name=c) for c in cols],
                               rows=[dict(zip(cols, r, strict=True)) for r in rows])


EPS = _ds("eps", "EPS growth 2025", ["sector", "growth_pct"],
          [("Tech", 18), ("Financials", 12), ("Market", 11), ("Industrials", 9), ("Energy", 6), ("Utilities", 4)])
QUARTERS = ["Q1 24", "Q2 24", "Q3 24", "Q4 24", "Q1 25", "Q2 25", "Q3 25", "Q4 25"]
EPS_Q = _ds("eps_q", "Sector earnings, quarterly", ["quarter", "utilities", "market"],
            list(zip(QUARTERS, [9.1, 8.4, 7.0, 5.9, 5.2, 4.6, 4.1, 4.0], [11.5, 11.2, 11.0, 10.8, 10.9, 11.1, 11.0, 11.0], strict=True)))
NAMES = _ds("names", "Utility holdings", ["Company", "Weight %", "EPS growth %", "Net debt / EBITDA", "Action"],
            [("Northgrid", 2.1, 7, 4.2, "Hold"), ("Solvane Power", 1.6, 5, 5.1, "Hold"), ("Eastwater", 1.2, 2, 6.0, "Engage"),
             ("Kestrel Gas", 0.9, -1, 5.8, "Engage"), ("Brightline", 0.7, 9, 3.4, "Add")])

BAR = Chart(data=ChartSpec(dataset_id="eps", category_column="sector", value_columns=["growth_pct"]), kind="bar", unit="%",
            highlight="Utilities", insight=Insight(stat="−7 pts", headline="Slowest of six sectors, for the second year running",
                                                   points=["Funding costs took most of the gap", "Tariffs reset every 3–5 years"]))
LINE = Chart(data=ChartSpec(dataset_id="eps_q", category_column="quarter", value_columns=["utilities", "market"]), kind="line",
             unit="%", highlight="utilities", callout=Callout(category="Q3 24", text="Funding costs start rising"))
TABLE = ComparisonTable(table=TableSpec(dataset_id="names"), highlight_column="Net debt / EBITDA",
                        total_row={"Weight %": "sum", "EPS growth %": "mean", "Net debt / EBITDA": "mean"})


def _deck(visual):
    return Deck(title="D", slides=[SlideContent(headline="H", kicker="K", visual=visual)])


def _pptx_shapes(tmp_path, visual, ds):
    out = build_house_pptx(_deck(visual), [ds], tmp_path / "d.pptx")
    return {sh.name: sh for sh in Presentation(str(out)).slides[0].shapes}


def _prims(visual, ds):
    return {p.name: p for p in render_slide(_deck(visual).slides[0], 0, _deck(visual), load_tokens(), {ds.dataset_id: ds})}


def _ctx(ds):
    return RenderCtx(load_tokens(), "light", _deck(None), 0, {ds.dataset_id: ds})


def _rgb(fill):
    return str(fill.fore_color.rgb).lower()


def test_ac6_bar_insight(tmp_path):
    shapes = _pptx_shapes(tmp_path, BAR, EPS)
    chart = shapes["chart"].chart
    assert chart.chart_type == 57  # BAR_CLUSTERED
    ser = chart.plots[0].series[0]
    assert len(list(ser.values)) == 6
    fills = {cat: _rgb(ser.points[i].format.fill) for i, cat in enumerate(chart.plots[0].categories)}
    assert fills.pop("Utilities") == "2a78d6"
    assert set(fills.values()) == {"eaeef3"}
    dl = chart.plots[0].data_labels
    assert chart.plots[0].has_data_labels and dl.number_format.rstrip('"').endswith("%")
    card = shapes["card:insight"]
    assert round(card.width / 9525) == 520 and _rgb(card.fill) == "f4f6f9"
    p = _prims(BAR, EPS)
    assert p["chart"].x + p["chart"].w + 48 == p["card:insight"].x  # 48 px gap
    assert p["card:insight"].x + 520 == 96 + 1728


def test_chart_without_insight_is_full_width():
    p = _prims(LINE, EPS_Q)
    assert (p["chart"].x, p["chart"].w) == (96, 1728)
    assert "card:insight" not in p


def test_ac8_totals(tmp_path):
    tbl = _pptx_shapes(tmp_path, TABLE, NAMES)["table"].table
    total = [tbl.cell(6, ci).text for ci in range(5)]
    assert total[1:4] == ["6.5", "4.4", "4.9"]
    header = [tbl.cell(0, ci).text for ci in range(5)]
    hl = header.index("NET DEBT / EBITDA")
    assert _rgb(tbl.cell(0, hl).fill) == "121722"
    assert tbl.cell(3, hl).text == "6.0"  # as written


def test_table_align_and_mono_from_data():
    t = _prims(TABLE, NAMES)["table"]
    assert t.align == ["left", "right", "right", "right", "left"]
    assert t.mono == [False, True, True, True, False]
    assert t.highlight_col == 3
    assert t.rows[3][2] == "−1"


def test_comparison_table_accepts_tablespec_default_max_rows():
    ds = _ds("big", "Big", ["name", "v"], [(f"n{i}", i) for i in range(12)])
    t = _prims(ComparisonTable(table=TableSpec(dataset_id="big")), ds)["table"]
    assert len(t.rows) == 8
    with pytest.raises(ValueError):
        ComparisonTable(table=TableSpec(dataset_id="big", max_rows=9))


def test_ac32_cap(tmp_path):
    rows = [(f"S{i:02d}", v) for i, v in enumerate([50, 3, 40, 2, 30, 1, 25, 5, 20, 4, 15, 12, 10, 11])]
    ds = _ds("many", "Many", ["sector", "v"], rows)
    visual = Chart(data=ChartSpec(dataset_id="many", category_column="sector", value_columns=["v"]), kind="bar")
    ctx = _ctx(ds)
    chart = next(p for p in VISUALS["chart"](visual, body_box(ctx.tokens), ctx) if isinstance(p, ChartPrim))
    assert len(chart.categories) == 10 and chart.categories[-1] == "Other"
    assert chart.series[0].values[-1] == sum(sorted(v for _, v in rows)[:5])
    assert [f.rule for f in ctx.findings] == ["chart_capped"]
    assert ctx.findings[0].stage == "fit" and ctx.findings[0].slide == 0
    ser = _pptx_shapes(tmp_path, visual, ds)["chart"].chart.plots[0].series[0]
    assert len(list(ser.values)) == 10


def test_ac34_line(tmp_path):
    shapes = _pptx_shapes(tmp_path, LINE, EPS_Q)
    chart = shapes["chart"].chart
    assert chart.chart_type == 65  # LINE_MARKERS
    series = {s.name: s for s in chart.plots[0].series}
    assert set(series) == {"utilities", "market"}
    assert all(len(list(s.values)) == 8 for s in series.values())
    assert str(series["utilities"].format.line.color.rgb).lower() == "2a78d6"
    assert str(series["market"].format.line.color.rgb).lower() == "c4ccd7"
    assert series["utilities"].format.line.width == 6 * 9525 and series["market"].format.line.width == 4 * 9525  # highlight is heavier
    assert 'stroke="#2a78d6" stroke-width="6"' in render_deck_html(_deck(LINE), [EPS_Q]).lower()
    assert "callout" in shapes
    p = _prims(LINE, EPS_Q)
    x, _ = line_point(p["chart"], 2, 7.0)
    assert p["callout"].x <= x <= p["callout"].x + p["callout"].w
    assert p["callout:text"].text == "Funding costs start rising"


def test_bar_negative_values():
    ds = _ds("neg", "Neg", ["k", "v"], [("a", 3), ("b", -1)])
    html = render_deck_html(_deck(Chart(data=ChartSpec(dataset_id="neg", category_column="k", value_columns=["v"]), kind="bar")), [ds])
    svg = html[html.index('data-name="chart"'):]
    svg = svg[:svg.index("</svg>")]
    (ax, aw), (bx, bw) = [(float(x), float(w)) for x, w in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', svg)]
    assert bx + bw == pytest.approx(ax)  # the negative bar ends at the zero line, where the positive one starts
    assert bx < ax
    assert ">−1<" in svg


def test_chart_non_numeric_column_falls_back():
    ds = _ds("txt", "Txt", ["k", "v"], [("a", "high"), ("b", "low")])
    visual = Chart(data=ChartSpec(dataset_id="txt", category_column="k", value_columns=["v"]), kind="column")
    with pytest.raises(VisualDataError):
        VISUALS["chart"](visual, body_box(load_tokens()), _ctx(ds))


def test_unknown_dataset_or_column_raises():
    ctx = _ctx(EPS)
    with pytest.raises(VisualDataError):
        VISUALS["chart"](Chart(data=ChartSpec(dataset_id="nope", category_column="sector", value_columns=["growth_pct"]), kind="bar"),
                         body_box(ctx.tokens), ctx)
    with pytest.raises(VisualDataError):
        VISUALS["chart"](Chart(data=ChartSpec(dataset_id="e", category_column="k", value_columns=["v"]), kind="line"),
                         body_box(ctx.tokens), _ctx(_ds("e", "Empty", ["k", "v"], [])))
    with pytest.raises(VisualDataError):
        VISUALS["comparison_table"](ComparisonTable(table=TableSpec(dataset_id="eps", columns=["sector", "nope"])), body_box(ctx.tokens), ctx)


LONG = "Regulated networks and integrated utilities (Europe)"


@pytest.mark.parametrize("kind, cats", [("bar", [LONG, "Tech"]), ("column", [f"Sector {LONG} {k}" for k in range(6)])])
def test_clipped_category_label_is_overflow(kind, cats):
    ds = _ds("s", "S", ["k", "v"], [(c, k + 1) for k, c in enumerate(cats)])
    ctx = _ctx(ds)
    VISUALS["chart"](Chart(data=ChartSpec(dataset_id="s", category_column="k", value_columns=["v"]), kind=kind), body_box(ctx.tokens), ctx)
    assert [(f.rule, f.slot, f.stage, f.slide) for f in ctx.findings] == [("overflow", "chart", "fit", 0)]


def test_short_category_labels_are_fine():
    ctx = _ctx(EPS)
    VISUALS["chart"](BAR, body_box(ctx.tokens), ctx)
    assert ctx.findings == []


@pytest.mark.parametrize("kind", ["bar", "column"])
def test_pptx_axes_match_html(tmp_path, kind):
    ds = _ds("neg", "Neg", ["k", "v"], [("a", 3), ("b", -1)])
    chart = _pptx_shapes(tmp_path, Chart(data=ChartSpec(dataset_id="neg", category_column="k", value_columns=["v"]), kind=kind), ds)["chart"].chart
    assert (chart.value_axis.minimum_scale, chart.value_axis.maximum_scale) == (-1, 3)  # the HTML's [min(0, lo), max(0, hi)]
    xml = chart._chartSpace.xml
    assert re.search(r'<c:catAx>.*<c:tickLblPos val="low"/>.*</c:catAx>', xml, re.S)  # labels clear of negative bars
    assert "<c:manualLayout>" in xml and '<c:layoutTarget val="inner"/>' in xml


@pytest.mark.parametrize("v", ["nan", "inf", "-inf", float("nan")])
def test_number_rejects_non_finite(v):
    from arp.reporting.visuals._common import number

    with pytest.raises(VisualDataError):
        number(v)


def test_unit_with_quote_gives_valid_format():
    from arp.reporting.pptx_writer import _number_format

    assert _number_format([1.5, -2.0], 'm"x') == '0.0"mx";"−"0.0"mx"'
