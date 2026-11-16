"""Render model core: slide anatomy, body box, source line (spec 2026-11-15-slide-components)."""

import pytest

from arp.reporting import render_model
from arp.reporting.house_style import load_tokens, with_frame
from arp.reporting.render_model import Rect, Text, anatomy, body_box, render_slide, source_line
from arp.reporting.style_profile import ingest_template
from arp.schemas.chart_specs import TableSpec
from arp.schemas.reporting import Box, DatasetColumn, Deck, QuantitativeDataset, SlideContent
from arp.schemas.visuals import ComparisonTable, Points, Section
from arp.storage.reporting_store import ReportingStore
from tests.fixtures.frame_template import frame_fonts, make_frame_pptx

EPS = QuantitativeDataset(dataset_id="eps", name="EPS growth 2025", columns=[DatasetColumn(name="v")], rows=[{"v": i} for i in range(6)])


@pytest.fixture(autouse=True)
def stub_points(monkeypatch):
    calls = []

    def stub(visual, box, ctx):
        calls.append((visual, box, ctx))
        return [Rect("stub", box.x, box.y, box.w, box.h, "#000000")]

    monkeypatch.setitem(render_model.VISUALS, "points", stub)
    monkeypatch.setitem(render_model.VISUALS, "section", stub)
    return calls


@pytest.fixture
def framed(tmp_path):
    store = ReportingStore(tmp_path / "reports", tmp_path / "templates")
    fonts = [(p.name, p) for p in frame_fonts(tmp_path / "fonts")]
    style = ingest_template(store, make_frame_pptx(tmp_path / "frame.pptx"), "frame.pptx", fonts)
    return with_frame(load_tokens(), style.frame, style.font_dir, style.slide_width_emu)


def _slide(**kw) -> SlideContent:
    return SlideContent(headline="EPS grew 12%", subheading="Sub", kicker="Earnings", source_refs=["eps"],
                        visual=Points(points=["a", "b", "c"]), **kw)


def _render(tokens=None, slide=None, mode="light"):
    slide = slide or _slide()
    return render_slide(slide, 2, Deck(title="D", slides=[slide]), tokens or load_tokens(), {"eps": EPS}, mode)


def _by_name(prims):
    return {p.name: p for p in prims}


def test_ac2_strip():
    p = _by_name(_render())
    for i, x in enumerate((96, 112, 128, 144, 160), start=1):
        s = p[f"strip:{i}"]
        assert isinstance(s, Rect)
        assert (s.x, s.y, s.w, s.h) == (x, 64, 12, 12)
        assert s.fill == ("#2a78d6" if i == 3 else "#121722")


def test_strip_dark_mode():
    p = _by_name(_render(mode="dark"))
    assert p["strip:3"].fill == "#3987e5"
    assert p["title"].color == "#e8ebf0"


def test_ac3_title_and_source_zones():
    p = _by_name(_render())
    assert (p["title"].y, p["title"].h) == (104, 128)
    assert p["title"].text == "EPS grew 12%"
    src = p["source"]
    assert src.y >= 952 and src.y + src.h <= 1000
    assert src.text == "Source: EPS growth 2025"
    assert p["page"].text == "3"
    assert p["kicker"].text == "EARNINGS"
    assert p["subtitle"].text == "Sub"


def test_ac4_source_line():
    ds = {"eps": EPS}
    assert source_line(SlideContent(headline="h", source_refs=["eps"]), ds) == "Source: EPS growth 2025"
    table = ComparisonTable(table=TableSpec(dataset_id="eps", row_offset=1, max_rows=3))
    assert source_line(SlideContent(headline="h", source_refs=["eps"], visual=table), ds) == "Source: EPS growth 2025, rows 2–4"
    whole = ComparisonTable(table=TableSpec(dataset_id="eps", max_rows=8))
    assert source_line(SlideContent(headline="h", source_refs=["eps"], visual=whole), ds) == "Source: EPS growth 2025"
    assert source_line(SlideContent(headline="h", source_refs=["eps", "Bloomberg"]), ds) == "Source: EPS growth 2025; Bloomberg"
    assert source_line(SlideContent(headline="h"), ds) == ""


def test_body_box_and_visual_dispatch(stub_points):
    p = _by_name(_render())
    assert body_box(load_tokens()) == Box(x=96, y=328, w=1728, h=592)
    assert (p["stub"].x, p["stub"].y, p["stub"].w, p["stub"].h) == (96, 328, 1728, 592)
    _, _, ctx = stub_points[0]
    assert (ctx.index, ctx.mode, ctx.datasets) == (2, "light", {"eps": EPS})


def test_section_is_full_bleed():
    slide = SlideContent(headline="S", visual=Section(number=1, title="Intro"))
    names = [p.name for p in _render(slide=slide)]
    assert names == ["stub"]


def test_ac20_frame_strip(framed):
    p = _by_name(_render(framed))
    f = framed.frame
    assert (p["title"].x, p["title"].y, p["title"].w, p["title"].h) == pytest.approx((f.headline.x, f.headline.y, f.headline.w, f.headline.h))
    assert (p["strip:1"].x, p["strip:1"].y) == pytest.approx((144, 32), abs=1)
    assert (p["subtitle"].x, p["subtitle"].y) == pytest.approx((f.subheading.x, f.subheading.y))
    assert p["title"].family == f.headline_font.family
    assert "source" in p  # the fixture body ends above 928


def test_ac30_source_to_notes(framed):
    frame = framed.frame.model_copy(update={"body": Box(x=144, y=346, w=1584, h=694)})  # ends at 1040
    tokens = framed.model_copy(update={"frame": frame})
    prims = anatomy(_slide(source_line="Source: EPS growth 2025"), 2, tokens, "light")
    assert not any(p.name == "source" for p in prims)
    assert any(isinstance(p, Text) and p.name == "title" for p in prims)
