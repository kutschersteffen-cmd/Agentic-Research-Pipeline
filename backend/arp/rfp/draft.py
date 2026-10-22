"""Auto-fill (spec §3): a draft built only from library entries, kept only when every quote grounds in its entry and
every number comes from a cited entry or the question."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field

from arp.grounding import ground_claim
from arp.llm.base import LLMClient
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.rfp.text import has_figures, numbers
from arp.schemas.common import Citation, DocType, DocumentChunk, SourceDocument

NO_SOURCE, DRAFTED, EDITED, APPROVED, LEFT_BLANK = "no source", "drafted", "edited", "approved", "left blank"
CHECK_FIGURE, STALE_SOURCE = "check figure", "stale source"
TOP_ENTRIES = 8

_SYSTEM = """You draft the answer to one question in an investor's RFP, using ONLY the library entries given.
Each entry is a question and an answer the firm has already approved, marked [E<id>].

- Combine and shorten entries and fit the wording to the question, but add no fact, figure, date or name that is
  not in a cited entry's answer.
- Cite every entry you use: its entry_id and a quote copied character for character from that entry's answer.
- When the entries do not answer the question, return an empty answer and no citations. Never guess."""


@dataclass(frozen=True)
class Entry:
    id: int
    question: str
    answer: str
    review_by: date


class Cited(BaseModel):
    entry_id: int
    quote: str = Field(description="Copied character for character from the entry's answer.")


class DraftOut(BaseModel):
    answer: str = Field(default="", description="Empty when the entries do not answer the question.")
    citations: list[Cited] = Field(default_factory=list)


@dataclass
class Draft:
    status: str
    answer: str = ""
    sources: list[dict] = field(default_factory=list)  # {"entry_id", "quote"}
    flags: list[str] = field(default_factory=list)


def flags_for(answer: str, source_review_bys: list[date], today: date) -> list[str]:
    out = [CHECK_FIGURE] if has_figures(answer) else []
    return out + ([STALE_SOURCE] if any(r < today for r in source_review_bys) else [])


def select_entries(question: str, entries: list[Entry], settings=None) -> list[Entry]:
    """The top entries for `question`: BM25, fused with vectors when hybrid retrieval is on."""
    if not entries:
        return []
    by_chunk = {f"rfp-{e.id}-{hashlib.sha256((e.question + e.answer).encode()).hexdigest()[:12]}": e for e in entries}
    chunks = [
        DocumentChunk(chunk_id=cid, doc_id=str(e.id), company_id="rfp", doc_type=DocType.OTHER,
                      text=f"{e.question}\n{e.answer}", char_start=0, char_end=len(e.question) + len(e.answer) + 1)
        for cid, e in by_chunk.items()
    ]
    hybrid = settings is not None and settings.hybrid_retrieval_enabled
    store = None
    if hybrid:
        from arp.retrieval.content_store_factory import content_store_for

        store = content_store_for(settings)
    picked = select_relevant_chunks(
        chunks, [question], max_chunks=TOP_ENTRIES, require_hit=True, fallback_to_all=True,
        hybrid_retrieval_enabled=hybrid, content_store=store,
    )
    return [by_chunk[c.chunk_id] for c in picked]


async def draft_answer(question: str, entries: list[Entry], llm: LLMClient, *, today: date, settings=None) -> Draft:
    shown = select_entries(question, entries, settings)
    if not shown:
        return Draft(NO_SOURCE)
    listing = "\n\n".join(f"[E{e.id}]\nQuestion: {e.question}\nAnswer: {e.answer}" for e in shown)
    out, _ = await llm.complete_structured(
        system=_SYSTEM, prompt=f"Library entries:\n\n{listing}\n\nRFP question: {question}", output_model=DraftOut
    )
    answer = out.answer.strip()
    if not answer or not out.citations:
        return Draft(NO_SOURCE)
    by_id = {e.id: e for e in shown}  # an entry the model was not shown never grounds
    docs = {str(e.id): SourceDocument(doc_id=str(e.id), company_id="rfp", doc_type=DocType.OTHER, title=e.question,
                                      full_text=e.answer) for e in shown}
    cites, grounded = ground_claim(
        [Citation(doc_id=str(c.entry_id), doc_type=DocType.OTHER, quote=c.quote) for c in out.citations], docs,
        claim_is_empty=False,
    )
    if not grounded:
        return Draft(NO_SOURCE)
    cited = [by_id[c.entry_id] for c in out.citations]
    if not numbers(answer) <= numbers(question).union(*(numbers(e.answer) for e in cited)):
        return Draft(NO_SOURCE)
    sources = [{"entry_id": c.entry_id, "quote": g.span_text or c.quote} for c, g in zip(out.citations, cites, strict=True)]
    return Draft(DRAFTED, answer, sources, flags_for(answer, [e.review_by for e in cited], today))
