import pytest

from arp.reporting.browser import measure
from arp.reporting.fit import fit_deck
from arp.reporting.html_render import render_deck_html
from arp.reporting.slide_fill import SlotRewrite
from arp.schemas.reporting import (
    ColumnKind,
    DatasetColumn,
    Deck,
    Finding,
    QuantitativeDataset,
    ReportRequest,
    SlideContent,
    TableSpec,
)

_REQ = ReportRequest(title="T", qualitative_notes="")


def _deck(slide):
    title = SlideContent(headline="T", layout="title", variant="plain", slots={"title": "T", "subtitle": "S"})
    return Deck(title="T", slides=[title, slide])


def _bullets(variant, items, notes=""):
    return SlideContent(headline="Headline", layout="bullets", variant=variant, slots={"items": items}, speaker_notes=notes)


def _sentence(n):
    return " ".join(f"word{k}" for k in range(n))


async def _overflow_ratio(slide):
    found = await measure(render_deck_html(_deck(slide), [], mode=_REQ.layout.theme))
    return [f for f in found if f.rule == "overflow" and f.slot == "items"]


@pytest.mark.asyncio
async def test_fit_shortens_mild_overflow(fake_llm):
    # Grow the text until the slot overflows mildly (ratio <= 1.6), then script a short rewrite.
    for n in range(100, 300, 10):
        slide = SlideContent(headline="Headline", layout="two_column", variant="text_text", slots={"left": _sentence(n), "right": "ok"})
        found = [f for f in await measure(render_deck_html(_deck(slide), [], mode="light")) if f.rule == "overflow"]
        if found:
            break
    assert found and float(found[0].message.removeprefix("ratio=")) <= 1.6
    llm = fake_llm({"SlotRewrite": [SlotRewrite(text="short")]})
    deck, findings = await fit_deck(_deck(slide), _REQ, llm)
    assert llm.calls == ["SlotRewrite"]
    assert deck.slides[1].slots["left"] == "short"
    assert [f for f in findings if f.stage != "design"] == []


@pytest.mark.asyncio
async def test_fit_switches_to_roomier_variant(fake_llm):
    slide = _bullets("three", [_sentence(70)] * 5)
    llm = fake_llm({})
    deck, _ = await fit_deck(_deck(slide), _REQ, llm, max_passes=1)
    assert deck.slides[1].variant == "five" and llm.calls == []


@pytest.mark.asyncio
async def test_fit_splits_long_list(fake_llm):
    slide = _bullets("five", [_sentence(60)] * 10)
    deck, _ = await fit_deck(_deck(slide), _REQ, fake_llm({}))
    halves = deck.slides[1:]
    assert len(halves) >= 2 and {s.headline for s in halves} == {"Headline"}
    assert all("[split_from slide 1]" in s.speaker_notes for s in halves)


@pytest.mark.asyncio
async def test_fit_gives_up_after_three_passes(fake_llm):
    slide = _bullets("five", [_sentence(30)] * 40)
    deck, findings = await fit_deck(_deck(slide), _REQ, fake_llm({}))
    assert len(deck.slides) - 1 <= 8  # content slides: the title slide is not counted
    assert "overflow" in {f.rule for f in findings}


@pytest.mark.asyncio
async def test_fit_reports_dropped_slot_on_variant_switch(fake_llm):
    slide = SlideContent(headline="Headline", layout="bullets", variant="three", slots={"items": [_sentence(70)] * 5, "extra": "x"})
    deck, findings = await fit_deck(_deck(slide), _REQ, fake_llm({}), max_passes=1)
    assert deck.slides[1].variant == "five"
    assert any(f.rule == "slot_dropped" and f.slot == "extra" for f in findings)


