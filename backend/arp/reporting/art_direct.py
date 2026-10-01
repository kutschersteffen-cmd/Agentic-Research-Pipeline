"""Art director: deterministic layout choice after slide fill, before lint. No LLM calls.

The model's layout pick is a hint; the content's shape picks the layout (spec §2), then the deck's rhythm rules
adjust it. Content is never rewritten: a layout that would drop a non-empty slot, overflow a list or fail a
structured parse is skipped. Every change is an info finding.
"""

from __future__ import annotations

import re

from arp.reporting.house_style import get_variant
from arp.reporting.slide_fill import structure_errors
from arp.schemas.reporting import Deck, Finding, SlideContent

_ORDERED = re.compile(
    r"^((Jan(uary)?|Feb(ruary)?|Mar(ch)?|Apr(il)?|May|June?|July?|Aug(ust)?|Sep(t(ember)?)?|Oct(ober)?|Nov(ember)?|Dec(ember)?"
    r"|Q[1-4]|\d{4})\b|\d+[.)]|(First|Then|Next|Finally)\b)"
)
IMPERATIVES = {"Agree", "Adopt", "Approve", "Mandate", "Scale", "Confirm", "Decide", "Run", "Pick", "Calibrate", "Review",
               "Escalate", "Fund", "Launch"}
_N = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
_NUM = re.compile(r"number_\d+")


def _ordered(items: list[str]) -> bool:
    return any(_ORDERED.match(t.strip()) for t in items)


def _texts(slide: SlideContent) -> dict[str, str]:
    """Filled prose slots: not numbers, their labels or the takeaway bar."""
    return {k: v for k, v in slide.slots.items() if isinstance(v, str) and v.strip() and k != "takeaway_bar"
            and not _NUM.fullmatch(k) and not k.startswith("label_")}


def _words(slide: SlideContent) -> int:
    lists = [t for v in slide.slots.values() if isinstance(v, list) for t in v]
    return sum(len(t.split()) for t in [*_texts(slide).values(), *lists])


def shape_of(slide: SlideContent) -> str:
    numbers = sum(1 for k, v in slide.slots.items() if _NUM.fullmatch(k) and v)
    items = slide.slots.get("items") or []
    texts = _texts(slide)
    if slide.table:
        return "table"
    if slide.chart:
        return "chart_short" if _words(slide) <= 25 else "chart_long"
    if numbers == 1:
        return "stat_1"
    if 2 <= numbers <= 4:
        return "stats"
    if slide.slots.get("left") and slide.slots.get("right"):
        return "contrast"
    if isinstance(items, list) and 3 <= len(items) <= 5 and _ordered(items):
        return "ordered"
    if isinstance(items, list) and 3 <= len(items) <= 4 and all(len(t.split()) < 12 for t in items):
        return "parallel"
    if len(texts) == 1 and not numbers and not any(isinstance(v, list) and v for v in slide.slots.values()):
        return "statement"
    return "other"


def candidates(shape: str, slide: SlideContent, density: str = "committee", last: bool = False) -> list[tuple[str, str]]:
    """Ordered (layout, variant) picks for the shape; `last` marks the deck's last content slide. Not yet checked for fit."""
    items = slide.slots.get("items") or []
    n = len(items) if isinstance(items, list) else 0
    out: list[tuple[str, str]] = []
    if density == "committee":  # the amendment's preferences come first; relayout's parse check skips what does not fit
        if last and n and all(t.split()[0] in IMPERATIVES for t in items if t.split()):
            out.append(("decisions", "default"))
        if 4 <= n <= 6 and (_ordered(items) or slide.layout in ("steps", "timeline", "flow")):
            out.append(("flow", "default"))
        if _words(slide):  # exhibit plus commentary
            if slide.chart:
                out += [("scatter_zone", "default")] * (slide.chart.chart_type == "scatter") + [("split", "chart")]
            if slide.table:
                out += [("table", "heat")] * bool(slide.table.heat) + [("split", "table")]
        if n:
            out.append(("profile", "default"))
    if shape in ("stat_1", "stats"):
        k = sum(1 for key, v in slide.slots.items() if _NUM.fullmatch(key) and v)
        out += [("stat_row", _N[k])] + [("big_number", _N[k])] * (k <= 3)
    elif shape == "parallel":
        out += [("cards", _N[n]), ("cards", "rows"), ("summary", "default")]
    elif shape == "ordered":
        out += [("steps", _N[n]), ("timeline", "three" if n == 3 else "six")]
    elif shape == "statement":
        out.append(("statement", "plain"))
    elif shape == "chart_short":
        out += [("chart_focus", "full"), ("split", "chart"), ("chart_takeaway", "full")]
    elif shape == "chart_long":
        out += [("split", "chart"), ("chart_takeaway", "chart_left")]
    elif shape == "contrast":
        out += [("compare", "default"), ("two_column", "text_text")]
    elif shape == "table":
        out += ([("table", "highlight"), ("split", "table")] if _texts(slide) else [("table", "compact")])
        out += [("table", "heat")] * bool(slide.table.heat)
    elif slide.layout in ("bullets", "cards") and 3 <= n <= 4:  # legacy bullets move (spec §1); one or two cards would stand alone
        out += [("cards", "three" if n <= 3 else "four"), ("cards", "rows"), ("summary", "default")]  # where a sparse cards slide goes next
    return list(dict.fromkeys(out))


