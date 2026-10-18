"""Unchanged reports are not downloaded again; known bytes at a new URL are an alias
(spec: Not downloading again (conditional GET), Same file, new URL (alias); AC-56..73)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from arp.config import Settings
from arp.discovery import crawler, downloader
from arp.discovery.crawler import CandidateDocumentLink
from arp.discovery.downloader import CAPTURE_LOG, download_documents
from arp.discovery.pipeline import create_discovery_run, execute_discovery_run
from arp.discovery.site_finder import WebSearchClient
from arp.ingestion.indexing_config import IndexingConfig
from arp.schemas.common import CompanyRef, DocType
from arp.storage.document_blob_store import blob_store_for
from arp.storage.jsonl_io import read_jsonl
from arp.storage.run_store import RunStore
from tests.pdf_fixtures import p1, p2

W_SITE = CompanyRef(
    company_id="w", name="Testwerke AG", lei="5299009TESTWERKE0063", isin="DE000TST0006", country="DE",
    website="https://www.testwerke.de/",
)
GB = "https://www.testwerke.de/gb2025.pdf"
GB_V2 = GB + "?v=2"
ETAG = '"v1"'
LAST_MODIFIED = "Wed, 01 Apr 2026 08:00:00 GMT"


@pytest.fixture(autouse=True)
def _no_ssrf(monkeypatch):
    async def noop(request):
        return None

    for module in (crawler, downloader):
        monkeypatch.setattr(module, "ssrf_guard_request_hook", noop)


@pytest.fixture
def pdfs(tmp_path) -> dict[str, bytes]:
    # built once per test: reportlab stamps each build, so a rebuild is different bytes
    return {"P1": p1(tmp_path / "p1.pdf").read_bytes(), "P2": p2(tmp_path / "p2.pdf").read_bytes()}


class _NullSearchClient(WebSearchClient):
    async def search(self, query: str, max_results: int = 5) -> list:
        return []


def _pdf(content: bytes, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(200, content=content, headers={"content-type": "application/pdf", **(headers or {})})


class _Site:
    """The homepage links to `links`; `pdf(request)` answers every .pdf request, which is recorded."""

    def __init__(self, links: list[str], pdf) -> None:
        self.links, self.pdf, self.requests = links, pdf, []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            anchors = "".join(f'<a href="{link}">Annual Report 2025</a>' for link in self.links)
            return httpx.Response(200, html=f"<html><body>{anchors}</body></html>")
        if request.url.path.endswith(".pdf"):
            self.requests.append(request)
            if request.url.path == "/a.pdf":
                await asyncio.sleep(0.05)
            return self.pdf(request)
        return httpx.Response(404)

    def to(self, url: str) -> list[httpx.Request]:
        return [r for r in self.requests if str(r.url) == url]


def _settings(tmp_path) -> Settings:
    return Settings(
        documents_dir=tmp_path / "documents", discovery_state_dir=tmp_path / "state", runs_dir=tmp_path / "runs",
        cache_dir=tmp_path / "cache", blob_store_dir=tmp_path / "blobs", discovery_request_delay_seconds=0,
    )


async def _run(tmp_path, pg, site: _Site) -> dict:
    """One discovery run for W; both runs of a test share the settings dirs and the blob store. Returns the result row."""
    settings = _settings(tmp_path)
    run_store = RunStore(pg, settings.runs_dir)
    run_id = create_discovery_run([W_SITE], None, "manual", run_store)
    await execute_discovery_run(
        run_id, [W_SITE], settings=settings, run_store=run_store, search_client=_NullSearchClient(),
        transport=httpx.MockTransport(site),
    )
    [row] = run_store.read_results(run_id)
    return row


def _events(tmp_path) -> list[dict]:
    path = _settings(tmp_path).documents_dir / "_events.jsonl"
    return list(read_jsonl(path)) if path.exists() else []


def _captures(tmp_path) -> list[dict]:
    return list(read_jsonl(_settings(tmp_path).documents_dir / CAPTURE_LOG))


def _manifest(tmp_path) -> dict[str, dict]:
    return json.loads((_settings(tmp_path).discovery_state_dir / "w.json").read_text())


def _store(tmp_path):
    return blob_store_for(IndexingConfig.from_settings(_settings(tmp_path)))


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def _run1(tmp_path, pg, pdfs, headers: dict[str, str] | None = None) -> dict:
    """Run 1 of the two-run setup: the homepage links only to gb2025.pdf, which returns P1 with ETag and Last-Modified."""
    headers = {"etag": ETAG, "last-modified": LAST_MODIFIED} if headers is None else headers
    return await _run(tmp_path, pg, _Site([GB], lambda r: _pdf(pdfs["P1"], headers)))


def _p1_or_304(pdfs):
    """Run 2: 304 to a conditional request, P1 with 200 to a plain one."""

    def answer(request: httpx.Request) -> httpx.Response:
        if "if-none-match" in request.headers or "if-modified-since" in request.headers:
            return httpx.Response(304, headers={"etag": ETAG})
        return _pdf(pdfs["P1"], {"etag": ETAG, "last-modified": LAST_MODIFIED})

    return answer


# --- 304: reuse the stored copy ---------------------------------------------------------------

async def test_ac_56(tmp_path, pg, pdfs):
    await _run1(tmp_path, pg, pdfs)
    site = _Site([GB], _p1_or_304(pdfs))
    await _run(tmp_path, pg, site)
    [request] = site.to(GB)
    assert request.headers["If-None-Match"] == '"v1"'


async def test_ac_57(tmp_path, pg, pdfs):
    await _run1(tmp_path, pg, pdfs)
    site = _Site([GB], _p1_or_304(pdfs))
    await _run(tmp_path, pg, site)
    [request] = site.to(GB)
    assert request.headers["If-Modified-Since"] == "Wed, 01 Apr 2026 08:00:00 GMT"


async def test_ac_58(tmp_path, pg, pdfs):
    [before] = (await _run1(tmp_path, pg, pdfs))["documents_found"]
    [after] = (await _run(tmp_path, pg, _Site([GB], _p1_or_304(pdfs))))["documents_found"]
    assert (after["sha256"], after["local_path"]) == (before["sha256"], before["local_path"])
    assert (after["company_match"], after["page_count"], after["reporting_year"]) == ("identifier", 30, 2025)


async def test_ac_59(tmp_path, pg, pdfs):
    await _run1(tmp_path, pg, pdfs)
    after_run1 = len(_events(tmp_path))
    await _run(tmp_path, pg, _Site([GB], _p1_or_304(pdfs)))
    assert len(_events(tmp_path)) == after_run1


async def test_ac_60(tmp_path, pg, pdfs):
    await _run1(tmp_path, pg, pdfs)
    after_run1 = len(_captures(tmp_path))
    await _run(tmp_path, pg, _Site([GB], _p1_or_304(pdfs)))
    [record] = [r for r in _captures(tmp_path)[after_run1:] if r["url_chain"][-1] == GB]
    assert (record["status"], record["content_key"], record["collected"]) == (304, _sha(pdfs["P1"]), True)


# --- 304 but the stored copy is gone: plain GET -----------------------------------------------

async def _blob_deleted(tmp_path, pg, pdfs) -> tuple[_Site, dict]:
    await _run1(tmp_path, pg, pdfs)
    sha = _sha(pdfs["P1"])
    (_settings(tmp_path).blob_store_dir / sha[:2] / sha).unlink()
    assert not _store(tmp_path).exists(sha)
    site = _Site([GB], _p1_or_304(pdfs))
    return site, await _run(tmp_path, pg, site)


async def test_ac_61(tmp_path, pg, pdfs):
    site, _ = await _blob_deleted(tmp_path, pg, pdfs)
    requests = site.to(GB)
    assert len(requests) == 2
    assert "if-none-match" not in requests[1].headers and "if-modified-since" not in requests[1].headers


async def test_ac_62(tmp_path, pg, pdfs):
    await _blob_deleted(tmp_path, pg, pdfs)
    assert _store(tmp_path).exists(_sha(pdfs["P1"]))


async def test_ac_68(tmp_path, pg, pdfs):
    _, row = await _blob_deleted(tmp_path, pg, pdfs)
    [doc] = row["documents_found"]
    assert doc["sha256"] == _sha(pdfs["P1"])


async def _local_copy_deleted(tmp_path, pg, pdfs) -> tuple[_Site, dict]:
    [doc] = (await _run1(tmp_path, pg, pdfs))["documents_found"]
    Path(doc["local_path"]).unlink()
    site = _Site([GB], _p1_or_304(pdfs))
    return site, await _run(tmp_path, pg, site)


async def test_ac_69(tmp_path, pg, pdfs):
    site, _ = await _local_copy_deleted(tmp_path, pg, pdfs)
    requests = site.to(GB)
    assert len(requests) == 2
    assert "if-none-match" not in requests[1].headers and "if-modified-since" not in requests[1].headers


async def test_ac_70(tmp_path, pg, pdfs):
    _, row = await _local_copy_deleted(tmp_path, pg, pdfs)
    [doc] = row["documents_found"]
    assert Path(doc["local_path"]).exists()


# --- 200 as on main ---------------------------------------------------------------------------

async def test_ac_63(tmp_path, pg, pdfs):
    await _run1(tmp_path, pg, pdfs)
    after_run1 = len(_events(tmp_path))
    await _run(tmp_path, pg, _Site([GB], lambda r: _pdf(pdfs["P2"])))
    new = _events(tmp_path)[after_run1:]
    assert [(e["event_type"], e["document"]["url"]) for e in new] == [("updated_document", GB)]


async def test_ac_64(tmp_path, pg, pdfs):
    await _run1(tmp_path, pg, pdfs, headers={})
    site = _Site([GB], lambda r: _pdf(pdfs["P1"]))
    await _run(tmp_path, pg, site)
    [request] = site.to(GB)
    assert "if-none-match" not in request.headers and "if-modified-since" not in request.headers


# --- same bytes, new URL ----------------------------------------------------------------------

async def _moved(tmp_path, pg, pdfs, content: bytes) -> dict:
    await _run1(tmp_path, pg, pdfs)
    return await _run(tmp_path, pg, _Site([GB_V2], lambda r: _pdf(content)))


async def test_ac_65(tmp_path, pg, pdfs):
    await _run1(tmp_path, pg, pdfs)
    after_run1 = len(_events(tmp_path))
    await _run(tmp_path, pg, _Site([GB_V2], lambda r: _pdf(pdfs["P1"])))
    assert len(_events(tmp_path)) == after_run1


async def test_ac_66(tmp_path, pg, pdfs):
    await _moved(tmp_path, pg, pdfs, pdfs["P1"])
    assert _manifest(tmp_path)[GB_V2]["alias_of"] == GB


async def test_ac_67(tmp_path, pg, pdfs):
    await _run1(tmp_path, pg, pdfs)
    after_run1 = len(_events(tmp_path))
    await _run(tmp_path, pg, _Site([GB_V2], lambda r: _pdf(pdfs["P2"])))
    new = _events(tmp_path)[after_run1:]
    assert [(e["event_type"], e["document"]["url"]) for e in new] == [("new_document", GB_V2)]


async def test_ac_71(tmp_path, pg, pdfs):
    row = await _moved(tmp_path, pg, pdfs, pdfs["P1"])
    found = [d for d in row["documents_found"] if d["url"] == GB_V2]
    assert len(found) == 1
    assert found[0]["alias_of"] == GB


# --- same bytes at two URLs in one run --------------------------------------------------------

async def test_ac_72(tmp_path, pg, pdfs):
    await _run(tmp_path, pg, _Site(["/a.pdf", "/b.pdf"], lambda r: _pdf(pdfs["P1"])))
    events = _events(tmp_path)
    assert [(e["event_type"], e["document"]["url"]) for e in events] == [("new_document", "https://www.testwerke.de/a.pdf")]


async def test_ac_73(tmp_path, pg, pdfs):
    await _run(tmp_path, pg, _Site(["/a.pdf", "/b.pdf"], lambda r: _pdf(pdfs["P1"])))
    assert _manifest(tmp_path)["https://www.testwerke.de/b.pdf"]["alias_of"] == "https://www.testwerke.de/a.pdf"


# --- 304 with nothing stored ------------------------------------------------------------------

async def test_304_without_known_entry_skipped(tmp_path):
    candidate = CandidateDocumentLink(url=GB, doc_type=DocType.ANNUAL_REPORT_10K, link_text="Annual Report 2025")
    docs = await download_documents(
        W_SITE, [candidate], tmp_path / "documents", "test-agent", store=_store(tmp_path),
        transport=httpx.MockTransport(lambda r: httpx.Response(304)), known={},
    )
    assert docs == []
    assert not (tmp_path / "documents" / CAPTURE_LOG).exists()
