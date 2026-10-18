from __future__ import annotations

from typing import TypedDict

import httpx
from langgraph.graph import END, StateGraph

from arp.discovery.gleif import lei_for_isin
from arp.discovery.identity_agents import adjudicate_identity, gather_signals
from arp.discovery.match_rules import (
    MatchRule,
    RuleOutcome,
    apply_identifier_rules,
    apply_name_rules,
    identifiers_of,
)
from arp.discovery.site_check import check_homepage
from arp.discovery.site_finder import WebSearchClient, homepage_from_ids
from arp.holdings.validate import isin_is_valid
from arp.ingestion.edgar import EdgarDocumentSource
from arp.llm.base import LLMClient, LLMUsage
from arp.net_safety import ssrf_guard_request_hook
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import (
    IdentityAdjudication,
    IdentityResolutionResult,
    IdentitySignals,
    IdentityVerdict,
)
from arp.schemas.review import ReasonCode
from arp.storage.identifier_map import IdentifierMapStore


class IdentityState(TypedDict):
    company: CompanyRef
    llm: LLMClient
    edgar: EdgarDocumentSource
    search_client: WebSearchClient
    max_search_results: int
    signals: IdentitySignals | None
    adjudication: IdentityAdjudication | None
    usages: list[LLMUsage]
    identifier_map: IdentifierMapStore | None
    outcome: RuleOutcome | None
    id_outcome: RuleOutcome | None
    result: IdentityResolutionResult | None
    lookup_user_agent: str | None  # None: no GLEIF/Wikidata/site lookups
    transport: httpx.AsyncBaseTransport | None
    derived_lei: str | None
    homepage: tuple[str, str] | None  # (url, site-check verdict) found by identifier, owned or unclear


def _route_after_rules(state: IdentityState) -> str:
    return "finalize_rules" if state["outcome"] else "gather_signals"


def _route_after_name_rules(state: IdentityState) -> str:
    # An identifier-resolved company never reaches the model; it is flagged instead.
    return "finalize_rules" if (state["outcome"] or state["id_outcome"]) else "adjudicate"


def _lookup_client(state: IdentityState) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": state["lookup_user_agent"]},
        timeout=15.0,
        event_hooks={"request": [ssrf_guard_request_hook]},
        transport=state["transport"],
    )


async def _checked_homepage(state: IdentityState, company: CompanyRef, **ids: str | None) -> tuple[str, str] | None:
    """Wikidata homepage by identifier plus site check: (url, verdict) when owned or unclear, else None."""
    ua, transport = state["lookup_user_agent"], state["transport"]
    url = await homepage_from_ids(ua, transport=transport, **ids)
    if url is None:
        return None
    check = await check_homepage(url, company, ua, transport=transport)
    return (url, check.verdict) if check.verdict != "rejected" else None


async def _check_known(state: IdentityState) -> dict:
    company = state["company"]
    isin = (company.isin or "").strip().upper()
    # A supplied LEI, website or CIK already settles the rules; no new lookup for those.
    if state["lookup_user_agent"] is None or company.lei or company.website or company.cik or not isin_is_valid(isin):
        return {}
    async with _lookup_client(state) as client:
        return {"derived_lei": await lei_for_isin(client, isin)}


async def _apply_rules(state: IdentityState) -> dict:
    company = state["company"]
    if state["derived_lei"]:
        company = company.model_copy(update={"lei": state["derived_lei"]})
    outcome = apply_identifier_rules(company, state["identifier_map"])
    # Resolved by identifier but nothing to crawl or look up by: find a CIK by name, then a human confirms.
    lookup = (
        outcome is not None
        and outcome.rule in (MatchRule.EXACT_LEI, MatchRule.IDENTIFIER_MAP)
        and not (company.website or company.cik)
    )
    homepage = None
    if lookup and state["lookup_user_agent"] is not None:
        # A checked Wikidata homepage settles it without the EDGAR name lookup.
        homepage = await _checked_homepage(state, company, lei=company.lei, isin=company.isin)
    return {"id_outcome": outcome, "outcome": None if lookup and not homepage else outcome, "homepage": homepage}


