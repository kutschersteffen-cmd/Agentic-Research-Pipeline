from __future__ import annotations

from typing import TypedDict

from arp.config import Settings
from arp.extraction.aggregator import build_extracted_field, no_evidence_field
from arp.extraction.extractor_agent import ExtractionDraft, extract_field
from arp.extraction.graph_shape import build_extract_verify_graph
from arp.extraction.verifier_agent import VerifierOutput, verify_extraction
from arp.ingestion.parsing import chunk_document
from arp.llm.base import LLMClient, LLMUsage
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocumentChunk, ProvenanceInfo, SourceDocument
from arp.schemas.datapoints import ExtractedField, FieldDefinition


class FieldState(TypedDict):
    company_name: str
    field: FieldDefinition
    documents: list[SourceDocument]
    documents_by_id: dict[str, SourceDocument]
    llm: LLMClient
    verifier_llm: LLMClient
    settings: Settings | None
    fuzzy_threshold: float
    confidence_review_threshold: float
    evidence: list[DocumentChunk]
    draft: ExtractionDraft | None
    verifier: VerifierOutput | None
    usages: list[LLMUsage]
    extractor_usage: LLMUsage | None
    verifier_usage: LLMUsage | None
    extracted: ExtractedField | None
    needs_review: bool


async def _gather_evidence(state: FieldState) -> dict:
    field = state["field"]
    settings = state["settings"]
    all_chunks: list[DocumentChunk] = []
    for doc in state["documents"]:
        if field.source_doc_types and doc.doc_type not in field.source_doc_types:
            continue
        all_chunks.extend(chunk_document(doc, keywords=field.seed_keywords))

    content_store = None
    if settings is not None and settings.hybrid_retrieval_enabled:
        from arp.retrieval.content_store_factory import build_hybrid_content_store

        content_store = build_hybrid_content_store(settings)

    evidence = select_relevant_chunks(
        all_chunks,
        field.seed_keywords,
        doc_type_filter=field.source_doc_types or None,
        hybrid_retrieval_enabled=settings is not None and settings.hybrid_retrieval_enabled,
        content_store=content_store,
    )
    return {"evidence": evidence}


def _route_after_evidence(state: FieldState) -> str:
    return "extract" if state["evidence"] else "finalize_no_evidence"


async def _finalize_no_evidence(state: FieldState) -> dict:
    extracted, needs_review = no_evidence_field(state["field"])
    return {"extracted": extracted, "needs_review": needs_review}


async def _extract(state: FieldState) -> dict:
    draft, usage = await extract_field(state["company_name"], state["field"], state["evidence"], state["llm"])
    return {"draft": draft, "usages": state["usages"] + [usage], "extractor_usage": usage}


async def _verify(state: FieldState) -> dict:
    verifier, usage = await verify_extraction(
        state["company_name"], state["field"], state["evidence"], state["draft"], state["verifier_llm"]
    )
    return {"verifier": verifier, "usages": state["usages"] + [usage], "verifier_usage": usage}


async def _aggregate(state: FieldState) -> dict:
    extracted, needs_review = build_extracted_field(
        state["field"],
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
    extracted = extracted.model_copy(update={"provenance": provenance})
    return {"extracted": extracted, "needs_review": needs_review}


# Compiled once and reused across every field invocation -- this graph runs
# at companies x fields scale per extraction run.
_COMPILED_GRAPH = build_extract_verify_graph(
    FieldState,
    gather_evidence=_gather_evidence,
    route_after_evidence=_route_after_evidence,
    finalize_no_evidence=_finalize_no_evidence,
    extract=_extract,
    verify=_verify,
    aggregate=_aggregate,
)


async def extract_one_field(
    company_name: str,
    field: FieldDefinition,
    *,
    documents: list[SourceDocument],
    documents_by_id: dict[str, SourceDocument],
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings | None = None,
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[ExtractedField, bool, list[LLMUsage]]:
    """Runs one field's evidence-gather -> extract -> independent-verify ->
    programmatic-grounding-check -> aggregate flow as a LangGraph graph.
    Returns (extracted_field, needs_review, usages).

    `verifier_llm` is a second, deliberately different-model client for the
    verify step -- decorrelates errors an identical extractor/verifier model
    pair would otherwise be prone to repeat. Defaults to `llm` (the old
    single-model behavior) only for callers that don't supply one.

    `settings`, when supplied, additionally gates hybrid (BM25 + local
    multilingual embedding) evidence retrieval via
    settings.hybrid_retrieval_enabled -- omitted (None), evidence selection
    stays pure BM25, matching every caller written before this option
    existed.
    """
    initial: FieldState = {
        "company_name": company_name,
        "field": field,
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
        "extracted": None,
        "needs_review": False,
    }
    final_state = await _COMPILED_GRAPH.ainvoke(initial)
    return final_state["extracted"], final_state["needs_review"], final_state["usages"]
