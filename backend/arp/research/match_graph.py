from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from arp.config import Settings
from arp.grounding import ground_citations
from arp.ingestion.parsing import chunk_document
from arp.llm.base import LLMClient, LLMUsage
from arp.research.indirect_exposure.exposure import compute_indirect_exposure
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.research.matcher_agents import run_adjudicator, run_advocate, run_opposing
from arp.research.revenue_exposure.resolver import RevenueResolverContext, band_exposure, resolve_company_activity_exposure
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import CompanyRef, DocumentChunk, SourceDocument
from arp.schemas.exposure import IndirectExposureResult
from arp.schemas.revenue_exposure import RevenueExposureResult
from arp.schemas.thematic import ActivityDefinition, AgentOpinion, CompanyMatch, ExposureEstimate, MatchVerdict

_MAX_EVIDENCE_CHUNKS_PER_CALL = 12


def _no_evidence_opinion() -> AgentOpinion:
    return AgentOpinion(
        stance="No evidence found",
        rationale="No document chunks matched this activity's seed keywords in the available disclosures.",
        citations=[],
        exposure_estimate=ExposureEstimate.NONE,
    )


class MatchState(TypedDict):
    """State threaded through one (company, activity) pair's matching
    graph. `usages` accumulates every LLM call's usage across whichever
    branch actually runs; `match` is the only required output."""

    company: CompanyRef
    activity: ActivityDefinition
    documents: list[SourceDocument]
    documents_by_id: dict[str, SourceDocument]
    llm: LLMClient
    verifier_llm: LLMClient | None
    settings: Settings
    indirect_model: LeontiefModel | None
    revenue_resolver: RevenueResolverContext | None
    company_isic: str | None
    indirect: IndirectExposureResult | None
    revenue_exposure: RevenueExposureResult | None
    evidence: list[DocumentChunk]
    advocate: AgentOpinion | None
    opposing: AgentOpinion | None
    usages: list[LLMUsage]
    match: CompanyMatch | None


async def _compute_indirect(state: MatchState) -> dict:
    indirect_model = state["indirect_model"]
    company_isic = state["company_isic"]
    activity = state["activity"]
    indirect = None
    if indirect_model is not None and company_isic and activity.core_isic_codes:
        indirect = compute_indirect_exposure(
            state["company"].company_id, company_isic, indirect_model, set(activity.core_isic_codes), indirect_model.edition_label
        )
    return {"indirect": indirect}


async def _resolve_revenue(state: MatchState) -> dict:
    revenue_resolver = state["revenue_resolver"]
    if revenue_resolver is None:
        return {"revenue_exposure": None}
    revenue_exposure, usage = await resolve_company_activity_exposure(
        state["company"],
        state["activity"],
        state["company_isic"],
        documents=state["documents"],
        ctx=revenue_resolver,
        llm=state["llm"],
        verifier_llm=state["verifier_llm"],
    )
    return {"revenue_exposure": revenue_exposure, "usages": state["usages"] + [usage]}


def _route_after_revenue(state: MatchState) -> str:
    revenue_exposure = state["revenue_exposure"]
    if revenue_exposure is not None and revenue_exposure.revenue.value_pct is not None:
        # Path 1 (catalogue) or path 2 (extraction) resolved a hard
        # number -- the qualitative debate (path 3) is skipped entirely,
        # both for cost and because a real disclosed/extracted figure
        # shouldn't be second-guessed by a categorical LLM judgment over
        # the same question.
        return "finalize_from_revenue"
    return "gather_evidence"


