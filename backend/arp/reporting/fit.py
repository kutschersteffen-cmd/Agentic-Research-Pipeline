"""Fit loop: render the deck, measure it, and fix each overflowing slide with one action per pass.

Order of actions: shorten the slot (mild overflow), switch to the variant's `roomier` one, split a long list.
Headline overflow is never rewritten (the headline is approved); overflow_x and anything left over is reported.
"""

from __future__ import annotations

from math import floor

from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.browser import measure
from arp.reporting.house_style import get_variant
from arp.reporting.html_render import render_deck_html
from arp.reporting.lint import lint_deck
from arp.reporting.slide_fill import rewrite_slot
from arp.schemas.reporting import Deck, Finding, ReportRequest, SlideContent

_MILD = 1.6


def _words(v: str | list[str]) -> int:
    return len(v.split()) if isinstance(v, str) else sum(len(t.split()) for t in v)


def _note(s: SlideContent, marker: str) -> SlideContent:
    return s.model_copy(update={"speaker_notes": f"{s.speaker_notes} {marker}".strip()})


async def _fit_slide(
    deck: Deck, i: int, slot: str, kind: str, ratio: float, request: ReportRequest, llm: LLMClient, usage: LLMUsage | None,
) -> tuple[list[SlideContent], list[Finding]]:
    """The replacement slides for slide `i` (or the slide itself when nothing applies) plus new findings."""
    s = deck.slides[i]
    if kind in ("text", "list") and ratio <= _MILD:
        limit = floor(_words(s.slots[slot]) / ratio * 0.9)
        try:
            new = await rewrite_slot(s, slot, f"Shorten to at most {limit} words. Keep every number.", request, llm, usage)
        except (ValueError, KeyError):
            return [s], []  # keep the finding, as lint does
        # Re-lint only this slot; never start another lint rewrite from here.
        view = deck.model_copy(update={"slides": [*deck.slides[:i], new, *deck.slides[i + 1 :]]})
        return [new], [f for f in lint_deck(view, request) if f.slide == i and f.slot == slot]
    roomier = get_variant(s.layout, s.variant).roomier
    if roomier:
        names = {sp.name for sp in get_variant(s.layout, roomier).slots}
        kept = {k: v for k, v in s.slots.items() if k in names}
        dropped = [Finding(slide=i, slot=k, stage="fit", rule="slot_dropped", message=f"Slot {k!r} does not exist in {s.layout}/{roomier}; its content was dropped.") for k in s.slots if k not in names]
        return [s.model_copy(update={"variant": roomier, "slots": kept})], dropped
    items = s.slots.get(slot)
    if kind == "list" and isinstance(items, list) and len(items) >= 2:
        h = len(items) // 2
        marker = f"[split_from slide {i}]"
        return [_note(s.model_copy(update={"slots": {**s.slots, slot: items[:h]}}), marker), _note(s.model_copy(update={"slots": {**s.slots, slot: items[h:]}}), marker)], []
    # ponytail: table slides are not split (TableSpec has no row offset); they are reported. Add an offset field to split them.
    return [s], []


async def fit_deck(
    deck: Deck, request: ReportRequest, llm: LLMClient, max_passes: int = 3, usage: LLMUsage | None = None,
) -> tuple[Deck, list[Finding]]:
    extra: list[Finding] = []
    for _ in range(max_passes):
        found = await measure(render_deck_html(deck, request.datasets, mode=request.layout.theme))
        todo: dict[int, tuple[str, float]] = {}
        for f in found:
            if f.rule == "overflow" and f.slot not in (None, "headline"):
                todo.setdefault(f.slide, (f.slot, float(f.message.removeprefix("ratio="))))
        if not todo:
            break
        slides = list(deck.slides)
        for i in sorted(todo, reverse=True):  # splitting slide i must not shift the indices still to do
            slot, ratio = todo[i]
            kind = next((sp.kind for sp in get_variant(slides[i].layout, slides[i].variant).slots if sp.name == slot), "")
            new, fs = await _fit_slide(deck.model_copy(update={"slides": slides}), i, slot, kind, ratio, request, llm, usage)
            slides[i : i + 1] = new
            extra += fs
        deck = deck.model_copy(update={"slides": slides})
    return deck, extra + await measure(render_deck_html(deck, request.datasets, mode=request.layout.theme))
