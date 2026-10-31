from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import TypedDict

from pydantic import ValidationError

from arp.config import Settings
from arp.extraction.adjudicator import AdjudicatorOutput, adjudicate, disagreement
from arp.extraction.aggregator import build_extracted_fields, no_evidence_field
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue, extract_field
from arp.extraction.graph_shape import build_extract_verify_graph
from arp.extraction.verifier_agent import DisagreementType, VerifierOutput, blind_verify, verify_extraction
from arp.extraction.vision_check import check_on_page
from arp.ingestion.parsing import chunk_document
from arp.ingestion.xbrl import FactSource, XbrlFact
from arp.llm.base import LLMClient, LLMUsage
from arp.normalise.value import typed_value
from arp.orchestration.step_tally import run_graph
from arp.planning.doc_routing import route_documents, section_filter
from arp.retrieval.keywords_de import with_german
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocumentChunk, ProvenanceInfo, SourceDocument
from arp.schemas.datapoints import ExtractedField, FieldDefinition, ValueState
from arp.schemas.review import ReasonCode
from arp.walkthrough import trace

logger = logging.getLogger(__name__)


class FieldState(TypedDict):
    company_name: str
    field: FieldDefinition
    documents: list[SourceDocument]
    documents_by_id: dict[str, SourceDocument]
    llm: LLMClient
    verifier_llm: LLMClient
    settings: Settings | None
    fuzzy_threshold: float
    schema_version: str
    fiscal_year_end: str | None
    planned_periods: list[str] | None
    confidence_review_threshold: float
    evidence: list[DocumentChunk]
    evidence_unranked: bool
    draft: ExtractionDraft | None
    verifier: VerifierOutput | None
    adjudicator: AdjudicatorOutput | None
    usages: list[LLMUsage]
    extractor_usage: LLMUsage | None
    verifier_usage: LLMUsage | None
    adjudicator_usage: LLMUsage | None
    extracted: list[ExtractedField]
    needs_review: bool
    facts: FactSource | None
    grouped: tuple[ExtractionDraft, list[DocumentChunk], LLMUsage] | None  # draft, evidence and usage of a group call
    extract_failed: bool  # the answer never fit the field type: stored as not found, routed to review
    seen: dict | None  # walkthrough trace only: model answers the state does not keep (blind draft, page reading)


def _tagged_field(state: FieldState, fact: XbrlFact, period_end: str) -> ExtractedField:
    field = state["field"]
    value, raw, unit_text, decimal = fact.reported()
    pv = PeriodValue(value=value, raw_value_text=raw, unit_text=unit_text, planned_period_end=period_end)
    tv = typed_value(field, pv, fiscal_year_end=state["fiscal_year_end"], planned={period_end}, decimal=decimal)
    return ExtractedField(
        field_id=field.field_id,
        field_name=field.name,
        value=tv.value,
        raw_value_text=raw,
        citations=[fact.as_citation()],
        confidence=1.0,
        grounded=True,  # the citation is the tagged fact itself (see XbrlFact.as_citation)
        verifier_notes=" ".join(tv.notes) or None,
        review_reasons=tv.reasons,
        provenance=ProvenanceInfo(schema_version=state["schema_version"], field_version=field.version),
        value_state=tv.value_state,
        unit=tv.unit,
        canonical_value=tv.canonical_value,
        canonical_unit=tv.canonical_unit,
        scale_applied=tv.scale_applied,
        period_text=tv.period_text,
        period_start=fact.period_start,
        period_end=tv.period_end,
        basis=tv.basis,
        qualifiers=tv.qualifiers,
        reported_precision=tv.reported_precision,
        fx_rate=tv.fx_rate,
        fx_rate_ref=tv.fx_rate_ref,
        method="tagged",
    )


MAX_END_DRIFT_DAYS = 7


