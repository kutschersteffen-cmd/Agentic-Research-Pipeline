import pytest

from arp.research.exposure_layers import run_company_l1
from arp.research.revenue_exposure.resolver import to_exposure
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import ExtractedField


def _field(value):
    # model_construct keeps the Python type (a validated model turns the int 101 into 101.0)
    return ExtractedField.model_construct(field_id="f", field_name="f", value=value, citations=[], confidence=1.0, raw_value_text=None)


@pytest.mark.parametrize(
    "value,expected",
    [(0.8, 0.008), (1, 0.01), (18.5, 0.185), (22, 0.22), (100, 1.0), (0, 0.0), ("18.5", 0.185)],
)
def test_percent_becomes_fraction(value, expected):
    r = to_exposure(_field(value), "s:v1")
    assert r.source == "extracted"
    assert abs(r.value_pct - expected) < 1e-9


@pytest.mark.parametrize(
    "value,shown",
    [(101, "101"), (-5, "-5"), (100.5, "100.5"), (float("nan"), "nan"), (float("inf"), "inf"), ("101", "101"), ("nan", "nan")],
)
def test_out_of_range_is_unresolved(value, shown):
    r = to_exposure(_field(value), "s:v1")
    assert (r.source, r.value_pct, r.notes) == ("unresolved", None, f"Extracted value {shown} is outside 0-100.")


def test_non_numeric_is_unresolved():
    r = to_exposure(_field("abc"), "s:v1")
    assert (r.source, r.value_pct, r.notes) == ("unresolved", None, "Extracted value was not numeric.")


@pytest.mark.parametrize("extracted", [None, _field(None)])
def test_missing_is_unresolved(extracted):
    r = to_exposure(extracted, "s:v1")
    assert (r.source, r.value_pct, r.notes) == ("unresolved", None, "")


def _l1(value):
    ref = CompanyRef(company_id="c", name="C")
    rev = to_exposure(_field(value), "s:v1").model_dump()
    match = {"company_id": "c", "verdict": "include", "revenue_exposure": {"activity_id": "a", "revenue": rev}}
    return run_company_l1([ref], [{"_key": "c", "company_matches": [match]}])[0][2]


def test_small_share_is_not_full_exposure():
    assert abs(_l1(0.8) - 0.008) < 1e-9


def test_out_of_range_gives_no_l1():
    assert _l1(101) is None
