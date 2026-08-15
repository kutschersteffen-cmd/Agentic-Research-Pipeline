from __future__ import annotations

from arp.discovery.site_finder import WebSearchClient
from arp.ingestion.edgar import EdgarDocumentSource
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.discovery import (
    IdentityAdjudication,
    IdentityCandidate,
    IdentityChallenge,
    IdentitySignals,
    WebSearchHit,
)

# Implements the same propose/challenge/adjudicate "control and challenge
# agents" pattern as arp/research/matcher_agents.py's Advocate/Opposing/
# Adjudicator, applied to a harder problem: identity resolution has no
# downstream mechanical check the way grounding.py catches a bad citation,
# so the challenge/adjudicate steps are the only defense against a
# confidently wrong company match -- and the adjudicator's own claims are
# further checked against real signals in code (see identity_graph.py)
# rather than trusted outright.

_PROPOSE_SYSTEM = """\
You are a research analyst identifying a public company from its name alone. \
Given only a company name (and, if available, its country/sector), propose: \
a few likely legal-name variants (e.g. with/without "Inc.", "Corp", "Ltd", \
regional suffixes, common abbreviations); a likely stock ticker if you are \
confident of one (otherwise leave it null -- do not guess); and 2-3 short \
web search queries that would help find this company's official corporate \
or investor-relations homepage. Do not invent a website, ticker, or CIK \
you are not confident about -- that will be checked separately against \
real sources, not taken on your word."""

_CHALLENGE_SYSTEM = """\
You are a skeptical analyst stress-testing a proposed company identity \
match before it is used to source financial disclosures. You are given the \
original company name, the candidate identity, and the real signals found \
for it (SEC EDGAR ticker/CIK/title matches and web search results). \
Actively look for: no real EDGAR or web match at all; more than one \
similarly plausible EDGAR match (e.g. a common name, multiple listings, a \
holding company vs. an operating subsidiary); search results that look \
like a look-alike domain, a news aggregator, or an unrelated company \
rather than the company's own corporate/investor-relations site; any \
search result that doesn't actually appear to be about the named company. \
List concrete concerns (empty if you genuinely find none) and your own \
lean on the verdict. Do not soften real ambiguity to seem more useful -- \
an "uncertain" lean here is exactly what routes to human review, which is \
the correct outcome when the evidence doesn't clearly support one match."""

_ADJUDICATE_SYSTEM = """\
You are the adjudicator making the final call on a candidate company \
identity match, given the original name, the candidate, the real signals \
found (EDGAR matches, web search results), and a skeptical analyst's \
challenge. Decide the final verdict: 'resolved' only if a specific EDGAR \
match or web search result clearly and unambiguously identifies the named \
company, with no credible competing match; 'uncertain' if there is a \
plausible match but real ambiguity or an unresolved concern from the \
challenge; 'unresolved' if there is no credible match at all. confidence \
must reflect your actual certainty -- low confidence for anything short of \
a clean, unambiguous match. resolved_website and resolved_cik MUST be \
copied verbatim from a URL or CIK that actually appears in the provided \
signals -- never invent one, even a plausible-looking one; leave either \
null if no signal supports it. Set them only when verdict is 'resolved'."""


def _format_signals(signals: IdentitySignals) -> str:
    lines: list[str] = []
    if signals.edgar_matches:
        lines.append("SEC EDGAR matches:")
        lines.extend(f"  - ticker={m.ticker} cik={m.cik} title={m.title!r}" for m in signals.edgar_matches)
    else:
        lines.append("SEC EDGAR matches: none found")
    if signals.search_results:
        lines.append("Web search results:")
        lines.extend(f"  - title={r.title!r} url={r.url} snippet={r.snippet!r}" for r in signals.search_results)
    else:
        lines.append("Web search results: none found")
    return "\n".join(lines)


async def propose_identity(
    company_name: str,
    llm: LLMClient,
    *,
    country_hint: str | None = None,
    sector_hint: str | None = None,
) -> tuple[IdentityCandidate, LLMUsage]:
    prompt = f"Company name: {company_name}\n"
    if country_hint:
        prompt += f"Country: {country_hint}\n"
    if sector_hint:
        prompt += f"Sector: {sector_hint}\n"
    return await llm.complete_structured(system=_PROPOSE_SYSTEM, prompt=prompt, output_model=IdentityCandidate)


async def resolve_signals(
    company_name: str,
    candidate: IdentityCandidate,
    *,
    edgar: EdgarDocumentSource,
    search_client: WebSearchClient,
    max_search_results: int = 5,
) -> IdentitySignals:
    """Deterministic, non-LLM step: looks up real signals for the
    candidate identity via SEC EDGAR's own company map (arp/ingestion/
    edgar.py::search_by_name) and web search. Never itself summarized or
    filtered by an LLM before the challenge/adjudicate steps see it --
    ambiguity here (e.g. multiple EDGAR matches) is preserved as-is so the
    challenge step can flag it, not resolved silently.
    """
    edgar_matches = list(await edgar.search_by_name(company_name))
    name_guesses = list(candidate.legal_name_guesses)
    if candidate.ticker_guess:
        name_guesses.append(candidate.ticker_guess)
    for guess in name_guesses:
        for m in await edgar.search_by_name(guess):
            if m not in edgar_matches:
                edgar_matches.append(m)

    search_results: list[WebSearchHit] = []
    seen_urls: set[str] = set()
    queries = candidate.search_queries or [f"{company_name} investor relations", f"{company_name} official website"]
    for query in queries:
        for r in await search_client.search(query, max_results=max_search_results):
            if r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            search_results.append(WebSearchHit(title=r.title, url=r.url, snippet=r.snippet))

    return IdentitySignals(edgar_matches=edgar_matches, search_results=search_results)


async def challenge_identity(
    company_name: str, candidate: IdentityCandidate, signals: IdentitySignals, llm: LLMClient
) -> tuple[IdentityChallenge, LLMUsage]:
    prompt = (
        f"Original company name: {company_name}\n\n"
        f"Candidate identity:\n"
        f"  legal name guesses: {candidate.legal_name_guesses}\n"
        f"  ticker guess: {candidate.ticker_guess}\n\n"
        f"{_format_signals(signals)}"
    )
    return await llm.complete_structured(system=_CHALLENGE_SYSTEM, prompt=prompt, output_model=IdentityChallenge)


async def adjudicate_identity(
    company_name: str,
    candidate: IdentityCandidate,
    signals: IdentitySignals,
    challenge: IdentityChallenge,
    llm: LLMClient,
) -> tuple[IdentityAdjudication, LLMUsage]:
    prompt = (
        f"Original company name: {company_name}\n\n"
        f"Candidate identity:\n"
        f"  legal name guesses: {candidate.legal_name_guesses}\n"
        f"  ticker guess: {candidate.ticker_guess}\n\n"
        f"{_format_signals(signals)}\n\n"
        f"Challenge analyst's concerns: {challenge.concerns}\n"
        f"Challenge analyst's lean: {challenge.lean.value}"
    )
    return await llm.complete_structured(system=_ADJUDICATE_SYSTEM, prompt=prompt, output_model=IdentityAdjudication)
