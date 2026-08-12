from __future__ import annotations

from arp.discovery.site_finder import WebSearchClient
from arp.schemas.taxonomy_sources import SourceCandidate, SourceCandidateType

# Query templates for each candidate type. Deliberately varied phrasing per
# query rather than one query repeated, since a single search engine call
# returns a narrow slice and different phrasings surface different real
# organizations/funds.
_AUTHORITY_QUERY_TEMPLATES = [
    "{theme} official taxonomy classification",
    "{theme} IEA definition taxonomy",
    "{theme} EU taxonomy sustainable activities",
    "{theme} industry standard classification body",
]
_FUND_QUERY_TEMPLATES = [
    "{theme} ETF",
    "{theme} thematic index fund",
    "{theme} index methodology",
]


async def _run_queries(
    theme_name: str, templates: list[str], source_type: SourceCandidateType, search_client: WebSearchClient, per_query: int
) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    seen_urls: set[str] = set()
    for template in templates:
        query = template.format(theme=theme_name)
        try:
            results = await search_client.search(query, max_results=per_query)
        except Exception:  # noqa: BLE001 - one bad query shouldn't blank the whole discovery step
            continue
        for r in results:
            if r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            candidates.append(SourceCandidate(source_type=source_type, name=r.title, url=r.url, snippet=r.snippet))
    return candidates


async def discover_authority_sources(
    theme_name: str, search_client: WebSearchClient, max_candidates: int = 10
) -> list[SourceCandidate]:
    """Searches for candidate authoritative sources for a theme -- official
    taxonomies, standards-body definitions, government/IGO classifications
    (IEA, EU taxonomy, etc.) -- for the user to review and select from.
    Nothing here is fetched or used automatically; this only proposes.
    """
    candidates = await _run_queries(theme_name, _AUTHORITY_QUERY_TEMPLATES, SourceCandidateType.AUTHORITY, search_client, per_query=4)
    return candidates[:max_candidates]


async def discover_thematic_funds(
    theme_name: str, search_client: WebSearchClient, max_candidates: int = 10
) -> list[SourceCandidate]:
    """Searches for existing thematic ETFs/indices already built around
    this (or an adjacent) theme, for the user to select as a bottom-up
    reference -- see arp/research/taxonomy_sources/etf_holdings.py for what
    happens once a fund is selected and its holdings supplied.
    """
    candidates = await _run_queries(theme_name, _FUND_QUERY_TEMPLATES, SourceCandidateType.THEMATIC_FUND, search_client, per_query=4)
    return candidates[:max_candidates]
