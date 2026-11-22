"""HTML and PPTX writers for render-model primitives, and the visual/legacy dispatch (spec 2026-11-15-slide-components)."""

import json
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.enum.text import PP_ALIGN

from arp.reporting import render_model
from arp.reporting.browser import _page
from arp.reporting.deck_compat import deck_from_plan
from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.house_style import load_tokens, with_frame
from arp.reporting.html_render import render_deck_html
from arp.reporting.render_model import ChartPrim, Line, Rect, Series, TablePrim, Text
from arp.reporting.style_profile import ingest_template
from arp.schemas.reporting import (
    Box,
    ContentItem,
    DatasetColumn,
    Deck,
    QuantitativeDataset,
    ReportPlan,
    ReportSection,
    SlideContent,
)
from arp.schemas.visuals import Points
from arp.storage.reporting_store import ReportingStore
from tests.fixtures.frame_template import frame_fonts, make_frame_pptx
from tests.fixtures.stress_deck import stress_deck

EPS = QuantitativeDataset(dataset_id="eps", name="EPS growth 2025", columns=[DatasetColumn(name="v")], rows=[{"v": i} for i in range(6)])
GOLDEN = Path(__file__).parent / "golden" / "legacy_stress_shapes.json"


@pytest.fixture(autouse=True)
def stub_points(monkeypatch):
    """One of each primitive kind, so both writers are exercised before the real visuals exist."""

    def stub(visual, box, ctx):
        c = render_model.palette(ctx.tokens, ctx.mode)
        return [
            Rect("card", box.x, box.y, 400, 200, c["ground"], line=c["line"], line_w=2, emphasis=True),
            Text("card:text", box.x + 24, box.y + 24, 352, 80, "Point one\nsecond line", 28, 600, "Hanken Grotesk", c["ink"], anchor="middle"),
            Text("label", box.x + 420, box.y, 200, 40, "Today", 20, 400, "Hanken Grotesk", c["panel"], align="center", fill_under=c["ink"]),
            Text("num", box.x + 640, box.y, 200, 120, "01", 96, 600, "Hanken Grotesk", c["line"], outline=True),
            Line("connector:1", [(box.x + 420, box.y + 100), (box.x + 600, box.y + 100), (box.x + 600, box.y + 180)], c["ink"], 2, arrow=True),
            Line("rule", [(box.x, box.y + 210), (box.x + 400, box.y + 210)], c["line"], 1),
            ChartPrim("chart", box.x + 860, box.y, 860, 280, "bar", ["Tech", "Utilities"], [Series("growth", [18, 4], [c["series_2"], c["highlight"]])], "%", True),
            ChartPrim("chart:2", box.x + 860, box.y + 300, 420, 280, "line", ["Q1", "Q2", "Q3"],
                      [Series("u", [9.1, 8.4, 7.0], [c["highlight"]] * 3), Series("m", [11.5, 11.2, 11.0], [c["series_2"]] * 3)], "%", True),
            TablePrim("table", box.x, box.y + 300, 840, 280, ["Company", "Weight %"], [["Northgrid", "2.1"], ["Eastwater", "1.2"]],
                      ["Total", "3.3"], 1, {}, align=["left", "right"], mono=[False, True]),
        ]

    monkeypatch.setitem(render_model.VISUALS, "points", stub)


def _slide(**kw) -> SlideContent:
    return SlideContent(**{"headline": "EPS grew 12%", "kicker": "Earnings", "source_refs": ["eps"], "visual": Points(points=["a", "b", "c"]), **kw})


def _legacy() -> SlideContent:
    return SlideContent(headline="Legacy", layout="bullets", variant="three", slots={"items": ["x"]}, source_refs=["eps"])


def _pptx_boxes(path: Path, index: int) -> dict[str, tuple]:
    slide = Presentation(str(path)).slides[index]
    return {sh.name: (sh.left / 9525, sh.top / 9525, sh.width / 9525, sh.height / 9525) for sh in slide.shapes}


