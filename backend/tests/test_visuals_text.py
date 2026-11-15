"""Text visuals: cover, section, KPI row, two columns, points, next steps (spec 2026-11-15-slide-components)."""

import pytest
from pptx import Presentation

from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.house_style import load_tokens
from arp.reporting.html_render import render_deck_html
from arp.reporting.render_model import Rect, Text, render_slide
from arp.schemas.reporting import Deck, SlideContent
from arp.schemas.visuals import Column, Cover, Figure, KpiRow, NextAction, NextSteps, Points, Section, Tile, TwoColumn

TILES = [Tile(value="4%", label="Utilities EPS growth", delta="▼ 7 pts vs market"), Tile(value="11%", label="Market EPS growth"),
         Tile(value="6.2%", label="Sector funding cost"), Tile(value="30%", label="Debt due by 2027")]
VISUALS = {
    "cover": Cover(title="Utilities outlook 2026", context="Committee · 15 Nov 2026", answer="Utilities trail the market by 7 points.",
                   figures=[Figure(value="−7 pts", label="Earnings gap"), Figure(value="Q3", label="Turning point")]),
    "section": Section(number=2, title="Where the gap comes from", summary="Funding costs and slow tariff resets"),
    "kpi_row": KpiRow(tiles=TILES, emphasis=0),
    "two_column": TwoColumn(kpis=TILES[:3], left=Column(title="Why we stay", points=["One.", "Two."]),
                            right=Column(title="What makes us add", points=["Three.", "Four.", "Five."])),
    "points": Points(points=["First point", "Second point", "Third point"], emphasis=1),
    "next_steps": NextSteps(actions=[NextAction(text="Keep the underweight", owner="Portfolio team", when="Now"),
                                     NextAction(text="Engage Eastwater", owner="Stewardship", when="Before Q3"),
                                     NextAction(text="Review after Q3")]),
}


def _render(visual, mode="light", deck=None, index=0):
    deck = deck or Deck(title="D", slides=[SlideContent(headline="Head", kicker="K", visual=visual)])
    return {p.name: p for p in render_slide(deck.slides[index], index, deck, load_tokens(), {}, mode)}


def test_ac5_kpi_tiles():
    p = _render(VISUALS["kpi_row"])
    for n, x in enumerate((96, 534, 972, 1410), start=1):
        tile = p[f"kpi:tile:{n}"]
        assert isinstance(tile, Rect)
        assert (tile.x, tile.w) == (x, 414)
        assert tile.fill == ("#121722" if n == 1 else "#f4f6f9")
        assert tile.emphasis is (n == 1)
    assert p["kpi:tile:1:value"].color == "#ffffff"


def test_ac15_dark():
    p = _render(VISUALS["kpi_row"], mode="dark")
    assert p["kpi:tile:1"].fill == "#e8ebf0"
    assert p["kpi:tile:1:value"].color == "#141921"


def test_kpi_emphasis_out_of_range_is_ignored():
    p = _render(KpiRow(tiles=TILES[:2], emphasis=5))
    assert not any(x.emphasis for x in p.values())


def test_next_steps_rows_centred():
    p = _render(VISUALS["next_steps"])
    rows = [v for k, v in p.items() if k.startswith("row:") and k.count(":") == 1]
    assert len(rows) == 3
    top, bottom = min(r.y for r in rows), max(r.y + r.h for r in rows)
    assert abs((top + bottom) / 2 - (328 + 920) / 2) <= 2
    assert p["row:1:text"].weight == 600 and p["row:2:text"].weight == 400
    assert not any(x.emphasis for x in p.values())


def test_section_agenda_marks_current():
    a = SlideContent(headline="A", visual=Section(number=1, title="The gap"))
    b = SlideContent(headline="B", visual=VISUALS["section"])
    deck = Deck(title="D", slides=[a, SlideContent(headline="x", visual=VISUALS["points"]), b])
    p = _render(None, deck=deck, index=2)
    assert p["section:number"].outline and p["section:number"].text == "02"
    assert [p["agenda:1"].text, p["agenda:2"].text] == ["01  The gap", "■ 02  Where the gap comes from"]


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("kind", list(VISUALS))
def test_text_rules(kind, mode):
    p = _render(VISUALS[kind], mode)
    anatomy = {"kicker", "title", "subtitle", "source", "page"}
    texts = [x for x in p.values() if isinstance(x, Text) and x.text and x.name not in anatomy]
    assert texts
    for t in texts:
        assert t.size >= 18, t.name
        assert t.fill_under, t.name


def test_unicode_text_round_trip(tmp_path):
    vis = KpiRow(tiles=[Tile(value="−7 pts", label="Gap", delta="▲ 2 pts"), Tile(value="€12m", label="Cost")])
    deck = Deck(title="D", slides=[SlideContent(headline="H", visual=vis)])
    out = build_house_pptx(deck, [], tmp_path / "d.pptx")
    runs = {r.text for sh in Presentation(str(out)).slides[0].shapes if sh.has_text_frame
            for para in sh.text_frame.paragraphs for r in para.runs}
    html = render_deck_html(deck, [])
    for s in ("−7 pts", "€12m", "▲ 2 pts"):
        assert s in runs
        assert s in html
