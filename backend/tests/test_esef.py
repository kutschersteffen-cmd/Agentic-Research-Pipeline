"""E16: European ESEF (iXBRL) filings -- visible text with exact fact offsets, tagged facts into E29."""

import asyncio
import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import httpx
import pytest

from arp.config import Settings
from arp.discovery import downloader
from arp.discovery.crawler import CandidateDocumentLink, classify_link
from arp.extraction.pipeline import _extract_company
from arp.ingestion.esef import EsefDocumentSource, EsefFactSource, parse_ixbrl, parse_package
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.ingestion.xbrl import CompanyFactsSource, XbrlFactSource
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition, FieldQuality, FieldStatus
from arp.storage.document_blob_store import LocalBlobStore
from arp.storage.document_store import DocumentContentStore

FIXTURES = Path(__file__).parent / "fixtures" / "esef"
XHTML = (FIXTURES / "beispiel-2024.xhtml").read_bytes()
PACKAGE = (FIXTURES / "beispiel-2024.zip").read_bytes()
LEI = "529900T8BM49AURSDO55"
COMPANY = CompanyRef(company_id="c1", name="Beispiel AG", lei=LEI)


def _settings(tmp_path, **kw) -> Settings:
    return Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", schema_registry_dir=tmp_path / "schemas",
        documents_dir=tmp_path / "docs", cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc", **kw,
    )


def _field() -> FieldDefinition:
    return FieldDefinition(
        name="revenue_eur_m", description="Total revenue.", data_type=FieldDataType.CURRENCY_AMOUNT, unit="EUR millions",
        extraction_instructions="Total revenue for the fiscal year.", seed_keywords=["revenue"],
        xbrl_tags=["ifrs-full:Revenue"], status=FieldStatus.RELEASED,
    )


def _local_source(tmp_path, name="beispiel-2024.xhtml"):
    dest = tmp_path / "docs" / "c1" / DocType.ANNUAL_REPORT_10K.value
    dest.mkdir(parents=True)
    shutil.copy(FIXTURES / name, dest / name)
    store = DocumentContentStore(tmp_path / "store")
    blobs = tmp_path / "blobs"
    source = LocalFileDocumentSource(tmp_path / "docs", content_store=store, indexing_config=IndexingConfig(blob_store_dir=blobs))
    return source, store, LocalBlobStore(blobs)


async def test_esef_filing_yields_tagged_facts_through_e29(tmp_path, fake_llm):
    source, store, _ = _local_source(tmp_path)
    llm, verifier_llm = fake_llm({}), fake_llm({})
    field = _field()
    result = await _extract_company(
        COMPANY, DataPointSchema(name="Rev", fields=[field], release_flag=True),
        registry=DocumentSourceRegistry([source]), llm=llm, verifier_llm=verifier_llm, settings=_settings(tmp_path),
    )
    fields = result.record.fields
    assert [f.method for f in fields] == ["tagged", "tagged"]  # 2024 and its 2023 comparative
    f24 = next(f for f in fields if f.period_end == "2024-12-31")
    assert (f24.canonical_value, f24.canonical_unit) == (1234.5, "EUR millions")  # the precise duplicate, not "1.2 billion"
    [c] = f24.citations
    stored = store.lookup(c.content_key, c.parser_version).full_text
    assert c.grounded and stored[c.char_start:c.char_end] == c.quote == "1,234.5"
    assert llm.calls == [] and verifier_llm.calls == []


def test_scale_and_sign():
    text, facts = parse_ixbrl(XHTML)
    op = {f.period_end: f for f in facts if f.concept == "ifrs-full:ProfitLossFromOperatingActivities"}
    assert op["2024-12-31"].value == -45_600_000 and op["2023-12-31"].value == 12_300_000
    for f in facts:
        assert text[f.char_start:f.char_end] == f.printed
    assert op["2024-12-31"].printed == "45.6" and op["2024-12-31"].unit == "EUR"
    rev = [f for f in facts if f.concept == "ifrs-full:Revenue"]
    assert sorted(f.value for f in rev) == [1_100_000_000, 1_200_000_000, 1_234_500_000]  # hidden and segment facts left out
    assert "9999" not in text and "ifrs-full" not in text and "color" not in text  # header, hidden facts, styles


