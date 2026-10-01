"""House deck, LLM call per slide: pick a layout/variant for an approved headline and fill its slots.

The output is checked against the layout library and the datasets straight after the call;
a bad reference gets one retry with the errors, then a flagged placeholder -- never a failed deck.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.content_planner import _datasets_context
from arp.reporting.house_style import SlotSpec, get_variant, load_layouts
from arp.schemas.reporting import Finding, QuantitativeDataset, ReportRequest, SlideContent, StorylineSlide

_FILLED_ELSEWHERE = {"chart": "set `chart`", "table": "set `table`", "image": "set `image_path`"}

_RULES = """\
You build one slide of an investment-research deck. The headline is fixed; \
choose the layout/variant that best supports it and fill that variant's slots.

Rules:
- `layout` and `variant` must be one of the pairs listed below, and `slots` \
may only use that variant's text/list/number slot names. Respect each slot's \
word and item limits (list limits are per item).
- chart/table/image slots are not filled through `slots`: set `chart` or \
`table` (a real dataset_id and real column names) or `image_path` instead.
- Use only facts and numbers from the notes and datasets. Never invent any.
- Put detail that does not fit in `speaker_notes`.

Layouts (layout/variant: slots):
"""


def add_usage(a: LLMUsage, b: LLMUsage) -> LLMUsage:
    return LLMUsage(input_tokens=a.input_tokens + b.input_tokens, output_tokens=a.output_tokens + b.output_tokens, model=b.model or a.model)


class SlotRewrite(BaseModel):
    text: str | list[str]


def _slot_desc(s: SlotSpec) -> str:
    if s.kind in _FILLED_ELSEWHERE:
        return f"{s.name} ({s.kind}; {_FILLED_ELSEWHERE[s.kind]})"
    limits = [f"max {s.max_words} words" if s.max_words else "", f"max {s.max_items} items" if s.max_items else ""]
    return f"{s.name} ({', '.join([s.kind, *filter(None, limits)])})"


def _system_prompt() -> str:
    lines = [
        f"- {ly.id}/{v.id} [{ly.purpose}]: " + "; ".join(_slot_desc(s) for s in v.slots)
        for ly in load_layouts().values() for v in ly.variants
    ]
    return _RULES + "\n".join(lines) + "\n"


def validate_slide(slide: SlideContent, datasets: list[QuantitativeDataset]) -> list[str]:
    try:
        spec = get_variant(slide.layout, slide.variant)
    except KeyError as e:
        return [e.args[0]]
    fillable = [s.name for s in spec.slots if s.kind not in _FILLED_ELSEWHERE]
    errors = [f"slot {n!r} is not in {slide.layout}/{slide.variant}; allowed: {fillable}" for n in slide.slots if n not in fillable]
    kinds = {s.kind for s in spec.slots}
    for kind, value in (("chart", slide.chart), ("table", slide.table)):
        if value is not None and kind not in kinds:
            errors.append(f"{slide.layout}/{slide.variant} has no {kind} slot; drop `{kind}` or pick a variant with one")
        if value is None and kind in kinds:
            errors.append(f"{slide.layout}/{slide.variant} needs a `{kind}`")
    by_id = {d.dataset_id: d for d in datasets}
    refs = []
    if slide.chart:
        c = slide.chart
        refs.append((c.dataset_id, [c.category_column, c.x_column, c.y_column, c.value_column, *c.value_columns]))
    if slide.table:
        refs.append((slide.table.dataset_id, slide.table.columns))
    for dataset_id, columns in refs:
        ds = by_id.get(dataset_id)
        if ds is None:
            errors.append(f"unknown dataset_id {dataset_id!r}; known: {sorted(by_id)}")
            continue
        errors += [f"dataset {dataset_id!r} has no column {col!r}; columns: {ds.column_names()}" for col in columns if col and col not in ds.column_names()]
    return errors


def _prompt(slide: StorylineSlide, index: int, request: ReportRequest) -> str:
    return (
        f"Deck: {request.title}\nGoal: {request.goal or '(none given)'}\n"
        f"Audience: level={request.audience.level.value}, tone={request.audience.tone.value}\n\n"
        f"Slide {index} headline (fixed): {slide.headline}\nPurpose: {slide.purpose}\n"
        f"Sources: {', '.join(slide.source_refs) or '(any)'}\n\n"
        f"Qualitative notes:\n{request.qualitative_notes}\n\n"
        f"Quantitative datasets:\n{_datasets_context(request.datasets)}\n"
    )


async def fill_slide(slide: StorylineSlide, index: int, request: ReportRequest, llm: LLMClient) -> tuple[SlideContent, list[Finding], LLMUsage]:
    prompt = _prompt(slide, index, request)
    content, usage = await llm.complete_structured(system=_system_prompt(), prompt=prompt, output_model=SlideContent)
    errors = validate_slide(content, request.datasets)
    if errors:
        retry_prompt = prompt + "\nYour previous answer had these errors; fix them:\n- " + "\n- ".join(errors) + "\n"
        content, u2 = await llm.complete_structured(system=_system_prompt(), prompt=retry_prompt, output_model=SlideContent)
        usage = add_usage(usage, u2)
        errors = validate_slide(content, request.datasets)
    if errors:
        placeholder = SlideContent(headline=slide.headline, layout="bullets", variant="three", slots={"items": []}, source_refs=slide.source_refs)
        return placeholder, [Finding(slide=index, stage="data", rule="bad_reference", message="; ".join(errors))], usage
    # The headline is the approved storyline's, never the model's rewrite of it.
    return content.model_copy(update={"headline": slide.headline, "source_refs": slide.source_refs or content.source_refs}), [], usage


async def rewrite_slot(
    slide: SlideContent, slot: str, instruction: str, request: ReportRequest, llm: LLMClient, usage: LLMUsage | None = None,
) -> SlideContent:
    """`usage`, when given, is incremented in place with this call's tokens."""
    spec = next((s for s in get_variant(slide.layout, slide.variant).slots if s.name == slot), None)
    if spec is None:
        raise ValueError(f"slot {slot!r} is not in {slide.layout}/{slide.variant}")
    prompt = (
        f"Deck: {request.title}\nSlide headline: {slide.headline}\n"
        f"Slot {_slot_desc(spec)} currently holds: {json.dumps(slide.slots.get(slot))}\n"
        f"Instruction: {instruction}\n"
        f"Return only the replacement in `text`{' as a list of items' if spec.kind == 'list' else ''}. Keep every fact; invent none."
    )
    out, u = await llm.complete_structured(system=_system_prompt(), prompt=prompt, output_model=SlotRewrite)
    if usage is not None:
        usage.input_tokens += u.input_tokens
        usage.output_tokens += u.output_tokens
    return slide.model_copy(update={"slots": {**slide.slots, slot: out.text}})
