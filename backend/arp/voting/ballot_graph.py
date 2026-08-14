from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from arp.grounding import ground_citations
from arp.ingestion.parsing import chunk_document
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import CompanyRef, DocumentChunk, SourceDocument, new_id
from arp.schemas.voting import CompanyBallot, Proposal, VoteRecord
from arp.storage.engagement_store import EngagementStore
from arp.voting.policy_agent import PolicyRule, apply_policy
from arp.voting.proposal_agent import extract_proposals


class BallotState(TypedDict):
    company: CompanyRef
    meeting_date: str | None
    documents: list[SourceDocument]
    documents_by_id: dict[str, SourceDocument]
    llm: LLMClient
    engagement_store: EngagementStore | None
    fuzzy_threshold: float
    rules: list[PolicyRule]
    fund_name: str | None
    max_evidence_chunks: int
    chunks: list[DocumentChunk]
    meeting_id: str
    usages: list[LLMUsage]
    ballot: CompanyBallot | None


async def _gather_evidence(state: BallotState) -> dict:
    chunks: list[DocumentChunk] = []
    for doc in state["documents"]:
        chunks.extend(chunk_document(doc))
    return {"chunks": chunks[: state["max_evidence_chunks"]]}


def _route_after_evidence(state: BallotState) -> str:
    return "extract_and_apply_policy" if state["chunks"] else "finalize_empty"


async def _finalize_empty(state: BallotState) -> dict:
    company = state["company"]
    ballot = CompanyBallot(company_id=company.company_id, name=company.name, meeting_id=state["meeting_id"], meeting_date=state["meeting_date"], votes=[])
    return {"ballot": ballot}


async def _extract_and_apply_policy(state: BallotState) -> dict:
    company, documents, documents_by_id = state["company"], state["documents"], state["documents_by_id"]
    meeting_id, meeting_date = state["meeting_id"], state["meeting_date"]
    llm = state["llm"]
    usages = list(state["usages"])

    draft, usage = await extract_proposals(company.name, meeting_date, state["chunks"], llm)
    usages.append(usage)

    record = state["engagement_store"].get(company.company_id) if state["engagement_store"] else None
    votes: list[VoteRecord] = []
    for p_draft in draft.proposals:
        grounded_citations = ground_citations(p_draft.citations, documents_by_id, state["fuzzy_threshold"])
        proposal = Proposal(
            company_id=company.company_id,
            meeting_id=meeting_id,
            meeting_date=meeting_date,
            proposal_number=p_draft.proposal_number,
            type=p_draft.type,
            sponsor=p_draft.sponsor,
            resolution_text=p_draft.resolution_text,
            management_recommendation=p_draft.management_recommendation,
            supporting_data=p_draft.supporting_data,
            citations=grounded_citations,
            confidence=p_draft.confidence,
            source_doc_id=documents[0].doc_id if documents else None,
        )
        recommendation, policy_usage = await apply_policy(proposal, record, llm, rules=state["rules"], fund_name=state["fund_name"])
        usages.append(policy_usage)
        votes.append(VoteRecord(proposal=proposal, policy_recommendation=recommendation))

    ballot = CompanyBallot(company_id=company.company_id, name=company.name, meeting_id=meeting_id, meeting_date=meeting_date, votes=votes)
    return {"ballot": ballot, "usages": usages}


def _build_graph():
    graph = StateGraph(BallotState)
    graph.add_node("gather_evidence", _gather_evidence)
    graph.add_node("finalize_empty", _finalize_empty)
    graph.add_node("extract_and_apply_policy", _extract_and_apply_policy)

    graph.set_entry_point("gather_evidence")
    graph.add_conditional_edges(
        "gather_evidence",
        _route_after_evidence,
        {"extract_and_apply_policy": "extract_and_apply_policy", "finalize_empty": "finalize_empty"},
    )
    graph.add_edge("finalize_empty", END)
    graph.add_edge("extract_and_apply_policy", END)
    return graph.compile()


_COMPILED_GRAPH = _build_graph()


async def process_company_ballot(
    company: CompanyRef,
    meeting_date: str | None,
    *,
    documents: list[SourceDocument],
    llm: LLMClient,
    engagement_store: EngagementStore | None,
    fuzzy_threshold: float,
    rules: list[PolicyRule],
    fund_name: str | None,
    max_evidence_chunks: int = 20,
) -> tuple[CompanyBallot, list[LLMUsage]]:
    """Runs one company's proxy-voting flow (evidence gather -> Proposal
    Analysis Agent -> Policy Application Agent per extracted proposal,
    including the engagement-alignment cross-check) as a LangGraph graph.
    """
    documents_by_id = {d.doc_id: d for d in documents}
    initial: BallotState = {
        "company": company,
        "meeting_date": meeting_date,
        "documents": documents,
        "documents_by_id": documents_by_id,
        "llm": llm,
        "engagement_store": engagement_store,
        "fuzzy_threshold": fuzzy_threshold,
        "rules": rules,
        "fund_name": fund_name,
        "max_evidence_chunks": max_evidence_chunks,
        "chunks": [],
        "meeting_id": new_id("mtg"),
        "usages": [],
        "ballot": None,
    }
    final_state = await _COMPILED_GRAPH.ainvoke(initial)
    return final_state["ballot"], final_state["usages"]
