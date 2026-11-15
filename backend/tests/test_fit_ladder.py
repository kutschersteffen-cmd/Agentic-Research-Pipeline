"""Task 8: visual fill, the fit ladder and the needs-review gate (spec rows AC-9, 10, 27, 28, 31, 51, 53, 54)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from arp.api.deps import get_reporting_store
from arp.api.routers import reporting as reporting_router
from arp.reporting.fit import fit_ladder
from arp.reporting.house_pipeline import build_house_deck
from arp.reporting.house_style import load_tokens
from arp.reporting.lint import lint_deck
from arp.reporting.sheet import sheet_deck
from arp.reporting.slide_fill import SlotRewrite, fill_slide
from arp.reporting.style_profile import ingest_template
from arp.reporting.visual_qa import QAResult
from arp.schemas.chart_specs import ChartSpec, TableSpec
from arp.schemas.reporting import (
    DatasetColumn,
    Deck,
    LayoutInstructions,
    OutputFormat,
    QuantitativeDataset,
    ReportManifest,
    ReportRequest,
    ReportStatus,
    SlideContent,
    Storyline,
    StorylineSlide,
)
from arp.schemas.visuals import Chart, ComparisonTable, KpiRow, NextAction, NextSteps, Points, Tile
from arp.storage.reporting_store import ReportingStore
from tests.fixtures.frame_template import frame_fonts, make_frame_pptx

_HOUSE = LayoutInstructions(output_format=OutputFormat.HOUSE_DECK)


def _store(tmp_path) -> ReportingStore:
    return ReportingStore(tmp_path / "reports", tmp_path / "templates")


def _request(notes: str = "n", datasets=(), template_id=None) -> ReportRequest:
    return ReportRequest(title="T", qualitative_notes=notes, datasets=list(datasets), template_id=template_id, layout=_HOUSE)


def _one(headline: str, visual: str, **kw) -> Storyline:
    return Storyline(title="Deck", slides=[StorylineSlide(headline=headline, purpose="p", visual=visual, **kw)])


def _tiles(value: str, n: int = 4) -> list[Tile]:
    return [Tile.model_construct(value=value, label=f"Item {k}", delta="") for k in range(n)]


def _content(visual: BaseModel) -> SlideContent:
    return SlideContent.model_construct(headline="ignored", visual=visual, subheading="", kicker="", layout="", variant="",
                                        slots={}, source_refs=[], speaker_notes="", source_line="", needs_review=False,
                                        chart=None, table=None, image_path=None, type_step=0)


def _mine(findings, i):
    return [f.rule for f in findings if f.slide == i]


# ---- AC-9: visual numbers are linted ------------------------------------------------------------------------------------


def test_ac9_visual_numbers_linted():
    deck, data, notes = sheet_deck()
    kpi = deck.slides[2].visual
    tiles = [*kpi.tiles]
    tiles[1] = tiles[1].model_copy(update={"value": "9.9%"})
    deck.slides[2] = deck.slides[2].model_copy(update={"visual": kpi.model_copy(update={"tiles": tiles})})
    found = [f for f in lint_deck(deck, _request(notes, data)) if f.rule == "number_not_in_source" and f.slide == 2]
    assert len(found) == 1 and "9.9%" in found[0].message


# ---- AC-10, AC-54: fill ----------------------------------------------------------------------------------------------------


async def test_ac10_emphasis_dropped(fake_llm):
    llm = fake_llm({"SlideContent": [SlideContent(headline="x", visual=KpiRow(tiles=_tiles("4%"), emphasis=7))]})
    content, findings, _ = await fill_slide(_one("H", "kpi_row").slides[0], 1, _request("4%"), llm)
    assert content.visual.type == "kpi_row" and content.visual.emphasis is None
    assert [f.rule for f in findings] == ["bad_reference"]
    assert llm.calls == ["SlideContent"]


async def test_ac54_points_fallback(tmp_path, fake_llm):
    bad = _content(KpiRow.model_construct(type="kpi_row", tiles=_tiles("4%", 5), emphasis=None))
    storyline = _one("Utilities lag the market", "kpi_row", rationale="Four numbers side by side")
    llm = fake_llm({"SlideContent": [bad, bad], "QAResult": [QAResult(edits=[])]})
    deck, findings = await build_house_deck("r1", _request("4%"), storyline, llm, _store(tmp_path))
    v = deck.slides[1].visual
    assert v.type == "points" and v.points[:2] == ["Utilities lag the market", "Four numbers side by side"]
    assert [f.rule for f in findings if f.rule == "bad_reference"] == ["bad_reference"]
    assert llm.calls.count("SlideContent") == 2


async def test_chart_data_error_falls_back_to_points(fake_llm):
    ds = QuantitativeDataset(dataset_id="d", name="D", columns=[DatasetColumn(name="k"), DatasetColumn(name="v")],
                             rows=[{"k": "a", "v": "lots"}, {"k": "b", "v": "few"}])
    chart = SlideContent(headline="x", visual=Chart(data=ChartSpec(dataset_id="d", category_column="k", value_columns=["v"]), kind="bar"))
    llm = fake_llm({"SlideContent": [chart, chart]})
    content, findings, _ = await fill_slide(_one("H", "chart", rationale="R").slides[0], 1, _request("n", [ds]), llm)
    assert content.visual.type == "points" and [f.rule for f in findings] == ["bad_reference"]


async def test_fill_rejects_long_subheading_once(fake_llm):
    long = SlideContent(headline="x", subheading=" ".join(["w"] * 17), visual=Points(points=["a", "b", "c"]))
    ok = SlideContent(headline="x", visual=Points(points=["a", "b", "c"]))
    llm = fake_llm({"SlideContent": [long, ok]})
    content, findings, _ = await fill_slide(_one("H", "points").slides[0], 1, _request(), llm)
    assert content.visual.points == ["a", "b", "c"] and findings == [] and llm.calls == ["SlideContent", "SlideContent"]


# ---- AC-27: switch -------------------------------------------------------------------------------------------------------


def _narrow_template(store, tmp_path) -> str:
    fonts = [(p.name, p) for p in frame_fonts(tmp_path / "fonts")]
    style = ingest_template(store, make_frame_pptx(tmp_path / "frame.pptx"), "frame.pptx", fonts)
    body = style.frame.body.model_copy(update={"w": 900})
    store.save_template_style(style.model_copy(update={"frame": style.frame.model_copy(update={"body": body})}))
    return style.template_id


async def test_ac27_switch_to_table(tmp_path, fake_llm):
    store = _store(tmp_path)
    request = _request("Each line made 1,234.5m.", template_id=_narrow_template(store, tmp_path))
    store.save_request("r1", request)
    kpi = SlideContent(headline="x", visual=KpiRow(tiles=_tiles("1,234.5m")))
    same = SlotRewrite(text=["1,234.5m"] * 4)
    llm = fake_llm({"SlideContent": [kpi], "SlotRewrite": [same] * 4, "QAResult": [QAResult(edits=[])]})
    deck, findings = await build_house_deck("r1", request, _one("Four lines", "kpi_row"), llm, store)
    rules = [r for r in _mine(findings, 1) if r in ("type_step", "switched")]
    assert rules == ["type_step", "switched"]
    assert deck.slides[1].visual.type == "comparison_table"
    assert store.load_request("r1").datasets  # the table's rows are saved with the request, so a re-render finds them


# ---- AC-28: split --------------------------------------------------------------------------------------------------------


async def test_ac28_split(tmp_path, fake_llm):
    words = " ".join(["cell"] * 40)
    cols = ["a", "b", "c"]
    ds = QuantitativeDataset(dataset_id="t", name="T", columns=[DatasetColumn(name=c) for c in cols],
                             rows=[dict.fromkeys(cols, words) for _ in range(8)])
    table = SlideContent(headline="x", visual=ComparisonTable(table=TableSpec(dataset_id="t")))
    llm = fake_llm({"SlideContent": [table], "SlotRewrite": [SlotRewrite(text=words)] * 8, "QAResult": [QAResult(edits=[])]})
    storyline = _one("Eight names compared", "comparison_table", kicker="Holdings")
    deck, findings = await build_house_deck("r1", _request("n", [ds]), storyline, llm, _store(tmp_path))
    a, b = deck.slides[1:3]
    assert len(deck.slides) == 3 and a.headline == b.headline == "Eight names compared"
    assert a.kicker.endswith(" 1/2") and b.kicker.endswith(" 2/2")
    assert (a.visual.table.row_offset, a.visual.table.max_rows, b.visual.table.row_offset, b.visual.table.max_rows) == (0, 4, 4, 4)
    assert [f.rule for f in findings if f.rule == "split"] == ["split"]
    for i, s in ((1, a), (2, b)):
        if any(f.slide == i and f.rule in ("overflow", "overflow_x") for f in findings):
            assert s.needs_review


# ---- AC-31, AC-51: needs review blocks the download until approved -------------------------------------------------------


@pytest.fixture
def client(tmp_path, fake_llm, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(reporting_router, "get_llm_client", lambda: fake_llm({}))
    app = FastAPI()
    app.include_router(reporting_router.router)
    app.dependency_overrides[get_reporting_store] = lambda: store
    return TestClient(app), store


async def _flagged_report(store, fake_llm):
    headline = " ".join(["Utilities"] * 40)
    points = SlideContent(headline="x", visual=Points(points=["a", "b", "c"]))
    same = SlotRewrite(text=headline)
    llm = fake_llm({"SlideContent": [points], "SlotRewrite": [same] * 4, "QAResult": [QAResult(edits=[])]})
    m = ReportManifest(title="T", output_format=OutputFormat.HOUSE_DECK, status=ReportStatus.COMPLETED,
                       output_filename="output.pdf", output_files=["output.pdf", "output.pptx"])
    store.save_manifest(m)
    deck, findings = await build_house_deck(m.report_id, _request(), _one(headline, "points"), llm, store)
    return m.report_id, deck, findings


async def test_ac31_needs_review_blocks_download(client, fake_llm):
    http, store = client
    rid, deck, findings = await _flagged_report(store, fake_llm)
    assert deck.slides[1].needs_review
    assert _mine(findings, 1).count("needs_review") == 1
    for file in ("output.pptx", "output.pdf"):
        r = http.get(f"/api/reports/{rid}/download?file={file}")
        assert r.status_code == 409 and r.json()["detail"] == "Slide 2 needs review"


async def test_ac51_approve_unblocks(client, fake_llm):
    http, store = client
    rid, _, _ = await _flagged_report(store, fake_llm)
    assert http.post(f"/api/reports/{rid}/slides/9/approve").status_code == 404
    assert http.post("/api/reports/rpt_nope/slides/2/approve").status_code == 404
    assert http.post(f"/api/reports/{rid}/slides/2/approve").status_code == 200
    assert store.load_deck(rid).slides[1].needs_review is False
    assert http.get(f"/api/reports/{rid}/download?file=output.pptx").status_code == 200


# ---- AC-53: shorten ------------------------------------------------------------------------------------------------------


async def test_ac53_shortened(tmp_path, fake_llm):
    long = "x" * 200  # one unbreakable word: wider than the row at 28 px
    points = SlideContent(headline="x", visual=Points(points=["Rates fall", "Refinancing", long]))
    llm = fake_llm({"SlideContent": [points], "SlotRewrite": [SlotRewrite(text="Tariffs reset in the second half")],
                    "QAResult": [QAResult(edits=[])]})
    deck, findings = await build_house_deck("r1", _request(), _one("Earnings turn late", "points"), llm, _store(tmp_path))
    rules = _mine(findings, 1)
    assert rules.count("shortened") == 1
    assert not {"overflow", "overflow_x", "needs_review"} & set(rules)
    assert deck.slides[1].visual.points[2] == "Tariffs reset in the second half"


# ---- Underfill --------------------------------------------------------------------------------------------------------------


async def test_underfill_steps_up_then_flags(fake_llm):
    steps = NextSteps(actions=[NextAction(text="Hold"), NextAction(text="Review")])
    deck = Deck(title="T", slides=[SlideContent(headline="Two actions", visual=steps)])
    deck, findings = await fit_ladder(deck, _request(), fake_llm({}), load_tokens(), None)
    assert deck.slides[0].type_step == -1
    assert [f.rule for f in findings] == ["underfill"]


# ---- Review fixes ------------------------------------------------------------------------------------------------------


async def test_switched_tiles_stay_linted(tmp_path, fake_llm):
    store = _store(tmp_path)
    request = _request("Each line made 1,234.5m.", template_id=_narrow_template(store, tmp_path))
    tiles = _tiles("1,234.5m")
    tiles[1] = Tile.model_construct(value="9.9%", label="Item 1", delta="")
    llm = fake_llm({"SlideContent": [SlideContent(headline="x", visual=KpiRow(tiles=tiles))], "QAResult": [QAResult(edits=[])]})
    deck, findings = await build_house_deck("r1", request, _one("Four lines", "kpi_row"), llm, store)
    assert deck.slides[1].visual.type == "comparison_table"
    found = [f for f in findings if f.rule == "number_not_in_source" and f.slide == 1]
    assert len(found) == 1 and "9.9%" in found[0].message


async def test_blank_points_fallback_needs_review(fake_llm):
    llm = fake_llm({})  # no answer scripted: the call fails, the fallback has only the headline
    content, findings, _ = await fill_slide(StorylineSlide(headline="Utilities lag", purpose="", visual="kpi_row"), 1, _request(), llm)
    assert content.visual.points == ["Utilities lag", "", ""] and content.needs_review
    assert "needs_review" in [f.rule for f in findings]


def test_split_table_halves_show_their_rows():
    from arp.reporting.fit import _split
    from arp.reporting.render_model import TablePrim, render_slide

    ds = QuantitativeDataset(dataset_id="t", name="T", columns=[DatasetColumn(name="name"), DatasetColumn(name="v")],
                             rows=[{"name": f"row{k}", "v": k} for k in range(7)])
    request = _request("n", [ds])
    slide = SlideContent(headline="H", visual=ComparisonTable(table=TableSpec(dataset_id="t")))
    halves = _split(slide, request)
    deck = Deck(title="T", slides=halves)
    tables = [next(p for p in render_slide(s, i, deck, load_tokens(), {"t": ds}) if isinstance(p, TablePrim)) for i, s in enumerate(halves)]
    assert [[r[0] for r in t.rows] for t in tables] == [["row0", "row1", "row2", "row3"], ["row4", "row5", "row6"]]


@pytest.mark.parametrize("visual", [Points(points=["a", "b", "c"]), NextSteps(actions=[NextAction(text="Hold"), NextAction(text="Review")])])
def test_step_up_keeps_rows_centred(visual):
    from arp.reporting.render_model import BODY, Rect, render_slide

    slide = SlideContent(headline="H", visual=visual, type_step=-1)
    rows = [p for p in render_slide(slide, 0, Deck(title="T", slides=[slide]), load_tokens(), {})
            if isinstance(p, Rect) and p.name.startswith("row:") and p.name.count(":") == 1]
    top, bottom = rows[0].y, rows[-1].y + rows[-1].h
    assert top - BODY.y == pytest.approx(BODY.y + BODY.h - bottom)
