from __future__ import annotations

import json
from pathlib import Path

from arp.xbrl_pipeline.flatten import build_catalog, flatten_company_facts

FIXTURE = Path(__file__).parent / "fixtures" / "xbrl" / "companyfacts_small.json"


def _facts() -> dict:
    return json.loads(FIXTURE.read_text())


def _rows(concepts=None):
    return list(
        flatten_company_facts(
            _facts(), company_id="ex", cik="0001234567", source_sha="sha", concepts=concepts
        )
    )


def test_flatten_all_yields_every_fact():
    rows = _rows()
    assert len(rows) == 5
    assert any(r.fiscal_period == "Q1" for r in rows)
    dei = next(r for r in rows if r.taxonomy == "dei")
    assert dei.period_start is None
    assert dei.unit == "shares"


def test_flatten_filters_by_tag_id():
    assert len(_rows(frozenset({"us-gaap:Revenues"}))) == 3


def test_flatten_empty_filter_matches_nothing():
    assert _rows(frozenset()) == []


def test_catalog_lists_every_concept():
    catalog = build_catalog(_facts())
    assert len(catalog) == 3
    rev = next(c for c in catalog if c.concept == "Revenues")
    assert rev.fact_count == 3
    assert rev.first_year == 2023
    assert rev.last_year == 2024
    assert rev.units == ["USD"]
    assert rev.label == "Revenues"