@pytest.mark.asyncio
async def test_fit_splits_long_table_without_duplicate_rows(fake_llm):
    ds = QuantitativeDataset(
        dataset_id="d", name="d", columns=[DatasetColumn(name="a", kind=ColumnKind.NUMBER)], rows=[{"a": k} for k in range(40)],
    )
    req = ReportRequest(title="T", qualitative_notes="", datasets=[ds])
    slide = SlideContent(headline="Headline", layout="table", variant="compact", table=TableSpec(dataset_id="d", max_rows=40))
    deck, _ = await fit_deck(_deck(slide), req, fake_llm({}), max_passes=1)
    parts = deck.slides[1:]
    assert len(parts) == 2 and {s.headline for s in parts} == {"Headline"}
    shown = [r for s in parts for r in range(s.table.row_offset, s.table.row_offset + s.table.max_rows)]
    assert shown == list(range(40))


@pytest.mark.asyncio
async def test_fit_falls_through_to_roomier_when_rewrite_fails(fake_llm, monkeypatch):
    import arp.reporting.fit as fit

    async def boom(*a, **k):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(fit, "rewrite_slot", boom)
    slide = _bullets("three", [_sentence(48)] * 5)  # mild overflow, so the rewrite is tried first
    assert 1 < float((await _overflow_ratio(slide))[0].message.removeprefix("ratio=")) <= 1.6
    deck, _ = await fit_deck(_deck(slide), _REQ, fake_llm({}), max_passes=1)
    assert deck.slides[1].variant == "five"


@pytest.mark.asyncio
async def test_fit_split_shifts_later_findings(fake_llm):
    deck = _deck(_bullets("five", [_sentence(60)] * 10))
    deck.slides.append(_bullets("three", ["ok"]))
    after = Finding(slide=2, stage="data", rule="bad_reference", message="m")
    on_split = Finding(slide=1, stage="data", rule="bad_reference", message="m")
    out, _ = await fit_deck(deck, _REQ, fake_llm({}), max_passes=1, shift=[after, on_split])
    assert len(out.slides) == 4 and out.slides[3].slots["items"] == ["ok"]
    assert (after.slide, on_split.slide) == (3, 1)


_QUADS = [f"Q{i} :: sub :: " + _sentence(40) + f" :: {s}" for i, s in enumerate(["low", "high", "mid", "neutral"])]


@pytest.mark.asyncio
async def test_fit_never_splits_a_structured_slot(fake_llm):
    slide = SlideContent(headline="h", layout="matrix2x2", variant="default", slots={"quadrants": _QUADS, "x_axis": "x", "y_axis": "y"})
    deck, findings = await fit_deck(_deck(slide), _REQ, fake_llm({}))  # any rewrite call would fail the fake: overflow is far past mild
    assert len(deck.slides) == 2 and deck.slides[1].slots["quadrants"] == _QUADS
    assert any(f.rule == "overflow" and f.slot == "quadrants" for f in findings)


@pytest.mark.asyncio
async def test_fit_keeps_a_structured_slot_when_its_rewrite_breaks_the_format(fake_llm):
    items = [f"Stage {i} :: " + _sentence(12) + " :: " + _sentence(12) for i in range(5)]
    slide = SlideContent(headline="h", layout="flow", variant="default", slots={"items": items})
    llm = fake_llm({"SlotRewrite": [SlotRewrite(text=["Stage one without separators", "Stage two"])] * 3})
    deck, findings = await fit_deck(_deck(slide), _REQ, llm)
    assert deck.slides[1].slots["items"] == items
    assert any(f.rule == "overflow" and f.slot == "items" for f in findings)


@pytest.mark.asyncio
async def test_fit_never_rewrites_the_title_slide_title(fake_llm):
    long_title = _sentence(11)  # a mild overflow, which on any other slot would be shortened
    deck = Deck(title="T", slides=[SlideContent(headline=long_title, layout="title", variant="plain", slots={"title": long_title, "subtitle": "S"})])
    llm = fake_llm({})
    out, findings = await fit_deck(deck, _REQ, llm)
    assert out.slides[0].slots["title"] == long_title and llm.calls == []
    assert any(f.slide == 0 and f.slot == "title" and f.rule == "overflow" for f in findings)