def days_apart(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


async def _try_tagged(state: FieldState) -> dict:
    """E29: the filer's own XBRL fact for every planned period, or nothing (the
    model path then extracts as before). A fact must be for the planned fiscal
    year; one for another year never stands in for it."""
    field, facts, planned = state["field"], state["facts"], state["planned_periods"]
    if not (field.xbrl_tags and facts and planned):
        return {}
    found = {end: facts.fact_for_tags(field.xbrl_tags, fiscal_year=int(end[:4])) for end in planned}
    # The fact must cover the planned period itself: 52/53-week drift (a few days) is the
    # same period; a September year end against a planned December end is not.
    found = {end: f if f and f.period_end and days_apart(f.period_end, end) <= MAX_END_DRIFT_DAYS else None
             for end, f in found.items()}
    # ponytail: all periods or none; take the tagged ones and extract only the rest if comparatives often lack facts
    if not all(found.values()):
        return {}
    extracted = [_tagged_field(state, fact, end) for end, fact in found.items()]
    return {"extracted": extracted, "needs_review": any(f.review_reasons for f in extracted)}


def _route_after_tagged(state: FieldState) -> str:
    return "end" if state["extracted"] else "gather_evidence"


def field_evidence(
    field: FieldDefinition, documents: list[SourceDocument], settings: Settings | None, on_unranked_fallback=None
) -> list[DocumentChunk]:
    """The ranked evidence one field's extraction sees. Blocking (BM25/embedding/rerank are
    CPU-bound); `golden-set retrieval` replays it, so the eval measures exactly this path."""
    keywords = with_german(field.seed_keywords)
    all_chunks: list[DocumentChunk] = []
    for doc in route_documents(field, documents):
        all_chunks.extend(chunk_document(doc, keywords=keywords))
    all_chunks = section_filter(field, all_chunks)

    content_store = None
    if settings is not None and settings.hybrid_retrieval_enabled:
        from arp.retrieval.content_store_factory import build_hybrid_content_store

        content_store = build_hybrid_content_store(settings)

    opensearch_client = None
    if settings is not None and settings.retrieval_backend == "opensearch" and settings.opensearch_url:
        from arp.storage.opensearch_client import get_client

        opensearch_client = get_client(settings.opensearch_url)

    limits = {}
    if settings is not None:
        limits = {
            "max_chunks": settings.evidence_max_chunks,
            "rerank_candidates": settings.rerank_candidates if settings.rerank_enabled else None,
        }
    return select_relevant_chunks(
        all_chunks,
        keywords,
        doc_type_filter=None if field.document_routing else field.source_doc_types or None,
        hybrid_retrieval_enabled=settings is not None and settings.hybrid_retrieval_enabled,
        content_store=content_store,
        retrieval_backend=settings.retrieval_backend if settings is not None else "bm25",
        opensearch_client=opensearch_client,
        fallback_to_all=field.high_risk,
        on_unranked_fallback=on_unranked_fallback,
        semantic_query=field.retrieval_query,
        **limits,
    )


def merge_evidence(rankings: list[list[DocumentChunk]], cap: int) -> list[DocumentChunk]:
    """Several fields' ranked evidence as one list: round-robin, so each field's best passages make the cut."""
    seen: dict[str, DocumentChunk] = {}
    for rank in range(max(map(len, rankings), default=0)):
        for r in rankings:
            if rank < len(r) and len(seen) < cap:
                seen.setdefault(r[rank].chunk_id, r[rank])
    return list(seen.values())


async def _gather_evidence(state: FieldState) -> dict:
    if state.get("grouped"):
        return {"evidence": state["grouped"][1], "evidence_unranked": False}
    unranked: list[bool] = []
    evidence = await asyncio.to_thread(  # keep the CPU-bound ranking off the event loop
        field_evidence, state["field"], state["documents"], state["settings"], lambda: unranked.append(True)
    )
    return {"evidence": evidence, "evidence_unranked": bool(unranked)}


def _route_after_evidence(state: FieldState) -> str:
    return "extract" if state["evidence"] else "finalize_no_evidence"


async def _finalize_no_evidence(state: FieldState) -> dict:
    extracted, needs_review = no_evidence_field(state["field"])
    return {"extracted": [extracted], "needs_review": needs_review}


async def _extract(state: FieldState) -> dict:
    if state.get("grouped"):  # extracted by the group call; its usage is counted once, by the caller
        draft, _, usage = state["grouped"]
        return {"draft": draft, "extractor_usage": usage}
    try:
        draft, usage = await extract_field(
            state["company_name"], state["field"], state["evidence"], state["llm"], state["planned_periods"]
        )
    except ValidationError:
        # shortcut: the failed calls' token usage is not counted (the error carries none); count it if cost tracking needs it
        logger.warning("extraction of %s never fit the field type", state["field"].field_id)
        return {"draft": ExtractionDraft(confidence=0.0), "extract_failed": True}
    return {"draft": draft, "usages": state["usages"] + [usage], "extractor_usage": usage}


async def _verify(state: FieldState) -> dict:
    seen = state["seen"]
    if state.get("extract_failed"):  # nothing to verify: the field stays not found, in review
        return {"verifier": VerifierOutput(agrees=True, confidence=0.0, notes="Not verified: the extraction failed."),
                "verifier_usage": None}
    if state["field"].high_risk:  # E38: re-extract without seeing the draft
        verifier, usage = await blind_verify(
            state["company_name"], state["field"], state["evidence"], state["draft"], state["verifier_llm"],
            state["planned_periods"], state["fiscal_year_end"],
            on_draft=None if seen is None else lambda d: seen.update(blind_draft=d),
        )
    else:
        verifier, usage = await verify_extraction(
            state["company_name"], state["field"], state["evidence"], state["draft"], state["verifier_llm"]
        )
    return {"verifier": verifier, "usages": state["usages"] + [usage], "verifier_usage": usage}


async def _adjudicate(state: FieldState) -> dict:
    """E40: a third call, on the verifier client."""
    # ponytail: the verifier's model decides twice; add a separate adjudicator model setting if it rubber-stamps itself.
    out, usage = await adjudicate(
        state["company_name"], state["field"], state["evidence"], state["draft"], state["verifier"],
        state["verifier_llm"],
    )
    return {"adjudicator": out, "usages": state["usages"] + [usage], "adjudicator_usage": usage}


def _route_after_verify(state: FieldState) -> str:
    """Only a typed disagreement reaches the adjudicator."""
    return "aggregate" if disagreement(state["verifier"]) == DisagreementType.NONE else "adjudicate"


async def _aggregate(state: FieldState) -> dict:
    extracted = build_extracted_fields(
        state["field"],
        state["draft"],
        state["verifier"],
        state["documents_by_id"],
        state["fuzzy_threshold"],
        state["confidence_review_threshold"],
        passages={c.chunk_id: c for c in state["evidence"]},
        fiscal_year_end=state["fiscal_year_end"],
        planned_periods=state["planned_periods"],
        adjudicator=state["adjudicator"],
    )
    extractor_usage = state["extractor_usage"]
    verifier_usage = state["verifier_usage"]
    provenance = ProvenanceInfo(
        provider=extractor_usage.provider if extractor_usage else "",
        extractor_model=extractor_usage.model if extractor_usage else None,
        extractor_prompt_version=extractor_usage.prompt_version if extractor_usage else None,
        verifier_model=verifier_usage.model if verifier_usage else None,
        verifier_prompt_version=verifier_usage.prompt_version if verifier_usage else None,
        adjudicator_model=state["adjudicator_usage"].model if state["adjudicator_usage"] else None,
        schema_version=state["schema_version"],
        field_version=state["field"].version,
    )
    extracted = [f.model_copy(update={"provenance": provenance}) for f in extracted]
    if state["evidence_unranked"]:
        # Both passes saw the first chunks in document order (only a high-risk field falls back), so their
        # agreement that nothing is there proves nothing.
        extracted = [
            f.model_copy(update={"review_reasons": [*f.review_reasons, ReasonCode.HIGH_RISK_NOT_FOUND_UNRANKED]})
            if f.value_state == ValueState.NOT_FOUND else f
            for f in extracted
        ]
    if state.get("extract_failed"):
        extracted = [f.model_copy(update={"review_reasons": [*f.review_reasons, ReasonCode.EXTRACTION_FAILED]})
                     for f in extracted]
    usages = state["usages"]
    if state["settings"] and state["settings"].vision_fallback_enabled:
        passages = {c.chunk_id: c for c in state["evidence"]}
        seen = state["seen"]
        checked = []
        for f in extracted:
            if ReasonCode.NOT_GROUNDED in f.review_reasons:
                f, usage = await check_on_page(
                    state["company_name"], state["field"], f, passages, state["documents_by_id"], state["verifier_llm"],
                    on_reading=None if seen is None else lambda r: seen.update(reading=r),
                )
                usages = usages + [usage] if usage else usages
                if seen is not None and usage:
                    seen["vision_usage"] = usage
            checked.append(f)
        extracted = checked
    return {"extracted": extracted, "needs_review": any(f.review_reasons for f in extracted), "usages": usages}


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
    try_tagged=_try_tagged,
    route_after_tagged=_route_after_tagged,
    adjudicate=_adjudicate,
    route_after_verify=_route_after_verify,
)


