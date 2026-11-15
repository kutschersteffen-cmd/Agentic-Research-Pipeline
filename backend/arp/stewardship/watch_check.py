"""Argus checks watch items against documents and finds commitments in call and meeting notes (spec
stewardship-commitment-loop, "The check" and "Finding commitments in notes"). The model only drafts: code grounds
every quote before a pending suggestion is written, and nothing here changes an item's status."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from arp.grounding import ground_citations
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.discovery import DocumentEvent, DocumentEventType
from arp.schemas.engagement import EvidenceSuggestion, WatchItem
from arp.storage.postgres_engagement_store import is_iso_date

if TYPE_CHECKING:
    from arp.ingestion.registry import DocumentSourceRegistry
    from arp.llm.base import LLMClient
    from arp.storage.postgres_engagement_store import PostgresEngagementStore

logger = logging.getLogger(__name__)

_MAX_DOC_CHARS = 60_000  # longer documents are narrowed to the passages that match the items' words
_MAX_CHUNKS = 15
# shortcut: the unique btree index on (activity_id, quote) holds keys up to ~2,700 bytes. A note's quote is one sentence
# (the golden notes' longest is 178 characters, the golden report quotes' 317), so a quote over 2,000 bytes is dropped as
# ungrounded instead of failing the insert. Move the index to md5(quote) if notes ever need longer quotes.
_MAX_QUOTE_BYTES = 2_000


class WatchItemVerdict(BaseModel):
    item_id: str
    verdict: Literal["found", "against", "unclear"]
    quote: str = ""  # verbatim from the document; empty for unclear
    reason: str = ""  # one sentence


class WatchCheckDraft(BaseModel):
    results: list[WatchItemVerdict]


class FoundCommitment(BaseModel):
    text: str
    proof_statement: str | None = None
    target_date: str | None = None  # YYYY-MM-DD, only when the note states a date
    quote: str  # verbatim from the note


class CommitmentFindDraft(BaseModel):
    commitments: list[FoundCommitment]


class ArgusFailed(Exception):
    """A model call failed (error, timeout, output that does not parse): nothing from that request is stored."""


CHECK_SYSTEM = """You are Argus, a stewardship analyst at an asset manager. The house asked a company for things \
(objectives), recorded what the company promised (commitments) and keeps questions to watch (topics). You read one \
company document and decide, for each watch item, what the document shows:
- found: the document states that the item was met, or answers the question with yes.
- against: the document states that the item was not met, was missed, dropped, reversed or contradicted, or answers \
the question with no.
- unclear: the document does not decide the item. This includes plans, intentions and progress that stop short of the \
item, and statements about a different target, year or scope.
Be strict: answer found or against only when one sentence of the document decides the item on its own. For found and \
against, copy that sentence verbatim into quote, character for character, without changing or joining text. For \
unclear, leave quote empty. Give a one-sentence reason. Return one result per item, using its id."""

FIND_SYSTEM = """You are Argus, a stewardship analyst at an asset manager. You read the note an analyst wrote after a \
call or meeting with a company and list every commitment the company made in it: a specific action the company or its \
representatives agreed to take. Not commitments: requests by the investor that the company did not agree to, vague \
intentions ("will consider", "is looking at"), things already done, and general statements of strategy.
For each commitment:
- text: what the company will do, as a short imperative phrase ("Publish a transition plan").
- proof_statement: one sentence saying what evidence would show it was met, or null.
- target_date: YYYY-MM-DD only when the note states a date or a period end ("by 31 March 2027" -> 2027-03-31, "by the \
end of 2027" -> 2027-12-31); otherwise null.
- quote: the sentence of the note that records the commitment, copied verbatim, character for character.
Return an empty list when the note records no commitment."""


def _document_text(doc: SourceDocument, items: list[WatchItem]) -> str:
    if len(doc.full_text) <= _MAX_DOC_CHARS:
        return doc.full_text
    from arp.ingestion.parsing import chunk_document
    from arp.retrieval.select_evidence import select_relevant_chunks

    terms = [t for i in items for t in (i.text, i.proof_statement) if t]
    chunks = select_relevant_chunks(chunk_document(doc, keywords=terms), terms, max_chunks=_MAX_CHUNKS, fallback_to_all=True)
    return "\n\n[...]\n\n".join(c.text for c in sorted(chunks, key=lambda c: c.char_start))


def check_prompt(doc: SourceDocument, items: list[WatchItem]) -> str:
    rows = [
        {"id": i.item_id, "kind": i.item_kind, "text": i.text, "proof_statement": i.proof_statement, "due_date": i.target_date}
        for i in items
    ]
    return (
        f"Document: {doc.title} ({doc.doc_type.value}, published {doc.published_at or 'unknown'})\n\n"
        f"<document>\n{_document_text(doc, items)}\n</document>\n\n"
        f"Watch items:\n{json.dumps(rows, indent=1)}"
    )


async def draft_check(llm: LLMClient, doc: SourceDocument, items: list[WatchItem]) -> WatchCheckDraft:
    return (await llm.complete_structured(system=CHECK_SYSTEM, prompt=check_prompt(doc, items), output_model=WatchCheckDraft))[0]


def _grounds(quote: str, doc: SourceDocument, fuzzy_threshold: float) -> Citation | None:
    citation = ground_citations([Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)], {doc.doc_id: doc}, fuzzy_threshold)[0]
    return citation if citation.grounded else None


def evidence_suggestions(
    draft: WatchCheckDraft, items: list[WatchItem], doc: SourceDocument, company_id: str, fuzzy_threshold: float
) -> tuple[list[EvidenceSuggestion], int]:
    """Steps 1 to 3 of the spec's "Code, after the call": the suggestions to write and the unclear count."""
    by_id = {i.item_id: i for i in items}
    out: list[EvidenceSuggestion] = []
    unclear = 0
    for r in draft.results:
        item = by_id.get(r.item_id)
        if item is None:
            continue
        citation = _grounds(r.quote, doc, fuzzy_threshold) if r.verdict != "unclear" and r.quote.strip() else None
        if citation is None:
            unclear += 1
            continue
        out.append(
            EvidenceSuggestion(
                kind="evidence", company_id=company_id, engagement_id=item.engagement_id, item_kind=item.item_kind,
                item_id=item.item_id, verdict=r.verdict, doc_id=doc.doc_id, doc_type=doc.doc_type.value,
                doc_title=doc.title, quote=r.quote, page=citation.page, reason=r.reason or None,
            )
        )
    return out, unclear


