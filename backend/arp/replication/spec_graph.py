from __future__ import annotations

from typing import TypedDict

from arp.config import Settings
from arp.extraction.graph_shape import build_extract_verify_graph
from arp.ingestion.parsing import chunk_document
from arp.llm.base import LLMClient, LLMUsage
from arp.replication.spec_aggregator import build_strategy_spec, no_evidence_spec
from arp.replication.spec_extractor_agent import StrategySpecDraft, extract_strategy_spec_draft
from arp.replication.spec_verifier_agent import SpecVerifierOutput, verify_strategy_spec
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocumentChunk, SourceDocument
from arp.schemas.strategy_replication import StrategySpec

# Fixed methodology/results-section vocabulary used to rank which chunks of
# the paper are worth showing the extractor -- deliberately broad enough to
# cover most quant "outperformance" papers' standard section language
# (formation/holding period, portfolio construction, sample period,
# performance statistics), not tuned to any one paper.
_METHODOLOGY_KEYWORDS = [
    "portfolio",
    "decile",
    "quintile",
    "formation period",
    "holding period",
    "rebalance",
    "sample period",
    "long-short",
    "zero-cost",
    "sharpe ratio",
    "t-statistic",
    "annualized return",
    "alpha",
    "universe",
    "NYSE",
    "book-to-market",
    "book value",
    "market value",
    "earnings-to-price",
    "value premium",
    "characteristic",
]


class SpecExtractionState(TypedDict):
    paper_citation: str
    document: SourceDocument
    llm: LLMClient
    verifier_llm: LLMClient
    settings: Settings | None
    fuzzy_threshold: float
    confidence_review_threshold: float
    evidence: list[DocumentChunk]
    draft: StrategySpecDraft | None
    verifier: SpecVerifierOutput | None
    usages: list[LLMUsage]
    spec: StrategySpec | None
    needs_review: bool


async def _gather_evidence(state: SpecExtractionState) -> dict:
    settings = state["settings"]
    chunks = chunk_document(state["document"], keywords=_METHODOLOGY_KEYWORDS)
    evidence = select_relevant_chunks(
        chunks,
        _METHODOLOGY_KEYWORDS,
        max_chunks=20,
        fallback_to_all=True,
        hybrid_retrieval_enabled=settings is not None and settings.hybrid_retrieval_enabled,
        retrieval_backend=settings.retrieval_backend if settings is not None else "bm25",
    )
    return {"evidence": evidence}


def _route_after_evidence(state: SpecExtractionState) -> str:
    return "extract" if state["evidence"] else "finalize_no_evidence"


async def _finalize_no_evidence(state: SpecExtractionState) -> dict:
    spec, needs_review = no_evidence_spec(state["paper_citation"])
    return {"spec": spec, "needs_review": needs_review}


async def _extract(state: SpecExtractionState) -> dict:
    draft, usage = await extract_strategy_spec_draft(state["paper_citation"], state["evidence"], state["llm"])
    return {"draft": draft, "usages": state["usages"] + [usage]}


async def _verify(state: SpecExtractionState) -> dict:
    verifier, usage = await verify_strategy_spec(
        state["paper_citation"], state["evidence"], state["draft"], state["verifier_llm"]
    )
    return {"verifier": verifier, "usages": state["usages"] + [usage]}


async def _aggregate(state: SpecExtractionState) -> dict:
    documents_by_id = {state["document"].doc_id: state["document"]}
    spec, needs_review = build_strategy_spec(
        state["paper_citation"],
        state["draft"],
        state["verifier"],
        documents_by_id,
        state["fuzzy_threshold"],
        state["confidence_review_threshold"],
    )
    return {"spec": spec, "needs_review": needs_review}


_COMPILED_GRAPH = build_extract_verify_graph(
    SpecExtractionState,
    gather_evidence=_gather_evidence,
    route_after_evidence=_route_after_evidence,
    finalize_no_evidence=_finalize_no_evidence,
    extract=_extract,
    verify=_verify,
    aggregate=_aggregate,
)


async def extract_strategy_spec(
    paper_citation: str,
    paper_text: str,
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings | None = None,
    fuzzy_threshold: float = 0.92,
    confidence_review_threshold: float = 0.6,
) -> tuple[StrategySpec, bool, list[LLMUsage]]:
    """Runs the gather-evidence -> extract -> independent-verify ->
    programmatic-grounding-check -> aggregate flow (arp/extraction/
    graph_shape.py's shared shape) against one paper's raw text, producing
    a StrategySpec the deterministic backtest engine can execute. Returns
    (spec, needs_review, usages).
    """
    from arp.schemas.common import DocType

    document = SourceDocument(
        doc_id="paper_doc",  # fixed, not new_id()-random: exactly one document per call, and a stable id lets
        # callers (and tests) pre-address it in citations before the graph runs.
        company_id="paper",
        doc_type=DocType.RESEARCH_PAPER,
        title=paper_citation,
        full_text=paper_text,
    )
    initial: SpecExtractionState = {
        "paper_citation": paper_citation,
        "document": document,
        "llm": llm,
        "verifier_llm": verifier_llm or llm,
        "settings": settings,
        "fuzzy_threshold": fuzzy_threshold,
        "confidence_review_threshold": confidence_review_threshold,
        "evidence": [],
        "draft": None,
        "verifier": None,
        "usages": [],
        "spec": None,
        "needs_review": False,
    }
    final_state = await _COMPILED_GRAPH.ainvoke(initial)
    return final_state["spec"], final_state["needs_review"], final_state["usages"]
