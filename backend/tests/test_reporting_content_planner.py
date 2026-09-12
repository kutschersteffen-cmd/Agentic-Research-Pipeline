from arp.reporting.content_planner import draft_report_plan
from arp.schemas.reporting import (
    AudienceProfile,
    ColumnKind,
    ContentItem,
    DatasetColumn,
    LayoutInstructions,
    QuantitativeDataset,
    ReportPlan,
    ReportRequest,
    ReportSection,
    TemplateLayoutInfo,
    TemplateStyleProfile,
)


def _plan() -> ReportPlan:
    return ReportPlan(title="Electrification Review", sections=[ReportSection(heading="Summary", narrative=[ContentItem(text="a")])])


async def test_draft_report_plan_returns_scripted_plan_and_usage(fake_llm):
    llm = fake_llm({"ReportPlan": [_plan()]})
    ds = QuantitativeDataset(name="Revenue", columns=[DatasetColumn(name="x", kind=ColumnKind.NUMBER)], rows=[{"x": 1}])
    request = ReportRequest(title="Electrification Review", qualitative_notes="Strong quarter", datasets=[ds])

    plan, usage = await draft_report_plan(request, llm)

    assert plan.title == "Electrification Review"
    assert usage.input_tokens == 10
    assert llm.calls == ["ReportPlan"]


async def test_draft_report_plan_prompt_includes_audience_layout_and_dataset_summary(fake_llm):
    llm = fake_llm({"ReportPlan": [_plan()]})
    ds = QuantitativeDataset(name="Revenue", columns=[DatasetColumn(name="segment", kind=ColumnKind.CATEGORY)], rows=[{"segment": "EV"}])
    request = ReportRequest(
        title="T",
        qualitative_notes="Some qualitative finding",
        datasets=[ds],
        audience=AudienceProfile(level="executive", description="Investment committee"),
        layout=LayoutInstructions(target_length=5, free_instructions="lead with risk"),
    )

    await draft_report_plan(request, llm)

    prompt = llm.prompts[0]
    assert "executive" in prompt
    assert "Investment committee" in prompt
    assert "Some qualitative finding" in prompt
    assert "Revenue" in prompt
    assert "lead with risk" in prompt
    assert "target_length=5" in prompt


async def test_draft_report_plan_includes_template_layout_names_in_prompt(fake_llm):
    llm = fake_llm({"ReportPlan": [_plan()]})
    request = ReportRequest(title="T", qualitative_notes="notes")
    style = TemplateStyleProfile(
        source_filename="house.pptx", slide_width_emu=1, slide_height_emu=1,
        layouts=[TemplateLayoutInfo(index=0, name="Title Slide"), TemplateLayoutInfo(index=1, name="Two Content")],
        stored_path="/tmp/house.pptx",
    )

    await draft_report_plan(request, llm, template_style=style)

    prompt = llm.prompts[0]
    assert "Title Slide" in prompt
    assert "Two Content" in prompt
