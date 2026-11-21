"""House deck, LLM call per slide: pick a layout/variant for an approved headline and fill its slots.

The output is checked against the layout library and the datasets straight after the call;
a bad reference gets one retry with the errors, then a flagged placeholder -- never a failed deck.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

from pydantic import BaseModel, ValidationError

from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.content_planner import _datasets_context
from arp.reporting.house_style import SlotSpec, get_variant, load_layouts, load_tokens
from arp.reporting.render_model import VisualDataError, render_slide
from arp.schemas.reporting import Deck, Finding, QuantitativeDataset, ReportRequest, SlideContent, StorylineSlide
from arp.schemas.visuals import FRIENDLY_NAMES, FlowAnswer, Points, Visual

WRITING_GUIDE = (Path(__file__).parent / "style" / "writing.md").read_text()
DESIGN_GUIDE = (Path(__file__).parent / "style" / "design.md").read_text()

_FILLED_ELSEWHERE = {"chart": "set `chart`", "table": "set `table`", "image": "set `image_path`"}
# There is no image upload, so any image_path the model sets is invented (and would be read from local disk):
# image variants are left out of the prompt, rejected by validate_slide, and image_path is always dropped.

_RULES = """\
You build one slide of an investment-research deck. The headline is fixed; \
choose the layout/variant that best supports it and fill that variant's slots.

Rules:
- `layout` and `variant` must be one of the pairs listed below, and `slots` \
may only use that variant's text/list/number slot names. Respect each slot's \
word and item limits (list limits are per item).
- chart/table slots are not filled through `slots`: set `chart` or \
`table` (a real dataset_id and real column names) instead. Never set `image_path`.
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
        for ly in load_layouts().values() for v in ly.variants if not any(s.kind == "image" for s in v.slots)
    ]
    return _RULES + "\n".join(lines) + "\n\n" + WRITING_GUIDE


def validate_slide(slide: SlideContent, datasets: list[QuantitativeDataset]) -> list[str]:
    try:
        spec = get_variant(slide.layout, slide.variant)
    except KeyError as e:
        return [e.args[0]]
    if any(s.kind == "image" for s in spec.slots):
        return [f"{slide.layout}/{slide.variant} needs an image and none is available; pick another layout"]
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


_VISUAL_RULES = """\
You build one slide of an investment-research deck as a typed visual. The headline is fixed.

Rules:
- Set `visual` to a `{type}` visual and nothing else: leave `layout`, `variant` and `slots` empty.
- Respect every field limit in the schema below (words, characters, item counts).
- `emphasis`, where the visual has one, is the 0-based index of the single item to stress, or null.
- Chart and table data come only from a dataset: a real dataset_id and real column names.
- `subheading`, if you set one, is at most 16 words.
- Use only facts and numbers from the notes and datasets. Never invent any.

`{type}` ({name}) schema:
{schema}
"""

FLOW_GUIDE = """\
Mermaid flowchart syntax (the whole text goes in `mermaid`):
- First line `flowchart LR` (left to right) or `flowchart TB` (top to bottom).
- A step `id[Label]`, a decision `id{Question?}`, data or a store `id[(Data)]`. Ids are letters, digits and _.
- A tech tag goes after `<br>` in the label, e.g. `load[Load filings<br>Postgres]`: one `<br>` at most, tag at most 24 characters.
- Arrows `a --> b`, labelled `a -->|yes| b`. One arrow per pair, no `&`.
- Actors: `classDef team`, then `class a,b team` or `a:::team`. With actors, every step has exactly one.
- Class `stored` marks a stored result; class `emphasis` marks the one step the headline is about.
- Limits: 2 to 12 steps, at most 4 actors and 20 arrows, labels of at most 5 words, arrow labels of at most 3 words.
- Not supported: subgraph, style, linkStyle, click, other node shapes or arrow types.
Example:
flowchart LR
  collect[Collect filings<br>ESEF]:::team --> check{Data complete?}:::team
  check -->|yes| review[Review results]:::analyst
  check -->|no| log[(Gap log)]:::analyst
  classDef team
  classDef analyst
  class log stored
  class review emphasis
"""


