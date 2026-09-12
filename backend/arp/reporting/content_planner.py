from __future__ import annotations

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.reporting import (
    QuantitativeDataset,
    ReportPlan,
    ReportRequest,
    TemplateStyleProfile,
)

_SYSTEM = """\
You are a Content Planner for an investment-research presentation/reporting \
tool. Given qualitative notes, a description of the available quantitative \
datasets, a target audience, and layout instructions, produce a structured \
ReportPlan: a title/subtitle and an ordered list of sections.

Rules:
- Every factual/numeric claim in the narrative must be grounded in either \
the qualitative notes or one of the described datasets -- never invent \
numbers, company names, or facts not present in the input.
- Match the audience: an "executive" audience gets short, headline-first \
bullets with minimal methodology; a "technical" audience can carry more \
detail and caveats; "general" avoids jargon. Match the requested tone.
- Respect layout_instructions exactly: target_length (section/slide count), \
max_bullets_per_slide, section_order_hint (use it as a starting point, but \
you may add sections it omits if the content needs them), and \
free_instructions.
- For each dataset worth visualizing, attach a `chart` (choose the \
chart_type that best fits the data shape -- e.g. a category-vs-value table \
is a bar/column chart, a value-over-time series is a line chart, \
shares-of-a-whole are a pie/doughnut chart, two numeric columns are a \
scatter chart, a row/column/value triple is a heatmap) referencing the \
dataset_id and real column names from its description, or a `table` when \
the raw figures matter more than a visual trend. Only reference \
dataset_id/column names that actually appear in the datasets you were given.
- If a TemplateStyleProfile is supplied, its layout names are informative \
context only (do not invent slide layouts that aren't listed); it does not \
change what content you plan.
- Every section needs a `heading`. Use layout_hint "section_header" only \
for pure divider sections with no body content. Use layout_hint \
"chart_focus" when a chart/table is the point of the section and \
narrative should be a short caption, not a wall of text.
- If include_agenda_slide is true and output_format is pptx, do not draft \
the agenda slide yourself -- the renderer adds it automatically from your \
section headings.
"""


def _datasets_context(datasets: list[QuantitativeDataset]) -> str:
    if not datasets:
        return "(no quantitative datasets supplied)"
    return "\n\n".join(ds.summary() for ds in datasets)


def _template_context(style: TemplateStyleProfile | None) -> str:
    if style is None:
        return "(no template ingested -- use a generic professional layout)"
    layouts = ", ".join(layout.name for layout in style.layouts) or "(none)"
    return f"Ingested template '{style.source_filename}'. Available slide layouts: {layouts}."


async def draft_report_plan(
    request: ReportRequest,
    llm: LLMClient,
    template_style: TemplateStyleProfile | None = None,
) -> tuple[ReportPlan, LLMUsage]:
    """The single LLM call in this pipeline: turns free-text qualitative
    input + dataset descriptions + audience/layout instructions into a
    structured ReportPlan. Nothing downstream (chart_builder, deck_builder,
    report_builder, pdf_builder) calls the model again -- every subsequent
    step is deterministic rendering of this plan, so a human can review or
    hand-edit the plan (ReportingStore.save_plan) before the final render
    without risking a different or inconsistent result on re-render.
    """
    prompt = (
        f"Title: {request.title}\n"
        f"Audience: level={request.audience.level.value}, tone={request.audience.tone.value}, "
        f"description={request.audience.description or '(none)'}, "
        f"focus_areas={request.audience.focus_areas or '(none)'}\n"
        f"Layout instructions: output_format={request.layout.output_format.value}, "
        f"target_length={request.layout.target_length or 'planner_choice'}, "
        f"max_bullets_per_slide={request.layout.max_bullets_per_slide}, "
        f"include_title_slide={request.layout.include_title_slide}, "
        f"include_agenda_slide={request.layout.include_agenda_slide}, "
        f"include_appendix={request.layout.include_appendix}, "
        f"section_order_hint={request.layout.section_order_hint or '(none)'}, "
        f"free_instructions={request.layout.free_instructions or '(none)'}\n\n"
        f"Template style:\n{_template_context(template_style)}\n\n"
        f"Qualitative notes:\n{request.qualitative_notes}\n\n"
        f"Quantitative datasets:\n{_datasets_context(request.datasets)}\n"
    )
    return await llm.complete_structured(system=_SYSTEM, prompt=prompt, output_model=ReportPlan)
