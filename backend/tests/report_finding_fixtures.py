"""Shared harness for the report-finding tests: one company, a scripted network, and a discovery run over it."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx

from arp.config import Settings
from arp.discovery.pipeline import create_discovery_run, execute_discovery_run
from arp.discovery.site_finder import SearchResult, WebSearchClient
from arp.schemas.common import CompanyRef
from arp.storage.run_store import RunStore
from tests.pdf_fixtures import make_image_pdf, make_pdf
from tests.postgres_helpers import pg_dsn

W = CompanyRef(company_id="w", name="Testwerke AG", lei="5299009TESTWERKE0063", website="https://www.testwerke.de/")
SITE = "https://www.testwerke.de"
TODAY = date(2026, 10, 19)
ANNUAL_Q = '"Testwerke AG" annual report 2025 filetype:pdf'
SUST_Q = '"Testwerke AG" sustainability report 2025 filetype:pdf'
INDEX_URL = "https://filings.xbrl.org/api/entities/5299009TESTWERKE0063/filings"
_PACKAGE = (Path(__file__).parent / "fixtures" / "esef" / "beispiel-2024.zip").read_bytes()


def page(*links: tuple[str, str]) -> httpx.Response:
    """An HTML page whose anchors are `(href, text)`."""
    body = "".join(f'<a href="{href}">{text}</a>' for href, text in links)
    return httpx.Response(200, html=f"<html><body>{body}</body></html>")


def pdf_response(tmp_path: Path, first_page: str = "Testwerke AG Annual Report 2025") -> httpx.Response:
    path = make_pdf(tmp_path / "fixture.pdf", [first_page], n_pages=3)
    return httpx.Response(200, content=path.read_bytes(), headers={"content-type": "application/pdf"})


def image_pdf_response(tmp_path: Path) -> httpx.Response:
    path = make_image_pdf(tmp_path / "fixture-image.pdf", n_pages=3)
    return httpx.Response(200, content=path.read_bytes(), headers={"content-type": "application/pdf"})


class FakeSearch(WebSearchClient):
    def __init__(self, log: list[str], results: dict[str, list[str | tuple[str, str]]] | None = None, error: Exception | None = None):
        self.log, self.results, self.error, self.calls = log, results or {}, error, []

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        self.log.append(f"query {query}")
        self.calls.append((query, max_results))
        if self.error:
            raise self.error
        hits = [(h, h) if isinstance(h, str) else (h[0], h[1]) for h in self.results.get(query, [])]
        return [SearchResult(title=title or url, url=url) for url, title in hits]


class FakeEdgar:
    def __init__(self, docs: list | None = None):
        self.docs, self.asked = docs or [], []

    async def fetch(self, company, doc_types=None):
        self.asked.append(company.company_id)
        return self.docs


@dataclass
class Run:
    row: dict
    manifest: object
    log: list[str]
    search: FakeSearch | None
    edgar: FakeEdgar

    def count(self, url: str) -> int:
        return self.log.count(f"request {url}")

    def host_count(self, host: str) -> int:
        return sum(1 for e in self.log if e.startswith("request ") and urlparse(e[8:]).hostname == host)

    def docs(self, doc_type: str | None = None) -> list[str]:
        return [d["url"] for d in self.row["documents_found"] if doc_type is None or d["doc_type"] == doc_type]

    def doc(self, url: str) -> dict:
        found = next((d for d in self.row["documents_found"] if d["url"] == url), None)
        assert found is not None, f"{url} not in documents_found: {self.docs()}"
        return found

    @property
    def queries(self) -> list[str]:
        return [e[6:] for e in self.log if e.startswith("query ")]


def _esef_response(esef: str | tuple[str, str]) -> httpx.Response:
    if esef == "error":
        return httpx.Response(500)
    filings = {
        "current": [("2025-12-31", "https://filings.xbrl.org/w/2025.zip")],
        "old": [("2024-12-31", "https://filings.xbrl.org/w/2024.zip")],
        "none": [],
    }.get(esef) if isinstance(esef, str) else [esef]
    return httpx.Response(200, json={"data": [{"attributes": {"period_end": p, "package_url": u}} for p, u in filings]})


_real_getaddrinfo = socket.getaddrinfo


def _resolver(host, *args, **kwargs):
    if host in ("localhost", "127.0.0.1"):  # the test database; no fixture URL uses these
        return _real_getaddrinfo(host, *args, **kwargs)
    ip = {"metadata.example.net": "169.254.169.254", "internal.testwerke.de": "10.0.0.5"}.get(host, "93.184.216.34")
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


async def discover(
    tmp_path, pg, monkeypatch, *, company: CompanyRef = W, esef: str | tuple[str, str] = "none", routes: dict | None = None,
    fallback=None, search: dict | Exception | None = None, default_search: bool = False, wikidata: str | None = None,
    edgar: FakeEdgar | None = None, **settings,
) -> Run:
    monkeypatch.setattr("arp.net_safety.socket.getaddrinfo", _resolver)
    log: list[str] = []
    routes = routes or {}

    def answer(request: httpx.Request) -> httpx.Response:
        log.append(f"request {request.url}")
        url, host, path = str(request.url), request.url.host, request.url.path
        if url in routes:
            route = routes[url]
            return route(request) if callable(route) else route
        if fallback and (response := fallback(request)) is not None:
            return response
        if url == INDEX_URL:
            return _esef_response(esef)
        if url.startswith("https://filings.xbrl.org/") and path.endswith(".zip"):
            return httpx.Response(200, content=_PACKAGE)
        if host == "query.wikidata.org":
            bindings = [{"w": {"value": wikidata}}] if wikidata else []
            return httpx.Response(200, json={"results": {"bindings": bindings}})
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if url == SITE + "/":
            return page()
        if path.lower().endswith(".pdf"):
            return pdf_response(tmp_path)
        if host == "html.duckduckgo.com":
            return httpx.Response(202)
        return httpx.Response(404)

    async def sleep(seconds):
        log.append(f"sleep {seconds}")

    config = Settings(
        anthropic_api_key="unused", documents_dir=tmp_path / "docs", discovery_state_dir=tmp_path / "disc",
        runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache", blob_store_dir=tmp_path / "blobs",
        **{"discovery_request_delay_seconds": 0.2, "esef_enabled": True, **settings},
    )
    fake_search = None if default_search else FakeSearch(log, None if isinstance(search, Exception) else search, search if isinstance(search, Exception) else None)
    fake_edgar = edgar or FakeEdgar()
    store = RunStore(pg_dsn(), config.runs_dir)
    run_id = create_discovery_run([company], None, "test", store)
    await execute_discovery_run(
        run_id, [company], settings=config, run_store=store, search_client=fake_search, edgar_source=fake_edgar,
        transport=httpx.MockTransport(answer), today=TODAY, sleep=sleep,
    )
    [row] = store.read_results(run_id)
    return Run(row=row, manifest=store.load_manifest(run_id), log=log, search=fake_search, edgar=fake_edgar)
