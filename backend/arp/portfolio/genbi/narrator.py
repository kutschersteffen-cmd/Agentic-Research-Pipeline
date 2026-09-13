from __future__ import annotations

import re

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.portfolio.genbi.schemas import DashboardFact, Narrative, PanelResult

_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\u201c]?[A-Z0-9])")
"""Splits on sentence punctuation only when what follows starts a new
sentence. Deliberately conservative about decimals and thousands
separators: "EUR 1.23 million" has no whitespace after the period, so it is
never split mid-figure."""
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SCALE_WORDS = {"million": 1e6, "millions": 1e6, "bn": 1e9, "billion": 1e9, "billions": 1e9, "m": 1e6, "k": 1e3, "thousand": 1e3}
_RELATIVE_TOLERANCE = 0.01
"""How far a quoted figure may sit from a computed one and still count as
the same number. Wide enough for honest rounding ("EUR 12.3 million" for
12,345,678), far too tight for an invented figure to land inside by luck."""

_SYSTEM_PROMPT = """\
You write the commentary for a portfolio-risk dashboard. Every panel has
already been computed by a deterministic engine, and you are given the
resulting figures as a list of facts. Your job is to say what they mean.

Hard rules:
- You may only state numbers and dates that appear in the supplied facts.
  Never compute, derive, rescale, sum, or estimate a figure of your own --
  not even an obvious subtraction of two facts. A number you introduce that
  no fact supports is detected mechanically and your whole draft is thrown
  away in favour of the raw facts.
- Quote figures as the facts render them (currency, separators, decimals).
- Do not describe a movement, cause, comparison, or risk that the facts do
  not show. "Exposure rose" is only sayable if a fact says it rose.
- Say plainly when coverage is partial: a weighted average over 60% of
  market value is a 60% answer, not a portfolio answer.

Write a short headline paragraph (2-4 sentences) for the dashboard as a
whole, and one or two sentences per panel. Plain professional English, no
bullet points, no markdown, no hedging filler.
"""


class _PanelNote(BaseModel):
    panel_id: str
    text: str


class _NarrativeDraft(BaseModel):
    headline: str = ""
    panel_notes: list[_PanelNote] = Field(default_factory=list)


def _numeric_variants(value: float) -> list[float]:
    """A computed figure and the ways an honest writer might restate it:
    itself, its millions/billions/thousands rendering, and its percentage
    form (a 0.312 share written as "31.2%"). Rescalings only -- never a
    different number.
    """
    variants = [value, value * 100.0]
    for scale in (1e3, 1e6, 1e9):
        variants.append(value / scale)
    return variants


def allowed_numbers(facts: list[DashboardFact]) -> list[float]:
    """The reference set a narrative is checked against: every fact's own
    value, every number appearing in its deterministic text rendering (so
    holding counts and snapshot counts inside a sentence count too), and
    the rescalings of both.
    """
    values: list[float] = []
    for fact in facts:
        if fact.value is not None:
            values.extend(_numeric_variants(fact.value))
        for token in _NUMBER_RE.findall(_ISO_DATE_RE.sub(" ", fact.text)):
            parsed = _parse_number(token)
            if parsed is not None:
                values.extend(_numeric_variants(parsed))
    return values


def allowed_dates(facts: list[DashboardFact]) -> set[str]:
    return {d for fact in facts for d in _ISO_DATE_RE.findall(fact.text)}


def _parse_number(token: str) -> float | None:
    try:
        return float(token.replace(",", "").replace("+", ""))
    except ValueError:  # pragma: no cover -- the regex only matches parseable tokens
        return None


def _matches(candidate: float, allowed: list[float]) -> bool:
    for value in allowed:
        if abs(candidate - value) <= max(abs(value) * _RELATIVE_TOLERANCE, 1e-9):
            return True
    return False


def check_grounding(text: str, facts: list[DashboardFact]) -> list[str]:
    """The hard, programmatic precision control for generated prose -- the
    numeric counterpart of `grounding.is_grounded` for citations. Returns
    the tokens (figures or dates) that no computed fact supports; an empty
    list means every number in the text traces back to something the
    deterministic engine actually computed.

    Deliberately not delegated to the model's own confidence: a narrative
    that mentions a figure nobody computed is caught by arithmetic, not by
    asking the model whether it made it up.
    """
    if not text.strip():
        return []
    allowed = allowed_numbers(facts)
    dates = allowed_dates(facts)

    ungrounded = [d for d in _ISO_DATE_RE.findall(text) if d not in dates]

    stripped = _ISO_DATE_RE.sub(" ", text)
    for match in _NUMBER_RE.finditer(stripped):
        candidate = _parse_number(match.group())
        if candidate is None:  # pragma: no cover -- regex guarantees parseability
            continue
        trailing = stripped[match.end() : match.end() + 12].lower()
        scale_word = next((word for word in _SCALE_WORDS if trailing.strip().startswith(word)), None)
        scaled = candidate * _SCALE_WORDS[scale_word] if scale_word else candidate
        if _matches(candidate, allowed) or _matches(scaled, allowed):
            continue
        ungrounded.append(match.group())
    return ungrounded


