"""House deck inside a company template frame (spec 2026-11-14-template-frame, Task 4)."""

import pytest
from pptx import Presentation

from arp.reporting.browser import _page, measure
from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.house_style import get_variant, load_tokens, slot_rect, with_frame
from arp.reporting.html_render import render_deck_html
from arp.reporting.style_profile import ingest_template
from arp.schemas.reporting import Box, Deck, SlideContent
from arp.storage.reporting_store import ReportingStore
from tests.fixtures.frame_template import frame_fonts, make_frame_pptx

_FRAMED = 6350  # EMU per px on a 13.33 in template
_HOUSE = 9525


@pytest.fixture
def tokens(tmp_path):
    store = ReportingStore(tmp_path / "reports", tmp_path / "templates")
    fonts = [(p.name, p) for p in frame_fonts(tmp_path / "fonts")]
    style = ingest_template(store, make_frame_pptx(tmp_path / "frame.pptx"), "frame.pptx", fonts)
    return with_frame(load_tokens(), style.frame, style.font_dir, style.slide_width_emu)


def _deck(subheading="S", refs=("ds_1",), notes="N") -> Deck:
    return Deck(title="T", slides=[
        SlideContent(headline="T", layout="title", variant="plain", slots={"title": "Deck title", "subtitle": "Sub"}),
        SlideContent(headline="H", subheading=subheading, layout="bullets", variant="three", slots={"items": ["a", "b"]},
                     source_refs=list(refs), speaker_notes=notes),
    ])


def _build(tmp_path, tokens, deck=None, **kw):
    return Presentation(str(build_house_pptx(deck or _deck(), [], tmp_path / "d.pptx", tokens=tokens, **kw)))


def _one(slide, name):
    [shape] = [s for s in slide.shapes if s.name == name]
    return shape


def _px(shape, k=_FRAMED):
    return [shape.left / k, shape.top / k, shape.width / k, shape.height / k]


def _names(slide):
    return {s.name for s in slide.shapes}


def _runs(shape):
    return [r for p in shape.text_frame.paragraphs for r in p.runs]


def test_ac8_slide_size_and_boxes(tmp_path, tokens):
    prs = _build(tmp_path, tokens)
    assert (prs.slide_width, prs.slide_height) == (12192000, 6858000)
    s = prs.slides[1]
    assert _px(_one(s, "headline")) == pytest.approx([144, 72, 1584, 144], abs=1)
    assert _px(_one(s, "subheading")) == pytest.approx([144, 230.4, 1584, 72], abs=1)


def test_ac9_headline_runs(tmp_path, tokens):
    [run] = _runs(_one(_build(tmp_path, tokens).slides[1], "headline"))
    assert (run.font.name, run.font.size.pt, run.font.bold) == ("Testa Serif", 32, True)


def test_ac27_subheading_runs(tmp_path, tokens):
    [run] = _runs(_one(_build(tmp_path, tokens).slides[1], "subheading"))
    assert (run.font.name, run.font.size.pt, bool(run.font.bold)) == ("Testa Sans", 18, False)


def test_ac28_body_runs(tmp_path, tokens):
    assert {r.font.name for r in _runs(_one(_build(tmp_path, tokens).slides[1], "slot:items"))} == {"Testa Sans"}


def test_ac10_slots_inside_body(tmp_path, tokens):
    s = _build(tmp_path, tokens).slides[1]
    for shape in (sh for sh in s.shapes if sh.name.startswith("slot:")):
        x, y, w, h = _px(shape)
        assert x >= 144 - 1 and x + w <= 1728 + 1 and y >= 345.6 - 1 and y + h <= 907.2 + 1, shape.name
    x, _, w, _ = _px(_one(s, "slot:items"))
    assert (x, x + w) == pytest.approx((144, 1458.7), abs=1)
    assert "accent_rule" not in _names(s)


