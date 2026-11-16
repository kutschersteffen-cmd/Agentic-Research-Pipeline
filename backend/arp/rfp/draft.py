"""Auto-fill (rfp-answers-design §3, rfp-approved-answers-first-design §1-3): a draft built from library entries. An
entry that answers the question as it is is copied by the code; otherwise the draft starts from the closest entry and is
kept only when nothing is missing, every quote grounds in its entry, every number comes from a cited entry or the
question, and the second model finds nothing unsupported or unanswered."""

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

_SYSTEM = """You draft the answer to one question in an investor's RFP from the firm's approved answers, using ONLY the
library entries given. Each entry is a question and an answer the firm has already approved, marked [E<id>].

- If one entry's answer answers the question as it is, set use_entry to that entry's id and leave the other fields
  empty: its answer is then used character for character.
- Otherwise answer from the approved answers: start from the closest entry, set base_entry_id to it, and change its
  answer as little as possible. Keep its words; only add, remove or replace what the question needs. Add no fact,
  figure, date or name that is not in a cited entry's answer.
- Cite every entry you use: its entry_id and a quote copied character for character from that entry's answer.
- List in missing every part of the question the entries do not answer. Say what is missing rather than guess. When
  the entries do not answer the question at all, return an empty answer, no citations, and what is missing."""

_VERIFY = """You check a drafted answer to an RFP question against the sources it cites. List in unsupported every fact,
figure, date or name in the draft that the sources do not state; rewording, shortening and combining are fine. List in
unanswered every part of the question the draft does not answer. Return two empty lists when the sources state
everything in the draft and the draft answers the whole question."""


@dataclass(frozen=True)
class Entry:
    id: int
    question: str
    answer: str
    review_by: date


class Cited(BaseModel):
    # exactly one of entry_id and document_id; a citation with both or neither fails the step (checked in code)
    entry_id: int | None = None
    document_id: int | None = None
    quote: str = Field(description="Copied character for character from the cited answer.")


class DraftOut(BaseModel):
    use_entry: int | None = Field(default=None, description="The id of an entry that answers the question as it is.")
    answer: str = Field(default="", description="The drafted text, when use_entry is null.")
    base_entry_id: int | None = Field(default=None, description="The entry the draft started from.")
    citations: list[Cited] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list, description="Each part of the question the sources do not answer.")


class FactCheck(BaseModel):
    unsupported: list[str] = Field(default_factory=list, description="Each fact in the draft that no source states.")
    unanswered: list[str] = Field(default_factory=list, description="Each part of the question the draft does not answer.")


@dataclass
class Draft:
    status: str
    answer: str = ""
    sources: list[dict] = field(default_factory=list)  # {"entry_id", "quote"}
    flags: list[str] = field(default_factory=list)
    base_entry_id: int | None = None
    document_priority: int | None = None


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


async def fact_check(verifier: LLMClient, question: str, support: list[str], answer: str) -> FactCheck:
    """The second model's check of `answer` against `support` (each `[E<id>] <whole answer>`)."""
    out, _ = await verifier.complete_structured(
        system=_VERIFY, prompt=f"Question: {question}\n\nSources:\n\n" + "\n\n".join(support) + f"\n\nDraft: {answer}",
        output_model=FactCheck,
    )
    return out


def _passes(question: str, out: DraftOut, shown: list[Entry]) -> tuple[str, list[dict], list[Entry], int | None] | None:
    """(answer, sources, cited entries, base entry id) when the step's conditions 1 to 4 hold, else None."""
    if out.missing:
        return None
    by_id = {e.id: e for e in shown}  # an entry the model was not shown never grounds
    if out.use_entry is not None:
        e = by_id.get(out.use_entry)
        return None if e is None else (e.answer, [{"entry_id": e.id, "quote": e.answer}], [e], e.id)
    answer = out.answer.strip()
    if not answer or not out.citations:
        return None
    # this slice shows no documents, so a document citation never grounds
    if any(c.document_id is not None or c.entry_id not in by_id for c in out.citations):
        return None
    docs = {str(e.id): SourceDocument(doc_id=str(e.id), company_id="rfp", doc_type=DocType.OTHER, title=e.question,
                                      full_text=e.answer) for e in shown}
    cites, grounded = ground_claim(
        [Citation(doc_id=str(c.entry_id), doc_type=DocType.OTHER, quote=c.quote) for c in out.citations], docs,
        claim_is_empty=False,
    )
    if not grounded:
        return None
    cited = list({c.entry_id: by_id[c.entry_id] for c in out.citations}.values())
    if not numbers(answer) <= numbers(question).union(*(numbers(e.answer) for e in cited)):
        return None
    sources = [{"entry_id": c.entry_id, "quote": g.span_text or c.quote} for c, g in zip(out.citations, cites, strict=True)]
    base = out.base_entry_id if out.base_entry_id in {e.id for e in cited} else cited[0].id
    return answer, sources, cited, base


async def draft_answer(question: str, entries: list[Entry], llm: LLMClient, verifier: LLMClient, *, today: date,
                       settings=None) -> Draft:
    """Step 0 of the chain: the top entries alone."""
    shown = select_entries(question, entries, settings)
    if not shown:
        return Draft(NO_SOURCE)
    listing = "\n\n".join(f"[E{e.id}]\nQuestion: {e.question}\nAnswer: {e.answer}" for e in shown)
    out, _ = await llm.complete_structured(
        system=_SYSTEM, prompt=f"Library entries:\n\n{listing}\n\nRFP question: {question}", output_model=DraftOut
    )
    passed = _passes(question, out, shown)
    if passed is None:
        return Draft(NO_SOURCE)
    answer, sources, cited, base = passed
    check = await fact_check(verifier, question, [f"[E{e.id}] {e.answer}" for e in cited], answer)
    if check.unsupported or check.unanswered:
        return Draft(NO_SOURCE)
    return Draft(DRAFTED, answer, sources, flags_for(answer, [e.review_by for e in cited], today), base, 0)