async def _finalize_from_revenue(state: MatchState) -> dict:
    company, activity, settings = state["company"], state["activity"], state["settings"]
    indirect, revenue_exposure = state["indirect"], state["revenue_exposure"]
    revenue = revenue_exposure.revenue
    banded = band_exposure(revenue.value_pct, settings)
    verdict = MatchVerdict.EXCLUDE if banded == ExposureEstimate.NONE else MatchVerdict.INCLUDE
    source_desc = "structured revenue catalogue" if revenue.source == "catalogue" else "an extracted, grounded disclosure figure"
    rationale = f"Resolved via {source_desc}: {revenue.value_pct:.1%} of revenue attributed to this activity. {revenue.notes}".strip()
    citations = [revenue.citation] if revenue.citation else []
    ungrounded = revenue.citation is not None and not revenue.citation.grounded
    flagged = revenue.source == "extracted" and (revenue.confidence < settings.confidence_review_threshold or ungrounded)
    match = CompanyMatch(
        company_id=company.company_id,
        ticker=company.ticker,
        name=company.name,
        activity_id=activity.activity_id,
        activity_name=activity.name,
        verdict=verdict,
        exposure_estimate=banded,
        confidence=revenue.confidence,
        adjudicator_rationale=rationale,
        citations=citations,
        indirect_exposure=indirect,
        revenue_exposure=revenue_exposure,
        flagged_for_review=flagged,
    )
    return {"match": match}


async def _gather_evidence(state: MatchState) -> dict:
    activity = state["activity"]
    settings = state["settings"]
    all_chunks: list[DocumentChunk] = []
    for doc in state["documents"]:
        all_chunks.extend(chunk_document(doc, keywords=activity.seed_keywords))

    content_store = None
    if settings.hybrid_retrieval_enabled:
        # Opt-in, so this store is only ever constructed on the path
        # that's actually going to use it -- see
        # arp/retrieval/content_store_factory.py for the SQLite-vs-
        # pgvector backend choice (Settings.embeddings_backend).
        from arp.retrieval.content_store_factory import build_hybrid_content_store

        content_store = build_hybrid_content_store(settings)

    evidence = select_relevant_chunks(
        all_chunks,
        activity.seed_keywords,
        max_chunks=_MAX_EVIDENCE_CHUNKS_PER_CALL,
        hybrid_retrieval_enabled=settings.hybrid_retrieval_enabled,
        content_store=content_store,
    )
    return {"evidence": evidence}


def _route_after_evidence(state: MatchState) -> str:
    return "run_advocate" if state["evidence"] else "finalize_no_evidence"


async def _finalize_no_evidence(state: MatchState) -> dict:
    company, activity, settings = state["company"], state["activity"], state["settings"]
    indirect, revenue_exposure = state["indirect"], state["revenue_exposure"]
    structural_flag = bool(
        indirect
        and max(indirect.upstream_exposure, indirect.downstream_exposure) >= settings.indirect_exposure_review_threshold
    )
    rationale = "No evidence of this activity was found in the available documents."
    if structural_flag:
        rationale += (
            " However, input-output propagation shows structural exposure to this activity's core "
            "sectors above the review threshold -- routed for a second look rather than excluded outright."
        )
    match = CompanyMatch(
        company_id=company.company_id,
        ticker=company.ticker,
        name=company.name,
        activity_id=activity.activity_id,
        activity_name=activity.name,
        verdict=MatchVerdict.EXCLUDE,
        exposure_estimate=ExposureEstimate.NONE,
        confidence=0.5 if structural_flag else 1.0,
        advocate=_no_evidence_opinion(),
        opposing=_no_evidence_opinion(),
        adjudicator_rationale=rationale,
        citations=[],
        indirect_exposure=indirect,
        revenue_exposure=revenue_exposure,
        flagged_for_review=structural_flag,
    )
    return {"match": match}


async def _run_advocate_node(state: MatchState) -> dict:
    advocate, usage = await run_advocate(state["company"].name, state["activity"], state["evidence"], state["llm"])
    return {"advocate": advocate, "usages": state["usages"] + [usage]}


async def _run_opposing_node(state: MatchState) -> dict:
    opposing, usage = await run_opposing(
        state["company"].name, state["activity"], state["evidence"], state["advocate"], state["llm"]
    )
    return {"opposing": opposing, "usages": state["usages"] + [usage]}


