from __future__ import annotations

import asyncio
import hashlib
import shutil
from datetime import date

import httpx
import pytest
from sqlalchemy import text

from arp import net_safety
from arp.config import get_settings
from arp.db.session import transaction
from arp.ingestion.indexing_config import IndexingConfig
from arp.storage.document_blob_store import blob_store_for
from arp.transition_barrier import dataset, fetching, store
from tests.transition_barrier_helpers import D_URLS, DOCS, FIXTURES, QUOTES, fetch_stub, pdf_with

pytestmark = pytest.mark.usefixtures("pg")
TODAY = date(2026, 10, 20)
SOURCES = {s.key: s for s in dataset.load_criteria(FIXTURES / "criteria_schema.json")[0].primary_sources}
D1, D2 = SOURCES["eu_ets_report"], SOURCES["cbam_regulation"]


def run(*sources):
    return asyncio.run(fetching.fetch_sources(list(sources), TODAY))


def rows(key: str) -> list[dict]:
    with transaction() as s:
        return [dict(r) for r in s.execute(text("select * from barrier_source_documents where source_key = :k order by id"), {"k": key}).mappings()]


def test_fetch_stores_pages_and_as_of(monkeypatch):
    fetch_stub(monkeypatch)
    assert run(D1) == []
    (row,) = rows("eu_ets_report")
    assert "The effective carbon price was USD 72/tCO2." in row["page_texts"][11]
    assert row["as_of"] == date(2026, 3, 31)
    assert (row["tier"], row["html"], row["title"], row["url"]) == ("primary", False, DOCS["D1"][0], D1.url)
    assert blob_store_for(IndexingConfig.from_settings(get_settings())).exists(row["content_key"])


def test_refetch_unchanged_is_noop(monkeypatch):
    fetch_stub(monkeypatch)
    run(D1)
    first = store.latest_source_documents(["eu_ets_report"])[0]["id"]
    run(D1)
    assert len(rows("eu_ets_report")) == 1
    assert store.latest_source_documents(["eu_ets_report"])[0]["id"] == first


def test_changed_document_adds_row(monkeypatch):
    fetch_stub(monkeypatch)
    run(D1)
    fetch_stub(monkeypatch, {D_URLS["D1"]: (pdf_with(["A new report."]), "application/pdf", "2026-09-01")})
    run(D1)
    assert len(rows("eu_ets_report")) == 2
    (latest,) = store.latest_source_documents(["eu_ets_report"])
    assert latest["page_texts"][0].strip() == "A new report." and latest["as_of"] == date(2026, 9, 1)


def test_latest_source_documents_follow_the_order_given(monkeypatch):
    fetch_stub(monkeypatch)
    run(D1, D2)
    assert [d["source_key"] for d in store.latest_source_documents(["cbam_regulation", "nope", "eu_ets_report"])] == [
        "cbam_regulation",
        "eu_ets_report",
    ]


def test_html_has_one_text_block(monkeypatch):
    quote = QUOTES["D2"][3]
    html = f"<html><body><article><p>{quote}</p></article></body></html>".encode()
    fetch_stub(monkeypatch, {D_URLS["D2"]: (html, "text/html; charset=utf-8", None)})
    assert run(D2) == []
    (row,) = rows("cbam_regulation")
    assert row["html"] is True and len(row["page_texts"]) == 1 and quote in row["page_texts"][0]
    assert row["as_of"] == TODAY


def test_ssrf_refused_makes_no_request(monkeypatch):
    requested = fetch_stub(monkeypatch)
    bad = D1.model_copy(update={"url": "http://169.254.169.254/latest"})
    (note,) = run(bad)
    assert note.startswith("Not fetched: ") and requested == [] and rows("eu_ets_report") == []


def test_no_text_layer_skipped(monkeypatch):
    fetch_stub(monkeypatch, {D_URLS["D1"]: (pdf_with([None, None]), "application/pdf", None)})
    assert run(D1) == [f"Not fetched: {D1.source_name} (no text layer)"]
    assert rows("eu_ets_report") == []


def test_http_error_and_unsupported_type_are_skipped(monkeypatch):
    fetch_stub(monkeypatch, {D_URLS["D2"]: (b"{}", "application/json", None)})
    notes = run(D2, D1.model_copy(update={"url": "https://example.org/missing.pdf"}))
    assert notes == [f"Not fetched: {D2.source_name} (unsupported type application/json)", f"Not fetched: {D1.source_name} (HTTP 404)"]


def test_manual_and_urlless_sources_skipped_silently(monkeypatch):
    requested = fetch_stub(monkeypatch)
    assert run(D1.model_copy(update={"manual": True}), D2.model_copy(update={"url": None})) == [] and requested == []


def test_fetch_creates_no_company(monkeypatch):
    def companies() -> int:
        with transaction() as s:
            return s.execute(text("select count(*) from companies")).scalar_one()

    before = companies()
    fetch_stub(monkeypatch)
    run(D1)
    assert companies() == before


def test_fetch_leaves_data_dir_untouched(tmp_path, monkeypatch):
    target = tmp_path / "transition_barrier"
    shutil.copytree(FIXTURES, target)
    monkeypatch.setenv("ARP_TRANSITION_BARRIER_DATA_DIR", str(target))
    get_settings.cache_clear()
    dataset.reset_caches()

    def digests() -> dict[str, str]:
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(target.rglob("*")) if p.is_file()}

    before = digests()
    fetch_stub(monkeypatch)
    run(D1)
    assert digests() == before
    get_settings.cache_clear()
    dataset.reset_caches()



def test_same_text_new_bytes_keeps_the_row(monkeypatch):  # HTML pages and generated PDFs change bytes on every fetch
    quote = QUOTES["D2"][3]
    fetch_stub(monkeypatch, {D_URLS["D2"]: (f"<html><body><p>{quote}</p><!-- 1 --></body></html>".encode(), "text/html", None)})
    run(D2)
    fetch_stub(monkeypatch, {D_URLS["D2"]: (f"<html><body><p>{quote}</p><!-- 2 --></body></html>".encode(), "text/html", None)})
    run(D2)
    (row,) = rows("cbam_regulation")
    assert blob_store_for(IndexingConfig.from_settings(get_settings())).exists(row["content_key"])


def test_only_http_200_is_fetched(monkeypatch):  # EUR-Lex /eli/ answers 202 with an empty body
    fetch_stub(monkeypatch)
    monkeypatch.setattr(fetching, "build_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(202))))
    assert run(D2) == [f"Not fetched: {D2.source_name} (HTTP 202)"]
    assert rows("cbam_regulation") == []


def test_fetch_client_has_the_ssrf_guard():
    client = fetching.build_client()
    assert net_safety.ssrf_guard_request_hook in client.event_hooks["request"]
    asyncio.run(client.aclose())


def test_one_bad_source_is_a_note(monkeypatch):
    fetch_stub(monkeypatch)
    notes = run(D2.model_copy(update={"url": "https://[bad/x"}), D1)
    assert notes == [f"Not fetched: {D2.source_name} (Invalid IPv6 URL)"]
    assert len(rows("eu_ets_report")) == 1
