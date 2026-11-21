"""Fit loop: render the deck, measure it, and fix each overflowing slide with one action per pass.

Order of actions: shorten the slot (mild overflow), switch to the variant's `roomier` one, split a long list.
Headline overflow is never rewritten (the headline is approved); overflow_x and anything left over is reported.
Slides with a visual are left to `fit_ladder` (below).
"""

from __future__ import annotations

import json
from math import ceil, floor

from pydantic import ValidationError

from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.browser import measure
from arp.reporting.design_checks import design_checks
from arp.reporting.house_style import Tokens, get_variant, load_tokens
from arp.reporting.html_render import render_deck_html
from arp.reporting.lint import DERIVED, _numbers, lint_deck
from arp.reporting.render_model import render_slide
from arp.reporting.slide_fill import WRITING_GUIDE, SlotRewrite, rewrite_slot
from arp.schemas.common import new_id
from arp.schemas.reporting import (
    ColumnKind,
    DatasetColumn,
    Deck,
    Finding,
    QuantitativeDataset,
    ReportRequest,
    SlideContent,
    TableSpec,
)
from arp.schemas.visuals import ComparisonTable
from arp.storage.report_images import layout_images

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
    if kind == "list" and isinstance(items, list) and len(items) >= 2:
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
    shift: list[Finding] | None = None, tokens: Tokens | None = None,
) -> tuple[Deck, list[Finding]]:
    """`shift`, when given, holds earlier findings on this deck: a split moves those after it down, in place.
    `tokens` carries a template frame when there is one (house tokens otherwise)."""
    extra: list[Finding] = []
    for _ in range(max_passes):
        found = await measure(render_deck_html(deck, request.datasets, tokens, mode=request.layout.theme, images=layout_images(request)), tokens)
        todo: dict[int, tuple[str, float]] = {}
        for f in found:
            if f.rule == "overflow" and f.slot not in (None, "headline") and deck.slides[f.slide].visual is None:
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
    found = await measure(render_deck_html(deck, request.datasets, tokens, mode=request.layout.theme, images=layout_images(request)), tokens)
    return deck, extra + [f for f in found if deck.slides[f.slide].visual is None]  # component slides are fit_ladder's


# ---- Component slides: the fit ladder ---------------------------------------------------------------------------------
# Spec: docs/superpowers/specs/2026-11-15-slide-components-design.md, "Fit ladder". Each overflowing slide with a visual
# tries, in order: shorten its visual text, type steps 1 and 2, a switch to a roomier visual, a split in two (each half
# trying the first three again), and finally `needs_review`. The approved headline and subtitle are never rewritten.

_STEPPED = {"kpi_row", "points", "next_steps", "two_column", "image"}  # the visuals whose text follows `type_step`
_APPROVED = {"title", "subtitle"}  # their overflow goes straight to needs_review
_SHORTEN = "You shorten slide text so it fits its box. Keep every number exactly as written. Keep every fact; invent none.\n\n" + WRITING_GUIDE


def _field(kind: str, name: str) -> tuple | None:
    """The visual field a primitive draws, as a path into the visual's dump; names count from 1, paths from 0."""
    match kind, name.split(":"):
        case "kpi_row", ["kpi", "tile", n, ("value" | "label" | "delta") as f]:
            return "tiles", int(n) - 1, f
        case "two_column", ["kpis", n, ("value" | "label" | "delta") as f]:
            return "kpis", int(n) - 1, f
        case "two_column", ["col", side]:
            return side, "title"
        case "two_column", ["col", side, "row", n]:
            return side, "points", int(n) - 1
        case "points", ["row", n, "text"]:
            return "points", int(n) - 1
        case "next_steps", ["row", n, ("text" | "owner") as f]:
            return "actions", int(n) - 1, f
        case "chart", ["card", "insight", ("stat" | "headline") as f]:
            return "insight", f
        case "chart", ["card", "insight", "point", n]:
            return "insight", "points", int(n) - 1
        case "chart", ["callout", "text"]:
            return "callout", "text"
        case "image", ["points", "row", n]:
            return "points", int(n) - 1
        case "image", ["image", n, "caption"]:
            return "images", int(n) - 1, "caption"
    return None


def _at(tree, path: tuple):
    for k in path:
        tree = tree[k]
    return tree


def _put(deck: Deck, i: int, new: list[SlideContent]) -> Deck:
    return deck.model_copy(update={"slides": [*deck.slides[:i], *new, *deck.slides[i + 1 :]]})


def _step(i: int, rule: str, message: str, slot: str | None = None) -> Finding:
    return Finding(slide=i, slot=slot, stage="fit", rule=rule, message=message)