async def test_ac1_boxes_match(tmp_path):
    deck = Deck(title="D", slides=[_legacy(), _slide()])
    out = build_house_pptx(deck, [EPS], tmp_path / "d.pptx")
    pptx = _pptx_boxes(out, 1)
    async with _page(render_deck_html(deck, [EPS])) as page:
        html = await page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('section.slide')[1].querySelectorAll('[data-name]')]
            .map(el => { const r = el.getBoundingClientRect(), s = el.closest('section.slide').getBoundingClientRect();
                         return [el.dataset.name, [r.left - s.left, r.top - s.top, r.width, r.height]]; }))""")
    names = {"strip:1", "strip:5", "kicker", "title", "source:rule", "source", "page", "card", "card:text", "label", "num",
             "connector:1", "rule", "chart", "chart:2", "table"}
    assert names <= set(html)
    assert set(html) == set(pptx), "both writers draw the same primitives"
    assert "subtitle" not in html  # empty text is skipped
    for name, box in html.items():
        assert box == pytest.approx(list(pptx[name]), abs=1), name


def test_legacy_slide_keeps_slots_in_mixed_deck(tmp_path):
    deck = Deck(title="D", slides=[_legacy(), _slide()])
    html = render_deck_html(deck, [EPS])
    assert 'data-slot="items"' in html and 'data-name="card"' in html
    prs = Presentation(str(build_house_pptx(deck, [EPS], tmp_path / "d.pptx")))
    assert "slot:items" in {sh.name for sh in prs.slides[0].shapes}
    assert "accent_rule" not in {sh.name for sh in prs.slides[1].shapes}


def test_pptx_primitive_details(tmp_path):
    prs = Presentation(str(build_house_pptx(Deck(title="D", slides=[_slide()]), [EPS], tmp_path / "d.pptx")))
    shapes = {sh.name: sh for sh in prs.slides[0].shapes}
    xml = shapes["connector:1"]._element.xml
    assert "a:tailEnd" in xml and "<a:noFill/>" in xml
    assert "a:tailEnd" not in shapes["rule"]._element.xml
    chart = shapes["chart"].chart
    assert chart.chart_type == 57  # BAR_CLUSTERED
    assert chart.plots[0].data_labels.number_format == '0"%"'
    assert str(chart.plots[0].series[0].points[1].format.fill.fore_color.rgb) == "2A78D6"
    line = shapes["chart:2"].chart
    assert line.chart_type == 65  # LINE_MARKERS
    assert line.plots[0].data_labels.number_format == '0.0"%"'
    tbl = shapes["table"].table
    assert [tbl.cell(r, 0).text for r in range(4)] == ["COMPANY", "Northgrid", "Eastwater", "Total"]
    assert "a:lnB" in tbl.cell(0, 0)._tc.xml and "a:lnT" in tbl.cell(3, 0)._tc.xml
    assert shapes["kicker"].text_frame.text == "EARNINGS"


def test_html_chart_is_inline_svg():
    html = render_deck_html(Deck(title="D", slides=[_slide()]), [EPS])
    assert '<svg data-name="chart"' in html and 'aria-roledescription="rect mark"' in html and ">18%<" in html  # Vega-Lite bars
    assert '<svg data-name="chart:2"' in html and 'class="mark-line' in html and ">u 7.0%<" in html  # line: series name and last value at the end


def _table_html(html: str) -> str:
    return html[html.index('data-name="table"'):html.index("</table>")]


def test_table_highlight_column_is_ink_not_highlight(tmp_path):
    """Highlight is a fill only: the highlighted column gets an ink header (panel text) and ground cells with ink text at 600."""
    deck = Deck(title="D", slides=[_slide()])
    tbl = {sh.name: sh for sh in Presentation(str(build_house_pptx(deck, [EPS], tmp_path / "d.pptx"))).slides[0].shapes}["table"].table
    head, cell, total = tbl.cell(0, 1), tbl.cell(1, 1), tbl.cell(3, 1)
    assert str(head.fill.fore_color.rgb) == "121722" and str(head.text_frame.paragraphs[0].runs[0].font.color.rgb) == "FFFFFF"
    for c in (cell, total):
        run = c.text_frame.paragraphs[0].runs[0]
        assert str(c.fill.fore_color.rgb) == "F4F6F9" and str(run.font.color.rgb) == "121722" and run.font.bold
    assert "2A78D6" not in shapes_xml(tbl)
    html = _table_html(render_deck_html(deck, [EPS])).lower()
    assert "#2a78d6" not in html
    assert "background:#121722" in html and "background:#f4f6f9" in html


def shapes_xml(tbl) -> str:
    return "".join(tbl.cell(r, c)._tc.xml for r in range(len(tbl.rows)) for c in range(len(tbl.columns))).upper()


def test_table_column_align_and_mono(tmp_path):
    deck = Deck(title="D", slides=[_slide()])
    tbl = {sh.name: sh for sh in Presentation(str(build_house_pptx(deck, [EPS], tmp_path / "d.pptx"))).slides[0].shapes}["table"].table
    mono = render_model.family(load_tokens().fonts.mono)
    num, txt = tbl.cell(1, 1).text_frame.paragraphs[0], tbl.cell(1, 0).text_frame.paragraphs[0]
    assert num.alignment == PP_ALIGN.RIGHT and num.runs[0].font.name == mono
    assert txt.alignment in (None, PP_ALIGN.LEFT) and txt.runs[0].font.name != mono
    assert tbl.cell(0, 1).text_frame.paragraphs[0].alignment == PP_ALIGN.RIGHT  # the header follows its column
    html = _table_html(render_deck_html(deck, [EPS]))
    assert html.count("text-align:right") == 4 and html.count("text-align:left") == 4


async def test_html_attributes_are_escaped(monkeypatch):
    evil = 'Evil"><script>x()</script>'

    def stub(visual, box, ctx):
        return [Text("t", box.x, box.y, 200, 40, "hi", 20, 400, evil, "#121722"),
                Rect("r", box.x, box.y + 50, 10, 10, '#000" onload="x()'),
                Line("l", [(box.x, box.y + 70), (box.x + 50, box.y + 70)], '#000"><script>x()</script>', 1, arrow=True),
                ChartPrim("c", box.x, box.y + 100, 400, 200, "column", ["a"], [Series("s", [1], ['#000"><script>x()</script>'])], '"<b>', True),
                TablePrim("tb", box.x, box.y + 320, 400, 100, ["h"], [["v"]], None, None, {"ink": '#000"><script>x()</script>'})]

    monkeypatch.setitem(render_model.VISUALS, "points", stub)
    html = render_deck_html(Deck(title="D", slides=[_slide()]), [EPS])
    assert "<script" not in html and 'onload="' not in html
    async with _page(html) as page:
        names = await page.evaluate("() => [...document.querySelectorAll('[data-name]')].map(e => e.dataset.name)")
        assert await page.evaluate("() => document.querySelectorAll('script').length") == 0
    assert {"t", "r", "l", "c", "tb"} <= set(names)


@pytest.fixture
def framed(tmp_path):
    store = ReportingStore(tmp_path / "reports", tmp_path / "templates")
    fonts = [(p.name, p) for p in frame_fonts(tmp_path / "fonts")]
    style = ingest_template(store, make_frame_pptx(tmp_path / "frame.pptx"), "frame.pptx", fonts)
    tokens = with_frame(load_tokens(), style.frame, style.font_dir, style.slide_width_emu)
    return tokens.model_copy(update={"frame": tokens.frame.model_copy(update={"body": Box(x=144, y=346, w=1584, h=694)})})


@pytest.mark.parametrize(("notes", "expected"), [("", "Source: EPS growth 2025"), ("Say this.", "Say this.\nSource: EPS growth 2025")])
def test_ac30_notes(tmp_path, framed, notes, expected):
    assert framed.emu_per_px == 6350
    deck = Deck(title="D", slides=[_slide(), _slide(), _slide(speaker_notes=notes)])
    prs = Presentation(str(build_house_pptx(deck, [EPS], tmp_path / "d.pptx", tokens=framed)))
    slide = prs.slides[2]
    assert "source" not in {sh.name for sh in slide.shapes}
    assert slide.notes_slide.notes_text_frame.text == expected
    assert prs.slide_width == round(1920 * 6350)


def test_ac30_no_source_no_notes(tmp_path, framed):
    prs = Presentation(str(build_house_pptx(Deck(title="D", slides=[_slide(source_refs=[])]), [], tmp_path / "d.pptx", tokens=framed)))
    assert not prs.slides[0].has_notes_slide or prs.slides[0].notes_slide.notes_text_frame.text == ""


def legacy_stress_shapes(tmp_path: Path) -> list[list]:
    deck, datasets = stress_deck("max")
    out = []
    for i, slide in enumerate(Presentation(str(build_house_pptx(deck, datasets, tmp_path / "s.pptx"))).slides):
        for sh in slide.shapes:
            runs = [r for p in sh.text_frame.paragraphs for r in p.runs] if sh.has_text_frame else []
            out.append([i, sh.name, sh.left, sh.top, sh.width, sh.height, runs[0].font.name if runs else None])
    return out


def test_ac22_legacy_unchanged(tmp_path):
    got, want = legacy_stress_shapes(tmp_path), json.loads(GOLDEN.read_text())
    assert [(s[0], s[1], s[6]) for s in got] == [(s[0], s[1], s[6]) for s in want]
    for g, w in zip(got, want, strict=True):
        assert g[2:6] == pytest.approx(w[2:6], abs=9525), g[:2]  # ±1 px


def test_ac23_classic_deck_has_slots(tmp_path):
    plan = ReportPlan(title="T", sections=[ReportSection(heading="H", narrative=[ContentItem(text="a"), ContentItem(text="b")])])
    prs = Presentation(str(build_house_pptx(deck_from_plan(plan), [], tmp_path / "d.pptx")))
    assert any(sh.name.startswith("slot:") for s in prs.slides for sh in s.shapes)


@pytest.mark.usefixtures("sample_house_universe", "pg")
def test_ac23_stewardship_has_slots(tmp_path):
    pytest.importorskip("zen")
    from arp.api.routers.stewardship import CreateStreamRequest, create_stream
    from arp.stewardship.client_report import build_pptx, client_report
    from arp.stewardship.process import StreamStore

    streams = StreamStore(tmp_path)
    stream = streams.get(create_stream(CreateStreamRequest(name="Example Pension Fund"), streams)["stream_id"])
    out = build_pptx(client_report(streams.root, stream, [], sla_days=45), tmp_path / "r.pptx")
    assert any(sh.name.startswith("slot:") for s in Presentation(str(out)).slides for sh in s.shapes)
