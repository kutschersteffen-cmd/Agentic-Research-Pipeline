from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.xbrl import XbrlFactSource
from arp.storage.safe_path import UnsafeIdentifierError
from arp.xbrl_pipeline.models import CatalogEntry, FactRow, ReportMeta, RequiredRow
from arp.xbrl_pipeline.store import XbrlStore

CIK = "0000000001"
FIXTURE = Path(__file__).parent / "fixtures" / "xbrl" / "companyfacts_small.json"


def _fact(**kw):
    base = dict(company_id="c1", cik=CIK, taxonomy="us-gaap", concept="Revenues", unit="USD", value=1.0,
                period_start="2023-10-01", period_end="2024-09-28", fiscal_year=2024, fiscal_period="FY",
                form="10-K", filed="2024-11-01", accession="a", source_sha="s")
    base.update(kw)
    return FactRow(**base)


def test_save_original_is_idempotent_and_returns_sha(tmp_path):
    s = XbrlStore(tmp_path)
    raw = FIXTURE.read_bytes()
    sha = s.save_original(CIK, raw)
    assert s.save_original(CIK, raw) == sha and len(sha) == 64
    assert len(list(s.company_dir(CIK).glob("companyfacts-*.json"))) == 1


def test_meta_roundtrip_and_original_loads_latest(tmp_path):
    s = XbrlStore(tmp_path)
    assert s.meta(CIK) is None and s.original(CIK) is None
    sha = s.save_original(CIK, FIXTURE.read_bytes())
    s.set_meta(CIK, source_sha=sha, tags=["us-gaap:Revenues"], company_id="c1", company_name="Ex", fact_count=5)
    m = s.meta(CIK)
    assert m["source_sha"] == sha and m["tags"] == ["us-gaap:Revenues"] and m["fact_count"] == 5 and m["fetched_at"]
    assert s.original(CIK)["entityName"] == "Example Corp"
    assert s.ciks() == [CIK]


def test_facts_catalog_required_roundtrip(tmp_path):
    s = XbrlStore(tmp_path)
    assert s.write_facts(CIK, [_fact(), _fact(value=2.0)]) == 2
    assert [f.value for f in s.read_facts(CIK)] == [1.0, 2.0]
    assert _fact().tag_id == "us-gaap:Revenues"
    cat = [CatalogEntry(taxonomy="us-gaap", concept="Revenues", label="R", fact_count=2, first_year=2023, last_year=2024, units=["USD"])]
    s.write_catalog(CIK, cat)
    assert s.read_catalog(CIK) == cat
    req = [RequiredRow(company_id="c1", cik=CIK, metric="revenue", fiscal_year=2024, status="found", concept="Revenues",
                       value=1.0, unit="USD", period_start=None, period_end="2024-09-28", form="10-K", filed=None)]
    s.write_required(CIK, req)
    assert s.read_required(CIK) == req


def test_save_report_and_report_meta_roundtrip(tmp_path):
    s = XbrlStore(tmp_path)
    assert s.report_meta(CIK) is None
    meta = ReportMeta(accession="0000-24-1", form="10-K", filing_date="2024-11-01", source_url="u",
                      primary_document="d.htm", filename="annual-0000-24-1.htm", sha256="x", size=3, inline_xbrl=False)
    p = s.save_report(CIK, b"abc", meta)
    assert p.name == "annual-0000-24-1.htm" and p.read_bytes() == b"abc"
    assert s.report_meta(CIK) == meta


def test_file_path_kinds(tmp_path):
    s = XbrlStore(tmp_path)
    assert s.file_path(CIK, "facts") is None
    s.write_facts(CIK, [_fact()])
    s.save_original(CIK, b"{}")
    assert s.file_path(CIK, "facts").name == "facts.jsonl"
    assert s.file_path(CIK, "original") is None  # no meta yet
    s.set_meta(CIK, source_sha=s.save_original(CIK, b"{}"), tags=None, company_id="c1", company_name=None, fact_count=1)
    assert s.file_path(CIK, "original").exists()
    assert s.file_path(CIK, "report") is None
    with pytest.raises(KeyError):
        s.file_path(CIK, "../x")


def test_unsafe_cik_rejected(tmp_path):
    with pytest.raises(UnsafeIdentifierError):
        XbrlStore(tmp_path).company_dir("../x")


def test_fetch_company_facts_raw_returns_data_and_bytes(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    raw = FIXTURE.read_text()
    (cache / f"xbrl_companyfacts_{CIK}.json").write_text(json.dumps({"_fetched_at": time.time(), "raw": raw}))
    edgar = EdgarDocumentSource(user_agent="t t@example.com", cache_dir=cache)
    data, got = asyncio.run(XbrlFactSource(edgar, cache).fetch_company_facts_raw(CIK))
    assert data["entityName"] == "Example Corp" and got == raw.encode()


def test_company_ids_merge_in_order_and_fall_back_to_legacy_meta(tmp_path):
    s = XbrlStore(tmp_path)
    assert s.company_ids(CIK) == []
    for cid in ("a", "b", "a"):
        s.set_meta(CIK, source_sha="x", tags=None, company_id=cid, company_name=None, fact_count=1)
    assert s.company_ids(CIK) == ["a", "b"] and s.meta(CIK)["company_id"] == "a"
    legacy = XbrlStore(tmp_path / "legacy")
    legacy.company_dir(CIK).mkdir(parents=True)
    (legacy.company_dir(CIK) / "meta.json").write_text(json.dumps({"company_id": "old"}))
    assert legacy.company_ids(CIK) == ["old"]


def test_save_original_prefix_and_meta_original_file(tmp_path):
    s = XbrlStore(tmp_path)
    raw = b'{"a": 1}'
    sha = s.save_original(CIK, raw, prefix="xbrl-json")
    name = f"xbrl-json-{sha[:16]}.json"
    s.set_meta(CIK, source_sha=sha, tags=None, company_id="c1", company_name=None, fact_count=1,
               market="esef", original_file=name)
    assert s.original(CIK) == {"a": 1}
    assert s.file_path(CIK, "original").name == name
    assert s.meta(CIK)["market"] == "esef" and s.meta(CIK)["skipped_dimensional"] == 0


def test_original_falls_back_to_companyfacts_name(tmp_path):
    s = XbrlStore(tmp_path)
    sha = s.save_original(CIK, b'{"a": 1}')
    s.set_meta(CIK, source_sha=sha, tags=None, company_id="c1", company_name=None, fact_count=1)
    assert s.original(CIK) == {"a": 1}
    assert s.file_path(CIK, "original").name == f"companyfacts-{sha[:16]}.json"


def test_save_report_uses_meta_filename_and_rejects_paths(tmp_path):
    s = XbrlStore(tmp_path)

    def meta(filename):
        return ReportMeta(accession="a", form="ESEF", filing_date=None, source_url="u", primary_document="d",
                          filename=filename, sha256="x", size=1, inline_xbrl=True)

    with pytest.raises(ValueError):
        s.save_report(CIK, b"z", meta("../x.zip"))
    assert s.save_report(CIK, b"z", meta("package-abc.zip")).name == "package-abc.zip"
