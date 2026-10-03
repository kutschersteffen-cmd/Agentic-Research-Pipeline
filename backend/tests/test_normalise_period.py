import csv
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from arp.normalise import period as P
from arp.normalise.period import Qualifier, detect_qualifiers, normalise_basis, reported_precision, resolve_period
from arp.schemas.common import CompanyRef


def rp(text, fye=None):
    r = resolve_period(text, fiscal_year_end=fye)
    return r.start, r.end


def test_52_week_year():
    assert rp("52 weeks ended 30 March 2024") == (date(2023, 4, 2), date(2024, 3, 30))


def test_53_week_year():
    assert rp("53 weeks ended 1 April 2023")[0] == date(2022, 3, 27)


def test_published_retailer_anchor():
    # Tesco FY2023/24: 52 weeks, began 26 Feb 2023, ended 24 Feb 2024 (from its annual report).
    assert rp("52 weeks ended 24 February 2024") == (date(2023, 2, 26), date(2024, 2, 24))


def test_april_year_end():
    r = resolve_period("FY2024", fiscal_year_end="04-30")
    assert (r.start, r.end) == (date(2023, 5, 1), date(2024, 4, 30))
    assert r.fye_assumed is False


def test_june_year_end_anchor():
    # Microsoft FY2024 ran 1 Jul 2023 to 30 Jun 2024.
    assert rp("FY 2024", "06-30") == (date(2023, 7, 1), date(2024, 6, 30))
    assert rp("2024", "06-30") == (date(2023, 7, 1), date(2024, 6, 30))


def test_split_fiscal_year():
    assert rp("FY2023/24", "03-31") == (date(2023, 4, 1), date(2024, 3, 31))
    assert rp("2023/24", "03-31") == (date(2023, 4, 1), date(2024, 3, 31))
    assert rp("FY1999/00", "12-31")[1] == date(2000, 12, 31)


def test_unknown_fye_assumes_calendar():
    r = resolve_period("FY2024", fiscal_year_end=None)
    assert (r.start, r.end) == (date(2024, 1, 1), date(2024, 12, 31))
    assert r.fye_assumed is True


def test_leap_day_year_end():
    assert rp("FY2024", "02-29") == (date(2023, 3, 1), date(2024, 2, 29))
    assert rp("FY2023", "02-29") == (date(2022, 3, 1), date(2023, 2, 28))
    assert rp("year ended 29 February 2024") == (date(2023, 3, 1), date(2024, 2, 29))


def test_year_ended_and_as_at():
    assert rp("Fiscal year ended December 31, 2023") == (date(2023, 1, 1), date(2023, 12, 31))
    assert rp("year ended 2023-06-30") == (date(2022, 7, 1), date(2023, 6, 30))
    assert rp("As at 31 Dec 2022") == (date(2022, 12, 31), date(2022, 12, 31))
    assert rp("as of Mar 31, 2024") == (date(2024, 3, 31), date(2024, 3, 31))


def test_quarter():
    assert rp("Q1 2024") == (date(2024, 1, 1), date(2024, 3, 31))
    assert rp("q4 2023") == (date(2023, 10, 1), date(2023, 12, 31))
    assert rp("Q2 2024") == (date(2024, 4, 1), date(2024, 6, 30))


@pytest.mark.parametrize("text", [None, "", "recent years", "Q5 2024", "year ended 32 March 2024", "FY24"])
def test_unparseable_period_is_none(text):
    r = resolve_period(text, fiscal_year_end="03-31")
    assert (r.start, r.end, r.fye_assumed) == (None, None, False)


def _basis_rows():
    with open(Path(P.__file__).parent / "tables" / "basis_v1.csv", encoding="utf8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("row", _basis_rows(), ids=lambda r: r["alias"])
def test_every_basis_row(row):
    assert normalise_basis(row["alias"]) == row["canonical"]
    assert normalise_basis(row["alias"].upper()) == row["canonical"]


def test_basis_canonicals_and_unknown():
    assert {r["canonical"] for r in _basis_rows()} == {
        "location_based", "market_based", "operational_control", "financial_control",
        "equity_share", "reported", "adjusted", "like_for_like",
    }
    assert normalise_basis("Market-based") == "market_based"
    assert normalise_basis("vibes") is None
    assert normalise_basis(None) is None


def test_qualifiers_kept_as_flags():
    assert detect_qualifiers("approximately 1,200 (restated)") == [Qualifier.ESTIMATED, Qualifier.RESTATED]


def test_qualifier_values_and_edges():
    assert [q.value for q in Qualifier] == ["estimated", "restated", "partial_coverage", "fiscal_year_end_assumed"]
    assert detect_qualifiers(None, "") == []
    assert detect_qualifiers("1,200", "tCO2e") == []
    assert detect_qualifiers("~5", "c. 5") == [Qualifier.ESTIMATED]
    assert detect_qualifiers("excluding JV", "covers 80% of sites") == [Qualifier.PARTIAL_COVERAGE]
    assert detect_qualifiers("Re-stated", "partial") == [Qualifier.RESTATED, Qualifier.PARTIAL_COVERAGE]
    assert detect_qualifiers("scope 1 emissions") == []  # no bare "c." inside words


def test_reported_precision():
    assert reported_precision("1,234.50") == 2
    assert reported_precision("1,234") == 0
    assert reported_precision("$ 12.5 million") == 1
    assert reported_precision("n/a") is None
    assert reported_precision(None) is None
    assert reported_precision("1,234.50 and 3.1") == 2


def test_company_ref_fiscal_year_end_validated():
    with pytest.raises(ValidationError):
        CompanyRef(company_id="x", name="X", fiscal_year_end="4/30")
    assert CompanyRef(company_id="x", name="X", fiscal_year_end="04-30").fiscal_year_end == "04-30"
    assert CompanyRef(company_id="x", name="X").fiscal_year_end is None


def test_year_end_28_feb_before_leap_year():
    assert rp("FY2024", "02-28") == (date(2023, 3, 1), date(2024, 2, 28))
    assert rp("year ended 28 February 2024") == (date(2023, 3, 1), date(2024, 2, 28))


def test_fy2025_feb28_start_is_day_after_2024_02_28_which_is_leap_day():
    assert rp("FY2025", "02-28") == (date(2024, 2, 29), date(2025, 2, 28))
