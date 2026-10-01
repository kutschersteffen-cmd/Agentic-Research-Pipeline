import pytest

from arp.reporting import slide_fill
from arp.reporting.house_style import load_layouts
from arp.reporting.slide_fill import SlotRewrite, fill_slide, rewrite_slot
from arp.schemas.reporting import (
    ChartSpec,
    ColumnKind,
    DatasetColumn,
    QuantitativeDataset,
    ReportRequest,
    SlideContent,
    StorylineSlide,
)

_DS = QuantitativeDataset(
    dataset_id="ds_w", name="Weights",
    columns=[DatasetColumn(name="sector", kind=ColumnKind.CATEGORY), DatasetColumn(name="weight")],
    rows=[{"sector": "Utilities", "weight": 3.1}],
)
_REQ = ReportRequest(title="T", qualitative_notes="notes", datasets=[_DS])
_STORY = StorylineSlide(headline="Utilities are 3.1% of the book, below benchmark.", purpose="p")


def _chart_slide(column: str) -> SlideContent:
    return SlideContent(
        headline="different", layout="chart_takeaway", variant="full", slots={"takeaway": "t"},
        chart=ChartSpec(dataset_id="ds_w", category_column="sector", value_columns=[column]),
    )


async def test_fill_slide_keeps_storyline_headline(fake_llm):
    llm = fake_llm({"SlideContent": [_chart_slide("weight")]})
    slide, findings, _ = await fill_slide(_STORY, 1, _REQ, llm)
    assert slide.headline == _STORY.headline and findings == []


async def test_fill_slide_retries_once_on_bad_column_then_placeholder(fake_llm):
    llm = fake_llm({"SlideContent": [_chart_slide("nope"), _chart_slide("nope")]})
    slide, findings, _ = await fill_slide(_STORY, 1, _REQ, llm)
    assert llm.calls == ["SlideContent", "SlideContent"]
    assert "nope" in llm.prompts[1]  # the error is fed back on the retry
    assert findings[0].rule == "bad_reference" and findings[0].slide == 1 and slide.layout == "bullets"
    assert slide.headline == _STORY.headline


async def test_fill_slide_accepts_valid_retry(fake_llm):
    llm = fake_llm({"SlideContent": [_chart_slide("nope"), _chart_slide("weight")]})
    slide, findings, _ = await fill_slide(_STORY, 1, _REQ, llm)
    assert findings == [] and slide.layout == "chart_takeaway"


def test_validate_slide_flags_unknown_variant_and_slot():
    assert slide_fill.validate_slide(SlideContent(headline="h", layout="bullets", variant="nine"), [])
    assert slide_fill.validate_slide(SlideContent(headline="h", layout="bullets", variant="three", slots={"bogus": "x"}), [])


def test_validate_slide_flags_chart_and_table_mismatch_with_variant():
    chart = ChartSpec(dataset_id="ds_w", category_column="sector", value_columns=["weight"])
    on_bullets = SlideContent(headline="h", layout="bullets", variant="three", slots={"items": ["a"]}, chart=chart)
    assert any("chart" in e for e in slide_fill.validate_slide(on_bullets, [_DS]))
    missing = SlideContent(headline="h", layout="table", variant="compact")
    assert any("table" in e for e in slide_fill.validate_slide(missing, [_DS]))
    assert slide_fill.validate_slide(_chart_slide("weight"), [_DS]) == []


async def test_rewrite_slot_unknown_slot_is_value_error(fake_llm):
    slide = SlideContent(headline="h", layout="bullets", variant="three", slots={"items": []})
    with pytest.raises(ValueError, match="nope"):
        await rewrite_slot(slide, "nope", "shorter", _REQ, fake_llm({}))


def test_system_prompt_lists_every_variant():
    prompt = slide_fill._system_prompt()
    for ly in load_layouts().values():
        for v in ly.variants:
            assert f"{ly.id}/{v.id}" in prompt


async def test_rewrite_slot_replaces_only_that_slot(fake_llm):
    llm = fake_llm({"SlotRewrite": [SlotRewrite(text="shorter")]})
    before = SlideContent(headline="h", layout="two_column", variant="text_text", slots={"left": "long text", "right": "keep"})
    after = await rewrite_slot(before, "left", "make it shorter", _REQ, llm)
    assert after.slots == {"left": "shorter", "right": "keep"} and before.slots["left"] == "long text"
