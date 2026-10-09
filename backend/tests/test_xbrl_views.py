from __future__ import annotations

import json
from pathlib import Path

import pytest

from arp.xbrl_pipeline.flatten import build_catalog, flatten_company_facts
from arp.xbrl_pipeline.models import ReportMeta
from arp.xbrl_pipeline.store import XbrlStore
from arp.xbrl_pipeline.views import download_path, list_company_files, pivot_facts, query_facts

FIXTURE = Path(__file__).parent / "fixtures" / "xbrl" / "companyfacts_small.json"
CIK = "0001234567"
REPORT = b"<html>annual</html>"


def _store(tmp_path: Path, extra: list | None = None) -> XbrlStore:
    store = XbrlStore(tmp_path / "x")
    raw = FIXTURE.read_bytes()
    facts = json.loads(raw)
    sha = store.save_original(CIK, raw)
    rows = list(flatten_company_facts(facts, company_id="ex", cik=CIK, source_sha=sha)) + (extra or [])
    store.write_facts(CIK, rows)
    store.write_catalog(CIK, build_catalog(facts))
    store.set_meta(CIK, source_sha=sha, tags=None, company_id="ex", company_name="Example Inc",
                   fact_count=len(rows))
    store.save_report(CIK, REPORT, ReportMeta(
        accession="0001-24-000001", form="10-K", filing_date="2024-11-01", source_url="http://x",
        primary_document="a.htm", filename="annual-0001-24-000001.htm", sha256="s", size=len(REPORT),
        inline_xbrl=True))
    return store


def _restated(store: XbrlStore):
    base = next(r for r in store.read_facts(CIK)
                if r.concept == "Revenues" and r.period_end == "2024-09-28" and r.form == "10-K")
    return base.model_copy(update={"value": 1250.0, "filed": "2025-03-01", "form": "10-K/A"})


def test_list_company_files_has_sizes_and_report(tmp_path):
    store = _store(tmp_path)
    items, total = list_company_files(store)
    assert total == 1
    f = items[0]
    assert (f.cik, f.company_id, f.name, f.fact_count) == (CIK, "ex", "Example Inc", 5)
    assert f.original_size == len(FIXTURE.read_bytes())
    assert f.report is not None and f.report.size == len(REPORT)
    assert list_company_files(store, offset=1) == ([], 1)


def test_query_facts_filters_by_text_and_returns_label(tmp_path):
    rows, total = query_facts(_store(tmp_path), CIK, q="revenues")
    assert total == 3
    assert [r.label for r in rows] == ["Revenues"] * 3


def test_query_facts_annual_only(tmp_path):
    rows, total = query_facts(_store(tmp_path), CIK, annual_only=True)
    assert total == 4
    assert sorted((r.tag_id, r.period_end) for r in rows) == [
        ("dei:EntityCommonStockSharesOutstanding", "2024-10-18"),
        ("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", "2024-09-28"),
        ("us-gaap:Revenues", "2023-09-30"),
        ("us-gaap:Revenues", "2024-09-28"),
    ]


def test_query_facts_sort_and_paging(tmp_path):
    rows, total = query_facts(_store(tmp_path), CIK, sort="value", order="asc", limit=2)
    assert total == 5
    assert [r.value for r in rows] == [150, 300]


def test_query_facts_rejects_unknown_sort(tmp_path):
    with pytest.raises(ValueError):
        query_facts(_store(tmp_path), CIK, sort="label")


def test_query_facts_period_year_and_taxonomy(tmp_path):
    rows, total = query_facts(_store(tmp_path), CIK, taxonomy="dei", period_year=2024)
    assert (total, [r.concept for r in rows]) == (1, ["EntityCommonStockSharesOutstanding"])


def test_pivot_years_and_values(tmp_path):
    t = pivot_facts(_store(tmp_path), CIK)
    assert t.years == [2024, 2023]
    assert t.total == 3
    by = {r.tag_id: r for r in t.rows}
    assert by["us-gaap:Revenues"].values == {2024: 1200.0, 2023: 1000.0}
    assert by["us-gaap:Revenues"].label == "Revenues"
    assert by["us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"].values == {2024: 150.0, 2023: None}
    assert by["dei:EntityCommonStockSharesOutstanding"].values == {2024: 15000.0, 2023: None}
    assert by["dei:EntityCommonStockSharesOutstanding"].unit == "shares"


def test_pivot_paging_total_is_before_paging(tmp_path):
    t = pivot_facts(_store(tmp_path), CIK, limit=1)
    assert (t.total, len(t.rows)) == (3, 1)


def test_pivot_latest_filed_wins(tmp_path):
    store = _store(tmp_path)
    store.write_facts(CIK, [*store.read_facts(CIK), _restated(store)])
    t = pivot_facts(store, CIK, q="us-gaap:Revenues")
    assert [r.values for r in t.rows] == [{2024: 1250.0, 2023: 1000.0}]


def test_download_path_kinds_and_errors(tmp_path):
    store = _store(tmp_path)
    assert download_path(store, CIK, "report").read_bytes() == REPORT
    assert download_path(store, CIK, "facts").name == "facts.jsonl"
    assert download_path(store, CIK, "original").name.startswith("companyfacts-")
    with pytest.raises(KeyError):
        download_path(store, CIK, "nope")
    with pytest.raises(FileNotFoundError):
        download_path(store, CIK, "required")


def test_download_path_rejects_tampered_report_filename(tmp_path):
    store = _store(tmp_path)
    (store.root / "secret.txt").write_text("s")
    rj = store.company_dir(CIK) / "report.json"
    meta = json.loads(rj.read_text())
    meta["filename"] = "../secret.txt"
    rj.write_text(json.dumps(meta))
    with pytest.raises(FileNotFoundError):
        download_path(store, CIK, "report")


def test_is_annual_rules(tmp_path):
    from arp.xbrl_pipeline.views import is_annual

    base = next(r for r in _store(tmp_path).read_facts(CIK) if r.concept == "Revenues" and r.period_end == "2024-09-28")
    assert is_annual(base)
    assert is_annual(base.model_copy(update={"form": "10-K/A"}))
    assert not is_annual(base.model_copy(update={"form": "10-Q"}))
    assert not is_annual(base.model_copy(update={"fiscal_period": "Q1"}))
    assert not is_annual(base.model_copy(update={"period_start": "2023-01-01"}))  # 636 days


def test_is_annual_accepts_esef_form():
    from arp.xbrl_pipeline.models import FactRow
    from arp.xbrl_pipeline.views import is_annual
    row = FactRow(company_id="c", cik="x", taxonomy="ifrs-full", concept="Revenue", unit="EUR", value=1.0,
                  period_start="2023-01-01", period_end="2023-12-31", fiscal_year=2023, fiscal_period="FY",
                  form="ESEF", filed=None, accession=None, source_sha="s", market="esef")
    assert is_annual(row)


def test_company_files_reports_market(tmp_path):
    store = _store(tmp_path)
    assert list_company_files(store)[0][0].market == "sec"
    sha = store.meta(CIK)["source_sha"]
    store.set_meta(CIK, source_sha=sha, tags=None, company_id="ex", company_name="E", fact_count=1, market="esef")
    assert list_company_files(store)[0][0].market == "esef"