def test_comma_decimal_format():
    xhtml = XHTML.replace(b'format="ixt:num-dot-decimal">1,234.5', b'format="ixt:num-comma-decimal">1.234,5')
    text, facts = parse_ixbrl(xhtml)
    [f] = [f for f in facts if f.printed == "1.234,5"]
    assert f.value == 1_234_500_000 and text[f.char_start:f.char_end] == "1.234,5"


def test_package_zip_and_bomb_rejected():
    assert parse_package(PACKAGE) == parse_ixbrl(XHTML)  # the largest reports/*.xhtml, not the cover page
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("p/reports/bomb.xhtml", b"\0" * 20_000_000)
    with pytest.raises(ValueError, match="too large"):
        parse_package(buf.getvalue())
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("p/META-INF/reportPackage.xml", b"<x/>")
    with pytest.raises(ValueError, match="reports"):
        parse_package(empty.getvalue())


async def test_esef_citation_publishable(tmp_path, fake_llm):
    from arp.publish.candidates import run_candidates
    from arp.publish.gate import lineage_error
    from arp.publish.release import split_by_gate
    from arp.schemas.common import RunManifest
    from arp.storage.run_store import RunStore

    source, store, blobs = _local_source(tmp_path, "beispiel-2024.zip")  # the package parses the same way
    field = _field()
    qualities = {(field.field_id, field.version): FieldQuality(field_id=field.field_id, version=field.version, first_audit_passed=True)}
    result = await _extract_company(
        COMPANY, DataPointSchema(name="Rev", fields=[field], release_flag=True), registry=DocumentSourceRegistry([source]),
        llm=fake_llm({}), verifier_llm=fake_llm({}), settings=_settings(tmp_path), qualities=qualities,
    )
    rs = RunStore(tmp_path / "pub-runs")
    rs.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    rs.append_jsonl(rs.results_path("r1"), {"company_id": "c1", "issuer_key": "ISS1", "issuer_scheme": "LEI",
                                            "fields": [f.model_dump(mode="json") for f in result.record.fields]})
    assert [(f.method, f.route) for f in result.record.fields] == [("tagged", "auto_accept")] * 2  # layer-2 checks pass
    cands, _ = run_candidates(rs, "r1")
    assert len(cands) == 2 and all(c.state == "auto_accepted" and c.citation is not None for c in cands)
    for c in cands:
        assert lineage_error(c.citation, blobs, content_store=store) is None
        assert c.citation.content_key == hashlib.sha256(PACKAGE).hexdigest()
    passed, blocked = split_by_gate(cands, blobs, withdrawn_docs=set(), content_store=store)
    assert blocked == [] and sum(len(v) for v in passed.values()) == 2


def test_crawler_accepts_xhtml_and_zip(tmp_path, monkeypatch):
    assert classify_link("https://ir.example/esef/report-2024.xhtml", "Download") == DocType.OTHER
    assert classify_link("https://ir.example/esef/beispiel-2024.zip", "Download") == DocType.OTHER

    async def noop(request):
        return None

    monkeypatch.setattr(downloader, "ssrf_guard_request_hook", noop)
    bodies = {"/r.xhtml": (XHTML, "application/xhtml+xml"), "/p.zip": (PACKAGE, "application/octet-stream")}

    def handler(request):
        body, ctype = bodies[request.url.path]
        return httpx.Response(200, content=body, headers={"content-type": ctype})

    cands = [CandidateDocumentLink(url=f"https://ir.example{p}", doc_type=DocType.ANNUAL_REPORT_10K, link_text=Path(p).stem)
             for p in bodies]
    found = asyncio.run(downloader.download_documents(
        COMPANY, cands, tmp_path / "docs", "ua", store=LocalBlobStore(tmp_path / "blobs"), transport=httpx.MockTransport(handler),
    ))
    assert sorted(Path(d.local_path).suffix for d in found) == [".xhtml", ".zip"]


