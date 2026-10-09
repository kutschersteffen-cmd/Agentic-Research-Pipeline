import json
from pathlib import Path

from arp.xbrl_pipeline.esef_json import catalog_from_rows, flatten_xbrl_json, parse_period

DOC = json.loads((Path(__file__).parent / "fixtures" / "xbrl_esef_sample.json").read_text())
LEI = "5299001FIXTURELEI0001"
FILING = {"fxo_id": f"{LEI}-2022-12-31-ESEF-DE-0", "date_added": "2023-04-01 10:00:00.000000"}


def _flat():
    return flatten_xbrl_json(DOC, company_id="c1", lei=LEI, source_sha="sha", filing=FILING)


def _by(rows, concept):
    return [r for r in rows if r.concept == concept]


def test_parse_period_duration_end_is_inclusive():
    assert parse_period("2022-01-01T00:00:00/2023-01-01T00:00:00") == ("2022-01-01", "2022-12-31")


def test_parse_period_instant():
    assert parse_period("2021-01-02T00:00:00") == (None, "2021-01-01")


def test_flatten_keeps_numeric_plain_facts_only():
    rows, skipped = _flat()
    assert {(r.taxonomy, r.concept) for r in rows} == {
        ("ifrs-full", "Revenue"),
        ("ifrs-full", "Equity"),
        ("avax", "Custom"),
        ("esrs", "GrossScope1GreenhouseGasEmissions"),
    }
    assert skipped == 1


def test_flatten_row_mapping():
    r = next(r for r in _by(_flat()[0], "Revenue") if r.period_end == "2022-12-31")
    assert (r.unit, r.fiscal_year, r.fiscal_period, r.form, r.market, r.cik) == (
        "EUR", 2022, "FY", "ESEF", "esef", LEI)
    assert (r.value, r.period_start, r.accession, r.filed, r.company_id, r.source_sha) == (
        1000.0, "2022-01-01", FILING["fxo_id"], "2023-04-01", "c1", "sha")


def test_half_year_has_no_fiscal_period():
    r = next(r for r in _by(_flat()[0], "Revenue") if r.period_end == "2022-06-30")
    assert r.fiscal_period is None


def test_instant_is_fy():
    r = _by(_flat()[0], "Equity")[0]
    assert (r.period_start, r.period_end, r.fiscal_period) == (None, "2022-01-01", "FY")


def test_non_finite_and_text_values_skipped():
    rows, _ = _flat()
    for c in ("Assets", "Liabilities", "Profit", "Expenses", "LegalFormOfEntity"):
        assert not _by(rows, c)


def test_duplicate_fact_kept_once():
    full = [r for r in _by(_flat()[0], "Revenue") if r.period_end == "2022-12-31"]
    assert len(full) == 1


def test_extension_and_esrs_concepts_kept():
    rows, _ = _flat()
    assert _by(rows, "Custom") and _by(rows, "GrossScope1GreenhouseGasEmissions")


def test_catalog_counts_years_and_units():
    cat = {e.concept: e for e in catalog_from_rows(_flat()[0])}
    rev = cat["Revenue"]
    assert (rev.fact_count, rev.first_year, rev.last_year, rev.units, rev.label) == (
        2, 2022, 2022, ["EUR"], None)
    assert cat["GrossScope1GreenhouseGasEmissions"].units == ["pure"]
