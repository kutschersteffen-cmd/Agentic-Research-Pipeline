from __future__ import annotations

from arp.discovery.site_finder import WebSearchClient
from arp.ingestion.edgar import EdgarDocumentSource
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.discovery import IdentityAdjudication, IdentitySignals, WebSearchHit

# A single LLM call, used only when a direct SEC EDGAR name lookup doesn't
# already give an unambiguous answer (see identity_graph.py's
# _clean_edgar_match short-circuit). Earlier versions of this module split
# identity resolution into three sequential calls (propose a candidate,
# challenge it, adjudicate) mirroring arp/research/matcher_agents.py's
# Advocate/Opposing/Adjudicator triad -- but unlike thematic classification,
# "which company is this" rarely has two genuinely defensible sides to
# debate, and EDGAR's own fuzzy/substring name search (arp/ingestion/
# edgar.py::search_by_name) already resolves the common case without any
# LLM involvement at all. The one call that remains still has no downstream
# mechanical check the way grounding.py catches a bad citation, so its
# resolved_website/resolved_cik claims are still verified against the real
# signals gathered here, in code, before being trusted (see
# identity_graph.py).

_ADJUDICATE_SYSTEM = """\
You are verifying which real company a name refers to, using SEC EDGAR \
matches and web search results actually found for it -- never inventing a \
candidate name, ticker, or URL yourself. Actively look for: no real EDGAR \
or web match at all; more than one similarly plausible EDGAR match (e.g. a \
common name, multiple listings, a holding company vs. an operating \
subsidiary); search results that look like a look-alike domain, a news \
aggregator, or an unrelated company rather than the company's own \
corporate/investor-relations site.

Decide the final verdict: 'resolved' only if a specific EDGAR match or web \
search result clearly and unambiguously identifies the named company, with \
no credible competing match; 'uncertain' if there is a plausible match but \
real ambiguity; 'unresolved' if there is no credible match at all. \
confidence must reflect your actual certainty -- low confidence for \
anything short of a clean, unambiguous match; do not soften real ambiguity \
to seem more useful, since 'uncertain' is exactly what routes to human \
review. resolved_website and resolved_cik MUST be copied verbatim from a \
URL or CIK that actually appears in the provided signals -- never invent \
one, even a plausible-looking one; leave either null if no signal supports \
it. Set them only when verdict is 'resolved'."""


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


async def gather_signals(
    company_name: str,
    *,
    edgar: EdgarDocumentSource,
    search_client: WebSearchClient,
    max_search_results: int = 5,
) -> IdentitySignals:
    """Deterministic, non-LLM step: looks up real signals for the company
    name via SEC EDGAR's own company map (arp/ingestion/edgar.py::
    search_by_name, which already does exact/substring/fuzzy matching on
    its own) and web search. Never itself summarized or filtered before
    the adjudicate step sees it -- ambiguity here (e.g. multiple EDGAR
    matches) is preserved as-is so the LLM (or identity_graph.py's clean-
    match short-circuit) can act on it, not resolved silently.
    """
    edgar_matches = await edgar.search_by_name(company_name)

    search_results: list[WebSearchHit] = []
    seen_urls: set[str] = set()
    queries = [f"{company_name} investor relations", f"{company_name} official website"]
    for query in queries:
        for r in await search_client.search(query, max_results=max_search_results):
            if r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            search_results.append(WebSearchHit(title=r.title, url=r.url, snippet=r.snippet))

    return IdentitySignals(edgar_matches=edgar_matches, search_results=search_results)


async def adjudicate_identity(
    company_name: str, signals: IdentitySignals, llm: LLMClient
) -> tuple[IdentityAdjudication, LLMUsage]:
    prompt = f"Company name: {company_name}\n\n{_format_signals(signals)}"
    return await llm.complete_structured(system=_ADJUDICATE_SYSTEM, prompt=prompt, output_model=IdentityAdjudication)
