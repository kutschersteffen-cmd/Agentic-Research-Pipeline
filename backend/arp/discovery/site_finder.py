from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""


class WebSearchClient(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise NotImplementedError


class DuckDuckGoSearchClient(WebSearchClient):
    """No-API-key fallback search, used only to resolve a company's IR
    homepage when the user hasn't supplied one directly in the universe
    file. Supplying `website`/`ir_url` per company is strongly preferred
    for precision and reliability at scale; this is a best-effort fallback.
    """

    _URL = "https://html.duckduckgo.com/html/"

    def __init__(self, user_agent: str, timeout: float = 15.0) -> None:
        self._headers = {"User-Agent": user_agent}
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout) as client:
            resp = await client.get(self._URL, params={"q": query})
            resp.raise_for_status()
        if resp.status_code == 202:  # DuckDuckGo's bot challenge page, not results
            logger.warning("DuckDuckGo returned a bot challenge for %r; no search results", query)
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        results: list[SearchResult] = []
        for a in soup.select("a.result__a")[:max_results]:
            href = a.get("href", "")
            url = _unwrap_ddg_redirect(href)
            if not url:
                continue
            results.append(SearchResult(title=a.get_text(strip=True), url=url))
        return results


def _unwrap_ddg_redirect(href: str) -> str | None:
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path == "/l/":
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg")
        return uddg[0] if uddg else None
    return href or None


_IR_HINTS = ("investor", "ir.", "/investors", "shareholder")

_WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"


async def homepage_from_cik(user_agent: str, cik: str | None) -> str | None:
    """The official website (P856) Wikidata records for an SEC CIK (P5531): keyless and
    exact, no name matching. Used before web search, which is often bot-blocked."""
    if not cik or not cik.isdigit():  # digits only: the value goes into the query text
        return None
    query = f'SELECT ?w WHERE {{ ?i wdt:P5531 "{cik.zfill(10)}"; wdt:P856 ?w }}'
    try:
        async with httpx.AsyncClient(headers={"User-Agent": user_agent}, timeout=15.0) as client:
            resp = await client.get(_WIKIDATA_SPARQL, params={"query": query, "format": "json"})
            resp.raise_for_status()
        urls = [b["w"]["value"] for b in resp.json()["results"]["bindings"]]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.info("Wikidata homepage lookup failed for CIK %s: %s", cik, exc)
        return None
    # ponytail: CIK only; add LEI (P1278) / ISIN (P946) when non-US companies need it
    return min(urls, key=len) if urls else None  # country variants (apple.com/de/) are longer than the root


async def resolve_company_homepage(company_name: str, search_client: WebSearchClient) -> str | None:
    """Resolve a plausible corporate/IR homepage URL for a company by name.

    Only used when the company universe doesn't already supply a website.
    """
    for query in (f"{company_name} investor relations", f"{company_name} official website"):
        try:
            results = await search_client.search(query, max_results=5)
        except httpx.HTTPError as exc:
            logger.info("Web search failed for %r: %s", query, exc)
            continue
        if not results:
            continue
        ir_hit = next((r for r in results if any(h in r.url.lower() for h in _IR_HINTS)), None)
        return ir_hit.url if ir_hit else results[0].url
    return None
