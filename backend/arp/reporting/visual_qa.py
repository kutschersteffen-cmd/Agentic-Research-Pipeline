"""Visual QA: one model look at the rendered slides, applying only valid non-headline edits, then one fit pass."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.fit import fit_deck
from arp.reporting.house_style import get_variant, load_layouts
from arp.reporting.lint import lint_deck
from arp.schemas.reporting import Deck, Finding, ReportRequest

_MAX_IMAGES = 20  # keeps the request small; later slides go unchecked (qa_truncated)

_SYSTEM = """You review rendered consulting slides (one image per slide, in deck order, slide 0 first).
Check each slide for:
- hierarchy clear
- one focal point
- orphan words
- a lone bullet
- a near-empty slide
- the chart supports the headline
Return only edits that fix a real problem, each naming the slide index. An edit may change the layout and/or
variant, and/or replace one slot's text. Use only the layouts, variants and slots listed. Never edit headlines.
Keep every fact and number; invent none. Return no edits when the deck is fine."""


class QAEdit(BaseModel):
    slide: int
    layout: str | None = None
    variant: str | None = None
    slot: str | None = None
    text: str | list[str] | None = None
    reason: str


class QAResult(BaseModel):
    edits: list[QAEdit]


def _prompt(deck: Deck) -> str:
    slides = [{"slide": i, **s.model_dump(include={"headline", "layout", "variant", "slots"})} for i, s in enumerate(deck.slides)]
    layouts = {ly.id: {v.id: [sp.name for sp in v.slots] for v in ly.variants} for ly in load_layouts().values()}
    return f"Slides:\n{json.dumps(slides)}\n\nLayouts (layout -> variant -> slots):\n{json.dumps(layouts)}"


def _apply(deck: Deck, e: QAEdit) -> tuple[Deck, str | None]:
    """The edited deck, or the unchanged deck plus why the edit was rejected."""
    if not 0 <= e.slide < len(deck.slides):
        return deck, f"no slide {e.slide}"
    s = deck.slides[e.slide]
    if e.slot == "headline" or (e.slide == 0 and e.slot == "title"):
        return deck, "headlines are never edited"
    layout, variant = e.layout or s.layout, e.variant or s.variant
    try:
        specs = {sp.name: sp.kind for sp in get_variant(layout, variant).slots}
    except KeyError as exc:
        return deck, str(exc)
    if (e.slot is None) != (e.text is None) or (e.slot is not None and e.slot not in specs):
        return deck, f"slot {e.slot!r} with text {e.text!r} does not fit {layout}/{variant}"
    if e.slot is None and (layout, variant) == (s.layout, s.variant):
        return deck, "edit changes nothing"
    slots = {k: v for k, v in s.slots.items() if k in specs}
    if e.slot is not None:
        text = e.text
        if specs[e.slot] == "list" and isinstance(text, str):
            text = [text]
        elif specs[e.slot] != "list" and isinstance(text, list):
            text = " ".join(text)
        slots[e.slot] = text
    new = s.model_copy(update={"layout": layout, "variant": variant, "slots": slots})
    return deck.model_copy(update={"slides": [*deck.slides[: e.slide], new, *deck.slides[e.slide + 1 :]]}), None


async def visual_qa(
    deck: Deck, pngs: list[Path], request: ReportRequest, llm: LLMClient, usage: LLMUsage | None = None,
) -> tuple[Deck, list[Finding]]:
    findings: list[Finding] = []
    if len(pngs) > _MAX_IMAGES:
        findings.append(Finding(slide=_MAX_IMAGES, stage="qa", rule="qa_truncated", message=f"Only the first {_MAX_IMAGES} of {len(pngs)} slides were checked."))
        pngs = pngs[:_MAX_IMAGES]
    try:
        result, u = await llm.complete_structured(
            system=_SYSTEM, prompt=_prompt(deck), output_model=QAResult, images=[p.read_bytes() for p in pngs],
        )
    except Exception as exc:  # QA is advisory: a failed call never fails the deck
        return deck, [*findings, Finding(slide=0, stage="qa", rule="qa_failed", message=str(exc))]
    if usage is not None:
        usage.input_tokens += u.input_tokens
        usage.output_tokens += u.output_tokens
    edited: set[tuple[int, str]] = set()
    for e in result.edits:
        deck, why = _apply(deck, e)
        if why:
            findings.append(Finding(slide=e.slide, slot=e.slot, stage="qa", rule="invalid_edit", message=why))
            continue
        findings.append(Finding(slide=e.slide, slot=e.slot, stage="qa", rule="applied", message=e.reason))
        if e.slot is not None:
            edited.add((e.slide, e.slot))
    if not any(f.rule == "applied" for f in findings):
        return deck, findings
    # QA text is linted (no rewrite), then one fit pass; there is no second QA call.
    findings += [f for f in lint_deck(deck, request) if (f.slide, f.slot) in edited]
    deck, fit_findings = await fit_deck(deck, request, llm, max_passes=1, usage=usage)
    return deck, findings + fit_findings
