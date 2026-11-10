"""Fixture companies C1-C5 of the discovery-review-queue spec, with in-process stand-ins (no network)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import httpx
from reportlab.pdfgen import canvas

from arp.config import Settings
from arp.discovery.pipeline import create_discovery_run, execute_discovery_run
from arp.discovery.site_finder import WebSearchClient
from arp.schemas.common import CompanyRef, DocType
from arp.storage.run_store import RunStore

C1 = CompanyRef(company_id="C1", name="First Co", country="DE")
C2 = CompanyRef(company_id="C2", name="Second Co", country="DE", website="https://c2.example/")
C3 = CompanyRef(company_id="C3", name="Third Co", country="DE", website="https://c3.example/")
C4 = CompanyRef(company_id="C4", name="Fourth Co", country="DE", website="https://c4.example/")
C5 = CompanyRef(company_id="C5", name="Fifth Co", country="US", cik="0000000005")

LONG_TEXT = ("The group's revenue and operating result developed in line with the forecast. " * 4).strip()
URL_A, URL_B = "https://c2.example/report-a.pdf", "https://c2.example/report-b.pdf"
URL_C3 = "https://c3.example/report.pdf"
URL_C4 = "https://c4.example/annual-report-2025.pdf"


def make_pdf_bytes(tmp: Path, name: str, lines: list[str], *, title: str | None = None, pages: int = 3) -> bytes:
    path = tmp / name
    c = canvas.Canvas(str(path))
    if title:
        c.setTitle(title)
    for _ in range(pages):
        for row, line in enumerate(lines):
            c.drawString(72, 760 - 14 * row, line)
        c.showPage()
    c.save()
    return path.read_bytes()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Bodies:
    """B1, B2 (C2: no company name, plenty of text), B3 (C3: almost no text), B4 (C4: names the company)."""

    def __init__(self, tmp: Path) -> None:
        self.b1 = make_pdf_bytes(tmp, "b1.pdf", [LONG_TEXT, "Unrelated Group Alpha"])
        self.b2 = make_pdf_bytes(tmp, "b2.pdf", [LONG_TEXT, "Unrelated Group Beta"])
        self.b3 = make_pdf_bytes(tmp, "b3.pdf", ["Hello"])
        self.b4 = make_pdf_bytes(tmp, "b4.pdf", ["Fourth Co annual report", LONG_TEXT], title="Annual Report 2025")


class NullSearch(WebSearchClient):
    async def search(self, query: str, max_results: int = 5) -> list:
        return []


class Edgar:
    """C5's only source: one 10-K."""

    async def fetch(self, company, doc_types=None):
        return [SimpleNamespace(doc_type=DocType.ANNUAL_REPORT_10K, source_url="https://sec.example/10k", sha256="e" * 64)]


def site(links_by_host: dict[str, dict[str, bytes]], requests: list[str] | None = None):
    """Homepage `/` links to each path of its host; every .pdf path answers with its bytes (recorded in `requests`)."""

    def handler(request: httpx.Request) -> httpx.Response:
        files = links_by_host.get(request.url.host, {})
        if request.url.path == "/":
            anchors = "".join(f'<a href="{u}">Annual Report 2025 {i}</a>' for i, u in enumerate(files))
            return httpx.Response(200, html=f"<html><body>{anchors}</body></html>")
        if requests is not None and request.url.path.endswith(".pdf"):
            requests.append(str(request.url))
        body = files.get(str(request.url))
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, content=body, headers={"content-type": "application/pdf"})

    return httpx.MockTransport(handler)


def settings_for(tmp_path, **kw) -> Settings:
    return Settings(
        documents_dir=tmp_path / "documents", discovery_state_dir=tmp_path / "state", runs_dir=tmp_path / "runs",
        cache_dir=tmp_path / "cache", blob_store_dir=tmp_path / "blobs", discovery_request_delay_seconds=0, **kw,
    )


async def run_discovery_for(tmp_path, pg, companies, transport, *, triggered_by="manual", run_store=None, run_id=None, **kw):
    """One discovery run (create + execute); returns (run_store, run_id, settings)."""
    settings = settings_for(tmp_path, **kw)
    run_store = run_store or RunStore(pg, settings.runs_dir)
    run_id = run_id or create_discovery_run(companies, None, triggered_by, run_store)
    await execute_discovery_run(
        run_id, companies, settings=settings, run_store=run_store, search_client=NullSearch(),
        edgar_source=Edgar(), transport=transport,
    )
    return run_store, run_id, settings
