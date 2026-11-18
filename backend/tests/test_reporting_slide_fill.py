import pytest

from arp.reporting import slide_fill
from arp.reporting.house_style import load_layouts
from arp.reporting.slide_fill import SlotRewrite, duplicate_data, fill_slide, rewrite_slot
from arp.schemas.reporting import (
    ChartSpec,
    ColumnKind,
    DatasetColumn,
    Deck,
    QuantitativeDataset,
    ReportRequest,
    SlideContent,
    StorylineSlide,
    TableSpec,
)
from arp.schemas.visuals import ComparisonTable

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


_FUNCS = QuantitativeDataset(
    dataset_id="functions", name="Functions",
    columns=[DatasetColumn(name="function", kind=ColumnKind.CATEGORY), DatasetColumn(name="control", kind=ColumnKind.CATEGORY)],
    rows=[{"function": "Extraction", "control": "Verifier"}],
)
_TABLE_REQ = ReportRequest(title="T", qualitative_notes="notes", datasets=[_DS, _FUNCS])


def _table_answer(dataset_id: str) -> SlideContent:
    return SlideContent(headline="h", visual=ComparisonTable(table=TableSpec(dataset_id=dataset_id)))


async def test_typed_table_must_use_a_dataset_the_storyline_slide_names(fake_llm):
    story = StorylineSlide(headline="Every function has a built-in control.", purpose="p", visual="comparison_table", source_refs=["functions", "README"])
    llm = fake_llm({"SlideContent": [_table_answer("ds_w"), _table_answer("functions")]})
    slide, findings, _ = await fill_slide(story, 1, _TABLE_REQ, llm)
    assert llm.calls == ["SlideContent", "SlideContent"] and "use one of this slide's datasets ['functions']" in llm.prompts[1]
    assert findings == [] and slide.visual.table.dataset_id == "functions"


async def test_typed_table_off_source_twice_falls_back_with_a_finding(fake_llm):
    story = StorylineSlide(headline="Every function has a built-in control.", purpose="p", visual="comparison_table", source_refs=["functions"])
    llm = fake_llm({"SlideContent": [_table_answer("ds_w"), _table_answer("ds_w")]})
    slide, findings, _ = await fill_slide(story, 1, _TABLE_REQ, llm)
    assert findings[0].rule == "bad_reference" and slide.visual.type == "points"


async def test_typed_table_may_use_any_dataset_when_the_slide_names_none(fake_llm):
    story = StorylineSlide(headline="Every function has a built-in control.", purpose="p", visual="comparison_table", source_refs=["README"])
    llm = fake_llm({"SlideContent": [_table_answer("ds_w")]})
    slide, findings, _ = await fill_slide(story, 1, _TABLE_REQ, llm)
    assert findings == [] and slide.visual.table.dataset_id == "ds_w"


def test_duplicate_data_flags_a_later_slide_with_the_same_dataset_and_columns():
    deck = Deck(title="T", slides=[_table_answer("functions"), _table_answer("ds_w"), _table_answer("functions"), _chart_slide("weight")])
    [f] = duplicate_data(deck)
    assert (f.slide, f.rule, f.stage) == (2, "duplicate_data", "data") and "slide 1" in f.message


def test_duplicate_data_allows_the_same_dataset_with_other_columns():
    deck = Deck(title="T", slides=[
        SlideContent(headline="a", visual=ComparisonTable(table=TableSpec(dataset_id="functions", columns=["function", "control"]))),
        SlideContent(headline="b", visual=ComparisonTable(table=TableSpec(dataset_id="functions", columns=["control", "function"]))),
    ])
    assert len(duplicate_data(deck)) == 1  # same columns in another order is the same data
    deck.slides[1] = SlideContent(headline="b", visual=ComparisonTable(table=TableSpec(dataset_id="ds_w", columns=["sector", "weight"])))
    assert duplicate_data(deck) == []
