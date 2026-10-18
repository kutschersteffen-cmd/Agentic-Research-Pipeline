from __future__ import annotations

import ssl

import httpx
import pytest

from arp import net_safety
from arp.discovery import site_finder
from arp.discovery.site_finder import SearchResult, WebSearchClient, homepage_from_ids, resolve_company_homepage

UA = "arp-test/1.0"
LEI = "5299009TESTWERKE0063"
ISIN = "DE000TST0006"
H1_URL = "https://www.testwerke.de/"
H1_EN_URL = "https://www.testwerke.de/en/"


@pytest.fixture(autouse=True)
def _no_ssrf(monkeypatch):
    async def noop(request):
        return None

    monkeypatch.setattr(site_finder, "ssrf_guard_request_hook", noop)


def _wikidata(*, by_property: dict[str, list[str]]) -> tuple[httpx.MockTransport, list[str]]:
    """Answers each SPARQL query with the URLs configured for the property it names; records the query texts."""
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        queries.append(query)
        urls = next((u for prop, u in by_property.items() if f"wdt:{prop} " in query), [])
        return httpx.Response(200, json={"results": {"bindings": [{"w": {"value": u}} for u in urls]}})

    return httpx.MockTransport(handler), queries


async def test_ac_10_shortest_p856_wins():
    transport, _ = _wikidata(by_property={"P1278": [H1_EN_URL, H1_URL]})
    assert await homepage_from_ids(UA, lei=LEI, transport=transport) == H1_URL


async def test_ac_11_lei_then_isin():
    transport, queries = _wikidata(by_property={"P946": [H1_URL]})
    assert await homepage_from_ids(UA, lei=LEI, isin=ISIN, transport=transport) == H1_URL
    assert len(queries) == 2
    assert "wdt:P1278" in queries[0]
    assert "wdt:P946" in queries[1]


async def test_ac_12_invalid_ids_no_request():
    transport, queries = _wikidata(by_property={})
    assert await homepage_from_ids(UA, lei="NOT-A-LEI", isin="XX123", cik="12x", transport=transport) is None
    assert queries == []


async def test_ac_42_single_p1278_query():
    transport, queries = _wikidata(by_property={"P1278": [H1_URL]})
    await homepage_from_ids(UA, lei=LEI, transport=transport)
    assert len(queries) == 1
    assert f'wdt:P1278 "{LEI}"' in queries[0]


async def test_cik_is_zero_padded():
    transport, queries = _wikidata(by_property={"P5531": [H1_URL]})
    assert await homepage_from_ids(UA, cik="123", transport=transport) == H1_URL
    assert 'wdt:P5531 "0000000123"' in queries[0]


async def test_http_error_tries_next_identifier():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["query"])
        if len(calls) == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"results": {"bindings": [{"w": {"value": H1_URL}}]}})

    assert await homepage_from_ids(UA, lei=LEI, isin=ISIN, transport=httpx.MockTransport(handler)) == H1_URL
    assert len(calls) == 2


async def test_wikidata_client_offers_openssl_default_ciphers(monkeypatch):
    """Wikimedia answers 403 to Python's default TLS cipher list; the client offers OpenSSL's DEFAULT list, as curl does."""
    seen: dict = {}

    class Recording(httpx.AsyncClient):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(site_finder.httpx, "AsyncClient", Recording)
    transport, _ = _wikidata(by_property={"P1278": [H1_URL]})
    assert await homepage_from_ids(UA, lei=LEI, transport=transport) == H1_URL
    expected = ssl.create_default_context()
    expected.set_ciphers("DEFAULT")
    assert [c["name"] for c in seen["verify"].get_ciphers()] == [c["name"] for c in expected.get_ciphers()]
    assert seen["verify"].verify_mode == ssl.CERT_REQUIRED and seen["verify"].check_hostname


async def test_wikidata_client_runs_real_ssrf_hook(monkeypatch):
    hooked: list[str] = []

    async def recorder(request):
        hooked.append(request.url.host)
        await net_safety.ssrf_guard_request_hook(request)

    monkeypatch.setattr(site_finder, "ssrf_guard_request_hook", recorder)
    # A public address, so the real hook passes without a DNS lookup.
    monkeypatch.setattr(net_safety.socket, "getaddrinfo", lambda host, port: [(None, None, None, "", ("93.184.216.34", 0))])
    transport, queries = _wikidata(by_property={"P946": [H1_URL]})
    assert await homepage_from_ids(UA, lei=LEI, isin=ISIN, transport=transport) == H1_URL
    assert hooked == ["query.wikidata.org"] * len(queries) == ["query.wikidata.org"] * 2


class _FixedSearch(WebSearchClient):
    def __init__(self, urls: list[str]) -> None:
        self._urls = urls

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return [SearchResult(title="t", url=u) for u in self._urls]


async def test_search_skips_aggregator_results():
    search = _FixedSearch(["https://www.marketscreener.com/quote/stock/TESTWERKE-AG-1/", H1_URL])
    assert await resolve_company_homepage("Testwerke AG", search) == H1_URL