def test_ac12_footer_present(tmp_path, tokens):
    s = _build(tmp_path, tokens).slides[1]
    for name in ("footer:refs", "footer:page"):
        _, y, _, h = _px(_one(s, name))
        assert (y, h) == pytest.approx((928, 56), abs=1)


def _low_body(tokens):
    frame = tokens.frame.model_copy(update={"body": Box(x=144, y=345.6, w=1584, h=1080 - 40 - 345.6)})
    return tokens.model_copy(update={"frame": frame})


@pytest.mark.parametrize(("notes", "refs", "expected"), [
    ("N", ("ds_1",), "N\nSources: ds_1"),
    ("", ("ds_1",), "Sources: ds_1"),
    ("N", (), "N"),
])
def test_ac13_footer_to_notes(tmp_path, tokens, notes, refs, expected):
    s = _build(tmp_path, _low_body(tokens), _deck(refs=refs, notes=notes)).slides[1]
    assert not {n for n in _names(s) if n.startswith("footer:")}
    got = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
    assert got == expected


def test_ac14_title_slide(tmp_path, tokens):
    s = _build(tmp_path, tokens).slides[0]
    house = slot_rect(load_tokens(), get_variant("title", "plain").slots[0])
    assert _px(_one(s, "slot:title")) == pytest.approx(list(house), abs=1)
    assert {r.font.name for r in _runs(_one(s, "slot:title"))} == {"Testa Serif"}
    assert "accent_rule" not in _names(s)


def test_ac22_no_template_unchanged(tmp_path):
    prs = _build(tmp_path, None)
    assert (prs.slide_width, prs.slide_height) == (18288000, 10287000)
    s = prs.slides[1]
    head = _one(s, "headline")
    assert _px(head, _HOUSE)[:2] == pytest.approx([96, 96], abs=1)
    assert {r.font.name for r in _runs(head)} == {"Geist"}
    assert "accent_rule" in _names(s)
    assert _px(_one(s, "footer:refs"), _HOUSE)[1] == pytest.approx(928, abs=1)


def test_dark_mode_keeps_template_heading_font(tmp_path, tokens):
    [run] = _runs(_one(_build(tmp_path, tokens, mode="dark").slides[1], "headline"))
    assert run.font.name == "Testa Serif"


async def test_ac11_html_matches(tokens):
    async with _page(render_deck_html(_deck(), [], tokens=tokens)) as page:
        got = await page.evaluate("""() => { const h = document.querySelectorAll('[data-slot="headline"]')[0];
            const r = h.getBoundingClientRect(), s = h.closest('section').getBoundingClientRect();
            return [r.left - s.left, r.top - s.top, r.width, r.height, getComputedStyle(h).fontFamily]; }""")
    assert got[:4] == pytest.approx([144, 72, 1584, 144], abs=2)
    assert got[4].strip("'\"").startswith("Testa Serif")


async def test_measure_subheading_overflow(tokens):
    found = await measure(render_deck_html(_deck(subheading=" ".join(["word"] * 60)), [], tokens=tokens), tokens)
    sub = [f for f in found if f.slot == "subheading"]
    assert [(f.rule, f.slide) for f in sub] == [("subheading_overflow", 1)]


# ---- Task 5: the build uses the frame; frameless templates are refused for house decks ----

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from arp.api.deps import get_reporting_store  # noqa: E402
from arp.api.routers import reporting as reporting_router  # noqa: E402
from arp.reporting.house_pipeline import build_house_deck  # noqa: E402
from arp.reporting.visual_qa import QAResult  # noqa: E402
from arp.schemas.reporting import (  # noqa: E402
    LayoutInstructions,
    OutputFormat,
    ReportPlan,
    ReportRequest,
    Storyline,
    StorylineSlide,
    TemplateStyleProfile,
)


@pytest.fixture
def store(tmp_path) -> ReportingStore:
    return ReportingStore(tmp_path / "reports", tmp_path / "templates")


