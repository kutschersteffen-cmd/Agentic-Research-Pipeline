"""Loading past RFP responses into the answer library (spec §1). Answers are stored verbatim from the file."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, Field

from arp.grounding import ground_citations
from arp.llm.base import LLMClient
from arp.rfp.detect import prompt_lines
from arp.rfp.locations import Layout, document_date
from arp.rfp.text import plus_12_months
from arp.schemas.common import Citation, DocType, SourceDocument

_SYSTEM = """You list the question-and-answer pairs in a past RFP response the firm sent to an investor.
The file is given as one line per location: `[location] text`.
For every pair, quote the question and the firm's full answer character for character from the file.
Leave out headings, instructions and questions with no answer."""


class QuotedPair(BaseModel):
    question: str = Field(description="Copied character for character from the file.")
    answer: str = Field(description="Copied character for character from the file.")


class QuotedPairs(BaseModel):
    pairs: list[QuotedPair] = Field(default_factory=list)


@dataclass(frozen=True)
class LibraryPair:
    question: str
    answer: str
    location: str
    approved_on: date
    review_by: date


async def extract_pairs(data: bytes, suffix: str, llm: LLMClient, *, today: date) -> tuple[list[LibraryPair], list[str]]:
    """(the pairs whose question and answer both ground in the file, the questions of the dropped ones)."""
    layout = Layout(data, suffix)
    starts, parts, pos = [], [], 0
    for loc, text in layout.items:
        starts.append((pos, loc))
        parts.append(text)
        pos += len(text) + 1
    doc = SourceDocument(doc_id="f", company_id="rfp", doc_type=DocType.OTHER, title="", full_text="\n".join(parts))
    dated = document_date(data) or today
    out, _ = await llm.complete_structured(system=_SYSTEM, prompt=prompt_lines(layout), output_model=QuotedPairs, max_tokens=16384)
    kept, dropped = [], []
    for p in out.pairs:
        q, a = ground_citations([Citation(doc_id="f", doc_type=DocType.OTHER, quote=s) for s in (p.question, p.answer)], {"f": doc})
        if not (q.grounded and a.grounded):
            dropped.append(p.question)
            continue
        location = next(loc for start, loc in reversed(starts) if start <= a.char_start)
        kept.append(LibraryPair(q.span_text, a.span_text, location, dated, plus_12_months(dated)))
    return kept, dropped