class FlowSlideAnswer(SlideContent):
    """Slide fill's output model for a `flow` slide: the visual is the model's Mermaid text, unparsed."""

    visual: FlowAnswer | None = None


_ITEMS = {"kpi_row": "tiles", "points": "points", "next_steps": "actions"}  # the list `emphasis` indexes


def _visual_model(kind: str) -> type[BaseModel] | None:
    return next((m for m in get_args(get_args(Visual)[0]) if m.model_fields["type"].default == kind), None)


def _data_refs(slide: SlideContent) -> list[tuple[str, tuple[str, ...]]]:
    """(dataset_id, columns) for each chart or table the slide shows, typed visual or legacy slot."""
    v, refs = slide.visual, []
    for spec in (getattr(v, "data", None), getattr(v, "table", None), slide.chart, slide.table):
        if spec is not None:
            cols = [getattr(spec, n, None) for n in ("category_column", "x_column", "y_column")]
            refs.append((spec.dataset_id, tuple(sorted(c for c in [*cols, *getattr(spec, "value_columns", []), *getattr(spec, "columns", [])] if c))))
    return refs


def _off_source(content: SlideContent, source_refs: list[str], request: ReportRequest) -> list[str]:
    """When the approved storyline names datasets for this slide, its chart or table must use one of them."""
    named = [r for r in source_refs if r in {d.dataset_id for d in request.datasets}]
    if not named:
        return []
    return [f"use one of this slide's datasets {named}, not {ds!r}" for ds, _ in _data_refs(content) if ds not in named]


def duplicate_data(deck: Deck) -> list[Finding]:
    """A later slide showing the same dataset and columns as an earlier one: usually the model reused a dataset because
    none fitted the headline."""
    seen: dict[tuple[str, tuple[str, ...]], int] = {}
    findings = []
    for i, slide in enumerate(deck.slides):
        for ref in _data_refs(slide):
            if ref in seen:
                findings.append(Finding(slide=i, stage="data", rule="duplicate_data",
                                        message=f"shows the same data as slide {seen[ref] + 1} (dataset {ref[0]!r})"))
            seen.setdefault(ref, i)
    return findings