async def check_documents(
    store: PostgresEngagementStore, llm: LLMClient, company_id: str, items: list[WatchItem], docs: list[SourceDocument],
    fuzzy_threshold: float,
) -> dict[str, int]:
    """One model call per document, all before anything is written; raises ArgusFailed when any call fails."""
    try:
        drafts = await asyncio.gather(*(draft_check(llm, doc, items) for doc in docs))
    except Exception as exc:  # noqa: BLE001 - any model failure is the one 502 the spec names
        raise ArgusFailed(str(exc)) from exc
    suggestions: list[EvidenceSuggestion] = []
    unclear = 0
    for draft, doc in zip(drafts, docs, strict=True):
        found, not_clear = evidence_suggestions(draft, items, doc, company_id, fuzzy_threshold)
        suggestions += found
        unclear += not_clear
    written, skipped = store.add_suggestions(company_id, suggestions) if suggestions else (0, 0)
    return {"documents": len(docs), "suggestions": written, "unclear": unclear, "skipped": skipped}


def newest(docs: list[SourceDocument], n: int = 5) -> list[SourceDocument]:
    """`published_at` if set, else `fetched_at`, descending; ties by `doc_id`."""
    docs = sorted(docs, key=lambda d: d.doc_id)
    return sorted(docs, key=lambda d: d.published_at or d.fetched_at, reverse=True)[:n]


async def check_on_events(
    events: list[DocumentEvent], company: CompanyRef | None, *, store: PostgresEngagementStore, llm: LLMClient,
    registry: DocumentSourceRegistry, fuzzy_threshold: float,
) -> None:
    """The automatic run: each new or updated document of a company with watch items is checked against all of them."""
    for company_id in dict.fromkeys(e.company_id for e in events):
        mine = [e for e in events if e.company_id == company_id and e.event_type in (DocumentEventType.NEW_DOCUMENT, DocumentEventType.UPDATED_DOCUMENT)]
        items = store.watch_items(company_id) if mine else []
        if not items:
            continue
        ref = company if company and company.company_id == company_id else CompanyRef(company_id=company_id, name=mine[0].company_name)
        by_path = {Path(d.local_path).resolve(): d for d in await registry.fetch_all(ref) if d.local_path}
        for event in mine:
            doc = by_path.get(Path(event.document.local_path).resolve()) if event.document.local_path else None
            if doc is None:
                logger.info("Watch check: %s is not a registered document of %s; skipped", event.document.url, company_id)
                continue
            try:
                counts = await check_documents(store, llm, company_id, items, [doc], fuzzy_threshold)
            except ArgusFailed:  # one failed document never stops the others
                logger.exception("Watch check of %s on %s failed", doc.doc_id, company_id)
                continue
            logger.info("Watch check of %s on %s: %s", doc.doc_id, company_id, counts)


def commitment_suggestions(
    draft: CommitmentFindDraft, note: SourceDocument, engagement_id: str, fuzzy_threshold: float
) -> tuple[list[EvidenceSuggestion], int]:
    """The `new_commitment` suggestions to write from `note` (doc_id = the activity id) and the ungrounded count."""
    out: list[EvidenceSuggestion] = []
    ungrounded = 0
    for c in draft.commitments:
        if len(c.quote.encode()) > _MAX_QUOTE_BYTES or not c.quote.strip() or _grounds(c.quote, note, fuzzy_threshold) is None:
            ungrounded += 1
            continue
        out.append(
            EvidenceSuggestion(
                kind="new_commitment", company_id=note.company_id, engagement_id=engagement_id, activity_id=note.doc_id,
                text=c.text, proof_statement=c.proof_statement or None,
                target_date=c.target_date if c.target_date and is_iso_date(c.target_date) else None, quote=c.quote,
            )
        )
    return out, ungrounded


def note_document(activity_id: str, company_id: str, summary: str) -> SourceDocument:
    return SourceDocument(doc_id=activity_id, company_id=company_id, doc_type=DocType.OTHER, title="note", full_text=summary)


async def draft_find(llm: LLMClient, summary: str) -> CommitmentFindDraft:
    return (await llm.complete_structured(system=FIND_SYSTEM, prompt=f"<note>\n{summary}\n</note>", output_model=CommitmentFindDraft))[0]


async def find_commitments(
    store: PostgresEngagementStore, llm: LLMClient, activity_id: str, fuzzy_threshold: float
) -> dict[str, int]:
    company_id, engagement_id, summary = store.note_for_find(activity_id)
    try:
        draft = await draft_find(llm, summary)
    except Exception as exc:  # noqa: BLE001 - see check_documents
        raise ArgusFailed(str(exc)) from exc
    suggestions, ungrounded = commitment_suggestions(draft, note_document(activity_id, company_id, summary), engagement_id, fuzzy_threshold)
    written, skipped = store.add_suggestions(company_id, suggestions) if suggestions else (0, 0)
    return {"suggestions": written, "ungrounded": ungrounded, "skipped": skipped}