async def _run_adjudicator_node(state: MatchState) -> dict:
    adjudication, usage = await run_adjudicator(
        state["company"].name, state["activity"], state["advocate"], state["opposing"], state["llm"]
    )
    settings = state["settings"]
    grounded_citations = ground_citations(adjudication.citations, state["documents_by_id"], settings.grounding_fuzzy_threshold)
    all_grounded = all(c.grounded for c in grounded_citations) if grounded_citations else False
    flagged = (
        adjudication.verdict == MatchVerdict.UNCERTAIN
        or adjudication.confidence < settings.confidence_review_threshold
        or (adjudication.verdict == MatchVerdict.INCLUDE and not all_grounded)
    )
    company, activity = state["company"], state["activity"]
    match = CompanyMatch(
        company_id=company.company_id,
        ticker=company.ticker,
        name=company.name,
        activity_id=activity.activity_id,
        activity_name=activity.name,
        verdict=adjudication.verdict,
        exposure_estimate=adjudication.exposure_estimate,
        confidence=adjudication.confidence,
        advocate=state["advocate"],
        opposing=state["opposing"],
        adjudicator_rationale=adjudication.adjudicator_rationale,
        citations=grounded_citations,
        indirect_exposure=state["indirect"],
        revenue_exposure=state["revenue_exposure"],
        flagged_for_review=flagged,
    )
    return {"match": match, "usages": state["usages"] + [usage]}


def _build_graph():
    graph = StateGraph(MatchState)
    graph.add_node("compute_indirect", _compute_indirect)
    graph.add_node("resolve_revenue", _resolve_revenue)
    graph.add_node("finalize_from_revenue", _finalize_from_revenue)
    graph.add_node("gather_evidence", _gather_evidence)
    graph.add_node("finalize_no_evidence", _finalize_no_evidence)
    graph.add_node("run_advocate", _run_advocate_node)
    graph.add_node("run_opposing", _run_opposing_node)
    graph.add_node("run_adjudicator", _run_adjudicator_node)

    graph.set_entry_point("compute_indirect")
    graph.add_edge("compute_indirect", "resolve_revenue")
    graph.add_conditional_edges(
        "resolve_revenue", _route_after_revenue, {"finalize_from_revenue": "finalize_from_revenue", "gather_evidence": "gather_evidence"}
    )
    graph.add_edge("finalize_from_revenue", END)
    graph.add_conditional_edges(
        "gather_evidence", _route_after_evidence, {"run_advocate": "run_advocate", "finalize_no_evidence": "finalize_no_evidence"}
    )
    graph.add_edge("finalize_no_evidence", END)
    graph.add_edge("run_advocate", "run_opposing")
    graph.add_edge("run_opposing", "run_adjudicator")
    graph.add_edge("run_adjudicator", END)
    return graph.compile()


# Compiled once at import time and reused across every (company, activity)
# invocation -- construction is not free, and this graph is invoked at
# companies x activities scale per run.
_COMPILED_GRAPH = _build_graph()


async def match_company_activity(
    company: CompanyRef,
    activity: ActivityDefinition,
    *,
    documents: list[SourceDocument],
    documents_by_id: dict[str, SourceDocument],
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings,
    indirect_model: LeontiefModel | None = None,
    revenue_resolver: RevenueResolverContext | None = None,
    company_isic: str | None = None,
) -> tuple[CompanyMatch, list[LLMUsage]]:
    """Runs the full per-(company, activity) matching decision as a
    LangGraph graph: the zero-LLM indirect-exposure computation, the
    revenue-exposure resolver's catalogue/extraction cascade (with its own
    internal LLM calls), and -- only if neither short-circuits with a hard
    number or an empty evidence set -- the Advocate/Opposing/Adjudicator
    debate, followed by the programmatic grounding check. Returns the
    final CompanyMatch plus every LLMUsage collected along the way.
    """
    initial: MatchState = {
        "company": company,
        "activity": activity,
        "documents": documents,
        "documents_by_id": documents_by_id,
        "llm": llm,
        "verifier_llm": verifier_llm or llm,
        "settings": settings,
        "indirect_model": indirect_model,
        "revenue_resolver": revenue_resolver,
        "company_isic": company_isic,
        "indirect": None,
        "revenue_exposure": None,
        "evidence": [],
        "advocate": None,
        "opposing": None,
        "usages": [],
        "match": None,
    }
    final_state = await _COMPILED_GRAPH.ainvoke(initial)
    return final_state["match"], final_state["usages"]
