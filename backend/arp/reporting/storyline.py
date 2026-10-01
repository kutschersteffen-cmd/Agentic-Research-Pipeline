"""House deck, LLM call 1: the storyline -- one takeaway headline per slide, approved by a human before any slide is built."""

from __future__ import annotations

from arp.llm.base import LLMClient, LLMUsage
from arp.reporting.content_planner import _datasets_context
from arp.reporting.slide_fill import WRITING_GUIDE
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



async def draft_storyline(request: ReportRequest, llm: LLMClient) -> tuple[Storyline, LLMUsage]:
    n = request.layout.target_length
    a = request.audience
    prompt = (
        f"Title: {request.title}\n"
        f"Goal: {request.goal or '(none given)'}\n"
        f"Audience: level={a.level.value}, tone={a.tone.value}, description={a.description or '(none)'}, "
        f"focus_areas={a.focus_areas or '(none)'}\n"
        f"Slide count: {f'exactly {n} slides, not counting the title slide' if n else 'your choice'}\n\n"
        f"Qualitative notes:\n{request.qualitative_notes}\n\n"
        f"Quantitative datasets:\n{_datasets_context(request.datasets)}\n"
    )
    storyline, usage = await llm.complete_structured(system=_SYSTEM, prompt=prompt, output_model=Storyline)
    storyline.approved = False  # approval is a human action, never the model's
    return storyline, usage
