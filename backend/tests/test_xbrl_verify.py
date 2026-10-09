from __future__ import annotations

import json
from pathlib import Path

import pytest

from arp.schemas.datapoints import ExtractedField, ExtractionRecord
from arp.storage.run_store import RunStore
from arp.xbrl_pipeline.models import RequiredRow, VerifyRow
from arp.xbrl_pipeline.store import XbrlStore
from arp.xbrl_pipeline.verify import CircularRunError, UnsupportedRunError, verify_run

MAPPING = {"revenue": "rev_f", "capex": "capex_f"}


def _req(metric: str, year: int, value: float | None, *, status: str = "found", unit: str = "USD") -> RequiredRow:
    return RequiredRow(
        company_id="ex", cik="0001234567", metric=metric, fiscal_year=year, status=status,
        concept="us-gaap:Revenues" if value is not None else None, value=value,
        unit=unit if value is not None else None, period_start=None,
        period_end=f"{year}-12-31" if value is not None else None, form="10-K", filed=None,
    )


def _field(field_id: str, value: float | None, year: int, unit: str = "USD") -> ExtractedField:
    return ExtractedField(
        field_id=field_id, field_name=field_id, value=value, confidence=0.9,
        canonical_value=value, canonical_unit=unit if value is not None else None,
        period_end=f"{year}-12-31",
    )


def _setup(tmp_path: Path, fields: list[ExtractedField], required: list[RequiredRow], *,
           xbrl_on: bool = False, settings: bool = True):
    runs, store = RunStore(tmp_path / "runs"), XbrlStore(tmp_path / "xbrl")
    rec = ExtractionRecord(company_id="ex", name="Ex", schema_id="s", run_id="r1", fields=fields)
    runs.results_path("r1").write_text(rec.model_dump_json() + "\n")
    if settings:
        (runs.run_dir("r1") / "step_settings.json").write_text(json.dumps({"xbrl_facts_enabled": xbrl_on}))
    store.write_required("0001234567", required)
    (store.company_dir("0001234567") / "meta.json").write_text("{}")
    return runs, store


def _verify(runs, store, **kw):
    return verify_run("r1", run_store=runs, store=store, mapping=MAPPING, **kw)


def test_match_within_tolerance(tmp_path):
    runs, store = _setup(tmp_path, [_field("rev_f", 1004.0, 2024)], [_req("revenue", 2024, 1000.0)])
    assert _verify(runs, store) == [VerifyRow(
        company_id="ex", metric="revenue", fiscal_year=2024, outcome="match",
        run_value=1004.0, xbrl_value=1000.0, unit="USD", run_unit="USD", detail="")]


def test_mismatch_outside_tolerance(tmp_path):
    runs, store = _setup(tmp_path, [_field("rev_f", 1006.0, 2024)], [_req("revenue", 2024, 1000.0)])
    rows = _verify(runs, store)
    assert [(r.outcome, r.run_value, r.xbrl_value) for r in rows] == [("mismatch", 1006.0, 1000.0)]


def test_missing_in_run(tmp_path):
    runs, store = _setup(
        tmp_path, [_field("capex_f", 150.0, 2024)],
        [_req("revenue", 2024, 1000.0), _req("capex", 2024, 150.0)])
    rows = {r.metric: r for r in _verify(runs, store)}
    assert rows["revenue"].outcome == "missing_in_run"
    assert (rows["revenue"].run_value, rows["revenue"].xbrl_value) == (None, 1000.0)
    assert rows["capex"].outcome == "match"


def test_missing_in_xbrl(tmp_path):
    runs, store = _setup(
        tmp_path, [_field("rev_f", 1000.0, 2024)],
        [_req("revenue", 2024, None, status="not_found")])
    rows = _verify(runs, store)
    assert [(r.outcome, r.run_value, r.xbrl_value) for r in rows] == [("missing_in_xbrl", 1000.0, None)]


def test_unit_difference_is_mismatch(tmp_path):
    runs, store = _setup(tmp_path, [_field("rev_f", 1000.0, 2024, unit="EUR")], [_req("revenue", 2024, 1000.0)])
    rows = _verify(runs, store)
    assert [(r.outcome, r.detail) for r in rows] == [("mismatch", "unit")]


