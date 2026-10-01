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


def test_system_prompt_lists_every_variant_but_image():
    prompt = slide_fill._system_prompt()
    for ly in load_layouts().values():
        for v in ly.variants:
            assert (f"{ly.id}/{v.id}" in prompt) != any(s.kind == "image" for s in v.slots)


async def test_rewrite_slot_replaces_only_that_slot(fake_llm):
    llm = fake_llm({"SlotRewrite": [SlotRewrite(text="shorter")]})
    before = SlideContent(headline="h", layout="two_column", variant="text_text", slots={"left": "long text", "right": "keep"})
    after = await rewrite_slot(before, "left", "make it shorter", _REQ, llm)
    assert after.slots == {"left": "shorter", "right": "keep"} and before.slots["left"] == "long text"


async def test_fill_slide_drops_model_image_path_without_reading_it(fake_llm, monkeypatch):
    def no_read(*a, **k):
        raise AssertionError("a file was read")

    monkeypatch.setattr("pathlib.Path.read_bytes", no_read)
    llm = fake_llm({"SlideContent": [_chart_slide("weight").model_copy(update={"image_path": "/etc/passwd"})]})
    slide, findings, _ = await fill_slide(_STORY, 1, _REQ, llm)
    assert slide.image_path is None and findings == []


async def test_fill_slide_rejects_image_layout_and_prompt_omits_it(fake_llm):
    image = SlideContent(headline="h", layout="image", variant="default", slots={"caption": "c"}, image_path="/etc/passwd")
    llm = fake_llm({"SlideContent": [image, image]})
    slide, findings, _ = await fill_slide(_STORY, 1, _REQ, llm)
    assert findings[0].rule == "bad_reference" and slide.image_path is None
    assert "image/default" not in slide_fill._system_prompt()


async def test_fill_slide_llm_failure_is_flagged_placeholder(fake_llm):
    slide, findings, _ = await fill_slide(_STORY, 2, _REQ, fake_llm({}))  # nothing scripted: the call raises
    assert slide.layout == "bullets" and slide.headline == _STORY.headline
    assert [(f.slide, f.stage, f.rule) for f in findings] == [(2, "data", "llm_failed")]


def test_validate_slide_reports_structured_item_errors_and_heat_columns():
    from arp.schemas.reporting import TableSpec

    flow = SlideContent(headline="h", layout="flow", variant="default", slots={"items": ["only one stage"]})
    assert any("flow" in e for e in slide_fill.validate_slide(flow, []))
    tree = SlideContent(headline="h", layout="tree", variant="default", slots={"items": ["q :: Q? :: a :: nope", "a :: =A :: high"]})
    assert any("unknown node 'nope'" in e for e in slide_fill.validate_slide(tree, []))
    ds = QuantitativeDataset(dataset_id="d", name="D", columns=[DatasetColumn(name="k", kind=ColumnKind.CATEGORY)], rows=[{"k": "a"}])
    heat = SlideContent(headline="h", layout="table", variant="heat", table=TableSpec(dataset_id="d", heat={"zz": [1, 2]}))
    assert any("no column 'zz'" in e for e in slide_fill.validate_slide(heat, [ds]))
