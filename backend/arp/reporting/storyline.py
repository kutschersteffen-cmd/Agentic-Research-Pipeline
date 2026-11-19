"""House deck, LLM call 1: the storyline -- one takeaway headline per slide, approved by a human before any slide is built."""

from __future__ import annotations

from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.content_planner import _datasets_context
from arp.reporting.slide_fill import DESIGN_GUIDE, WRITING_GUIDE, add_usage
from arp.schemas.reporting import ReportRequest, Storyline

_SYSTEM = """\
You draft the storyline of an investment-research slide deck: a title, an \
optional subtitle, and an ordered list of slides, each with a headline, its \
purpose and the sources it draws on.

Rules:
- Each headline is one full sentence stating the slide's takeaway, at most \
14 words. Not a topic label ("Market context") but a claim ("Utilities lag \
the market on earnings growth").
- Read in order, the headlines tell the argument: someone who reads only the \
headlines should reach the goal's conclusion.
- target_length, when set, is the exact slide count (the title slide is added \
separately and does not count).
- Every claim must be grounded in the notes or datasets -- never invent \
numbers, companies or facts. source_refs name the dataset ids or note topics used.
- Match the audience's level and tone.
""" + "\n" + WRITING_GUIDE



_SUBHEADING = (
    "Subheadings: give every slide a subheading: one sentence of at most 16 words, under the headline, "
    "adding the evidence or scope behind it. Same grounding rules as headlines.\n\n"
)

CONTENT_VISUALS = ("kpi_row", "chart", "comparison_table", "two_column", "points")

_ARCS = {
    "executive": "answer first, KPI and decision slides",
    "client_pitch": "problem, cost of inaction, evidence, plan, next steps",
    "committee": "context, analysis, options, decision",
    "workshop": "more flows and tables",
}

_DECK = """\
Deck settings: profile={profile} (arc: {arc}), purpose={purpose}, detail={detail}, at most {cap} content slides.
The deck `title` is at most 10 words. Also return `answer` (the deck's answer for the cover, at most 30 words), \
`figures` (0-2 headline numbers from the sources for the cover), `sections` (each a `title` of at most 6 words \
and a `summary` of at most 14) and `closing` (2-5 next actions). The cover, section dividers and next-steps \
slide are added by code: do not draft them as slides.
For every slide set `visual` to one of {visuals}; `chart_kind` (bar, column, stacked_column, line or heatmap) when it \
is chart; `rationale` (why that visual, at most 20 words); `section` (0-based index into `sections`); and \
`kicker` (a short label above the headline).

Visual guide:
{design}
"""


def content_cap(request: ReportRequest) -> int:
    """The most content slides a deck keeps: `max_slides`, and never more than 8 for the executive profile."""
    return min(request.deck.max_slides, 8) if request.deck.profile == "executive" else request.deck.max_slides


def _errors(storyline: Storyline) -> list[str]:
    """Field limits on what the model returns (spec "Visual calls") that the schema does not hold."""
    errors = ["title: at most 10 words"] if len(storyline.title.split()) > 10 else []
    errors += [f"slide {i} subheading: at most 16 words" for i, s in enumerate(storyline.slides, 1) if len(s.subheading.split()) > 16]
    if any(s.visual for s in storyline.slides) and not 2 <= len(storyline.closing) <= 5:
        errors.append("closing: 2 to 5 next actions")
    return errors


async def draft_storyline(request: ReportRequest, llm: LLMClient) -> tuple[Storyline, LLMUsage]:
    n = request.layout.target_length
    a = request.audience
    d = request.deck
    prompt = (
        f"Title: {request.title}\n"
        f"Goal: {request.goal or '(none given)'}\n"
        f"Audience: level={a.level.value}, tone={a.tone.value}, description={a.description or '(none)'}, "
        f"focus_areas={a.focus_areas or '(none)'}\n"
        f"Slide count: {f'exactly {n} slides, not counting the title slide' if n else 'your choice'}\n\n"
        + _DECK.format(profile=d.profile, arc=_ARCS[d.profile], purpose=d.purpose, detail=d.detail, cap=content_cap(request),
                       visuals=", ".join(CONTENT_VISUALS), design=DESIGN_GUIDE) + "\n"
        + _SUBHEADING
        + f"Qualitative notes:\n{request.qualitative_notes}\n\n"
        + f"Quantitative datasets:\n{_datasets_context(request.datasets)}\n"
    )
    storyline, usage = await llm.complete_structured(system=_SYSTEM, prompt=prompt, output_model=Storyline)
    errors = _errors(storyline)
    if errors:  # one retry with the errors, as in slide_fill
        retry = prompt + "\nYour previous answer had these errors; fix them:\n- " + "\n- ".join(errors) + "\n"
        storyline, u2 = await llm.complete_structured(system=_SYSTEM, prompt=retry, output_model=Storyline)
        usage = add_usage(usage, u2)
        errors = _errors(storyline)
    if errors:
        raise ValueError("Storyline: " + "; ".join(errors))
    storyline.approved = False  # approval is a human action, never the model's
    return storyline, usage