async def _finalize_rules(state: IdentityState) -> dict:
    """Rule outcomes, zero LLM calls. Resolved rules pass; name-only and
    ambiguous outcomes always go to a reviewer."""
    company, outcome, id_outcome = state["company"], state["outcome"], state["id_outcome"]
    if id_outcome is not None and outcome is not id_outcome:
        # Identifier rule plus name lookup: the CIK (or its absence) needs a human.
        name_cik = outcome.candidates[0] if outcome else None
        return {
            "result": IdentityResolutionResult(
                company_id=company.company_id,
                input_name=company.name,
                match_rule=id_outcome.rule.value,
                resolved_issuer_key=id_outcome.issuer_key,
                identifiers=identifiers_of(company),
                verdict=IdentityVerdict.UNCERTAIN,
                confidence=0.5 if name_cik else 0.0,
                resolved_cik=name_cik,
                signals=state["signals"] or IdentitySignals(),
                rationale=(
                    f"Resolved by {id_outcome.rule.value}; CIK {name_cik} from a single exact EDGAR title match, needs review."
                    if name_cik
                    else f"Resolved by {id_outcome.rule.value}; no CIK or website found, needs review."
                ),
                flagged_for_review=True,
                reason_codes=[ReasonCode.MATCH_AMBIGUOUS],
            )
        }
    base = {
        "company_id": company.company_id,
        "input_name": company.name,
        "match_rule": outcome.rule.value,
        "resolved_issuer_key": outcome.issuer_key,
        "identifiers": identifiers_of(company),
    }
    if state["homepage"] is not None:
        url, verdict = state["homepage"]
        owned = verdict == "owned"
        return {
            "result": IdentityResolutionResult(
                **base,
                verdict=IdentityVerdict.RESOLVED if owned else IdentityVerdict.UNCERTAIN,
                confidence=1.0 if owned else 0.5,
                resolved_website=url,
                signals=IdentitySignals(),
                rationale=f"Resolved by {outcome.rule.value}; Wikidata homepage {url}, site check {verdict}.",
                flagged_for_review=not owned,
                reason_codes=[] if owned else [ReasonCode.MATCH_AMBIGUOUS],
            )
        }
    if outcome.resolved:
        result = IdentityResolutionResult(
            **base,
            verdict=IdentityVerdict.RESOLVED,
            confidence=1.0,
            resolved_website=company.website,
            resolved_cik=company.cik,
            signals=IdentitySignals(),
            rationale=f"Resolved by rule {outcome.rule.value}; no LLM call needed.",
            flagged_for_review=False,
        )
    else:
        name_only = outcome.rule == MatchRule.NAME_ONLY
        result = IdentityResolutionResult(
            **base,
            verdict=IdentityVerdict.UNCERTAIN,
            confidence=0.5 if name_only else 0.0,
            resolved_website=company.website,
            resolved_cik=outcome.candidates[0] if name_only else company.cik,
            signals=state["signals"] or IdentitySignals(),
            rationale=(
                f"Single exact SEC EDGAR title match (CIK {outcome.candidates[0]}); name-only, needs review."
                if name_only
                else f"Identifier maps to several issuers: {', '.join(outcome.candidates)}."
            ),
            flagged_for_review=True,
            reason_codes=[ReasonCode.MATCH_AMBIGUOUS],
        )
    return {"result": result}


async def _gather_signals(state: IdentityState) -> dict:
    company = state["company"]
    kwargs = dict(edgar=state["edgar"], search_client=state["search_client"], max_search_results=state["max_search_results"])
    if state["lookup_user_agent"] is None:
        return {"signals": await gather_signals(company.name, **kwargs)}
    async with _lookup_client(state) as client:
        return {"signals": await gather_signals(company.name, **kwargs, gleif_client=client)}


async def _apply_name_rules(state: IdentityState) -> dict:
    return {"outcome": apply_name_rules(state["company"], state["signals"])}


