"""Fit loop: render the deck, measure it, and fix each overflowing slide with one action per pass.

Order of actions: shorten the slot (mild overflow), switch to the variant's `roomier` one, split a long list.
Headline and title-slide title overflow is never rewritten (both are approved); structured lists (structured.NO_SPLIT)
are never split; overflow_x and anything left over is reported.
"""

from __future__ import annotations

from math import ceil, floor

from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.browser import measure
from arp.reporting.house_style import get_variant
from arp.reporting.html_render import render_deck_html
from arp.reporting.lint import lint_deck
from arp.reporting.slide_fill import rewrite_slot
from arp.reporting.structured import NO_SPLIT
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
        except Exception:  # noqa: BLE001 -- unknown slot or a failed call
            pass  # fall through to roomier/split rather than retry the same failing call next pass
        else:
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
    if kind == "list" and (s.layout, slot) not in NO_SPLIT and isinstance(items, list) and len(items) >= 2:
        h = len(items) // 2
        marker = f"[split_from slide {i}]"
        return [_note(s.model_copy(update={"slots": {**s.slots, slot: items[:h]}}), marker), _note(s.model_copy(update={"slots": {**s.slots, slot: items[h:]}}), marker)], []
    if kind == "table" and s.table:
        ds = next((d for d in request.datasets if d.dataset_id == s.table.dataset_id), None)
        n = min(s.table.max_rows, len(ds.rows) - s.table.row_offset) if ds else 0  # visible rows
        if n >= 2:
            first = ceil(n / 2)
            marker = f"[split_from slide {i}]"
            t = s.table
            return [
                _note(s.model_copy(update={"table": t.model_copy(update={"max_rows": first})}), marker),
                _note(s.model_copy(update={"table": t.model_copy(update={"row_offset": t.row_offset + first, "max_rows": n - first})}), marker),
            ], []
    return [s], []


async def fit_deck(
    deck: Deck, request: ReportRequest, llm: LLMClient, max_passes: int = 3, usage: LLMUsage | None = None,
    shift: list[Finding] | None = None,
) -> tuple[Deck, list[Finding]]:
    """`shift`, when given, holds earlier findings on this deck: a split moves those after it down, in place."""
    extra: list[Finding] = []
    for _ in range(max_passes):
        found = await measure(render_deck_html(deck, request.datasets, mode=request.layout.theme, density=request.layout.density))
        todo: dict[int, tuple[str, float]] = {}
        for f in found:
            title = deck.slides[f.slide].layout == "title" and f.slot == "title"  # the approved storyline title, like the headline
            if f.rule == "overflow" and f.slot not in (None, "headline") and not title:
                todo.setdefault(f.slide, (f.slot, float(f.message.removeprefix("ratio="))))
        if not todo:
            break
        slides = list(deck.slides)
        for i in sorted(todo, reverse=True):  # splitting slide i must not shift the indices still to do
            slot, ratio = todo[i]
            kind = next((sp.kind for sp in get_variant(slides[i].layout, slides[i].variant).slots if sp.name == slot), "")
            new, fs = await _fit_slide(deck.model_copy(update={"slides": slides}), i, slot, kind, ratio, request, llm, usage)
            slides[i : i + 1] = new
            for f in [*(shift or []), *extra]:
                if f.slide > i:
                    f.slide += len(new) - 1
            extra += fs
        deck = deck.model_copy(update={"slides": slides})
    return deck, extra + await measure(render_deck_html(deck, request.datasets, mode=request.layout.theme, density=request.layout.density))