def deterministic_text(facts: list[DashboardFact], limit: int = 3) -> str:
    """The fallback prose: the facts themselves, in order, with repeats
    dropped (two panels over the same holdings both restate the total).
    Flatter than a written narrative but never wrong, which is the right
    trade when a draft has failed its grounding check."""
    seen: list[str] = []
    for fact in facts:
        if fact.text not in seen:
            seen.append(fact.text)
        if len(seen) == limit:
            break
    return " ".join(seen) or "No figures were computed for this panel."


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text.strip()) if part.strip()]


def _narrative_from(draft_text: str, facts: list[DashboardFact]) -> Narrative:
    """Checks the draft one sentence at a time and keeps the sentences that
    ground.

    Rejecting a whole draft over a single loose rounding ("roughly 18%" for
    a computed 17.7%) throws away correct prose to punish one adjective --
    the cure being worse than the disease, since what replaces it is a flat
    list of facts. Per-sentence, the cost of an ungrounded figure is the
    sentence carrying it, and what survives is still fully checked. Only
    when nothing survives does the deterministic fact text take over.
    """
    if not draft_text.strip():
        return Narrative(text=deterministic_text(facts), grounded=True, source="deterministic_fallback")

    kept: list[str] = []
    rejected: list[str] = []
    ungrounded: list[str] = []
    for sentence in split_sentences(draft_text):
        tokens = check_grounding(sentence, facts)
        if tokens:
            rejected.append(sentence)
            ungrounded += [t for t in tokens if t not in ungrounded]
        else:
            kept.append(sentence)

    if not kept:
        return Narrative(
            text=deterministic_text(facts),
            grounded=False,
            source="deterministic_fallback",
            ungrounded_tokens=ungrounded,
            rejected_sentences=rejected,
        )
    if not rejected:
        return Narrative(text=" ".join(kept), grounded=True, source="llm")
    return Narrative(
        text=" ".join(kept),
        grounded=False,
        source="llm_partial",
        ungrounded_tokens=ungrounded,
        rejected_sentences=rejected,
    )


def _render_facts(panels: list[PanelResult], dashboard_facts: list[DashboardFact]) -> str:
    lines: list[str] = []
    for panel in panels:
        lines.append(f"Panel {panel.panel.panel_id} -- {panel.panel.title} (question: {panel.panel.question or 'n/a'})")
        if panel.error:
            lines.append(f"  [this panel failed to execute: {panel.error}]")
        for fact in panel.facts:
            lines.append(f"  - {fact.text}")
        if not panel.facts and not panel.error:
            lines.append("  - (no figures -- the query returned no rows)")
    if dashboard_facts:
        lines.append("Dashboard-level facts:")
        lines += [f"  - {fact.text}" for fact in dashboard_facts]
    return "\n".join(lines)


async def narrate(
    *,
    title: str,
    brief: str,
    goal: str,
    panels: list[PanelResult],
    dashboard_facts: list[DashboardFact],
    llm: LLMClient,
) -> tuple[Narrative, dict[str, Narrative], list[str], LLMUsage]:
    """Layers commentary on top of already-computed panels, then checks
    every figure in that commentary back against the facts it was given.

    Returns `(headline, {panel_id: narrative}, warnings, usage)`. A draft
    that quotes a number no panel computed is rejected and replaced by the
    deterministic fact text, with a warning naming the offending tokens --
    the dashboard still ships, just without the prose that failed.
    """
    prompt = (
        f"Dashboard: {title}\nBrief: {brief}\nGoal: {goal or 'n/a'}\n\nComputed facts:\n"
        f"{_render_facts(panels, dashboard_facts)}"
    )
    draft, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_NarrativeDraft)

    warnings: list[str] = []
    all_facts = [fact for panel in panels for fact in panel.facts] + dashboard_facts
    headline = _narrative_from(draft.headline, all_facts)
    if headline.rejected_sentences:
        warnings.append(_rejection_warning("Headline", headline))

    notes = {note.panel_id: note.text for note in draft.panel_notes}
    narratives: dict[str, Narrative] = {}
    for panel in panels:
        narrative = _narrative_from(notes.get(panel.panel.panel_id, ""), panel.facts)
        if narrative.rejected_sentences:
            warnings.append(_rejection_warning(f"Narrative for panel {panel.panel.title!r}", narrative))
        narratives[panel.panel.panel_id] = narrative
    return headline, narratives, warnings, usage


def _rejection_warning(subject: str, narrative: Narrative) -> str:
    count = len(narrative.rejected_sentences)
    tokens = ", ".join(narrative.ungrounded_tokens)
    scope = "dropped, rest kept" if narrative.source == "llm_partial" else "dropped; computed facts shown instead"
    return f"{subject}: {count} sentence(s) {scope} -- no computed figure supports {tokens}."