def test_source_off_by_default(tmp_path, monkeypatch):
    from arp.api.deps import build_registry

    def no_network(*a, **kw):
        raise AssertionError("network call with ESEF off")

    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    settings = _settings(tmp_path)
    assert settings.esef_enabled is False
    store = DocumentContentStore(tmp_path / "store")
    assert not any(isinstance(s, EsefDocumentSource) for s in build_registry(settings, store).sources)
    on = build_registry(_settings(tmp_path, esef_enabled=True), store)
    assert any(isinstance(s, EsefDocumentSource) for s in on.sources)


@pytest.fixture
def no_ssrf(monkeypatch):
    from arp.ingestion import esef

    async def noop(request):
        return None

    monkeypatch.setattr(esef, "ssrf_guard_request_hook", noop)


async def test_esef_document_source_fetches_by_lei(tmp_path, no_ssrf):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == f"/api/entities/{LEI}/filings":
            return httpx.Response(200, json={"data": [
                {"attributes": {"period_end": "2023-12-31", "package_url": "/old.zip"}},
                {"attributes": {"period_end": "2024-12-31", "package_url": f"/{LEI}/2024-12-31/ESEF/DE/0/beispiel-2024.zip"}},
            ]})
        if request.url.path.endswith("beispiel-2024.zip"):
            return httpx.Response(200, content=PACKAGE)
        return httpx.Response(404)

    store = DocumentContentStore(tmp_path / "store")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = EsefDocumentSource(
        "https://filings.example", tmp_path / "cache", client=client, content_store=store,
        indexing_config=IndexingConfig(blob_store_dir=tmp_path / "blobs"),
    )
    [doc] = await source.fetch(COMPANY)
    assert "/old.zip" not in seen  # the latest filing only
    key = hashlib.sha256(PACKAGE).hexdigest()
    assert doc.content_key == key and doc.doc_type == DocType.ANNUAL_REPORT_10K and doc.decimal == "point"
    assert LocalBlobStore(tmp_path / "blobs").exists(key)  # store-or-fail original
    assert store.resolve_document(doc.doc_id).storage_uri.endswith(key)
    assert doc.full_text == parse_package(PACKAGE)[0]
    facts = EsefFactSource(parse_package(PACKAGE)[1], doc)
    fact = facts.fact_for_tags(["ifrs-full:Revenue"], fiscal_year=2024)
    c = fact.as_citation()
    assert (fact.value, c.doc_id, c.content_key, c.quote) == (1_234_500_000, doc.doc_id, key, "1,234.5")
    assert doc.full_text[c.char_start:c.char_end] == "1,234.5"
    assert await source.fetch(CompanyRef(company_id="c2", name="No LEI")) == []
    await client.aclose()


async def test_esef_package_downloaded_once(tmp_path, no_ssrf):
    downloads = []

    def handler(request):
        if request.url.path == f"/api/entities/{LEI}/filings":
            return httpx.Response(200, json={"data": [{"attributes": {"period_end": "2024-12-31", "package_url": "/p.zip"}}]})
        downloads.append(request.url.path)
        return httpx.Response(200, content=PACKAGE)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = EsefDocumentSource("https://filings.example", tmp_path / "cache", client=client)
    [first] = await source.fetch(COMPANY)
    [again] = await source.fetch(COMPANY)
    assert downloads == ["/p.zip"]  # the index is still polled; the package comes from the local copy
    assert again.local_path == first.local_path and again.full_text == first.full_text
    (tmp_path / "cache" / "esef" / f"{hashlib.sha256(PACKAGE).hexdigest()}.zip").write_bytes(b"corrupt")
    [healed] = await source.fetch(COMPANY)  # a local copy that no longer matches its hash is fetched again
    assert downloads == ["/p.zip", "/p.zip"] and healed.full_text == first.full_text
    await client.aclose()


def test_sec_companyfacts_wrapper_unchanged():
    row = {"start": "2024-01-01", "end": "2024-12-31", "val": 3, "fy": 2024, "fp": "FY", "form": "10-K",
           "filed": "2025-02-01", "accn": "0001-24-000001"}
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [row]}}}}}
    raw = XbrlFactSource.fact_for_tags(facts, ["us-gaap:Revenues"], fiscal_year=2024)
    wrapped = CompanyFactsSource(facts, "320193").fact_for_tags(["us-gaap:Revenues"], fiscal_year=2024)
    assert wrapped.value == raw.value and wrapped.as_citation() == raw.as_citation("320193")
    assert CompanyFactsSource(facts, "1").fact_for_tags(["us-gaap:Revenues"], fiscal_year=2023) is None
    assert json.loads(raw.model_dump_json())["tag"] == "Revenues"