def _check_visual(content: object, kind: str, request: ReportRequest, source_refs: list[str] = ()) -> tuple[SlideContent | None, list[str]]:
    """The AI's answer re-validated (field limits included), plus the errors that send it back; a data error found by
    rendering counts too."""
    try:
        raw = content.model_dump(warnings=False) if isinstance(content, BaseModel) else content
        content = SlideContent.model_validate(raw)
    except ValidationError as e:
        return None, [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
    if content.visual is None or content.visual.type != kind:
        return None, [f"set `visual` to a {kind} visual"]
    if len(content.subheading.split()) > 16:
        return None, ["subheading: at most 16 words"]
    if errors := _off_source(content, list(source_refs), request):
        return None, errors
    if kind == "flow":  # laid out later by layout_flows; a flow has no dataset to check and no layout to render yet
        return content, []
    try:
        render_slide(content, 1, Deck(title=request.title, slides=[content]), load_tokens(), {d.dataset_id: d for d in request.datasets})
    except VisualDataError as e:
        return None, [str(e)]
    return content, []


def _points_fallback(slide: StorylineSlide) -> Points:
    """The headline, then the rationale (and purpose), in chunks of at most 20 words; padded to the 3 points `points` needs."""
    chunks = []
    for text in (slide.headline, slide.rationale, slide.purpose):
        words = text.split()
        chunks += [" ".join(words[k:k + 20]) for k in range(0, len(words), 20)]
    chunks = chunks[:6]
    # Fewer than 3 chunks leaves blank rows; the caller sets needs_review on such a slide so it is seen before download.
    return Points(points=chunks + [""] * (3 - len(chunks)))


async def _fill_visual(slide: StorylineSlide, index: int, request: ReportRequest, llm: LLMClient) -> tuple[SlideContent, list[Finding], LLMUsage]:
    keep = {"headline": slide.headline, "subheading": slide.subheading, "kicker": slide.kicker, "source_refs": slide.source_refs}

    def fallback(rule: str, message: str) -> tuple[SlideContent, list[Finding], LLMUsage]:
        points = _points_fallback(slide)
        findings = [Finding(slide=index, stage="data", rule=rule, message=message)]
        blank = "" in points.points
        if blank:
            findings.append(Finding(slide=index, stage="data", rule="needs_review", message="the points fallback has blank rows"))
        return SlideContent(**keep, visual=points, needs_review=blank), findings, usage

    usage = LLMUsage()
    flow = slide.visual == "flow"
    model = FlowAnswer if flow else _visual_model(slide.visual)
    if model is None:
        return fallback("bad_reference", f"unknown visual {slide.visual!r}")
    system = _VISUAL_RULES.format(type=slide.visual, name=FRIENDLY_NAMES.get(slide.visual, slide.visual),
                                  schema=json.dumps(model.model_json_schema())) + "\n" + (FLOW_GUIDE + "\n" if flow else "") + WRITING_GUIDE
    output_model = FlowSlideAnswer if flow else SlideContent
    kind = slide.visual + (f" (chart kind: {slide.chart_kind})" if slide.chart_kind else "")
    prompt = _prompt(slide, index, request) + f"\nVisual: {kind}\nWhy this visual: {slide.rationale or '(not given)'}\n\nVisual guide:\n{DESIGN_GUIDE}"
    try:
        answer, usage = await llm.complete_structured(system=system, prompt=prompt, output_model=output_model)
        content, errors = _check_visual(answer, slide.visual, request, slide.source_refs)
        if errors:
            retry = prompt + "\nYour previous answer had these errors; fix them:\n- " + "\n- ".join(errors) + "\n"
            answer, u2 = await llm.complete_structured(system=system, prompt=retry, output_model=output_model)
            usage = add_usage(usage, u2)
            content, errors = _check_visual(answer, slide.visual, request, slide.source_refs)
    except Exception as exc:  # noqa: BLE001 -- the client retried already; one slide must not fail the deck
        return fallback("llm_failed", str(exc))
    if errors:
        return fallback("bad_reference", "; ".join(errors))
    findings = []
    v = content.visual
    if (items := _ITEMS.get(v.type)) and v.emphasis is not None and not 0 <= v.emphasis < len(getattr(v, items)):
        findings.append(Finding(slide=index, stage="data", rule="bad_reference",
                                message=f"emphasis {v.emphasis} is outside the {len(getattr(v, items))} {items}; dropped"))
        v = v.model_copy(update={"emphasis": None})
    return SlideContent(**keep, visual=v), findings, usage


async def fill_slide(slide: StorylineSlide, index: int, request: ReportRequest, llm: LLMClient) -> tuple[SlideContent, list[Finding], LLMUsage]:
    if slide.visual:
        return await _fill_visual(slide, index, request, llm)
    placeholder = SlideContent(headline=slide.headline, layout="bullets", variant="three", slots={"items": []}, source_refs=slide.source_refs)
    prompt = _prompt(slide, index, request)
    usage = LLMUsage()
    try:
        content, usage = await llm.complete_structured(system=_system_prompt(), prompt=prompt, output_model=SlideContent)
        content = content.model_copy(update={"image_path": None})
        errors = validate_slide(content, request.datasets)
        if errors:
            retry_prompt = prompt + "\nYour previous answer had these errors; fix them:\n- " + "\n- ".join(errors) + "\n"
            content, u2 = await llm.complete_structured(system=_system_prompt(), prompt=retry_prompt, output_model=SlideContent)
            content = content.model_copy(update={"image_path": None})
            usage = add_usage(usage, u2)
            errors = validate_slide(content, request.datasets)
    except Exception as exc:  # noqa: BLE001 -- the client retried already; one slide must not fail the deck
        return placeholder, [Finding(slide=index, stage="data", rule="llm_failed", message=str(exc))], usage
    if errors:
        return placeholder, [Finding(slide=index, stage="data", rule="bad_reference", message="; ".join(errors))], usage
    # The headline is the approved storyline's, never the model's rewrite of it.
    return content.model_copy(update={"headline": slide.headline, "subheading": slide.subheading, "source_refs": slide.source_refs or content.source_refs}), [], usage


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
