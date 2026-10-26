from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from arp.discovery.site_check import is_aggregator
from arp.holdings.validate import isin_is_valid
from arp.net_safety import ssrf_guard_request_hook
from arp.schemas.issuer import lei_is_valid, normalise_lei

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
    """No-API-key fallback search, used to resolve a company's IR homepage
    when the user hasn't supplied one directly in the universe file, and to
    find its annual/sustainability report PDFs. Supplying `website`/`ir_url` per company is strongly preferred
    for precision and reliability at scale; this is a best-effort fallback.
    """

    _URL = "https://html.duckduckgo.com/html/"

    def __init__(self, user_agent: str, timeout: float = 15.0, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._headers = {"User-Agent": user_agent}
        self._timeout = timeout
        self._transport = transport

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout, transport=self._transport) as client:
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


def build_web_search_client(user_agent: str, *, transport: httpx.AsyncBaseTransport | None = None) -> WebSearchClient:
    """The app's one web search client: DuckDuckGo, or the test stand-in when ARP_STANDINS_DIR is set."""
    from arp import standins

    if (folder := standins.active_dir()) is not None:
        return standins.StandInSearchClient(folder)
    return DuckDuckGoSearchClient(user_agent, transport=transport)


def _unwrap_ddg_redirect(href: str) -> str | None:
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path == "/l/":
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg")
        return uddg[0] if uddg else None
    return href or None


_IR_HINTS = ("investor", "ir.", "/investors", "shareholder")

_WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"


async def homepage_from_ids(
    user_agent: str,
    *,
    lei: str | None = None,
    isin: str | None = None,
    cik: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str | None:
    """The official website (P856) Wikidata records for an LEI (P1278), ISIN (P946) or SEC CIK
    (P5531), tried in that order, one request each: keyless and exact, no name matching. Returns
    the first identifier's shortest URL. An invalid identifier is skipped without a request, since
    the value goes into the query text."""
    lei = normalise_lei(lei) if lei else ""
    isin = "".join(isin.split()).upper() if isin else ""
    candidates = [
        ("P1278", lei if lei_is_valid(lei) else ""),
        ("P946", isin if isin_is_valid(isin) else ""),
        ("P5531", cik.zfill(10) if cik and cik.isdigit() else ""),
    ]
    # Wikimedia answers 403 to Python's default TLS fingerprint (its cipher list plus ALPN, as
    # httpx always sends); OpenSSL's DEFAULT list, which curl offers, passes.
    tls = httpx.create_ssl_context()
    tls.set_ciphers("DEFAULT")
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=15.0,
        verify=tls,
        event_hooks={"request": [ssrf_guard_request_hook]},
        transport=transport,
    ) as client:
        for prop, value in candidates:
            if not value:
                continue
            query = f'SELECT ?w WHERE {{ ?i wdt:{prop} "{value}"; wdt:P856 ?w }}'
            try:
                resp = await client.get(_WIKIDATA_SPARQL, params={"query": query, "format": "json"})
                resp.raise_for_status()
                urls = [b["w"]["value"] for b in resp.json()["results"]["bindings"]]
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                logger.info("Wikidata homepage lookup failed for %s %s: %s", prop, value, exc)
                continue
            if urls:
                return min(urls, key=len)  # country variants (apple.com/de/) are longer than the root
    return None


async def resolve_company_homepage(company_name: str, search_client: WebSearchClient) -> str | None:
    """Resolve a plausible corporate/IR homepage URL for a company by name.

    Only used when the company universe doesn't already supply a website.
    """
    for query in (f"{company_name} investor relations", f"{company_name} official website"):
        try:
            results = await search_client.search(query, max_results=5)
        except (httpx.HTTPError, RuntimeError) as exc:  # RuntimeError: the test stand-in's search failure
            logger.info("Web search failed for %r: %s", query, exc)
            continue
        results = [r for r in results if not is_aggregator(r.url)]
        if not results:
            continue
        ir_hit = next((r for r in results if any(h in r.url.lower() for h in _IR_HINTS)), None)
        return ir_hit.url if ir_hit else results[0].url
    return None