async def _measure(deck: Deck, request: ReportRequest, tokens: Tokens | None) -> list[Finding]:
    """The page's measurements plus the overflow the render model finds itself (a clipped chart category label)."""
    found = await measure(render_deck_html(deck, request.datasets, tokens, mode=request.layout.theme, images=layout_images(request)), tokens)
    model: list[Finding] = []
    by_id = {d.dataset_id: d for d in request.datasets}
    for i, s in enumerate(deck.slides):
        if s.visual is not None:
            render_slide(s, i, deck, tokens or load_tokens(), by_id, request.layout.theme, model, images=layout_images(request))
    return found + [f for f in model if f.rule == "overflow"]


async def _overflow(deck: Deck, i: int, request: ReportRequest, tokens: Tokens | None) -> list[Finding]:
    return [f for f in await _measure(deck, request, tokens) if f.slide == i]


async def _shorten(s: SlideContent, found: list[Finding], request: ReportRequest, llm: LLMClient, usage: LLMUsage | None) -> SlideContent | None:
    """One rewrite of the overflowing visual text fields; None when there are none, the call fails, a number is lost,
    a limit is broken or nothing changed."""
    paths = list(dict.fromkeys(p for f in found if f.slot and (p := _field(s.visual.type, f.slot))))
    if not paths:
        return None
    tree = s.visual.model_dump()
    old = [_at(tree, p) for p in paths]
    prompt = (f"Deck: {request.title}\nSlide headline: {s.headline}\n"
              f"These {len(old)} texts overflow their boxes: {json.dumps(old)}\n"
              f"Return {'the shorter text' if len(old) == 1 else f'the {len(old)} shorter texts, in the same order,'} in `text`.")
    try:
        out, u = await llm.complete_structured(system=_SHORTEN, prompt=prompt, output_model=SlotRewrite)
    except Exception:  # noqa: BLE001 -- a failed call skips this step, the ladder goes on
        return None
    if usage is not None:
        usage.input_tokens += u.input_tokens
        usage.output_tokens += u.output_tokens
    new = [out.text] if isinstance(out.text, str) else out.text
    if len(new) != len(old) or any({n for n, _, _ in _numbers(a)} - {n for n, _, _ in _numbers(b)} for a, b in zip(old, new, strict=True)):
        return None
    for p, text in zip(paths, new, strict=True):
        _at(tree, p[:-1])[p[-1]] = text
    try:
        visual = type(s.visual).model_validate(tree)
    except ValidationError:
        return None
    return None if visual == s.visual else s.model_copy(update={"visual": visual})


def _switch(s: SlideContent, request: ReportRequest) -> SlideContent | None:
    """The spec's switch table (PR 1 visuals). A KPI row's tiles become rows of a dataset added to `request` in place,
    since a comparison table only draws from a dataset; the caller saves the request."""
    v = s.visual
    if v.type == "kpi_row" and len(v.tiles) == 4:
        cols = ["Measure", "Value", *(["Change"] if any(t.delta for t in v.tiles) else [])]
        ds = QuantitativeDataset(dataset_id=new_id(DERIVED.rstrip("_")), name=s.headline, columns=[DatasetColumn(name=c, kind=ColumnKind.CATEGORY) for c in cols],
                                 rows=[dict(zip(cols, (t.label, t.value, t.delta), strict=False)) for t in v.tiles])
        request.datasets.append(ds)
        return s.model_copy(update={"visual": ComparisonTable(table=TableSpec(dataset_id=ds.dataset_id, columns=cols))})
    if v.type == "chart" and v.insight:
        sub = " · ".join(filter(None, [s.subheading, v.insight.stat]))
        return s.model_copy(update={"visual": v.model_copy(update={"insight": None}), "subheading": sub})
    if v.type == "two_column" and v.kpis:
        sub = " · ".join(filter(None, [s.subheading, *(f"{k.value} {k.label}" for k in v.kpis)]))
        return s.model_copy(update={"visual": v.model_copy(update={"kpis": []}), "subheading": sub})
    return None


def _split(s: SlideContent, request: ReportRequest) -> list[SlideContent] | None:
    """Two halves, the first taking the extra item; None when the visual has no split or a half would be too small."""
    v = s.visual
    halves = None
    if v.type == "comparison_table":
        t = v.table
        ds = next((d for d in request.datasets if d.dataset_id == t.dataset_id), None)
        n = min(t.max_rows, 8, len(ds.rows) - t.row_offset) if ds else 0
        if n >= 2:
            first = ceil(n / 2)
            halves = [v.model_copy(update={"table": t.model_copy(update={"max_rows": first})}),
                      v.model_copy(update={"table": t.model_copy(update={"row_offset": t.row_offset + first, "max_rows": n - first})})]
    elif v.type in ("points", "next_steps"):
        key, least = ("points", 3) if v.type == "points" else ("actions", 2)
        items, e = getattr(v, key), v.emphasis
        first = ceil(len(items) / 2)
        if len(items) - first >= least:
            halves = [v.model_copy(update={key: items[:first], "emphasis": e if e is not None and e < first else None}),
                      v.model_copy(update={key: items[first:], "emphasis": e - first if e is not None and e >= first else None})]
    if halves is None:
        return None
    return [s.model_copy(update={"visual": h, "kicker": f"{s.kicker} {k}/2"}) for k, h in enumerate(halves, start=1)]