def _index_source(tmp_path, package: bytes, **kw):
    def handler(request):
        if request.url.path.endswith("/filings"):
            return httpx.Response(200, json={"data": [{"attributes": {"period_end": "2024-12-31", "package_url": "/p.zip"}}]})
        return httpx.Response(200, content=package)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return EsefDocumentSource("https://filings.example", tmp_path / "cache", client=client, **kw), client


async def test_package_download_is_ssrf_guarded(tmp_path, monkeypatch):
    from arp.ingestion import esef
    from arp.net_safety import UnsafeURLError

    guarded = []

    async def refuse(request):
        guarded.append(str(request.url))
        raise UnsafeURLError("private address")

    monkeypatch.setattr(esef, "ssrf_guard_request_hook", refuse)
    source, client = _index_source(tmp_path, PACKAGE)
    assert await source.fetch(COMPANY) == []
    assert guarded == ["https://filings.example/p.zip"]
    await client.aclose()


async def test_package_over_size_cap_refused(tmp_path, no_ssrf):
    source, client = _index_source(tmp_path, PACKAGE, max_package_bytes=len(PACKAGE) - 1)
    assert await source.fetch(COMPANY) == []
    source, client2 = _index_source(tmp_path, PACKAGE, max_package_bytes=len(PACKAGE))
    assert len(await source.fetch(COMPANY)) == 1
    await client.aclose(), await client2.aclose()


async def test_malformed_package_is_logged_not_raised(tmp_path, no_ssrf):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("p/reports/r.xhtml", b"<html><body><p>unclosed")
    source, client = _index_source(tmp_path, buf.getvalue())
    assert await source.fetch(COMPANY) == []
    deep = b"<html>" + b"<div>" * 100_000 + b"</div>" * 100_000 + b"</html>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("p/reports/r.xhtml", deep)
    source, client2 = _index_source(tmp_path, buf.getvalue())
    assert await source.fetch(COMPANY) == []
    await client.aclose(), await client2.aclose()


async def test_us_filer_with_esef_document_uses_sec_first(tmp_path, fake_llm):
    class _Sec:
        async def resolve_cik(self, cik, ticker):
            return cik

        async def fact_source(self, cik):
            row = {"start": "{y}-01-01", "end": "{y}-12-31", "val": 0, "fy": 0, "fp": "FY", "form": "10-K", "filed": "x"}
            rows = [{**row, "start": f"{y}-01-01", "end": f"{y}-12-31", "val": 7e9, "fy": y, "filed": f"{y + 1}-02-01"}
                    for y in (2023, 2024)]
            return CompanyFactsSource({"facts": {"ifrs-full": {"Revenue": {"units": {"EUR": rows}}}}}, cik)

    source, _, _ = _local_source(tmp_path)
    us = CompanyRef(company_id="c1", name="Beispiel AG", cik="0000320193", lei=LEI)
    result = await _extract_company(
        us, DataPointSchema(name="Rev", fields=[_field()], release_flag=True), registry=DocumentSourceRegistry([source]),
        llm=fake_llm({}), verifier_llm=fake_llm({}), settings=_settings(tmp_path), xbrl_source=_Sec(),
    )
    assert [(f.method, f.canonical_value) for f in result.record.fields] == [("tagged", 7000.0)] * 2
    assert all(f.citations[0].doc_id.startswith("xbrl:") for f in result.record.fields)


def test_intake_zip_bomb_quarantined_before_testzip(tmp_path, monkeypatch):
    from arp.ingestion.intake import IntakeState, check_intake

    path = tmp_path / "bomb.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("p/reports/bomb.xhtml", b"\0" * 20_000_000)
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: pytest.fail("decompressed a zip bomb"))
    result = check_intake(path, "k", seen={})
    assert result.state == IntakeState.QUARANTINED and "too large" in result.reason
    good = tmp_path / "p.zip"
    good.write_bytes(PACKAGE)
    monkeypatch.undo()
    assert check_intake(good, "k2", seen={}).state == IntakeState.ACCEPTED
