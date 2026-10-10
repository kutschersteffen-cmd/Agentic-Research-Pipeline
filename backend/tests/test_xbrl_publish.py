"""Step 7b: SEC tagged values publish through a frozen copy of the companyfacts JSON."""

from __future__ import annotations

import hashlib
import json
import os

import httpx
import pytest

import arp.orchestration.reground as R
from arp.config import Settings
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.xbrl import XbrlFactSource, freeze_company_facts
from arp.publish.candidates import run_candidates
from arp.publish.gate import lineage_error, reground_match
from arp.publish.release import split_by_gate
from arp.schemas.common import Citation, RunManifest
from arp.schemas.datapoints import ExtractedField, FieldQuality
from arp.storage.document_blob_store import LocalBlobStore
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore
from tests.test_tagged_first import _facts, _FakeXbrl, _field, _run

CIK = "0000320193"
FACTS = _facts(2024, "2024-12-31")
RAW = json.dumps(FACTS).encode()


def _stores(tmp_path):
    return LocalBlobStore(tmp_path / "blobs"), DocumentContentStore(tmp_path / "docs")


async def _published_run(tmp_path, fake_llm, frozen):
    field = _field(["us-gaap:Revenues"])
    qualities = {(field.field_id, field.version): FieldQuality(field_id=field.field_id, version=field.version, first_audit_passed=True)}
    (f,), _, _ = await _run(tmp_path, fake_llm, field, FACTS, qualities=qualities, xbrl=_FakeXbrl(FACTS, frozen=frozen))
    assert (f.method, f.route) == ("tagged", "auto_accept")
    rs = RunStore(tmp_path / "pub-runs")
    rs.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    rs.append_jsonl(rs._results_path("r1"), {"company_id": "c1", "issuer_key": "ISS1", "issuer_scheme": "LEI",
                                            "fields": [f.model_dump(mode="json")]})
    return f, rs


async def test_tagged_value_publishes(tmp_path, fake_llm):
    blobs, texts = _stores(tmp_path)
    frozen = freeze_company_facts(RAW, CIK, blob_store=blobs, content_store=texts)
    assert freeze_company_facts(RAW, CIK, blob_store=blobs, content_store=texts) == frozen  # idempotent
    sha = hashlib.sha256(RAW).hexdigest()
    assert (frozen.doc_id, frozen.content_key, frozen.parser_version) == (f"xbrl:{CIK}:{sha[:16]}", sha, "xbrl_companyfacts_v1")
    line = "us-gaap:Revenues = 383,285,000,000 USD (period ending 2024-12-31, form 10-K, filed 2025-02-01)"
    assert frozen.text == line + "\n"
    assert texts.resolve_document(frozen.doc_id).storage_uri == blobs.uri(sha)

    f, rs = await _published_run(tmp_path, fake_llm, frozen)
    c = f.citations[0]
    assert (c.doc_id, c.content_key, c.parser_version, c.quote) == (frozen.doc_id, sha, "xbrl_companyfacts_v1", line)
    assert frozen.text[c.char_start:c.char_end] == line
    [cand] = run_candidates(rs, "r1")[0]
    assert cand.citation is not None
    passed, blocked = split_by_gate([cand], blobs, withdrawn_docs=set(), content_store=texts)
    assert blocked == [] and list(passed) == [("ISS1", frozen.doc_id)]
    assert reground_match(cand.citation, blob_store=blobs, content_store=texts, fuzzy_threshold=0.9)[0] == "ok"


async def test_missing_frozen_original_blocks_release(tmp_path, fake_llm):
    blobs, texts = _stores(tmp_path)
    frozen = freeze_company_facts(RAW, CIK, blob_store=blobs, content_store=texts)
    f, rs = await _published_run(tmp_path, fake_llm, frozen)
    (tmp_path / "blobs" / frozen.content_key[:2] / frozen.content_key).unlink()
    assert lineage_error(f.citations[0], blobs, content_store=texts) == "original_missing"
    [cand] = run_candidates(rs, "r1")[0]
    _, blocked = split_by_gate([cand], blobs, withdrawn_docs=set(), content_store=texts)
    assert blocked == [{"doc_id": frozen.doc_id, "reason": "original_missing", "item_keys": [cand.item_key]}]


async def test_reground_skips_xbrl_versions(tmp_path, monkeypatch):
    blobs, texts = _stores(tmp_path)
    frozen = freeze_company_facts(RAW, CIK, blob_store=blobs, content_store=texts)
    fact = XbrlFactSource.fact_for_tags(FACTS, ["us-gaap:Revenues"], fiscal_year=2024)
    c = fact.as_citation(CIK, frozen=frozen)
    rs = RunStore(tmp_path / "runs")
    rs.save_manifest(RunManifest(run_id="ext1", run_type="extraction"))
    rs.append_jsonl(rs._results_path("ext1"), {"company_id": "c1", "issuer_key": "ISS1", "issuer_scheme": "LEI", "fields": [
        {"field_id": "f1", "field_name": "Rev", "value": 1.0, "confidence": 1.0, "grounded": True, "period_end": "2024-12-31",
         "citations": [c.model_dump(mode="json")]}]})
    monkeypatch.setattr(R, "parser_version", lambda: "new")
    report = R.reground_runs(rs, settings=Settings(publish_state_dir=tmp_path / "state"), blob_store=blobs, content_store=texts)
    assert report == R.RegroundReport()


