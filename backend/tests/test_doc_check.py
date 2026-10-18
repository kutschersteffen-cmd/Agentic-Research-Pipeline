"""Document check on downloaded PDFs (spec: Document check; AC-27..32, AC-39..41)."""

from __future__ import annotations

from pathlib import Path

import httpx

from arp.config import Settings
from arp.discovery import crawler, downloader
from arp.discovery.doc_check import DocCheck, check_document
from arp.discovery.pipeline import create_discovery_run, execute_discovery_run
from arp.discovery.site_finder import WebSearchClient
from arp.schemas.common import CompanyRef
from arp.storage.run_store import RunStore
from tests.pdf_fixtures import p1, p2, p3, p4

W = CompanyRef(company_id="w", name="Testwerke AG", lei="5299009TESTWERKE0063", isin="DE000TST0006", country="DE")
W_SITE = W.model_copy(update={"website": "https://www.testwerke.de/"})
SITE = "https://www.testwerke.de"


# --- check_document ---------------------------------------------------------------------------

def test_check_identifier(tmp_path):
    assert check_document(p1(tmp_path / "p1.pdf"), W) == DocCheck("identifier", 30, 2025)


def test_check_name(tmp_path):
    assert check_document(p2(tmp_path / "p2.pdf"), W) == DocCheck("name", 30, 2025)


def test_check_none(tmp_path):
    assert check_document(p3(tmp_path / "p3.pdf"), W) == DocCheck("none", 30, 2025)


def test_check_no_text(tmp_path):
    assert check_document(p4(tmp_path / "p4.pdf"), W) == DocCheck("no_text", 30, None)


def test_check_corrupt_pdf_is_no_text(tmp_path):
    whole = p1(tmp_path / "p1.pdf").read_bytes()
    truncated = tmp_path / "truncated.pdf"
    truncated.write_bytes(whole[: len(whole) // 2])
    assert check_document(truncated, W) == DocCheck("no_text", None, None)


def test_check_non_string_title_still_checks(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, NumberObject

    writer = PdfWriter(clone_from=p2(tmp_path / "p2.pdf"))
    writer.add_metadata({"/Title": "x"})
    writer._info.get_object()[NameObject("/Title")] = NumberObject(2025)
    odd = tmp_path / "odd_title.pdf"
    writer.write(odd)
    assert check_document(odd, W) == DocCheck("name", 30, 2025)

# --- discovery run ----------------------------------------------------------------------------

class _NullSearchClient(WebSearchClient):
    async def search(self, query: str, max_results: int = 5) -> list:
        return []


def _pdf(builder, tmp_path) -> httpx.Response:
    return httpx.Response(200, content=builder(tmp_path / "fixture.pdf").read_bytes(), headers={"content-type": "application/pdf"})


async def _discover(tmp_path, monkeypatch, pg, served: dict[str, httpx.Response]):
    """Discovery run for W with supplied website; the homepage links only to the paths in `served`.
    Returns (documents_found as dicts, run manifest)."""
    links = "".join(
        f'<a href="{path}">{"Annual Report 2025" if path.endswith(".html") else "Geschäftsbericht 2025"}</a>' for path in served
    )
    homepage = httpx.Response(200, html=f"<html><body>{links}</body></html>")

    def handler(request: httpx.Request) -> httpx.Response:
        return homepage if request.url.path == "/" else served.get(request.url.path) or httpx.Response(404)

    async def _no_ssrf(request):
        return None

    monkeypatch.setattr(crawler, "ssrf_guard_request_hook", _no_ssrf)
    monkeypatch.setattr(downloader, "ssrf_guard_request_hook", _no_ssrf)
    settings = Settings(
        documents_dir=tmp_path / "documents", discovery_state_dir=tmp_path / "state",
        runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache", discovery_request_delay_seconds=0,
    )
    run_store = RunStore(pg, settings.runs_dir)
    run_id = create_discovery_run([W_SITE], None, "manual", run_store)
    await execute_discovery_run(
        run_id, [W_SITE], settings=settings, run_store=run_store, search_client=_NullSearchClient(),
        transport=httpx.MockTransport(handler),
    )
    rows = run_store.read_results(run_id)
    assert len(rows) == 1
    return rows[0]["documents_found"], run_store.load_manifest(run_id)


async def test_ac_27(tmp_path, monkeypatch, pg):
    docs, _ = await _discover(tmp_path, monkeypatch, pg, {"/p1.pdf": _pdf(p1, tmp_path)})
    assert len(docs) == 1
    assert (docs[0]["company_match"], docs[0]["page_count"], docs[0]["reporting_year"]) == ("identifier", 30, 2025)


async def test_ac_28(tmp_path, monkeypatch, pg):
    docs, _ = await _discover(tmp_path, monkeypatch, pg, {"/p2.pdf": _pdf(p2, tmp_path)})
    assert len(docs) == 1
    assert docs[0]["company_match"] == "name"


async def test_ac_29(tmp_path, monkeypatch, pg):
    docs, _ = await _discover(tmp_path, monkeypatch, pg, {"/p3.pdf": _pdf(p3, tmp_path)})
    assert len(docs) == 1
    assert docs[0]["company_match"] == "none"


async def test_ac_30(tmp_path, monkeypatch, pg):
    docs, _ = await _discover(tmp_path, monkeypatch, pg, {"/p3.pdf": _pdf(p3, tmp_path)})
    assert [d["url"] for d in docs] == [SITE + "/p3.pdf"]
    assert docs[0]["local_path"] and Path(docs[0]["local_path"]).is_file()


async def test_ac_31(tmp_path, monkeypatch, pg):
    docs, _ = await _discover(tmp_path, monkeypatch, pg, {"/p4.pdf": _pdf(p4, tmp_path)})
    assert len(docs) == 1
    assert docs[0]["company_match"] == "no_text"


async def test_ac_32(tmp_path, monkeypatch, pg):
    html = httpx.Response(200, text="<html><body><h1>Annual Report 2025</h1></body></html>", headers={"content-type": "text/html"})
    docs, _ = await _discover(tmp_path, monkeypatch, pg, {"/p1.pdf": _pdf(p1, tmp_path), "/annual-report-2025.html": html})
    assert len(docs) == 2
    [html_doc] = [d for d in docs if d["url"] == SITE + "/annual-report-2025.html"]
    assert (html_doc["company_match"], html_doc["page_count"], html_doc["reporting_year"]) == (None, None, None)


async def test_ac_39(tmp_path, monkeypatch, pg):
    _, manifest = await _discover(tmp_path, monkeypatch, pg, {"/p3.pdf": _pdf(p3, tmp_path)})
    assert manifest.review_count == 1


async def test_ac_40(tmp_path, monkeypatch, pg):
    _, manifest = await _discover(tmp_path, monkeypatch, pg, {"/p4.pdf": _pdf(p4, tmp_path)})
    assert manifest.review_count == 1


async def test_ac_41(tmp_path, monkeypatch, pg):
    _, manifest = await _discover(tmp_path, monkeypatch, pg, {"/p1.pdf": _pdf(p1, tmp_path)})
    assert manifest.review_count == 0