@pytest.fixture
def client(store, fake_llm, monkeypatch) -> TestClient:
    plan = ReportPlan(title="T", sections=[])
    monkeypatch.setattr(reporting_router, "get_llm_client", lambda: fake_llm({"ReportPlan": [plan]}))
    app = FastAPI()
    app.include_router(reporting_router.router)
    app.dependency_overrides[get_reporting_store] = lambda: store
    return TestClient(app)


def _ingest(store, tmp_path, **pptx) -> TemplateStyleProfile:
    fonts = [(p.name, p) for p in frame_fonts(tmp_path / "fonts", pptx.pop("fonts", ("TestaSerif-700.ttf", "TestaSans-400.ttf")))]
    return ingest_template(store, make_frame_pptx(tmp_path / "frame.pptx", **pptx), "frame.pptx", fonts)


def _req(tid, fmt="house_deck") -> dict:
    return {"title": "T", "qualitative_notes": "n", "layout": {"output_format": fmt}, "template_id": tid}


def test_ac7_frameless_house_deck_422(client, store, tmp_path):
    tid = _ingest(store, tmp_path, fonts=("TestaSans-400.ttf",)).template_id
    r = client.post("/api/reports", json=_req(tid))
    assert r.status_code == 422
    assert r.json()["detail"] == f'Template {tid} cannot frame a house deck: Upload the font file for "Testa Serif".'


def test_ac24_old_profile_422(client, store):
    old = TemplateStyleProfile(template_id="tpl_old", source_filename="a.pptx", slide_width_emu=1, slide_height_emu=1, stored_path="x")
    store.save_template_style(old)
    r = client.post("/api/reports", json=_req("tpl_old"))
    assert r.status_code == 422
    assert r.json()["detail"].endswith("re-upload it")


def test_ac25_classic_pptx_accepts_frameless(client, store, tmp_path):
    tid = _ingest(store, tmp_path, fonts=("TestaSans-400.ttf",)).template_id
    r = client.post("/api/reports?render=false", json=_req(tid, "pptx"))
    assert r.status_code == 200
    assert r.json()["template_id"] == tid


async def _framed_build(store, tmp_path, fake_llm, subheading):
    tid = _ingest(store, tmp_path).template_id
    request = ReportRequest(title="T", qualitative_notes="n", template_id=tid, layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK))
    storyline = Storyline(title="Deck", slides=[StorylineSlide(headline="H", subheading=subheading, purpose="p")])
    fill = SlideContent(headline="x", layout="bullets", variant="three", slots={"items": ["a", "b"]})
    llm = fake_llm({"SlideContent": [fill], "QAResult": [QAResult(edits=[])]})
    store.save_request("rep_1", request)
    return await build_house_deck("rep_1", request, storyline, llm, store)


async def test_ac16_subheading_never_rewritten(store, tmp_path, fake_llm):
    long = " ".join(["word"] * 60)
    deck, findings = await _framed_build(store, tmp_path, fake_llm, long)
    assert deck.slides[1].subheading == long
    s = Presentation(str(store.output_path("rep_1", "output.pptx"))).slides[1]
    sub = _one(s, "subheading")
    assert _px(sub) == pytest.approx([144, 230.4, 1584, 72], abs=1)
    assert {r.font.size.pt for r in _runs(sub)} == {18}
    [f] = [f for f in findings if f.slot == "subheading"]
    assert (f.rule, f.stage, f.slide) == ("subheading_overflow", "fit", 1)


async def test_split_keeps_subheading(tokens, fake_llm):
    from arp.reporting.fit import fit_deck

    long = [" ".join(["item"] * 60)] * 5  # far over the box, and bullets/five has no roomier variant: fit splits it
    deck = Deck(title="T", slides=[SlideContent(headline="H", subheading="Kept", layout="bullets", variant="five", slots={"items": long})])
    request = ReportRequest(title="T", qualitative_notes="n")
    deck, _ = await fit_deck(deck, request, fake_llm({}), tokens=tokens)
    assert len(deck.slides) > 1
    assert {s.subheading for s in deck.slides} == {"Kept"}