@pytest.mark.parametrize("unit,value,outcome,detail", [
    ("USD bn", 0.0000012, "match", ""),            # 0.0000012 bn = 1,200 USD
    ("USD million", 0.0013, "mismatch", ""),       # 1,300 USD, off by more than the tolerance
    ("foo", 1200.0, "mismatch", "unit"),           # unknown unit
    ("shares", 1200.0, "mismatch", "unit"),        # not a unit of currency
    ("EUR", 1200.0, "mismatch", "unit"),           # needs FX
])
def test_units_are_normalised_before_comparing(tmp_path, unit, value, outcome, detail):
    runs, store = _setup(tmp_path, [_field("rev_f", value, 2024, unit=unit)], [_req("revenue", 2024, 1200.0)])
    rows = _verify(runs, store)
    assert [(r.outcome, r.detail, r.run_unit, r.unit, r.xbrl_value) for r in rows] == [
        (outcome, detail, unit, "USD", 1200.0)]


def test_run_unit_is_none_without_run_value(tmp_path):
    runs, store = _setup(tmp_path, [_field("rev_f", None, 2024)], [_req("revenue", 2024, 1000.0)])
    assert [(r.outcome, r.run_unit) for r in _verify(runs, store)] == [("missing_in_run", None)]


def test_refuses_when_xbrl_was_on(tmp_path):
    runs, store = _setup(tmp_path, [_field("rev_f", 1000.0, 2024)], [_req("revenue", 2024, 1000.0)],
                         xbrl_on=True)
    with pytest.raises(CircularRunError):
        _verify(runs, store)
    assert not (runs.run_dir("r1") / "xbrl_verify.jsonl").exists()


def test_refuses_when_step_settings_missing(tmp_path):
    runs, store = _setup(tmp_path, [_field("rev_f", 1000.0, 2024)], [_req("revenue", 2024, 1000.0)],
                         settings=False)
    with pytest.raises(CircularRunError, match="record their step settings.*SEC XBRL facts first.*ARP_XBRL_FACTS_ENABLED=false"):
        _verify(runs, store)


def test_writes_verify_jsonl(tmp_path):
    runs, store = _setup(tmp_path, [_field("rev_f", 1000.0, 2024)], [_req("revenue", 2024, 1000.0)])
    rows = _verify(runs, store)
    lines = (runs.run_dir("r1") / "xbrl_verify.jsonl").read_text().splitlines()
    assert [VerifyRow.model_validate_json(x) for x in lines] == rows
    assert len(rows) == 1


@pytest.mark.parametrize("text", ["[]", "{not json"])
def test_refuses_when_step_settings_malformed(tmp_path, text):
    runs, store = _setup(tmp_path, [_field("rev_f", 1000.0, 2024)], [_req("revenue", 2024, 1000.0)])
    (runs.run_dir("r1") / "step_settings.json").write_text(text)
    with pytest.raises(CircularRunError, match="cannot prove XBRL was off"):
        _verify(runs, store)


def test_verify_matches_any_company_id_that_fetched_the_cik(tmp_path):
    runs, store = _setup(tmp_path, [], [_req("revenue", 2024, 1000.0)])
    rec = ExtractionRecord(company_id="acme-inc", name="Ex", schema_id="s", run_id="r1",
                           fields=[_field("rev_f", 1000.0, 2024)])
    runs.results_path("r1").write_text(rec.model_dump_json() + "\n")
    rows = [_req("revenue", 2024, 1000.0).model_copy(update={"company_id": "acme"})]
    store.write_required("0001234567", rows)
    store.set_meta("0001234567", source_sha="s", tags=None, company_id="acme", company_name=None, fact_count=1)
    store.set_meta("0001234567", source_sha="s", tags=None, company_id="acme-inc", company_name=None, fact_count=1)
    assert [(r.company_id, r.outcome) for r in _verify(runs, store)] == [("acme-inc", "match")]


def test_verify_with_legacy_meta_uses_its_single_company_id(tmp_path):
    runs, store = _setup(tmp_path, [_field("rev_f", 1000.0, 2024)], [_req("revenue", 2024, 1000.0)])
    (store.company_dir("0001234567") / "meta.json").write_text(json.dumps({"company_id": "ex"}))
    assert [r.outcome for r in _verify(runs, store)] == ["match"]


def test_non_generic_run_is_unsupported(tmp_path):
    runs, store = _setup(tmp_path, [_field("rev_f", 1000.0, 2024)], [_req("revenue", 2024, 1000.0)])
    runs.results_path("r1").write_text(json.dumps({"company_id": "ex", "financials": {}}) + "\n")
    with pytest.raises(UnsupportedRunError, match="run r1 does not contain generic extraction records"):
        _verify(runs, store)
