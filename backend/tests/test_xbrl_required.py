from __future__ import annotations

import json
from pathlib import Path

from arp.ingestion.xbrl import REVENUE_TAGS, XbrlFactSource
from arp.xbrl_pipeline.required import resolve_required

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
