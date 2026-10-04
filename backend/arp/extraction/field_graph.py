from __future__ import annotations

from datetime import date
from typing import TypedDict

from arp.config import Settings
from arp.extraction.adjudicator import AdjudicatorOutput, adjudicate, disagreement
from arp.extraction.aggregator import build_extracted_fields, no_evidence_field
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue, extract_field
from arp.extraction.graph_shape import build_extract_verify_graph
from arp.extraction.verifier_agent import DisagreementType, VerifierOutput, blind_verify, verify_extraction
from arp.ingestion.parsing import chunk_document
from arp.ingestion.xbrl import XbrlFact, XbrlFactSource
from arp.llm.base import LLMClient, LLMUsage
from arp.normalise.value import typed_value
from arp.orchestration.step_tally import run_graph
from arp.planning.doc_routing import route_documents, section_filter
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
    schema_version: str
    fiscal_year_end: str | None
    planned_periods: list[str] | None
    confidence_review_threshold: float
    evidence: list[DocumentChunk]
    draft: ExtractionDraft | None
    verifier: VerifierOutput | None
    adjudicator: AdjudicatorOutput | None
    usages: list[LLMUsage]
    extractor_usage: LLMUsage | None
    verifier_usage: LLMUsage | None
    adjudicator_usage: LLMUsage | None
    extracted: list[ExtractedField]
    needs_review: bool
    xbrl_facts: dict | None
    cik: str | None


def _tagged_field(state: FieldState, fact: XbrlFact, period_end: str) -> ExtractedField:
    field = state["field"]
    # Plain digits and a stated decimal point: the number as tagged, never a locale guess.
    raw = str(int(fact.value)) if fact.value.is_integer() else repr(fact.value)
    pv = PeriodValue(value=fact.value, raw_value_text=raw, unit_text=fact.unit, planned_period_end=period_end)
    tv = typed_value(field, pv, fiscal_year_end=state["fiscal_year_end"], planned={period_end}, decimal="point")
    return ExtractedField(
        field_id=field.field_id,
        field_name=field.name,
        value=tv.value,
        raw_value_text=raw,
        citations=[fact.as_citation(state["cik"])],
        confidence=1.0,
        grounded=True,  # the citation is the SEC fact itself (see XbrlFact.as_citation)
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


_MAX_END_DRIFT_DAYS = 7


def _days_apart(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


async def _try_tagged(state: FieldState) -> dict:
    """E29: the filer's own XBRL fact for every planned period, or nothing (the
    model path then extracts as before). A fact must be for the planned fiscal
    year; one for another year never stands in for it."""
    field, facts, planned = state["field"], state["xbrl_facts"], state["planned_periods"]
    if not (field.xbrl_tags and facts and state["cik"] and planned):
        return {}
    found = {end: XbrlFactSource.fact_for_tags(facts, field.xbrl_tags, fiscal_year=int(end[:4])) for end in planned}
    # The fact must cover the planned period itself: 52/53-week drift (a few days) is the
    # same period; a September year end against a planned December end is not.
    found = {end: f if f and f.period_end and _days_apart(f.period_end, end) <= _MAX_END_DRIFT_DAYS else None
             for end, f in found.items()}
    # ponytail: all periods or none; take the tagged ones and extract only the rest if comparatives often lack facts
    if not all(found.values()):
        return {}
    extracted = [_tagged_field(state, fact, end) for end, fact in found.items()]
    return {"extracted": extracted, "needs_review": any(f.review_reasons for f in extracted)}


def _route_after_tagged(state: FieldState) -> str:
    return "end" if state["extracted"] else "gather_evidence"


async def _gather_evidence(state: FieldState) -> dict:
    field = state["field"]
    settings = state["settings"]
    all_chunks: list[DocumentChunk] = []
    for doc in route_documents(field, state["documents"]):
        all_chunks.extend(chunk_document(doc, keywords=field.seed_keywords))
    all_chunks = section_filter(field, all_chunks)

    content_store = None
    if settings is not None and settings.hybrid_retrieval_enabled:
        from arp.retrieval.content_store_factory import build_hybrid_content_store

        content_store = build_hybrid_content_store(settings)

    opensearch_client = None
    if settings is not None and settings.retrieval_backend == "opensearch" and settings.opensearch_url:
        from arp.storage.opensearch_client import get_client

        opensearch_client = get_client(settings.opensearch_url)

    evidence = select_relevant_chunks(
        all_chunks,
        field.seed_keywords,
        doc_type_filter=None if field.document_routing else field.source_doc_types or None,
        hybrid_retrieval_enabled=settings is not None and settings.hybrid_retrieval_enabled,
        content_store=content_store,
        retrieval_backend=settings.retrieval_backend if settings is not None else "bm25",
        opensearch_client=opensearch_client,
    )
    return {"evidence": evidence}


def _route_after_evidence(state: FieldState) -> str:
    return "extract" if state["evidence"] else "finalize_no_evidence"


async def _finalize_no_evidence(state: FieldState) -> dict:
    extracted, needs_review = no_evidence_field(state["field"])
    return {"extracted": [extracted], "needs_review": needs_review}


async def _extract(state: FieldState) -> dict:
    draft, usage = await extract_field(
        state["company_name"], state["field"], state["evidence"], state["llm"], state["planned_periods"]
    )
    return {"draft": draft, "usages": state["usages"] + [usage], "extractor_usage": usage}


async def _verify(state: FieldState) -> dict:
    if state["field"].high_risk:  # E38: re-extract without seeing the draft
        verifier, usage = await blind_verify(
            state["company_name"], state["field"], state["evidence"], state["draft"], state["verifier_llm"],
            state["planned_periods"], state["fiscal_year_end"],
        )
    else:
        verifier, usage = await verify_extraction(
            state["company_name"], state["field"], state["evidence"], state["draft"], state["verifier_llm"]
        )
    return {"verifier": verifier, "usages": state["usages"] + [usage], "verifier_usage": usage}


async def _adjudicate(state: FieldState) -> dict:
    """E40: a third call, on the verifier client."""
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
    return {"extracted": extracted, "needs_review": any(f.review_reasons for f in extracted)}


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
    xbrl_facts: dict | None = None,
    cik: str | None = None,
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

    `xbrl_facts` (the company's companyfacts JSON) and `cik`, when supplied,
    let a field with `xbrl_tags` take its tagged values with no model call.
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
        "draft": None,
        "verifier": None,
        "adjudicator": None,
        "usages": [],
        "extractor_usage": None,
        "verifier_usage": None,
        "adjudicator_usage": None,
        "extracted": [],
        "needs_review": False,
        "xbrl_facts": xbrl_facts,
        "cik": cik,
    }
    final_state = await run_graph(_COMPILED_GRAPH, initial)
    return final_state["extracted"], final_state["needs_review"], final_state["usages"]
