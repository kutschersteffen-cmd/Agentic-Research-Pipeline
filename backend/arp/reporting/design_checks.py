"""Design checks on a rendered house deck: underfill, small text, low contrast, emphasis count (stage `fit`).

A content slide is one with the anatomy `title` primitive; cover and section slides lack it and are exempt from
`underfill` and `emphasis_count`. Text with no `fill_under` is measured against the slide background: `panel`, or
`ground` on a slide that draws a full-bleed `background` rect (section).
Spec: docs/superpowers/specs/2026-11-15-slide-components-design.md, "Design checks".
"""

from __future__ import annotations

from arp.reporting.house_style import Mode, Tokens, load_tokens
from arp.reporting.render_model import Primitive, Text, body_box, palette, render_slide
from arp.schemas.reporting import Deck, Finding, QuantitativeDataset

MIN_SPAN, MIN_TEXT, MIN_CONTRAST, MIN_CONTRAST_LARGE, LARGE = 296, 18, 4.5, 3.0, 48
ANATOMY = ("strip:", "kicker", "title", "subtitle", "source", "page")


def _luminance(color: str) -> float:
    rgb = [int(color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _box(p: Primitive) -> tuple[float, float, float, float] | None:
    if hasattr(p, "x"):
        return p.x, p.y, p.w, p.h
    if hasattr(p, "points") and p.points:
        xs, ys = [q[0] for q in p.points], [q[1] for q in p.points]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
    return None


def check_slides(slides: list[list[Primitive]], tokens: Tokens, mode: Mode = "light") -> list[Finding]:
    c, body = palette(tokens, mode), body_box(tokens)
    out: list[Finding] = []

    def add(i: int, rule: str, slot: str | None, message: str) -> None:
        out.append(Finding(slide=i, stage="fit", rule=rule, slot=slot, message=message))

    for i, prims in enumerate(slides):
        content = any(p.name == "title" for p in prims)
        full_bleed = any(p.name == "background" for p in prims)
        background = c["ground"] if full_bleed else c["panel"]
        for p in prims:
            if not isinstance(p, Text) or not p.text:
                continue
            if p.size < MIN_TEXT:
                add(i, "small_text", p.name, f"{p.name} is {p.size:g} px, under {MIN_TEXT}")
            if p.outline:
                continue
            need = MIN_CONTRAST_LARGE if p.size >= LARGE else MIN_CONTRAST
            ratio = contrast(p.color, p.fill_under or background)
            if ratio < need:
                add(i, "low_contrast", p.name, f"{p.name} contrast {ratio:.1f}:1, under {need:g}:1")
        if not content:
            continue
        if sum(getattr(p, "emphasis", False) for p in prims) > 1:
            add(i, "emphasis_count", None, "more than one emphasised element")
        boxes = [b for p in prims if not p.name.startswith(ANATOMY) and (b := _box(p))
                 and b[0] >= body.x and b[1] >= body.y and b[1] + b[3] <= body.y + body.h and b[0] + b[2] <= body.x + body.w]
        span = max((y + h for _, y, _, h in boxes), default=0) - min((y for _, y, _, _ in boxes), default=0)
        if span < MIN_SPAN:
            add(i, "underfill", None, f"body spans {span:g} px, under {MIN_SPAN}")
    return out


def design_checks(deck: Deck, datasets: list[QuantitativeDataset], tokens: Tokens | None = None, mode: Mode = "light") -> list[Finding]:
    """Render each slide that has a visual and check it; slides without a visual are skipped."""
    tokens = tokens or load_tokens()
    by_id = {d.dataset_id: d for d in datasets}
    slides = [render_slide(s, i, deck, tokens, by_id, mode) if s.visual is not None else [] for i, s in enumerate(deck.slides)]
    return check_slides(slides, tokens, mode)