def relayout(slide: SlideContent, layout: str, variant: str) -> tuple[SlideContent, list[str]]:
    """Moves the slide's content into layout/variant. Returns it and the names of the non-empty slots it lost."""
    spec = get_variant(layout, variant).slots
    slots = {k: v for k, v in slide.slots.items() if k in {sp.name for sp in spec}}
    rest = [k for k, v in slide.slots.items() if k not in slots and v]
    for sp in spec:  # an unmatched filled slot moves to a free slot of its kind: takeaway -> callout, items -> meters
        if sp.name not in slots and sp.kind in ("text", "list") and sp.name != "takeaway_bar" and not sp.name.startswith("label_"):
            k = next((k for k in rest if isinstance(slide.slots[k], list) == (sp.kind == "list")), None)
            if k:
                slots[sp.name] = slide.slots[k]
                rest.remove(k)
    kinds = {sp.kind for sp in spec}
    dropped = rest + [x for x in ("chart", "table") if getattr(slide, x) and x not in kinds]
    moved = slide.model_copy(update={"layout": layout, "variant": variant, "slots": slots,
                                     "chart": slide.chart if "chart" in kinds else None, "table": slide.table if "table" in kinds else None})
    return moved, dropped


def _fits(slide: SlideContent, density: str, last: bool = False) -> list[SlideContent]:
    """The candidates that keep every filled slot, hold every list within its item and word limits and parse, as moved
    slides (the current pick is not checked). The word limit matters where no fit stage follows (stewardship decks)."""
    out = []
    for ly, v in candidates(shape_of(slide), slide, density, last):
        if (ly, v) == (slide.layout, slide.variant):
            out.append(slide)
            continue
        moved, dropped = relayout(slide, ly, v)
        spec = get_variant(ly, v).slots
        lists = [(sp, items) for sp in spec if isinstance(items := moved.slots.get(sp.name), list)]
        full = any(sp.max_items and len(items) > sp.max_items for sp, items in lists)
        wordy = any(len(t.split()) > ((sp.committee_words if density == "committee" else None) or sp.max_words or 10**6)
                    for sp, items in lists for t in items)
        if not dropped and not full and not wordy and not structure_errors(moved, spec):
            out.append(moved)
    return out


def next_layouts(slide: SlideContent, density: str = "committee", last: bool = False) -> list[tuple[str, str]]:
    """The fitting picks after the slide's current layout, in order; `last` marks the deck's last content slide (for decisions)."""
    picks = [(s.layout, s.variant) for s in _fits(slide, density, last)]
    cur = (slide.layout, slide.variant)
    return picks[picks.index(cur) + 1:] if cur in picks else picks


def next_layout(slide: SlideContent, density: str = "committee", last: bool = False) -> tuple[str, str] | None:
    return next(iter(next_layouts(slide, density, last)), None)


def _visual(s: SlideContent) -> bool:
    return get_variant(s.layout, s.variant).visual


def rhythm_break(slides: list[SlideContent], i: int) -> str | None:
    """The rhythm rule slide i breaks, if any: a run of one layout three slides long through it, or a window of three
    content slides (title and sections aside) through it without a visual slide. Used by direct() and the design retry."""
    if any(len({s.layout for s in slides[a : a + 3]}) == 1 for a in range(max(0, i - 2), min(i, len(slides) - 3) + 1)):
        return "rhythm: no layout three times in a row"
    content = [j for j, s in enumerate(slides) if j and s.layout != "section"]
    k = content.index(i)
    if any(not any(_visual(slides[j]) for j in content[a : a + 3]) for a in range(max(0, k - 2), min(k, len(content) - 3) + 1)):
        return "rhythm: a visual slide in every three"
    return None


def direct(deck: Deck, density: str = "committee", shift: list[Finding] | None = None) -> tuple[Deck, list[Finding]]:
    """One pass, left to right. `shift`, when given, holds earlier findings on this deck: an inserted section moves them, in place."""
    content = [i for i, s in enumerate(deck.slides) if i and s.layout != "section"]
    out, findings, where = deck.slides[:1], [], {0: 0}
    since = sections = 0
    for i, s in enumerate(deck.slides[1:], 1):
        if s.layout == "section":
            sections, since = sections + 1, 0
            where[i] = len(out)
            out.append(s)
            continue
        # A divider every 5-7 slides: the 7th since the last one gets one, unless fewer than two content slides follow.
        if len(deck.slides) >= 12 and since == 6 and sum(j >= i for j in content) >= 2:
            sections, since = sections + 1, 0
            findings.append(Finding(slide=len(out), stage="design", rule="relayout", severity="info",
                                    message=f"section {sections} inserted before {s.headline!r} (a divider every 5-7 slides)"))
            out.append(SlideContent(headline=s.headline, layout="section", variant="default", slots={"number": str(sections), "title": s.headline}))
        opts = _fits(s, density, last=i == content[-1])
        opts += [s] * (s not in opts)
        why = shape_of(s)
        if why == "other":  # only two rules move unshaped content
            why = "legacy bullets" if s.layout == "bullets" else "committee pattern"
        pick = opts[0]
        if broken := rhythm_break([*out, pick], len(out)):  # the first pick that keeps both rules, else the first pick
            pick, why = next((o for o in opts if not rhythm_break([*out, o], len(out))), pick), broken
        if (pick.layout, pick.variant) != (s.layout, s.variant):
            findings.append(Finding(slide=len(out), stage="design", rule="relayout", severity="info",
                                    message=f"{s.layout}/{s.variant} → {pick.layout}/{pick.variant} ({why})"))
        where[i] = len(out)
        out.append(pick)
        since += 1
    for f in shift or []:
        f.slide = where.get(f.slide, f.slide)
    return deck.model_copy(update={"slides": out}), findings