def _trace_entry(state: FieldState, grouped: bool) -> dict:
    extracted, seen = state["extracted"], state["seen"]
    if extracted and extracted[0].method == "tagged":
        skipped = "tagged"
    elif not state["evidence"]:
        skipped = "no_evidence"
    else:
        skipped = None
    if state["field"].high_risk:
        verifier = trace.verifier_call(
            state["verifier_usage"], seen.get("blind_draft"), blind=True, verdict=state["verifier"]
        )
    else:
        verifier = trace.verifier_call(state["verifier_usage"], state["verifier"], blind=False, verdict=None)
    return trace.field_entry(
        state["field"].field_id,
        grouped=grouped,
        skipped=skipped,
        passages=[trace.passage(c) for c in state["evidence"]],
        extractor=trace.call(state["extractor_usage"], state["draft"]),
        verifier=verifier,
        adjudicator=trace.call(state["adjudicator_usage"], state["adjudicator"]),
        vision=trace.call(seen.get("vision_usage"), seen.get("reading")),
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
    schema_version: str = "",
    fiscal_year_end: str | None = None,
    planned_periods: list[str] | None = None,
    facts: FactSource | None = None,
    grouped: tuple[ExtractionDraft, list[DocumentChunk], LLMUsage] | None = None,
    trace_sink: dict | None = None,
) -> tuple[list[ExtractedField], bool, list[LLMUsage]]:
    """Runs one field's evidence-gather -> extract -> independent-verify ->
    adjudicate (typed disagreements only) -> programmatic-grounding-check -> aggregate flow as a LangGraph graph.
    Returns (extracted_fields, needs_review, usages): one field per
    reported period, latest first.

    `verifier_llm` is a second, deliberately different-model client for the
    verify step -- decorrelates errors an identical extractor/verifier model
    pair would otherwise be prone to repeat. Defaults to `llm` (the old
    single-model behavior) only for callers that don't supply one.

    `settings`, when supplied, additionally gates hybrid (BM25 + local
    multilingual embedding) evidence retrieval via
    settings.hybrid_retrieval_enabled -- omitted (None), evidence selection
    stays pure BM25, matching every caller written before this option
    existed.

    `facts` (the company's SEC companyfacts and/or ESEF filing facts), when
    supplied, lets a field with `xbrl_tags` take its tagged values with no model call.

    `grouped` (draft, evidence, usage): the field was already extracted by a group call
    (extractor_agent.extract_group); its evidence and draft are used as given, and verification,
    adjudication and grounding run on it as on any field. The usage is not added again.

    `trace_sink`, when supplied, gets `trace_sink[field.field_id]` = the field's walkthrough entry
    (passages and model answers), built from what the graph already holds: no extra model call.
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
        "schema_version": schema_version,
        "fiscal_year_end": fiscal_year_end,
        "planned_periods": planned_periods,
        "evidence": [],
        "evidence_unranked": False,
        "draft": None,
        "verifier": None,
        "adjudicator": None,
        "usages": [],
        "extractor_usage": None,
        "verifier_usage": None,
        "adjudicator_usage": None,
        "extracted": [],
        "needs_review": False,
        "facts": facts,
        "grouped": grouped,
        "extract_failed": False,
        "seen": None if trace_sink is None else {},
    }
    final_state = await run_graph(_COMPILED_GRAPH, initial)
    if trace_sink is not None:
        try:
            trace_sink[field.field_id] = _trace_entry(final_state, grouped is not None)
        except Exception:  # the trace never fails a field
            logger.warning("no trace for field %s", field.field_id, exc_info=True)
    return final_state["extracted"], final_state["needs_review"], final_state["usages"]
