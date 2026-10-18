"""Derived homepages are checked before the crawl; supplied ones are not (spec: Discovery pipeline; AC-23..26, AC-46)."""

from __future__ import annotations

import httpx
import pytest

from arp.config import Settings
from arp.discovery import crawler, downloader, site_check, site_finder
from arp.discovery.pipeline import create_discovery_run, execute_discovery_run
from arp.discovery.site_finder import SearchResult, WebSearchClient
from arp.schemas.common import CompanyRef
from arp.storage.run_store import RunStore

W = CompanyRef(company_id="w", name="Testwerke AG", lei="5299009TESTWERKE0063", isin="DE000TST0006", country="DE")
NAME_ONLY = CompanyRef(company_id="w", name="Testwerke AG")

H1_URL = "https://www.testwerke.de/"
H1 = '<html><head><title>Testwerke – Startseite</title></head><body><a href="/impressum">Impressum</a></body></html>'
IMPRINT = "<html><body><p>Testwerke AG, Musterstrasse 1, Teststadt</p><p>LEI: 5299009TESTWERKE0063</p></body></html>"
H2_URL = "https://www.marketscreener.com/quote/stock/TESTWERKE-AG-1/"
H3_URL = "https://www.otherco.co.uk/"
H3 = "<html><head><title>Otherco plc | Home</title></head><body><p>Welcome</p></body></html>"
H4_URL = "https://www.testwerke.de/"
H4 = "<html><head><title>Testwerke AG</title></head><body><p>Welcome</p></body></html>"


@pytest.fixture(autouse=True)
def _no_ssrf(monkeypatch):
    async def noop(request):
        return None

    for module in (crawler, downloader, site_check, site_finder):
        monkeypatch.setattr(module, "ssrf_guard_request_hook", noop)


class _Search(WebSearchClient):
    def __init__(self, urls: list[str]) -> None:
        self._results = [SearchResult(title=url, url=url) for url in urls]

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return self._results


class _NoEdgar:
    async def fetch(self, company, doc_types=None):
        return []


async def _discover(tmp_path, pg, company, pages: dict[str, str], *, search=(), wikidata_p1278: str | None = None):
    """One discovery run for `company`; `pages` are HTML by URL (anything else 404s, robots.txt included).
    Returns (the company's result row, every requested httpx.URL)."""
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.host == "query.wikidata.org":
            hit = wikidata_p1278 and "wdt:P1278" in request.url.params["query"]
            bindings = [{"w": {"value": wikidata_p1278}}] if hit else []
            return httpx.Response(200, json={"results": {"bindings": bindings}})
        page = pages.get(str(request.url))
        return httpx.Response(200, html=page) if page else httpx.Response(404)

    settings = Settings(
        documents_dir=tmp_path / "documents", discovery_state_dir=tmp_path / "state",
        runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache", discovery_request_delay_seconds=0,
    )
    run_store = RunStore(pg, settings.runs_dir)
    run_id = create_discovery_run([company], None, "manual", run_store)
    await execute_discovery_run(
        run_id, [company], settings=settings, run_store=run_store, search_client=_Search(list(search)),
        edgar_source=_NoEdgar(), transport=httpx.MockTransport(handler),
    )
    [row] = run_store.read_results(run_id)
    return row, seen


def _paths(seen: list[httpx.URL], host: str) -> list[str]:
    return [url.path for url in seen if url.host == host]


async def test_ac_23_search_skips_aggregator(tmp_path, pg):
    row, _ = await _discover(
        tmp_path, pg, NAME_ONLY, {H1_URL: H1, H1_URL + "impressum": IMPRINT}, search=[H2_URL, H1_URL],
    )
    assert row["homepage_used"] == "https://www.testwerke.de/"


async def test_ac_24_rejected_not_crawled(tmp_path, pg):
    row, seen = await _discover(tmp_path, pg, NAME_ONLY, {H3_URL: H3}, search=[H3_URL])
    assert row["homepage_used"] is None
    assert row["homepage_check"]["verdict"] == "rejected"
    assert _paths(seen, "www.otherco.co.uk") == ["/"]


async def test_ac_25_supplied_not_checked(tmp_path, pg):
    company = W.model_copy(update={"website": H3_URL})
    row, seen = await _discover(tmp_path, pg, company, {H3_URL: H3})
    assert row["homepage_used"] == "https://www.otherco.co.uk/"
    assert row["homepage_check"] is None
    assert _paths(seen, "www.otherco.co.uk").count("/") == 1


async def test_ac_26_unclear_crawled(tmp_path, pg):
    row, seen = await _discover(tmp_path, pg, W, {H4_URL: H4}, wikidata_p1278=H4_URL)
    assert row["homepage_used"] == "https://www.testwerke.de/"
    assert row["homepage_check"]["verdict"] == "unclear"
    # one fetch of H4 by the check, one by the crawl (which alone asks for robots.txt first)
    assert _paths(seen, "www.testwerke.de") == ["/", "/robots.txt", "/"]


async def test_ac_46_supplied_cik_homepage_checked(tmp_path, pg):
    company = W.model_copy(update={"cik": "123"})
    row, _ = await _discover(tmp_path, pg, company, {H4_URL: H4}, wikidata_p1278=H4_URL)
    assert row["homepage_used"] == "https://www.testwerke.de/"
    assert row["homepage_check"]["verdict"] == "unclear"
