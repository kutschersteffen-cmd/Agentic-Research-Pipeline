"""Manifest `review` mark and the download rules that honour it
(spec: discovery-review-queue; AC-17, AC-18, AC-22, AC-23, AC-35)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from reportlab.pdfgen import canvas

from arp.config import Settings
from arp.discovery import crawler, downloader
from arp.discovery.change_detector import ChangeDetector
from arp.discovery.crawler import CandidateDocumentLink
from arp.discovery.downloader import download_documents
from arp.ingestion.indexing_config import IndexingConfig
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.discovery import DiscoveredDocument
from arp.storage.document_blob_store import blob_store_for

C2 = CompanyRef(company_id="C2", name="Second Co", country="DE")
C4 = CompanyRef(company_id="C4", name="Fourth Co", country="DE")
URL_A = "https://c2.example/report-a.pdf"
URL_COPY = "https://c2.example/copy.pdf"


@pytest.fixture(autouse=True)
def _no_ssrf(monkeypatch):
    async def noop(request):
        return None

    for module in (crawler, downloader):
        monkeypatch.setattr(module, "ssrf_guard_request_hook", noop)


def _settings(tmp_path) -> Settings:
    return Settings(documents_dir=tmp_path / "documents", discovery_state_dir=tmp_path / "state",
                    cache_dir=tmp_path / "cache", blob_store_dir=tmp_path / "blobs")


def _pdf_bytes(tmp_path: Path, name: str, text: str, *, title: str | None = None, pages: int = 3) -> bytes:
    path = tmp_path / name
    c = canvas.Canvas(str(path))
    if title:
        c.setTitle(title)
    for _ in range(pages):
        c.drawString(72, 760, text)
        c.showPage()
    c.save()
    return path.read_bytes()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _cand(url: str) -> CandidateDocumentLink:
    return CandidateDocumentLink(url=url, doc_type=DocType.ANNUAL_REPORT_10K, link_text="Annual Report 2025")


async def _download(tmp_path, company, urls, bodies: dict[str, bytes], known=None):
    settings = _settings(tmp_path)
    return await download_documents(
        company, [_cand(u) for u in urls], settings.documents_dir, "test-agent",
        store=blob_store_for(IndexingConfig.from_settings(settings)),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=bodies[str(r.url)], headers={"content-type": "application/pdf"})),
        known=known,
    ), settings


def _known(url: str, sha: str, review: str | None) -> dict[str, DiscoveredDocument]:
    return {url: DiscoveredDocument(company_id="C2", doc_type=DocType.ANNUAL_REPORT_10K, url=url, sha256=sha, review=review)}


async def test_ac35_passing_document_row(tmp_path):
    body = _pdf_bytes(tmp_path, "c4.pdf", "Fourth Co annual report", title="Annual Report 2025")
    url = "https://c4.example/annual-report-2025.pdf"
    docs, _ = await _download(tmp_path, C4, [url], {url: body})
    [d] = docs
    assert (d.company_id, d.doc_type, d.url, d.sha256) == ("C4", DocType.ANNUAL_REPORT_10K, url, _sha(body))
    assert (d.company_match, d.page_count, d.reporting_year, d.alias_of, d.review) == ("name", 3, 2025, None, None)


async def test_review_kept_for_same_url_and_bytes(tmp_path):
    detector = ChangeDetector(tmp_path / "state", tmp_path / "events.jsonl")
    doc = DiscoveredDocument(company_id="C2", doc_type=DocType.ANNUAL_REPORT_10K, url=URL_A, sha256="s1")
    await detector.diff_and_record(C2, [doc])
    assert detector.set_review("C2", URL_A, "approved") is True
    again = DiscoveredDocument(company_id="C2", doc_type=DocType.ANNUAL_REPORT_10K, url=URL_A, sha256="s1")
    await detector.diff_and_record(C2, [again])
    assert again.review == "approved"
    assert detector.known_documents("C2")[URL_A].review == "approved"


async def test_review_cleared_for_new_bytes(tmp_path):
    detector = ChangeDetector(tmp_path / "state", tmp_path / "events.jsonl")
    await detector.diff_and_record(C2, [DiscoveredDocument(company_id="C2", doc_type=DocType.ANNUAL_REPORT_10K, url=URL_A, sha256="s1")])
    detector.set_review("C2", URL_A, "approved")
    changed = DiscoveredDocument(company_id="C2", doc_type=DocType.ANNUAL_REPORT_10K, url=URL_A, sha256="s3")
    await detector.diff_and_record(C2, [changed])
    assert changed.review is None
    assert detector.known_documents("C2")[URL_A].review is None


async def test_set_review_unknown_url_returns_false(tmp_path):
    detector = ChangeDetector(tmp_path / "state", tmp_path / "events.jsonl")
    assert detector.set_review("C2", URL_A, "rejected") is False


@pytest.mark.parametrize("served", ["same", "changed"])
async def test_rejected_url_not_requested(tmp_path, served):
    requests: list[str] = []
    settings = _settings(tmp_path)

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=b"%PDF-1.4 changed", headers={"content-type": "application/pdf"})

    docs = await download_documents(
        C2, [_cand(URL_A)], settings.documents_dir, "test-agent",
        store=blob_store_for(IndexingConfig.from_settings(settings)), transport=httpx.MockTransport(handler),
        known=_known(URL_A, "s1" if served == "same" else "old", "rejected"),
    )
    assert docs == [] and requests == []


async def test_rejected_sha_at_new_url_not_written(tmp_path):
    body = _pdf_bytes(tmp_path, "b1.pdf", "Some other company")
    docs, settings = await _download(tmp_path, C2, [URL_COPY], {URL_COPY: body}, known=_known(URL_A, _sha(body), "rejected"))
    assert docs == []
    assert not list((settings.documents_dir / "C2").rglob("*.pdf"))


async def test_304_for_rejected_bytes_at_a_new_url_is_not_kept(tmp_path):
    from arp.storage.document_blob_store import upload_or_fail

    body = _pdf_bytes(tmp_path, "b1.pdf", "Some other company")
    settings = _settings(tmp_path)
    store = blob_store_for(IndexingConfig.from_settings(settings))
    upload_or_fail(store, _sha(body), body)
    kept = tmp_path / "kept.pdf"
    kept.write_bytes(body)
    known = _known(URL_A, _sha(body), "rejected")
    known[URL_COPY] = DiscoveredDocument(
        company_id="C2", doc_type=DocType.ANNUAL_REPORT_10K, url=URL_COPY, sha256=_sha(body), local_path=str(kept), http_etag='"v1"',
    )
    docs = await download_documents(
        C2, [_cand(URL_COPY)], settings.documents_dir, "test-agent", store=store,
        transport=httpx.MockTransport(lambda r: httpx.Response(304)), known=known,
    )
    assert docs == []
