from __future__ import annotations

from typing import TypedDict

from arp.extraction.aggregator import build_extracted_field, no_evidence_field
from arp.extraction.extractor_agent import ExtractionDraft, extract_field
from arp.extraction.graph_shape import build_extract_verify_graph
from arp.extraction.verifier_agent import VerifierOutput, verify_extraction
from arp.ingestion.parsing import chunk_document
from arp.llm.base import LLMClient, LLMUsage
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocumentChunk, SourceDocument
from arp.schemas.datapoints import ExtractedField, FieldDefinition


class FieldState(TypedDict):
    company_name: str
    field: FieldDefinition
    documents: list[SourceDocument]
    documents_by_id: dict[str, SourceDocument]
    llm: LLMClient
    fuzzy_threshold: float
    confidence_review_threshold: float
    evidence: list[DocumentChunk]
    draft: ExtractionDraft | None
    verifier: VerifierOutput | None
    usages: list[LLMUsage]
    extracted: ExtractedField | None
    needs_review: bool


async def _gather_evidence(state: FieldState) -> dict:
    field = state["field"]
    all_chunks: list[DocumentChunk] = []
    for doc in state["documents"]:
        if field.source_doc_types and doc.doc_type not in field.source_doc_types:
            continue
        all_chunks.extend(chunk_document(doc, keywords=field.seed_keywords))
    evidence = select_relevant_chunks(all_chunks, field.seed_keywords, doc_type_filter=field.source_doc_types or None)
    return {"evidence": evidence}


def _route_after_evidence(state: FieldState) -> str:
    return "extract" if state["evidence"] else "finalize_no_evidence"


async def _finalize_no_evidence(state: FieldState) -> dict:
    extracted, needs_review = no_evidence_field(state["field"])
    return {"extracted": extracted, "needs_review": needs_review}


async def _extract(state: FieldState) -> dict:
    draft, usage = await extract_field(state["company_name"], state["field"], state["evidence"], state["llm"])
    return {"draft": draft, "usages": state["usages"] + [usage]}


async def _verify(state: FieldState) -> dict:
    verifier, usage = await verify_extraction(
        state["company_name"], state["field"], state["evidence"], state["draft"], state["llm"]
    )
    return {"verifier": verifier, "usages": state["usages"] + [usage]}


async def _aggregate(state: FieldState) -> dict:
    extracted, needs_review = build_extracted_field(
        state["field"],
        state["draft"],
        state["verifier"],
        state["documents_by_id"],
        state["fuzzy_threshold"],
        state["confidence_review_threshold"],
    )
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
    fuzzy_threshold: float,
    confidence_review_threshold: float,
) -> tuple[ExtractedField, bool, list[LLMUsage]]:
    """Runs one field's evidence-gather -> extract -> independent-verify ->
    programmatic-grounding-check -> aggregate flow as a LangGraph graph.
    Returns (extracted_field, needs_review, usages).
    """
    initial: FieldState = {
        "company_name": company_name,
        "field": field,
        "documents": documents,
        "documents_by_id": documents_by_id,
        "llm": llm,
        "fuzzy_threshold": fuzzy_threshold,
        "confidence_review_threshold": confidence_review_threshold,
        "evidence": [],
        "draft": None,
        "verifier": None,
        "usages": [],
        "extracted": None,
        "needs_review": False,
    }
    final_state = await _COMPILED_GRAPH.ainvoke(initial)
    return final_state["extracted"], final_state["needs_review"], final_state["usages"]
