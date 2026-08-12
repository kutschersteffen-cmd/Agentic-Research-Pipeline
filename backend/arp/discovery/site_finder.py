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


async def resolve_company_homepage(
    company_name: str, search_client: WebSearchClient, prefer_investor_relations: bool = True
) -> str | None:
    """Resolve a plausible corporate/IR homepage URL for a company by name.

    Only used when the company universe doesn't already supply a website.
    """
    queries = (
        [f"{company_name} investor relations"] if prefer_investor_relations else []
    ) + [f"{company_name} official website"]
    for query in queries:
        results = await search_client.search(query, max_results=5)
        if not results:
            continue
        if prefer_investor_relations:
            ir_hit = next((r for r in results if any(h in r.url.lower() for h in _IR_HINTS)), None)
            if ir_hit:
                return ir_hit.url
        if results:
            return results[0].url
    return None