async def _adjudicate(state: IdentityState) -> dict:
    company = state["company"]
    adjudication, usage = await adjudicate_identity(company.name, state["signals"], state["llm"])

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
    known_leis = {m.lei for m in signals.gleif_matches}
    website, cik, lei = adjudication.resolved_website, adjudication.resolved_cik, adjudication.resolved_lei
    website_ok = website is None or website in known_urls
    cik_ok = cik is None or cik in known_ciks
    lei_ok = lei is None or lei in known_leis
    if not (website_ok and cik_ok and lei_ok):
        adjudication = adjudication.model_copy(
            update={
                "verdict": IdentityVerdict.UNCERTAIN,
                "resolved_website": website if website_ok else None,
                "resolved_cik": cik if cik_ok else None,
                "resolved_lei": lei if lei_ok else None,
                "rationale": adjudication.rationale
                + " [downgraded: adjudicator's resolved website/cik/lei was not backed by a verified signal]",
            }
        )
    return {"adjudication": adjudication, "usages": state["usages"] + [usage]}


async def _finalize(state: IdentityState) -> dict:
    company = state["company"]
    adjudication = state["adjudication"]
    website = adjudication.resolved_website
    if adjudication.resolved_lei and not website and state["lookup_user_agent"] is not None:
        # Fills in the website for the reviewer only; the verdict and flag stay the adjudicator's.
        homepage = await _checked_homepage(state, company, lei=adjudication.resolved_lei)
        website = homepage[0] if homepage else None
    result = IdentityResolutionResult(
        company_id=company.company_id,
        input_name=company.name,
        verdict=adjudication.verdict,
        confidence=adjudication.confidence,
        resolved_website=website,
        resolved_cik=adjudication.resolved_cik,
        resolved_lei=adjudication.resolved_lei,
        signals=state["signals"],
        rationale=adjudication.rationale,
        # The model's answer is a suggestion for the reviewer, never a decision.
        flagged_for_review=True,
        match_rule=MatchRule.AMBIGUOUS.value,
        identifiers=identifiers_of(company),
        reason_codes=[ReasonCode.MATCH_AMBIGUOUS],
    )
    return {"result": result}


def _build_graph():
    graph = StateGraph(IdentityState)
    graph.add_node("check_known", _check_known)
    graph.add_node("apply_rules", _apply_rules)
    graph.add_node("finalize_rules", _finalize_rules)
    graph.add_node("gather_signals", _gather_signals)
    graph.add_node("apply_name_rules", _apply_name_rules)
    graph.add_node("adjudicate", _adjudicate)
    graph.add_node("finalize", _finalize)

    graph.set_entry_point("check_known")
    graph.add_edge("check_known", "apply_rules")
    graph.add_conditional_edges(
        "apply_rules", _route_after_rules, {"finalize_rules": "finalize_rules", "gather_signals": "gather_signals"}
    )
    graph.add_edge("gather_signals", "apply_name_rules")
    graph.add_conditional_edges(
        "apply_name_rules", _route_after_name_rules, {"finalize_rules": "finalize_rules", "adjudicate": "adjudicate"}
    )
    graph.add_edge("finalize_rules", END)
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
    confidence_threshold: float = 0.7,  # unused: adjudicated results are always flagged; kept for existing callers
    identifier_map: IdentifierMapStore | None = None,
    lookup_user_agent: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[IdentityResolutionResult, list[LLMUsage]]:
    """Runs identity resolution for one company: zero LLM calls for
    identifier rules and exact EDGAR name matches (the latter always
    flagged for review), exactly one LLM call (adjudicate, always flagged)
    otherwise. With `lookup_user_agent` set, also looks up a missing LEI from the
    ISIN and the website by identifier (Wikidata + site check), and adds GLEIF
    name matches to the adjudicate signals; with None, none of these run.
    """
    initial: IdentityState = {
        "company": company,
        "llm": llm,
        "edgar": edgar,
        "search_client": search_client,
        "max_search_results": max_search_results,
        "signals": None,
        "adjudication": None,
        "usages": [],
        "identifier_map": identifier_map,
        "outcome": None,
        "id_outcome": None,
        "result": None,
        "lookup_user_agent": lookup_user_agent,
        "transport": transport,
        "derived_lei": None,
        "homepage": None,
    }
    final_state = await _COMPILED_GRAPH.ainvoke(initial)
    result = final_state["result"].model_copy(update={"derived_lei": final_state["derived_lei"]})
    return result, final_state["usages"]
