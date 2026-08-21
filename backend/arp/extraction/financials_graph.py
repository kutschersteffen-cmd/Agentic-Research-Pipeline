from __future__ import annotations

from typing import TypedDict

from arp.config import Settings
from arp.extraction.financials_aggregator import build_financials_record
from arp.extraction.financials_extractor_agent import FinancialsExtractionDraft, extract_financials
from arp.extraction.financials_verifier_agent import FinancialsVerifierOutput, verify_financials
from arp.extraction.graph_shape import build_extract_verify_graph
from arp.extraction.segment_extractor_agent import SEGMENT_DOC_TYPES, SEGMENT_KEYWORDS
from arp.extraction.spend_extractor_agent import SPEND_DOC_TYPES, SPEND_KEYWORDS
from arp.ingestion.parsing import chunk_document
from arp.llm.base import LLMClient, LLMUsage
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import CompanyRef, DocumentChunk, ProvenanceInfo, SourceDocument
from arp.schemas.financials import CompanyFinancialsRecord
from arp.schemas.spend import SpendTopic

# Union of every section's doc types/keywords -- fetched and chunked once
# per company rather than once per topic, since segments/capex/R&D are
# almost always wanted together.
FINANCIALS_DOC_TYPES = sorted(set(SEGMENT_DOC_TYPES) | set(SPEND_DOC_TYPES), key=lambda d: d.value)
_ALL_KEYWORDS = sorted(set(SEGMENT_KEYWORDS) | set(SPEND_KEYWORDS[SpendTopic.CAPEX]) | set(SPEND_KEYWORDS[SpendTopic.RND]))

_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "segments": SEGMENT_KEYWORDS,
    "capex": SPEND_KEYWORDS[SpendTopic.CAPEX],
    "rnd": SPEND_KEYWORDS[SpendTopic.RND],
}
_MAX_CHUNKS_PER_TOPIC = 10


def _select_evidence(
    chunks: list[DocumentChunk], *, hybrid_retrieval_enabled: bool = False, content_store=None
) -> list[DocumentChunk]:
    """Per-topic BM25-ranked selection, capped per topic, then
    unioned/deduped -- so a topic with sparser evidence (e.g. a single
    CapEx sentence in a filing dominated by segment discussion) still gets
    its own guaranteed slice of the evidence sent to the single combined
    extractor call, instead of being crowded out by a single global
    ranking.
    """
    selected: dict[str, DocumentChunk] = {}
    for keywords in _TOPIC_KEYWORDS.values():
        for c in select_relevant_chunks(
            chunks,
            keywords,
            max_chunks=_MAX_CHUNKS_PER_TOPIC,
            hybrid_retrieval_enabled=hybrid_retrieval_enabled,
            content_store=content_store,
        ):
            selected[c.chunk_id] = c
    return list(selected.values())


class FinancialsState(TypedDict):
    company: CompanyRef
    documents: list[SourceDocument]
    documents_by_id: dict[str, SourceDocument]
    llm: LLMClient
    verifier_llm: LLMClient
    settings: Settings | None
    fuzzy_threshold: float
    confidence_review_threshold: float
    evidence: list[DocumentChunk]
    draft: FinancialsExtractionDraft | None
    verifier: FinancialsVerifierOutput | None
    usages: list[LLMUsage]
    extractor_usage: LLMUsage | None
    verifier_usage: LLMUsage | None
    record: CompanyFinancialsRecord | None


async def _gather_evidence(state: FinancialsState) -> dict:
    settings = state["settings"]
    all_chunks: list[DocumentChunk] = []
    for doc in state["documents"]:
        if doc.doc_type not in FINANCIALS_DOC_TYPES:
            continue
        all_chunks.extend(chunk_document(doc, keywords=_ALL_KEYWORDS))

    content_store = None
    hybrid_enabled = settings is not None and settings.hybrid_retrieval_enabled
    if hybrid_enabled:
        from arp.retrieval.content_store_factory import build_hybrid_content_store

        content_store = build_hybrid_content_store(settings)

    return {"evidence": _select_evidence(all_chunks, hybrid_retrieval_enabled=hybrid_enabled, content_store=content_store)}


def _route_after_evidence(state: FinancialsState) -> str:
    return "extract" if state["evidence"] else "finalize_no_evidence"


async def _finalize_no_evidence(state: FinancialsState) -> dict:
    # No matching evidence at all is the common case at scale (docs not
    # fetched, or the company simply doesn't discuss any of this) -- report
    # plainly rather than flooding the review queue.
    company = state["company"]
    record = CompanyFinancialsRecord(company_id=company.company_id, ticker=company.ticker, name=company.name, run_id="")
    return {"record": record}


async def _extract(state: FinancialsState) -> dict:
    draft, usage = await extract_financials(state["company"].name, state["evidence"], state["llm"])
    return {"draft": draft, "usages": state["usages"] + [usage], "extractor_usage": usage}


async def _verify(state: FinancialsState) -> dict:
    verifier, usage = await verify_financials(
        state["company"].name, state["evidence"], state["draft"], state["verifier_llm"]
    )
    return {"verifier": verifier, "usages": state["usages"] + [usage], "verifier_usage": usage}


async def _aggregate(state: FinancialsState) -> dict:
    company = state["company"]
    record, _needs_review = build_financials_record(
        company.company_id,
        company.ticker,
        company.name,
        state["draft"],
        state["verifier"],
        state["documents_by_id"],
        state["fuzzy_threshold"],
        state["confidence_review_threshold"],
    )
    extractor_usage = state["extractor_usage"]
    verifier_usage = state["verifier_usage"]
    provenance = ProvenanceInfo(
        extractor_model=extractor_usage.model if extractor_usage else None,
        extractor_prompt_version=extractor_usage.prompt_version if extractor_usage else None,
        verifier_model=verifier_usage.model if verifier_usage else None,
        verifier_prompt_version=verifier_usage.prompt_version if verifier_usage else None,
    )
    record = record.model_copy(update={"provenance": provenance})
    return {"record": record}


_COMPILED_GRAPH = build_extract_verify_graph(
    FinancialsState,
    gather_evidence=_gather_evidence,
    route_after_evidence=_route_after_evidence,
    finalize_no_evidence=_finalize_no_evidence,
    extract=_extract,
    verify=_verify,
    aggregate=_aggregate,
)


async def extract_company_financials(
    company: CompanyRef,
    *,
    documents: list[SourceDocument],
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings | None = None,
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[CompanyFinancialsRecord, list[LLMUsage]]:
    """Runs the combined segments/CapEx/R&D flow (one evidence gather, one
    combined extractor call, one combined independent-verifier call,
    then programmatic grounding + aggregation) as a LangGraph graph.

    `verifier_llm` defaults to `llm` only for callers that don't supply a
    separate model -- see `extract_one_field` for the same convention.
    `settings`, when supplied, gates hybrid retrieval the same way too.
    """
    documents_by_id = {d.doc_id: d for d in documents}
    initial: FinancialsState = {
        "company": company,
        "documents": documents,
        "documents_by_id": documents_by_id,
        "llm": llm,
        "verifier_llm": verifier_llm or llm,
        "settings": settings,
        "fuzzy_threshold": fuzzy_threshold,
        "confidence_review_threshold": confidence_review_threshold,
        "evidence": [],
        "draft": None,
        "verifier": None,
        "usages": [],
        "extractor_usage": None,
        "verifier_usage": None,
        "record": None,
    }
    final_state = await _COMPILED_GRAPH.ainvoke(initial)
    return final_state["record"], final_state["usages"]
