"""Deterministic writing lint for a filled deck, plus a bounded targeted rewrite of the slots it flags.

Each rule is one entry in RULES: `rule(deck, request) -> list[Finding]`. Headlines are linted but
never rewritten -- the user approved them.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterator

from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.house_style import get_variant
from arp.reporting.slide_fill import rewrite_slot
from arp.schemas.reporting import Deck, Finding, ReportRequest, SlideContent


def _texts(slide: SlideContent, headline: bool = False) -> Iterator[tuple[str, str]]:
    """(slot, text) for every string and list item; the headline only when asked."""
    if headline:
        yield "headline", slide.headline
    for slot, v in slide.slots.items():
        for t in [v] if isinstance(v, str) else v:
            yield slot, t


def _find(i: int, slot: str, rule: str, message: str) -> Finding:
    return Finding(slide=i, slot=slot, stage="lint", rule=rule, message=message)


def _words(t: str) -> int:
    return len(t.split())


def over_word_limit(deck: Deck, request: ReportRequest) -> list[Finding]:
    out = []
    for i, s in enumerate(deck.slides):
        try:
            specs = {sp.name: sp for sp in get_variant(s.layout, s.variant).slots}
        except KeyError:
            continue  # an unknown variant is a data finding, not ours
        for slot, v in s.slots.items():
            sp = specs.get(slot)
            if sp is None:
                continue
            items = [v] if isinstance(v, str) else v
            if sp.max_items and len(items) > sp.max_items:
                out.append(_find(i, slot, "over_word_limit", f"Use at most {sp.max_items} items."))
            if sp.max_words and any(_words(t) > sp.max_words for t in items):
                out.append(_find(i, slot, "over_word_limit", f"Shorten to at most {sp.max_words} words{' per item' if sp.kind == 'list' else ''}."))
    return out


_STOCK = re.compile(
    r"\b(?:leverag(?:e|es|ed|ing)(?!\s+(?:loans?|ratios?|buyouts?))|(?:delv|showcas|underscor|elevat|streamlin|navigat)(?:e|es|ed|ing)"
    r"|(?:unlock|empower|foster)(?:s|ed|ing)?|robust|seamless|landscape|pivotal|tapestry|holistic|synergy|cutting-edge"
    r"|game-changer|realm|testament|crucial|vibrant|paradigm)\b",
    re.I,
)
_NOT_X_BUT_Y = re.compile(r"\bnot (just |only |merely )?[^.;]{1,60}?,? but\b", re.I)


def _per_text(rule: str, pattern: re.Pattern, message: Callable[[re.Match], str]):
    def check(deck: Deck, request: ReportRequest) -> list[Finding]:
        return [
            _find(i, slot, rule, message(m))
            for i, s in enumerate(deck.slides) for slot, t in _texts(s, headline=True) if (m := pattern.search(t))
        ]
    return check


def triad_repeat(deck: Deck, request: ReportRequest) -> list[Finding]:
    hits = []
    for i, s in enumerate(deck.slides):
        lists = {k: v for k, v in s.slots.items() if isinstance(v, list)}
        if lists and all(len(v) == 3 and all(_words(t) < 5 for t in v) for v in lists.values()):
            hits += [(i, k) for k in lists]
    if len({i for i, _ in hits}) < 3:
        return []
    return [_find(i, k, "triad_repeat", "Vary the list shape: use a different number of items, with fuller sentences.") for i, k in hits]


_DASH = re.compile(r"[—–]| - ")


def dash_overuse(deck: Deck, request: ReportRequest) -> list[Finding]:
    out = []
    for i, s in enumerate(deck.slides):
        texts = list(_texts(s))
        if sum(len(_DASH.findall(t)) for _, t in texts) > 1:
            out += [_find(i, slot, "dash_overuse", "Use commas or full stops instead of dashes.") for slot in dict.fromkeys(sl for sl, t in texts if _DASH.search(t))]
    return out


_LABEL = re.compile(r"^\s*(?:\*\*[^*:]+:\*\*|[A-Za-z][\w ]{0,30}:(?!\d))")


def bold_label(deck: Deck, request: ReportRequest) -> list[Finding]:
    out = []
    for i, s in enumerate(deck.slides):
        hits = [(slot, t) for slot, t in _texts(s) if isinstance(s.slots[slot], list) and _LABEL.match(t)]
        if len(hits) >= 2:
            out += [_find(i, slot, "bold_label", "Drop the 'Label:' prefixes; write each item as a sentence.") for slot in dict.fromkeys(sl for sl, _ in hits)]
    return out


def _opener(t: str) -> str | None:
    ws = [w for w in re.findall(r"[a-z0-9']+", t.lower()) if w not in {"the", "a", "an"}]
    return ws[0] if ws else None


def repeated_opener(deck: Deck, request: ReportRequest) -> list[Finding]:
    slots = [(i, slot, _opener(t)) for i, s in enumerate(deck.slides) for slot, t in _texts(s)]
    counts = Counter(o for *_, o in slots if o)
    return [
        _find(i, slot, "repeated_opener", f"Start this differently; '{o}' opens {counts[o]} slots in the deck.")
        for i, slot, o in dict.fromkeys(slots) if o and counts[o] >= 3
    ]


_NUM = re.compile(r"(?<![\w.:])-?\d[\d,]*(?:\.\d+)?\s*(%|(?:bn|m|k|x)\b)?")
_MULT = {"bn": 1e9, "m": 1e6, "k": 1e3}


def _numbers(text: str) -> Iterator[tuple[float, int, str | None]]:
    """(value with multiplier, decimals, suffix) for each number in text."""
    for m in _NUM.finditer(text):
        raw = re.match(r"-?[\d,]*(?:\.(\d+))?", m.group()).group().replace(",", "")
        yield float(raw) * _MULT.get(m.group(1), 1), len(raw.partition(".")[2]), m.group(1)


def _sources(request: ReportRequest) -> list[float]:
    vals = [v for v, _, _ in _numbers(request.qualitative_notes)]
    for ds in request.datasets:
        vals += [float(c) for r in ds.rows for c in r.values() if isinstance(c, (int, float)) and not isinstance(c, bool)]
    return vals


def number_not_in_source(deck: Deck, request: ReportRequest) -> list[Finding]:
    src = _sources(request)
    out = []
    for i, s in enumerate(deck.slides):
        for slot, t in _texts(s, headline=True):
            for n, d, suffix in _numbers(t):
                if suffix is None and (abs(n) <= 10 and n == int(n) or 1900 <= abs(n) <= 2100 and n == int(n)):
                    continue
                tol = 0.5 * 10 ** -d * _MULT.get(suffix, 1)
                if not any(abs(n - v) <= tol or suffix == "%" and abs(n - v * 100) <= tol for v in src):
                    out.append(_find(i, slot, "number_not_in_source", f"A number here ({n:g}{suffix or ''}) is not in the notes or datasets; use a sourced figure or drop it."))
    return out


RULES: dict[str, Callable[[Deck, ReportRequest], list[Finding]]] = {
    "over_word_limit": over_word_limit,
    "stock_ai_word": _per_text("stock_ai_word", _STOCK, lambda m: f"Replace '{m.group()}' with a plain verb or the specific thing."),
    "not_x_but_y": _per_text("not_x_but_y", _NOT_X_BUT_Y, lambda m: "State the point directly instead of 'not X but Y'."),
    "triad_repeat": triad_repeat,
    "dash_overuse": dash_overuse,
    "bold_label": bold_label,
    "exclamation": _per_text("exclamation", re.compile("!"), lambda m: "Remove the exclamation mark."),
    "repeated_opener": repeated_opener,
    "number_not_in_source": number_not_in_source,
}


def lint_deck(deck: Deck, request: ReportRequest) -> list[Finding]:
    # Slide 0's `title` slot is the approved storyline title, same text as the headline: lint it once, as the headline.
    first = deck.slides[0].model_copy(update={"slots": {k: v for k, v in deck.slides[0].slots.items() if k != "title"}})
    view = deck.model_copy(update={"slides": [first, *deck.slides[1:]]})
    return [f for rule in RULES.values() for f in rule(view, request)]


async def lint_and_rewrite(
    deck: Deck, request: ReportRequest, llm: LLMClient, max_rounds: int = 2, usage: LLMUsage | None = None,
) -> tuple[Deck, list[Finding]]:
    """Rewrite each flagged slot with its findings as the instruction, at most `max_rounds` times; what survives is returned."""
    findings = lint_deck(deck, request)
    for _ in range(max_rounds):
        todo: dict[tuple[int, str], list[str]] = {}
        for f in findings:
            if f.slot != "headline":
                todo.setdefault((f.slide, f.slot), []).append(f.message)
        if not todo:
            break
        slides = list(deck.slides)
        for (i, slot), msgs in todo.items():
            try:
                new = await rewrite_slot(slides[i], slot, " ".join(dict.fromkeys(msgs)), request, llm, usage)
            except Exception:  # noqa: BLE001 -- unknown slot/variant or a failed call: keep the finding, keep the deck
                continue
            text, old = new.slots[slot], slides[i].slots[slot]
            if isinstance(old, list) and isinstance(text, str):
                text = [text]
            elif isinstance(old, str) and isinstance(text, list):
                text = " ".join(text)
            slides[i] = new.model_copy(update={"slots": {**new.slots, slot: text}})
        deck = deck.model_copy(update={"slides": slides})
        findings = lint_deck(deck, request)
    return deck, findings
