from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from arp.config import Settings
from arp.extraction.tnfd_aggregator import build_tnfd_record
from arp.extraction.tnfd_extractor_agent import TNFD_DOC_TYPES, TNFD_KEYWORDS, TNFDExtractionDraft, extract_tnfd
from arp.extraction.tnfd_verifier_agent import TNFDVerifierOutput, verify_tnfd
from arp.ingestion.parsing import chunk_document
from arp.llm.base import LLMClient, LLMUsage
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import CompanyRef, DocumentChunk, ProvenanceInfo, SourceDocument
from arp.schemas.tnfd import TNFDExtractionRecord

_MAX_CHUNKS = 40  # TNFD covers 4 pillars + metrics + sector guidance, so it
# needs a wider evidence slice than a single-topic extraction like segments.


class TNFDState(TypedDict):
    company: CompanyRef
    documents: list[SourceDocument]
    documents_by_id: dict[str, SourceDocument]
    run_id: str
    as_of: str
    llm: LLMClient
    verifier_llm: LLMClient
    settings: Settings | None
    fuzzy_threshold: float
    confidence_review_threshold: float
    evidence: list[DocumentChunk]
    draft: TNFDExtractionDraft | None
    verifier: TNFDVerifierOutput | None
    usages: list[LLMUsage]
    extractor_usage: LLMUsage | None
    verifier_usage: LLMUsage | None
    record: TNFDExtractionRecord | None


async def _gather_evidence(state: TNFDState) -> dict:
    settings = state["settings"]
    all_chunks: list[DocumentChunk] = []
    for doc in state["documents"]:
        if doc.doc_type not in TNFD_DOC_TYPES:
            continue
        all_chunks.extend(chunk_document(doc, keywords=TNFD_KEYWORDS))

    content_store = None
    hybrid_enabled = settings is not None and settings.hybrid_retrieval_enabled
    if hybrid_enabled:
        from arp.retrieval.content_store_factory import build_hybrid_content_store

        content_store = build_hybrid_content_store(settings)

    evidence = select_relevant_chunks(
        all_chunks,
        TNFD_KEYWORDS,
        max_chunks=_MAX_CHUNKS,
        hybrid_retrieval_enabled=hybrid_enabled,
        content_store=content_store,
    )
    return {"evidence": evidence}


def _route_after_evidence(state: TNFDState) -> str:
    return "extract" if state["evidence"] else "finalize_no_evidence"


async def _finalize_no_evidence(state: TNFDState) -> dict:
    # No matching evidence at all is the common case at scale (docs not
    # fetched, or the issuer simply hasn't published TNFD-aligned
    # disclosures) -- report plainly rather than flooding the review queue.
    company = state["company"]
    record = TNFDExtractionRecord(
        company_id=company.company_id,
        ticker=company.ticker,
        name=company.name,
        run_id=state["run_id"],
        as_of=state["as_of"],
    )
    return {"record": record}


async def _extract(state: TNFDState) -> dict:
    draft, usage = await extract_tnfd(
        state["company"].name, state["company"].sector, state["evidence"], state["llm"]
    )
    return {"draft": draft, "usages": state["usages"] + [usage], "extractor_usage": usage}


async def _verify(state: TNFDState) -> dict:
    verifier, usage = await verify_tnfd(
        state["company"].name, state["evidence"], state["draft"], state["verifier_llm"]
    )
    return {"verifier": verifier, "usages": state["usages"] + [usage], "verifier_usage": usage}


async def _aggregate(state: TNFDState) -> dict:
    company = state["company"]
    record, _needs_review = build_tnfd_record(
        company.company_id,
        company.ticker,
        company.name,
        state["run_id"],
        state["as_of"],
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


def _build_graph():
    graph = StateGraph(TNFDState)
    graph.add_node("gather_evidence", _gather_evidence)
    graph.add_node("finalize_no_evidence", _finalize_no_evidence)
    graph.add_node("extract", _extract)
    graph.add_node("verify", _verify)
    graph.add_node("aggregate", _aggregate)

    graph.set_entry_point("gather_evidence")
    graph.add_conditional_edges(
        "gather_evidence", _route_after_evidence, {"extract": "extract", "finalize_no_evidence": "finalize_no_evidence"}
    )
    graph.add_edge("finalize_no_evidence", END)
    graph.add_edge("extract", "verify")
    graph.add_edge("verify", "aggregate")
    graph.add_edge("aggregate", END)
    return graph.compile()


_COMPILED_GRAPH = _build_graph()


async def extract_company_tnfd(
    company: CompanyRef,
    *,
    documents: list[SourceDocument],
    run_id: str,
    as_of: str,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings | None = None,
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[TNFDExtractionRecord, list[LLMUsage]]:
    """Runs the combined TNFD flow (one evidence gather, one combined
    extractor call across all 4 pillars/14 recommendations/metrics, one
    combined independent-verifier call, then programmatic grounding +
    aggregation) as a LangGraph graph -- see extract_company_financials for
    the same shape.

    `verifier_llm` defaults to `llm` only for callers that don't supply a
    separate model. `settings`, when supplied, gates hybrid retrieval.
    """
    documents_by_id = {d.doc_id: d for d in documents}
    initial: TNFDState = {
        "company": company,
        "documents": documents,
        "documents_by_id": documents_by_id,
        "run_id": run_id,
        "as_of": as_of,
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
