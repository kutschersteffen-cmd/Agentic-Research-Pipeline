from __future__ import annotations

import json
from pathlib import Path

from arp.ingestion.xbrl import REVENUE_TAGS, XbrlFactSource
from arp.xbrl_pipeline.models import FactRow
from arp.xbrl_pipeline.required import resolve_required, resolve_required_esef

FIXTURE = Path(__file__).parent / "fixtures" / "xbrl" / "companyfacts_small.json"


def _facts() -> dict:
    return json.loads(FIXTURE.read_text())


def _rows():
    return resolve_required(_facts(), company_id="ex", cik="0001234567")


def _row(metric: str, year: int):
    return next(r for r in _rows() if r.metric == metric and r.fiscal_year == year)


def test_required_found_for_revenue_and_capex():
    r23, r24 = _row("revenue", 2023), _row("revenue", 2024)
    assert (r23.status, r23.value, r23.concept) == ("found", 1000, "us-gaap:Revenues")
    assert (r24.status, r24.value) == ("found", 1200)
    c24 = _row("capex", 2024)
    assert (c24.status, c24.value, c24.concept) == (
        "found", 150, "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"
    )


def test_required_capex_2023_is_not_found_not_guessed():
    c23 = _row("capex", 2023)
    assert c23.status == "not_found"
    assert c23.value is None


def test_required_matches_existing_resolver():
    expected = XbrlFactSource.fact_for_tags(_facts(), REVENUE_TAGS, fiscal_year=2024).value
    assert _row("revenue", 2024).value == expected


def test_foreign_filer_without_us_gaap_gives_not_found_rows():
    facts = {"facts": {"ifrs-full": {"Revenue": {"units": {"EUR": [
        {"end": "2024-12-31", "val": 5, "fy": 2024, "fp": "FY", "form": "20-F"}]}}}}}
    rows = resolve_required(facts, company_id="f", cik="0000000001")
    assert [(r.metric, r.status, r.fiscal_year) for r in rows] == [
        ("revenue", "not_found", None), ("capex", "not_found", None)]


def _f(concept, year, value=1.0, start=True, end=None, taxonomy="ifrs-full", fiscal_year=None):
    return FactRow(company_id="ex", cik="L", taxonomy=taxonomy, concept=concept, unit="EUR", value=value,
                   period_start=f"{year}-01-01" if start is True else start,
                   period_end=end or f"{year}-12-31", fiscal_year=fiscal_year or year, fiscal_period="FY",
                   form="ESEF", filed=None, accession=None, source_sha="s", market="esef")


def _esef(rows):
    return resolve_required_esef(rows, company_id="ex", lei="LEI")


def test_esef_revenue_first_candidate_wins():
    out = _esef([_f("RevenueFromContractsWithCustomers", 2024, 5), _f("Revenue", 2024, 7)])
    r = next(x for x in out if x.metric == "revenue")
    assert (r.status, r.value, r.concept, r.form, r.market, r.cik) == (
        "found", 7, "ifrs-full:Revenue", "ESEF", "esef", "LEI")


def test_esef_falls_back_to_second_candidate():
    out = _esef([_f("RevenueFromContractsWithCustomers", 2024, 5)])
    r = next(x for x in out if x.metric == "revenue")
    assert (r.status, r.concept) == ("found", "ifrs-full:RevenueFromContractsWithCustomers")


def test_esef_year_without_fact_is_not_found():
    capex = "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
    out = _esef([_f("Revenue", 2023), _f("Revenue", 2024), _f(capex, 2024, 3)])
    got = {(x.metric, x.fiscal_year): x.status for x in out}
    assert got == {("revenue", 2023): "found", ("revenue", 2024): "found",
                   ("capex", 2023): "not_found", ("capex", 2024): "found"}


def test_esef_ignores_half_year_and_other_taxonomies():
    rows = [_f("Revenue", 2024, taxonomy="custom"), _f("Revenue", 2024, end="2024-06-30"),
            _f("Revenue", 2024, start=None)]
    out = _esef(rows)
    assert [(x.metric, x.fiscal_year, x.status) for x in out] == [
        ("revenue", None, "not_found"), ("capex", None, "not_found")]


def test_esef_no_facts_gives_single_not_found_pair():
    out = _esef([_f("Assets", 2024, start=None, fiscal_year=None)])
    assert [(x.metric, x.fiscal_year, x.status, x.market) for x in out] == [
        ("revenue", None, "not_found", "esef"), ("capex", None, "not_found", "esef")]