def test_old_tagged_rows_still_load(tmp_path):
    old = {"doc_id": "xbrl:0000320193:0001-24-000001", "doc_type": "other", "grounded": True,
           "quote": "us-gaap:Revenues = 383,285,000,000 USD (period ending 2024-12-31, form 10-K, filed 2025-02-01)",
           "location": "SEC EDGAR XBRL companyfacts API"}
    row = {"field_id": "f1", "field_name": "Rev", "value": 1.0, "confidence": 1.0, "method": "tagged", "period_end": "2024-12-31",
           "citations": [old]}
    f = ExtractedField.model_validate(row)
    assert f.citations[0] == Citation.model_validate(old) and f.citations[0].content_key is None
    # Without a frozen original the citation is the old, unpublishable one.
    fact = XbrlFactSource.fact_for_tags(FACTS, ["us-gaap:Revenues"], fiscal_year=2024)
    assert fact.as_citation(CIK).model_dump() == Citation.model_validate({**old, "doc_type": "other"}).model_dump()
    rs = RunStore(tmp_path / "runs")
    rs.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    rs.append_jsonl(rs._results_path("r1"), {"company_id": "c1", "issuer_key": "ISS1", "issuer_scheme": "LEI",
                                            "fields": [{**row, "route": "auto_accept"}]})
    [cand] = run_candidates(rs, "r1")[0]
    assert split_by_gate([cand], None, withdrawn_docs=set())[1][0]["reason"] == "no_grounded_citation"


class _Client:
    """Stands in for httpx.AsyncClient: serves RAW, counts requests."""

    calls = 0

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kw):
        _Client.calls += 1
        return httpx.Response(200, content=RAW, request=httpx.Request("GET", url))


async def test_fact_source_freezes_fetched_bytes_and_cache_hits(tmp_path, monkeypatch):
    monkeypatch.setattr("arp.ingestion.xbrl.httpx.AsyncClient", _Client)
    _Client.calls = 0
    texts = DocumentContentStore(tmp_path / "docs")
    edgar = EdgarDocumentSource("t t@example.com", tmp_path / "cache", content_store=texts,
                                indexing_config=IndexingConfig(blob_store_dir=tmp_path / "blobs"))
    source = XbrlFactSource(edgar, tmp_path / "cache")
    first = await source.fact_source(CIK)
    second = await source.fact_source(CIK)  # from the cache: no second request
    assert _Client.calls == 1
    assert first.frozen is not None and first.frozen == second.frozen
    assert first.frozen.content_key == hashlib.sha256(RAW).hexdigest()
    c = first.fact_for_tags(["us-gaap:Revenues"], fiscal_year=2024).as_citation()
    assert c.content_key == first.frozen.content_key and c.char_start == 0


async def test_fact_source_without_blob_store_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr("arp.ingestion.xbrl.httpx.AsyncClient", _Client)
    texts = DocumentContentStore(tmp_path / "docs")
    edgar = EdgarDocumentSource("t t@example.com", tmp_path / "cache", content_store=texts,
                                indexing_config=IndexingConfig())  # no blob store configured
    source = await XbrlFactSource(edgar, tmp_path / "cache").fact_source(CIK)
    assert source.frozen is None
    c = source.fact_for_tags(["us-gaap:Revenues"], fiscal_year=2024).as_citation()
    assert c.grounded and c.content_key is None and c.doc_id == f"xbrl:{CIK}:0001-24-000001"


@pytest.mark.skipif(not os.environ.get("ARP_TEST_POSTGRES_DSN"), reason="ARP_TEST_POSTGRES_DSN not set")
async def test_tagged_value_publishes_pg(tmp_path, fake_llm):
    from arp.publish.facts import PublishStore
    from arp.publish.release import publish_run
    from arp.storage.postgres import ensure_schema
    from tests.postgres_helpers import reset_postgres_tables

    dsn = os.environ["ARP_TEST_POSTGRES_DSN"]
    ensure_schema(dsn)
    reset_postgres_tables(dsn)
    try:
        blobs, texts = _stores(tmp_path)
        frozen = freeze_company_facts(RAW, CIK, blob_store=blobs, content_store=texts)
        _, rs = await _published_run(tmp_path, fake_llm, frozen)
        result = publish_run(PublishStore(dsn), rs, "r1", principal=None, blob_store=blobs, content_store=texts)
        assert result.blocked == [] and len(result.releases) == 1
        assert result.releases[0].doc_id == frozen.doc_id
    finally:
        reset_postgres_tables(dsn)