def _approved(found: list[Finding]) -> bool:
    return any(f.slot in _APPROVED for f in found)


async def _steps(deck: Deck, i: int, found: list[Finding], request: ReportRequest, llm: LLMClient, tokens: Tokens | None,
                 usage: LLMUsage | None) -> tuple[Deck, list[Finding], list[Finding]]:
    """Steps 1–3 on slide `i`: the deck, the step findings, and the overflow still left."""
    out: list[Finding] = []
    new = await _shorten(deck.slides[i], found, request, llm, usage)
    if new is not None:
        deck = _put(deck, i, [new])
        out.append(_step(i, "shortened", "visual text shortened"))
        found = await _overflow(deck, i, request, tokens)
        if not found or _approved(found):
            return deck, out, found
    s = deck.slides[i]
    if s.visual.type in _STEPPED and s.type_step < 2:
        for step in range(max(s.type_step, 0) + 1, 3):
            deck = _put(deck, i, [deck.slides[i].model_copy(update={"type_step": step})])
            found = await _overflow(deck, i, request, tokens)
            if not found:
                break
        out.append(_step(i, "type_step", f"type step {step}"))
        if not found or _approved(found):
            return deck, out, found
    new = _switch(deck.slides[i], request)
    if new is not None:
        out.append(_step(i, "switched", f"{deck.slides[i].visual.type} became {new.visual.type}"))
        deck = _put(deck, i, [new])
        found = await _overflow(deck, i, request, tokens)
    return deck, out, found


def _flag(deck: Deck, i: int, found: list[Finding]) -> tuple[Deck, list[Finding]]:
    deck = _put(deck, i, [deck.slides[i].model_copy(update={"needs_review": True})])
    return deck, [*found, _step(i, "needs_review", "still overflows after the fit ladder; refine or approve the slide")]


async def _ladder(deck: Deck, i: int, found: list[Finding], request: ReportRequest, llm: LLMClient, tokens: Tokens | None,
                  usage: LLMUsage | None) -> tuple[Deck, list[Finding]]:
    if _approved(found):
        return _flag(deck, i, found)
    deck, out, found = await _steps(deck, i, found, request, llm, tokens, usage)
    halves = _split(deck.slides[i], request) if found and not _approved(found) else None
    if halves is None:
        if found:
            deck, flagged = _flag(deck, i, found)
            out += flagged
        return deck, out
    deck = _put(deck, i, halves)
    out.append(_step(i, "split", f"split into two slides of {deck.slides[i].visual.type}"))
    for j in (i, i + 1):
        found = await _overflow(deck, j, request, tokens)
        if found and not _approved(found):
            deck, more, found = await _steps(deck, j, found, request, llm, tokens, usage)
            out += more
        if found:
            deck, flagged = _flag(deck, j, found)
            out += flagged
    return deck, out


async def fit_ladder(
    deck: Deck, request: ReportRequest, llm: LLMClient, tokens: Tokens | None = None, usage: LLMUsage | None = None,
    shift: list[Finding] | None = None,
) -> tuple[Deck, list[Finding]]:
    """Fit the deck's component slides (legacy slides are fit_deck's). `shift` as in fit_deck. A KPI row switched to a
    table adds a dataset to `request.datasets`: the caller saves the request when it grew."""
    found = await _measure(deck, request, tokens)
    by_slide: dict[int, list[Finding]] = {}
    for f in found:
        v = deck.slides[f.slide].visual
        if v is not None and not (v.type == "flow" and v.layout and v.layout.too_big):  # flow_too_big already flagged it
            by_slide.setdefault(f.slide, []).append(f)
    extra: list[Finding] = []
    for i in sorted(by_slide, reverse=True):  # a split at i must not move the slides still to do
        before = len(deck.slides)
        deck, fs = await _ladder(deck, i, by_slide[i], request, llm, tokens, usage)
        for f in [*(shift or []), *extra]:
            if f.slide > i:
                f.slide += len(deck.slides) - before
        extra += fs
    # Underfill: one type size up (renderers centre their content); flagged if still under half the body height.
    under = [f.slide for f in design_checks(deck, request.datasets, tokens, request.layout.theme, layout_images(request)) if f.rule == "underfill"]
    for i in under:
        s = deck.slides[i]
        if s.type_step == 0 and not s.needs_review and s.visual.type in _STEPPED:
            bigger = _put(deck, i, [s.model_copy(update={"type_step": -1})])
            if not await _overflow(bigger, i, request, tokens):
                deck = bigger
    if under:
        extra += [f for f in design_checks(deck, request.datasets, tokens, request.layout.theme, layout_images(request)) if f.rule == "underfill"]
    return deck, extra
