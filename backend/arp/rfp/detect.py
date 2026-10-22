"""Finding the questions of an incoming RFP (spec §2): the model reports them, the code keeps only those it can locate."""

from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient
from arp.rfp.locations import Layout, paragraph_index
from arp.rfp.text import is_placeholder, normalise

_SYSTEM = """You find the questions an investor asks in an RFP file, and where each answer goes.
The file is given as one line per location: `[location] text`. Locations are `<sheet>!<cell>` in Excel,
`P<n>` (a paragraph) and `T<t>R<r>C<c>` (a table cell) in Word. Excel cells that are empty are not listed.

For every question, return:
- location: the location of the question text, exactly as listed;
- question: the text at that location, copied exactly;
- answer_location: where the answer is to be written.
  - A question in a cell: the empty or placeholder cell (such as `[Response]`) where the investor expects the answer,
    usually next to or below it. In Excel it may be an empty cell that is not listed.
  - A question in a Word paragraph: always the question's own `P<n>`, meaning "after this paragraph", even when an
    empty or placeholder paragraph follows it (that paragraph then receives the answer).

Instructions, headings, section titles and contact details are not questions."""


class ReportedQuestion(BaseModel):
    location: str
    question: str
    answer_location: str


class DetectedQuestions(BaseModel):
    questions: list[ReportedQuestion] = Field(default_factory=list)


class Detected(BaseModel):
    location: str
    answer_location: str
    question: str


def _located(layout: Layout, q: ReportedQuestion) -> bool:
    text, answer = layout.text(q.location), layout.text(q.answer_location)
    if text is None or not normalise(q.question) or normalise(text) != normalise(q.question) or answer is None:
        return False
    if paragraph_index(q.answer_location) is not None:
        return q.answer_location == q.location  # "after this paragraph": only the question's own P<n>
    return q.answer_location != q.location and is_placeholder(answer)


def prompt_lines(layout: Layout) -> str:
    return "\n".join(f"[{loc}] {text}" if text.strip() else f"[{loc}] (empty)" for loc, text in layout.items)


async def detect_questions(layout: Layout, llm: LLMClient) -> tuple[list[Detected], int]:
    """(the located questions in file order, how many reported questions could not be located)."""
    # shortcut: one call for the whole file; batch the lines if real RFPs outgrow the output limit
    out, _ = await llm.complete_structured(
        system=_SYSTEM, prompt=prompt_lines(layout), output_model=DetectedQuestions, max_tokens=16384
    )
    kept: dict[str, Detected] = {}
    not_located = 0
    for q in out.questions:
        if q.location in kept:
            continue
        # a second question for an answer location already taken would overwrite the first answer on export
        if _located(layout, q) and all(d.answer_location != q.answer_location for d in kept.values()):
            kept[q.location] = Detected(location=q.location, answer_location=q.answer_location, question=layout.text(q.location))
        else:
            not_located += 1
    return sorted(kept.values(), key=lambda d: layout.order[d.location]), not_located
