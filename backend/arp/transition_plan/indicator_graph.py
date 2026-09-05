from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from arp.llm.base import LLMClient, LLMUsage
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocumentChunk, SourceDocument
from arp.schemas.transition_plan import IndicatorAssessment, TransitionPlanIndicator
from arp.transition_plan.aggregator import answer_failed_indicator, build_indicator_assessment, no_evidence_indicator
from arp.transition_plan.indicator_agent import IndicatorAnswerDraft, answer_indicator
from arp.transition_plan.verifier_agent import IndicatorVerifierOutput, verify_indicator

_MAX_CHUNKS = 8  # matches the paper's Table S.6 "Top K Retrieval" parameter


class IndicatorState(TypedDict):
    company_name: str
    basic_info_text: str
    indicator: TransitionPlanIndicator
    all_chunks: list[DocumentChunk]
    documents_by_id: dict[str, SourceDocument]
    llm: LLMClient
    fuzzy_threshold: float
    evidence: list[DocumentChunk]
    draft: IndicatorAnswerDraft | None
    verifier: IndicatorVerifierOutput | None
    usages: list[LLMUsage]
    assessment: IndicatorAssessment | None
    error: str | None


async def _gather_evidence(state: IndicatorState) -> dict:
    # require_hit=False + fallback_to_all=True: the paper's tool always
    # retrieves its top-K chunks by embedding similarity regardless of
    # keyword overlap and lets the model answer "NA" when they're
    # irrelevant, rather than skipping retrieval outright for a weak
    # match. BM25 ranking (not embeddings) is this codebase's established,
    # deterministic/embedding-free default -- see select_evidence.py.
    evidence = select_relevant_chunks(
        state["all_chunks"],
        [state["indicator"].question],
        max_chunks=_MAX_CHUNKS,
        require_hit=False,
        fallback_to_all=True,
    )
    return {"evidence": evidence}


def _route_after_evidence(state: IndicatorState) -> str:
    return "answer" if state["evidence"] else "finalize_no_evidence"


async def _finalize_no_evidence(state: IndicatorState) -> dict:
    return {"assessment": no_evidence_indicator(state["indicator"])}


async def _answer(state: IndicatorState) -> dict:
    try:
        draft, usage = await answer_indicator(
            state["company_name"], state["basic_info_text"], state["indicator"], state["evidence"], state["llm"]
        )
    except ValidationError as exc:
        # The LLM client's own self-correction retries (see
        # LangChainAnthropicClient.complete_structured) are exhausted: the
        # model never produced a schema-valid answer for this indicator.
        # Isolated right here rather than left to propagate -- an
        # unrecoverable failure on 1 of 64 indicators must not cost the
        # other 63 (previously it did: uncaught, this bubbled all the way
        # up to run_batch's per-*company* try/except, failing the whole
        # company with nothing recorded for any indicator).
        return {"error": str(exc)}
    return {"draft": draft, "usages": state["usages"] + [usage]}


def _route_after_answer(state: IndicatorState) -> str:
    return "finalize_answer_error" if state.get("error") else "verify"


async def _verify(state: IndicatorState) -> dict:
    try:
        verifier, usage = await verify_indicator(
            state["company_name"], state["indicator"], state["evidence"], state["draft"], state["llm"]
        )
    except ValidationError as exc:
        # Same isolation as _answer: the verifier's own self-correction
        # retries are exhausted, so this indicator gets the same
        # distinctly-flagged failure state rather than taking the other 63
        # indicators down with it.
        return {"error": str(exc)}
    return {"verifier": verifier, "usages": state["usages"] + [usage]}


def _route_after_verify(state: IndicatorState) -> str:
    return "finalize_answer_error" if state.get("error") else "aggregate"


async def _finalize_answer_error(state: IndicatorState) -> dict:
    return {"assessment": answer_failed_indicator(state["indicator"], state["error"])}


async def _aggregate(state: IndicatorState) -> dict:
    assessment = build_indicator_assessment(
        state["indicator"], state["draft"], state["verifier"], state["documents_by_id"], state["fuzzy_threshold"]
    )
    return {"assessment": assessment}


def _build_graph():
    graph = StateGraph(IndicatorState)
    graph.add_node("gather_evidence", _gather_evidence)
    graph.add_node("finalize_no_evidence", _finalize_no_evidence)
    graph.add_node("answer", _answer)
    graph.add_node("verify", _verify)
    graph.add_node("finalize_answer_error", _finalize_answer_error)
    graph.add_node("aggregate", _aggregate)

    graph.set_entry_point("gather_evidence")
    graph.add_conditional_edges(
        "gather_evidence", _route_after_evidence, {"answer": "answer", "finalize_no_evidence": "finalize_no_evidence"}
    )
    graph.add_edge("finalize_no_evidence", END)
    graph.add_conditional_edges(
        "answer", _route_after_answer, {"verify": "verify", "finalize_answer_error": "finalize_answer_error"}
    )
    graph.add_conditional_edges(
        "verify", _route_after_verify, {"aggregate": "aggregate", "finalize_answer_error": "finalize_answer_error"}
    )
    graph.add_edge("finalize_answer_error", END)
    graph.add_edge("aggregate", END)
    return graph.compile()


# Compiled once and reused across every indicator invocation -- this graph
# runs at companies x 64 indicators scale per assessment run.
_COMPILED_GRAPH = _build_graph()


async def assess_one_indicator(
    company_name: str,
    basic_info_text: str,
    indicator: TransitionPlanIndicator,
    *,
    all_chunks: list[DocumentChunk],
    documents_by_id: dict[str, SourceDocument],
    llm: LLMClient,
    fuzzy_threshold: float,
) -> tuple[IndicatorAssessment, list[LLMUsage]]:
    """Runs one indicator's evidence-select -> answer -> independent-verify ->
    programmatic-grounding-check -> aggregate flow as a LangGraph graph,
    mirroring arp/extraction/field_graph.py's shape for a single data-point
    field.
    """
    initial: IndicatorState = {
        "company_name": company_name,
        "basic_info_text": basic_info_text,
        "indicator": indicator,
        "all_chunks": all_chunks,
        "documents_by_id": documents_by_id,
        "llm": llm,
        "fuzzy_threshold": fuzzy_threshold,
        "evidence": [],
        "draft": None,
        "verifier": None,
        "usages": [],
        "assessment": None,
        "error": None,
    }
    final_state = await _COMPILED_GRAPH.ainvoke(initial)
    return final_state["assessment"], final_state["usages"]
