from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from arp.discovery.identity_agents import (
    adjudicate_identity,
    challenge_identity,
    propose_identity,
    resolve_signals,
)
from arp.discovery.site_finder import WebSearchClient
from arp.ingestion.edgar import EdgarDocumentSource
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import (
    IdentityAdjudication,
    IdentityCandidate,
    IdentityChallenge,
    IdentityResolutionResult,
    IdentitySignals,
    IdentityVerdict,
)


class IdentityState(TypedDict):
    company: CompanyRef
    llm: LLMClient
    edgar: EdgarDocumentSource
    search_client: WebSearchClient
    max_search_results: int
    confidence_threshold: float
    candidate: IdentityCandidate | None
    signals: IdentitySignals | None
    challenge: IdentityChallenge | None
    adjudication: IdentityAdjudication | None
    usages: list[LLMUsage]
    result: IdentityResolutionResult | None


def _route_after_check(state: IdentityState) -> str:
    company = state["company"]
    return "finalize_known" if (company.website or company.cik) else "propose"


async def _check_known(state: IdentityState) -> dict:
    return {}


async def _finalize_known(state: IdentityState) -> dict:
    """website/cik already supplied in the input CompanyRef -- same
    "already known, don't re-derive" discipline as match_graph.py's
    _route_after_revenue skipping the qualitative debate when a hard
    number is already resolved. Zero LLM calls."""
    company = state["company"]
    result = IdentityResolutionResult(
        company_id=company.company_id,
        input_name=company.name,
        verdict=IdentityVerdict.RESOLVED,
        confidence=1.0,
        resolved_website=company.website,
        resolved_cik=company.cik,
        signals=IdentitySignals(),
        rationale="website/cik already supplied; identity resolution skipped.",
        flagged_for_review=False,
    )
    return {"result": result}


async def _propose(state: IdentityState) -> dict:
    company = state["company"]
    candidate, usage = await propose_identity(
        company.name, state["llm"], country_hint=company.country, sector_hint=company.sector
    )
    return {"candidate": candidate, "usages": state["usages"] + [usage]}


async def _resolve(state: IdentityState) -> dict:
    company = state["company"]
    signals = await resolve_signals(
        company.name,
        state["candidate"],
        edgar=state["edgar"],
        search_client=state["search_client"],
        max_search_results=state["max_search_results"],
    )
    return {"signals": signals}


async def _challenge(state: IdentityState) -> dict:
    company = state["company"]
    challenge, usage = await challenge_identity(company.name, state["candidate"], state["signals"], state["llm"])
    return {"challenge": challenge, "usages": state["usages"] + [usage]}


async def _adjudicate(state: IdentityState) -> dict:
    company = state["company"]
    adjudication, usage = await adjudicate_identity(
        company.name, state["candidate"], state["signals"], state["challenge"], state["llm"]
    )

    # The mechanical, grounding.py-equivalent safety net: never trust the
    # LLM's self-reported resolved_website/resolved_cik -- verify each
    # actually appears in the real signals gathered for this company (not
    # just "looks plausible"), and force the verdict down to UNCERTAIN if
    # not, regardless of what the LLM claimed. This is code, not a prompt
    # instruction, so it holds even if the model doesn't follow the
    # system prompt's "copy verbatim" rule.
    signals = state["signals"]
    known_ciks = {m.cik for m in signals.edgar_matches}
    known_urls = {r.url for r in signals.search_results}
    website, cik = adjudication.resolved_website, adjudication.resolved_cik
    website_ok = website is None or website in known_urls
    cik_ok = cik is None or cik in known_ciks
    if not (website_ok and cik_ok):
        adjudication = adjudication.model_copy(
            update={
                "verdict": IdentityVerdict.UNCERTAIN,
                "resolved_website": website if website_ok else None,
                "resolved_cik": cik if cik_ok else None,
                "rationale": adjudication.rationale
                + " [downgraded: adjudicator's resolved website/cik was not backed by a verified signal]",
            }
        )
    return {"adjudication": adjudication, "usages": state["usages"] + [usage]}


async def _finalize(state: IdentityState) -> dict:
    company = state["company"]
    adjudication = state["adjudication"]
    result = IdentityResolutionResult(
        company_id=company.company_id,
        input_name=company.name,
        verdict=adjudication.verdict,
        confidence=adjudication.confidence,
        resolved_website=adjudication.resolved_website,
        resolved_cik=adjudication.resolved_cik,
        signals=state["signals"],
        rationale=adjudication.rationale,
        flagged_for_review=(
            adjudication.verdict != IdentityVerdict.RESOLVED or adjudication.confidence < state["confidence_threshold"]
        ),
    )
    return {"result": result}


def _build_graph():
    graph = StateGraph(IdentityState)
    graph.add_node("check_known", _check_known)
    graph.add_node("finalize_known", _finalize_known)
    graph.add_node("propose", _propose)
    graph.add_node("resolve", _resolve)
    graph.add_node("challenge", _challenge)
    graph.add_node("adjudicate", _adjudicate)
    graph.add_node("finalize", _finalize)

    graph.set_entry_point("check_known")
    graph.add_conditional_edges(
        "check_known", _route_after_check, {"finalize_known": "finalize_known", "propose": "propose"}
    )
    graph.add_edge("finalize_known", END)
    graph.add_edge("propose", "resolve")
    graph.add_edge("resolve", "challenge")
    graph.add_edge("challenge", "adjudicate")
    graph.add_edge("adjudicate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


# Compiled once and reused across every company invocation.
_COMPILED_GRAPH = _build_graph()


async def resolve_company_identity(
    company: CompanyRef,
    *,
    llm: LLMClient,
    edgar: EdgarDocumentSource,
    search_client: WebSearchClient,
    max_search_results: int = 5,
    confidence_threshold: float = 0.7,
) -> tuple[IdentityResolutionResult, list[LLMUsage]]:
    """Runs the propose -> resolve -> challenge -> adjudicate identity
    resolution graph for one company, or short-circuits to a trivial
    RESOLVED result (zero LLM calls) when website/cik is already known.
    """
    initial: IdentityState = {
        "company": company,
        "llm": llm,
        "edgar": edgar,
        "search_client": search_client,
        "max_search_results": max_search_results,
        "confidence_threshold": confidence_threshold,
        "candidate": None,
        "signals": None,
        "challenge": None,
        "adjudication": None,
        "usages": [],
        "result": None,
    }
    final_state = await _COMPILED_GRAPH.ainvoke(initial)
    return final_state["result"], final_state["usages"]
