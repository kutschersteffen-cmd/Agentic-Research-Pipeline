from __future__ import annotations

import logging
from xml.etree import ElementTree

import httpx

from arp.discovery.site_finder import SearchResult, WebSearchClient

logger = logging.getLogger(__name__)

_ATOM_NS = "{http://www.w3.org/2005/Atom}"

# The quantitative-finance categories on arXiv -- portfolio management,
# statistical finance, trading/market microstructure, pricing, risk
# management, general finance. Restricting to these (rather than
# searching all of arXiv) keeps results on-topic for a strategy-
# replication search instead of returning physics papers that happen to
# share vocabulary with a finance query.
_DEFAULT_ARXIV_CATEGORIES = ["q-fin.PM", "q-fin.ST", "q-fin.TR", "q-fin.PR", "q-fin.RM", "q-fin.GN"]


class ArxivSearchClient(WebSearchClient):
    """Free, no-API-key search against arXiv's own public API
    (export.arxiv.org/api), restricted by default to the quantitative-
    finance categories -- a legitimate, documented alternative to
    scraping a general search engine for candidate strategy papers. See
    https://arxiv.org/help/api/user-manual for the API this wraps.

    arXiv skews toward more recent/technical quant work (many "outperformance"
    strategy papers, especially older or more purely empirical-finance
    ones, live on SSRN instead -- see SemanticScholarSearchClient, which
    covers that broader venue set). Use both via CompositeSearchClient for
    real coverage.
    """

    _BASE_URL = "http://export.arxiv.org/api/query"

    def __init__(self, categories: list[str] | None = None, timeout: float = 15.0) -> None:
        self._categories = categories or _DEFAULT_ARXIV_CATEGORIES
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        category_filter = " OR ".join(f"cat:{c}" for c in self._categories)
        search_query = f"({category_filter}) AND all:{query}"
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(self._BASE_URL, params=params)
            resp.raise_for_status()
        return _parse_arxiv_atom(resp.text)


def _parse_arxiv_atom(xml_text: str) -> list[SearchResult]:
    root = ElementTree.fromstring(xml_text)
    results: list[SearchResult] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        title_el = entry.find(f"{_ATOM_NS}title")
        summary_el = entry.find(f"{_ATOM_NS}summary")
        id_el = entry.find(f"{_ATOM_NS}id")
        if id_el is None or not id_el.text:
            continue
        title = " ".join(title_el.text.split()) if title_el is not None and title_el.text else ""
        snippet = " ".join(summary_el.text.split())[:400] if summary_el is not None and summary_el.text else ""
        results.append(SearchResult(title=title, url=id_el.text.strip(), snippet=snippet))
    return results


class SemanticScholarSearchClient(WebSearchClient):
    """Free academic search via the Semantic Scholar Graph API
    (api.semanticscholar.org) -- indexes a much broader range of scholarly
    venues than arXiv (SSRN-hosted, NBER, and journal-published working
    papers among them) via its corpus, which is what makes it the
    practical stand-in for "search SSRN directly": SSRN itself (now an
    Elsevier property) publishes no public search API, and scraping its
    search results would run against its terms of service -- this is the
    legitimate alternative. No API key required for light use; pass one
    to raise the otherwise-low unauthenticated rate limit. See
    https://api.semanticscholar.org/api-docs/graph.
    """

    _BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, api_key: str | None = None, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        params = {"query": query, "limit": max_results, "fields": "title,abstract,url,venue,year"}
        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
            resp = await client.get(self._BASE_URL, params=params)
            resp.raise_for_status()
        return _parse_semantic_scholar_response(resp.json())


def _parse_semantic_scholar_response(data: dict) -> list[SearchResult]:
    results: list[SearchResult] = []
    for paper in data.get("data", []):
        url = paper.get("url")
        if not url:
            continue
        title = paper.get("title") or ""
        venue_year = " ".join(str(v) for v in (paper.get("venue"), paper.get("year")) if v)
        abstract = paper.get("abstract") or ""
        snippet = " -- ".join(p for p in (venue_year, abstract) if p)[:400]
        results.append(SearchResult(title=title, url=url, snippet=snippet))
    return results


class CompositeSearchClient(WebSearchClient):
    """Fans one query out to several WebSearchClients and merges the
    results, deduped by URL, in the order the clients were given. Lets a
    caller (e.g. `arp replicate discover-papers`) combine ArxivSearchClient
    + SemanticScholarSearchClient (and optionally a generic web fallback)
    as one search source, without anything downstream (paper_discovery.py)
    needing to know more than one client was involved -- it only ever
    talks to the WebSearchClient interface.

    A failing client is logged and skipped rather than failing the whole
    search -- matches discover_candidate_papers' own "one bad query
    shouldn't blank the whole discovery step" contract one level up.
    """

    def __init__(self, clients: list[WebSearchClient]) -> None:
        self._clients = clients

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        seen_urls: set[str] = set()
        merged: list[SearchResult] = []
        for client in self._clients:
            try:
                results = await client.search(query, max_results=max_results)
            except Exception:
                logger.warning("CompositeSearchClient: a search client failed, skipping it for this query", exc_info=True)
                continue
            for r in results:
                if r.url in seen_urls:
                    continue
                seen_urls.add(r.url)
                merged.append(r)
        return merged[:max_results]
